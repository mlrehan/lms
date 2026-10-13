"""How much of the LMS URL each video provider is told, and why.

The recording embed is a redirect, so the `Referrer-Policy` on it decides what
the provider learns. `no-referrer` was chosen to tell them nothing -- correct
in intent, and it stopped YouTube working at all.

Measured in a browser, two iframes side by side on the same page, same video:

* default referrer  -> the player renders and offers play
* `no-referrer`     -> "Video player configuration error -- Error 153"

Vimeo played identically either way. So the rule is not "send a referrer" but
"send the embedding *origin* to the providers whose player checks it, and
nothing to anyone else" -- the origin is the thing YouTube validates, and the
batch, session and viewer are no part of it.

These tests pin that split so a future tightening back to `no-referrer`
everywhere fails here rather than silently taking YouTube playback down.
"""

from __future__ import annotations

import pytest

from backend.api.v1.sessions import _referrer_policy_for

ORIGIN_ONLY = "strict-origin-when-cross-origin"
NOTHING = "no-referrer"


@pytest.mark.parametrize(
    "link",
    [
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
    ],
)
def test_youtube_is_told_the_origin_because_its_player_demands_one(link: str) -> None:
    assert _referrer_policy_for(link) == ORIGIN_ONLY


@pytest.mark.parametrize(
    "link",
    [
        "https://player.vimeo.com/video/76979871",
        "https://lait.zoom.us/rec/share/abc123",
        "https://drive.google.com/file/d/1A2B/preview",
        "https://cdn.example.org/lecture.mp4",
    ],
)
def test_everyone_else_is_told_nothing(link: str) -> None:
    """Vimeo was measured playing fine without a referrer, so it is not given
    one. The default stays closed."""
    assert _referrer_policy_for(link) == NOTHING


def test_a_host_that_merely_mentions_youtube_is_not_youtube() -> None:
    """`evil.test/youtube.com` and `notyoutube.com` must not earn the origin."""
    assert _referrer_policy_for("https://evil.test/youtube.com") == NOTHING
    assert _referrer_policy_for("https://notyoutube.com/embed/x") == NOTHING
    assert _referrer_policy_for("https://youtube.com.evil.test/embed/x") == NOTHING
