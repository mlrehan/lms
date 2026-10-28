"""Which address a request really came from -- the one rule every audit row uses.

**The chain this deployment actually has** (see DEPLOYMENT.md): browser -> the
host's nginx -> the Next.js console (the BFF, bound to 127.0.0.1) -> this API
(no published port). Only the hops this process is told to trust may vouch
for the address before them.

**Forwarding headers are believed only from a trusted peer.** The previous
rule took the *first* `X-Forwarded-For` entry from anybody. nginx's
`$proxy_add_x_forwarded_for` keeps whatever the client sent and appends the
real address, so the first entry was the attacker's to choose -- an audit
trail anyone could sign in under somebody else's address. Here the chain is
read from the right: start at the socket peer, and step left only while the
current hop is a trusted proxy. The first untrusted address is the client.

**An unknown client is unknown.** When a trusted proxy passes no usable
address, the result is no address, scope UNAVAILABLE -- never the proxy's own
address, which is how 15,000 audit rows came to say 127.0.0.1. A direct
caller (an untrusted peer) is itself the client.

Pure functions, no I/O, so every case is unit-testable.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network

_MAX_HOPS = 20
_MAX_HEADER = 2048


class IpScope(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"        # RFC 1918, unique-local, carrier-grade NAT
    LOOPBACK = "LOOPBACK"
    RESERVED = "RESERVED"      # link-local, multicast, documentation, unspecified...
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ClientAddress:
    ip: str | None
    scope: IpScope


UNAVAILABLE = ClientAddress(None, IpScope.UNAVAILABLE)


def parse_ip(value: str | None) -> IPAddress | None:
    """A validated address, or None. Strips brackets, ports and zone ids; unwraps
    an IPv4-mapped IPv6 address (`::ffff:1.2.3.4`) to the IPv4 it carries."""
    if not value:
        return None
    text = value.strip().strip('"')
    if not text or len(text) > 64:
        return None
    if text.startswith("["):  # [2001:db8::1]:443
        end = text.find("]")
        if end == -1:
            return None
        text = text[1:end]
    elif text.count(":") == 1:  # 203.0.113.7:51234
        text = text.split(":", 1)[0]
    text = text.split("%", 1)[0]  # fe80::1%eth0
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def classify(ip: IPAddress | None) -> IpScope:
    if ip is None:
        return IpScope.UNAVAILABLE
    if ip.is_loopback:
        return IpScope.LOOPBACK
    if ip.is_global:
        return IpScope.PUBLIC
    # 100.64.0.0/10 (carrier-grade NAT) is neither global nor `is_private` in
    # Python; it is an address behind somebody's NAT, which is what PRIVATE means here.
    if ip.is_private or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")):
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            return IpScope.RESERVED
        if ip.version == 4 and any(ip in ipaddress.ip_network(n) for n in _RESERVED_V4):
            return IpScope.RESERVED
        if ip.version == 6 and any(ip in ipaddress.ip_network(n) for n in _RESERVED_V6):
            return IpScope.RESERVED
        return IpScope.PRIVATE
    return IpScope.RESERVED


# `is_private` also covers these, but none is an address a person browses from.
_RESERVED_V4 = ("192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
                "240.0.0.0/4", "255.255.255.255/32", "0.0.0.0/8")
_RESERVED_V6 = ("2001:db8::/32", "64:ff9b:1::/48", "100::/64", "2001::/23")


@lru_cache(maxsize=32)
def parse_trusted(spec: str) -> tuple[Network, ...]:
    """`SERVER_FORWARDED_ALLOW_IPS` ("127.0.0.1,172.16.0.0/12") as networks. Bad entries are
    skipped, never widened: '*' is refused here as it is in production config validation."""
    networks: list[Network] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or part == "*":
            continue
        try:
            network = ipaddress.ip_network(part, strict=False)
        except ValueError:
            continue
        networks.append(network)
        # A trusted IPv4 proxy can also be seen as its IPv4-mapped IPv6 form.
        if network.version == 4:
            networks.append(ipaddress.ip_network(f"::ffff:{network.network_address}/{96 + network.prefixlen}"))
    return tuple(networks)


def _trusted(ip: IPAddress, trusted: tuple[Network, ...]) -> bool:
    return any(ip.version == n.version and ip in n for n in trusted)


def resolve_client(peer: str | None, forwarded_for: str | None, trusted_spec: str) -> ClientAddress:
    """The client's address for a request whose socket peer is `peer`.

    `forwarded_for` is the raw `X-Forwarded-For` value (possibly several
    headers joined by commas). It is consulted only when the peer is trusted.
    """
    trusted = parse_trusted(trusted_spec)
    peer_ip = parse_ip(peer)
    if peer_ip is None:
        return UNAVAILABLE
    if not _trusted(peer_ip, trusted):
        # Nobody vouches for anything: the peer is the client.
        return ClientAddress(str(peer_ip), classify(peer_ip))

    raw = (forwarded_for or "")[:_MAX_HEADER]
    hops = [h for h in (p.strip() for p in raw.split(",")) if h][-_MAX_HOPS:]
    for hop in reversed(hops):
        ip = parse_ip(hop)
        if ip is None:
            # A malformed entry from a trusted proxy ends the chain: what lies
            # to its left was never vouched for by anyone we trust.
            return UNAVAILABLE
        if _trusted(ip, trusted):
            continue
        return ClientAddress(str(ip), classify(ip))
    # Every hop was a trusted proxy, or there were none: the client is unknown.
    return UNAVAILABLE
