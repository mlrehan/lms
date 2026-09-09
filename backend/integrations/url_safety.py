"""Deciding whether the server may connect to a caller-supplied URL.

**This is the one place in the platform where institution input decides what
the server process itself connects to**, and that inverts the usual threat.
Everywhere else a bad value reads or writes the wrong row; here it makes the
application open a socket. The application runs inside the deployment's
network, holding database credentials, with a route to whatever the cloud
provider exposes on a link-local address. Unguarded, "send my webhooks here"
is a request-forgery primitive: point it at `169.254.169.254`, receive the
instance credentials in your own HTTP log, and never touch the API again.

Four properties, each one of them the thing most SSRF filters get wrong:

1. **Scheme allowlist, not a blocklist.** `http`/`https` only. A blocklist
   has to enumerate `file:`, `gopher:`, `ftp:`, `dict:` and whatever the
   HTTP client supports next release; an allowlist does not.
2. **Resolve, then check the resolved addresses** -- never the hostname.
   `internal.example.com` and a DNS record pointing at `127.0.0.1` look
   identical to a name-based filter, and the second one wins.
3. **Check *every* address a name resolves to.** A name with an A record on
   a public address and a second on `10.0.0.5` passes any check that looks
   at `getaddrinfo()[0]` and then connects to whichever the client picks.
4. **Re-check at the moment of use**, not only when the endpoint is saved. A
   hostname that resolved publicly last week can resolve internally today,
   and validation at registration only proves something about last week.

**The residual risk is recorded rather than glossed:** this does not close
DNS rebinding. Between the check and the connection the name can be
re-resolved by the HTTP client to a different address. Closing it properly
means pinning the checked address into the connection itself, which the
delivery client does not currently do; the exposure is one request to an
internal address with an attacker-chosen body and no response returned to
them, and it is bounded further by refusing redirects.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Ports that are almost never a legitimate webhook receiver and are very often
# something a request-forgery is reaching for. Not a security boundary on its
# own -- the address checks are -- but it removes the easiest targets.
BLOCKED_PORTS = frozenset({
    22, 23, 25, 110, 143, 445, 465, 587, 993, 995,
    1433, 1521, 3306, 3389, 5432, 5984, 6379, 9200, 11211, 27017,
})

MAX_URL_LENGTH = 500


@dataclass(frozen=True)
class UrlRejected(Exception):
    """Why a URL may not be used. Carries a reason a person can act on."""

    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.reason


def _is_forbidden(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Reject anything that is not a public unicast address.

    Written as a series of named properties rather than a list of CIDR
    ranges: `ipaddress` already knows what "private", "loopback" and
    "link-local" mean, and a hand-maintained range list is one RFC behind
    from the day it is written. `169.254.0.0/16` -- the cloud metadata
    service -- is covered by `is_link_local`, which is the point.
    """
    if address.is_loopback:
        return "loopback address"
    # Link-local is checked *before* private: `ipaddress` reports
    # 169.254.0.0/16 as both, and "link-local (the cloud metadata service)"
    # tells an operator what they actually pointed at, where "private
    # address" leaves them guessing.
    if address.is_link_local:
        return "link-local address (this includes the cloud metadata service)"
    if address.is_private:
        return "private address"
    if address.is_reserved:
        return "reserved address"
    if address.is_multicast:
        return "multicast address"
    if address.is_unspecified:
        return "unspecified address"
    if isinstance(address, ipaddress.IPv6Address):
        # An IPv4-mapped IPv6 address (`::ffff:127.0.0.1`) is a loopback
        # wearing a different notation, and the v6 properties above do not
        # see through it.
        mapped = address.ipv4_mapped
        if mapped is not None:
            return _is_forbidden(mapped)
    return None


def resolve_addresses(host: str, port: int) -> list[str]:
    """Every address this name currently resolves to.

    Separated so the caller can log what was actually checked -- "we refused
    your URL" is not actionable without "because it resolves to 10.0.0.4".
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlRejected(f"Hostname does not resolve: {host}") from exc
    return sorted({info[4][0] for info in infos})


def assert_safe_url(raw_url: str) -> str:
    """Return the URL if the server may connect to it, else raise.

    Called both when an endpoint is saved *and* immediately before every
    delivery. The second call is the one that matters: the first only proves
    something about the moment somebody clicked save.
    """
    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise UrlRejected("URL is empty or too long.")

    parsed = urlparse(raw_url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlRejected(
            f"Only {', '.join(sorted(ALLOWED_SCHEMES))} URLs are allowed."
        )
    if not parsed.hostname:
        raise UrlRejected("URL has no host.")
    if parsed.username or parsed.password:
        # Credentials in the URL would be written to the endpoint row and to
        # every log line that mentions it.
        raise UrlRejected("Credentials in the URL are not allowed.")

    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    if port in BLOCKED_PORTS:
        raise UrlRejected(f"Port {port} is not an allowed webhook destination.")

    # An address literal is checked directly; a name is resolved first. Both
    # end at the same test, so `http://127.0.0.1/` and a hostname whose A
    # record is `127.0.0.1` are refused identically.
    addresses = resolve_addresses(parsed.hostname, port)
    if not addresses:
        raise UrlRejected(f"Hostname does not resolve: {parsed.hostname}")

    for candidate in addresses:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:  # pragma: no cover - getaddrinfo returns literals
            raise UrlRejected(f"Unusable address: {candidate}") from None
        # *Every* address, not the first: a name with one public and one
        # private record must be refused, because the client will connect to
        # whichever it likes.
        problem = _is_forbidden(address)
        if problem is not None:
            raise UrlRejected(
                f"{parsed.hostname} resolves to {candidate}, which is a {problem}."
            )

    return raw_url.strip()
