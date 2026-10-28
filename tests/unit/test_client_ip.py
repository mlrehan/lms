"""Which address an audit row records for a request -- `backend/core/client_ip.py`.

The cases are the ones that went wrong, or could: a forged X-Forwarded-For,
a proxy that passes no address (previously recorded as the proxy itself),
IPv6 and IPv4-mapped forms, and private space.
"""

from __future__ import annotations

import pytest

from backend.core.client_ip import ClientAddress, IpScope, classify, parse_ip, resolve_client

TRUSTED = "127.0.0.1,::1,172.16.0.0/12"


def test_a_forged_first_entry_is_ignored_and_the_proxy_appended_address_wins():
    # nginx's $proxy_add_x_forwarded_for keeps what the client sent and appends
    # the real peer; the old rule took the first, attacker-chosen entry.
    assert resolve_client("127.0.0.1", "1.2.3.4, 81.2.69.142", TRUSTED) == ClientAddress("81.2.69.142", IpScope.PUBLIC)


def test_an_untrusted_peer_cannot_vouch_for_anyone():
    assert resolve_client("81.2.69.142", "8.8.8.8", TRUSTED) == ClientAddress("81.2.69.142", IpScope.PUBLIC)


def test_a_trusted_proxy_that_passes_no_address_yields_unknown_never_itself():
    # The defect behind 15,000 audit rows reading 127.0.0.1.
    assert resolve_client("127.0.0.1", None, TRUSTED) == ClientAddress(None, IpScope.UNAVAILABLE)
    assert resolve_client("172.18.0.4", "", TRUSTED) == ClientAddress(None, IpScope.UNAVAILABLE)


def test_a_chain_of_trusted_proxies_is_walked_to_the_client():
    assert resolve_client("172.18.0.4", "2a02:c204:2110:73::99, 127.0.0.1", TRUSTED) == ClientAddress(
        "2a02:c204:2110:73::99", IpScope.PUBLIC
    )


def test_only_proxies_in_the_chain_means_unknown():
    assert resolve_client("127.0.0.1", "172.18.0.9, 127.0.0.1", TRUSTED).scope is IpScope.UNAVAILABLE


def test_a_malformed_entry_from_a_trusted_proxy_ends_the_chain():
    # Whatever is left of a garbage hop was vouched for by nobody we trust.
    assert resolve_client("127.0.0.1", "81.2.69.142, not-an-ip", TRUSTED).scope is IpScope.UNAVAILABLE


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("::ffff:127.0.0.1", "::ffff:81.2.69.142", "81.2.69.142"),  # IPv4-mapped on both sides
        ("[::1]:54012", "[2001:4860:4860::8888]:443", "2001:4860:4860::8888"),  # brackets and ports
        ("127.0.0.1", "81.2.69.142:51234", "81.2.69.142"),  # IPv4 with a port
    ],
)
def test_ipv6_ports_and_mapped_forms(peer, forwarded, expected):
    assert resolve_client(peer, forwarded, TRUSTED).ip == expected


@pytest.mark.parametrize(
    ("ip", "scope"),
    [
        ("81.2.69.142", IpScope.PUBLIC),
        ("2a02:c204:2110:73::1", IpScope.PUBLIC),
        ("10.4.0.7", IpScope.PRIVATE),
        ("192.168.10.196", IpScope.PRIVATE),
        ("100.64.3.2", IpScope.PRIVATE),  # carrier-grade NAT
        ("fd12:3456::1", IpScope.PRIVATE),
        ("127.0.0.1", IpScope.LOOPBACK),
        ("::1", IpScope.LOOPBACK),
        ("169.254.1.1", IpScope.RESERVED),
        ("203.0.113.9", IpScope.RESERVED),  # documentation range
        ("2001:db8::1", IpScope.RESERVED),
    ],
)
def test_classification(ip, scope):
    assert classify(parse_ip(ip)) is scope


def test_a_private_client_behind_the_proxy_is_recorded_as_private():
    assert resolve_client("127.0.0.1", "192.168.10.196", TRUSTED) == ClientAddress("192.168.10.196", IpScope.PRIVATE)


def test_star_is_not_a_trust_everything_wildcard():
    # '*' would make every address look like a proxy; it is refused, so the peer is the client.
    assert resolve_client("172.18.0.4", "81.2.69.142", "*").ip == "172.18.0.4"


def test_oversized_and_garbage_values_are_refused():
    assert parse_ip("x" * 100) is None
    assert parse_ip("1.2.3.4.5") is None
    assert resolve_client(None, "81.2.69.142", TRUSTED).scope is IpScope.UNAVAILABLE
