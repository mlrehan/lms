"""Parsing `Range`, which is what makes a recording seekable.

A player that asks for bytes 40 minutes in and is handed the whole file with a
`200` restarts the download on every scrub. These tests cover the header forms
real players send -- including `bytes=-N`, which is how an MP4's index at the
end of the file gets read before playback can start at all.
"""

from __future__ import annotations

import pytest

from backend.api.streaming import _MAX_SPAN, _parse

TOTAL = 1_000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),                    # no header: the whole file
        ("", None),
        ("bytes=0-", (0, TOTAL - 1)),    # "the rest", which is all of it
        ("bytes=100-199", (100, 199)),
        ("bytes=0-0", (0, 0)),           # one byte: how Safari probes support
        ("bytes=-20", (980, 999)),       # the tail, for the index
        ("bytes=-5000", (0, 999)),       # a tail longer than the file is the file
        ("bytes=999-", (999, 999)),
    ],
)
def test_understood_headers(header: str | None, expected: tuple[int, int] | None) -> None:
    assert _parse(header, TOTAL) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=1500-1600", "bytes=-0", "bytes=200-100"])
def test_unsatisfiable_is_distinct_from_absent(header: str) -> None:
    """`False`, not `None`: one is a 416 telling the player the real length, the
    other is "send the whole file". Collapsing them would answer a nonsense
    range with the entire recording."""
    assert _parse(header, TOTAL) is False


@pytest.mark.parametrize("header", ["garbage", "items=0-10", "bytes=0-10, 20-30"])
def test_headers_we_do_not_speak_fall_back_to_the_whole_file(header: str) -> None:
    """Multi-range and malformed headers. Every client copes with a 200; not
    every client copes with a refusal."""
    assert _parse(header, TOTAL) is None


def test_one_answer_is_bounded_however_much_is_asked_for() -> None:
    """`bytes=0-` on a two-hour recording would otherwise pin a worker to one
    viewer for the whole download. The player just asks again."""
    span = _parse("bytes=0-", 500 * 1024 * 1024)
    assert span == (0, _MAX_SPAN - 1)
