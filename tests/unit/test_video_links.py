"""Reading a pasted video URL.

The security half is the scheme check. A stored link is later written into an
`iframe src`, a `video src` or an `href`, and `javascript:` in any of those
runs script in the page -- so these tests assert refusal of the dangerous
schemes by name rather than trusting that a URL "looks fine".

The rest is normalisation, and the cases are the ones people actually paste:
the watch page rather than the embed, a share link with tracking parameters
on the end, a mobile `youtu.be` link, a Vimeo page URL.
"""

from __future__ import annotations

import pytest

from backend.core.video_links import (
    MAX_URL_LENGTH,
    VideoLinkError,
    parse_video_url,
    validate_video_url,
)


class TestUnsafeLinksAreRefused:
    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "  javascript:alert(document.cookie)  ",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ],
    )
    def test_a_script_bearing_scheme_cannot_be_stored(self, url: str) -> None:
        """These are the ones that execute when framed or linked."""
        with pytest.raises(VideoLinkError):
            parse_video_url(url)

    def test_credentials_in_the_address_are_refused(self) -> None:
        """`https://youtube.com@evil.test/` reads as YouTube and is not."""
        with pytest.raises(VideoLinkError):
            parse_video_url("https://www.youtube.com@evil.test/watch?v=dQw4w9WgXcQ")

    @pytest.mark.parametrize("url", ["", "   ", "not-a-url", "https://", "http://localhost"])
    def test_something_that_is_not_an_address_is_refused(self, url: str) -> None:
        with pytest.raises(VideoLinkError):
            parse_video_url(url)

    def test_a_newline_cannot_be_smuggled_in(self) -> None:
        """A header-splitting shape, refused before it reaches a redirect."""
        with pytest.raises(VideoLinkError):
            parse_video_url("https://vimeo.com/1\r\nSet-Cookie: a=b")

    def test_an_absurdly_long_link_is_refused(self) -> None:
        with pytest.raises(VideoLinkError):
            parse_video_url("https://vimeo.com/" + "9" * (MAX_URL_LENGTH + 10))

    def test_the_message_says_what_to_do(self) -> None:
        with pytest.raises(VideoLinkError) as caught:
            parse_video_url("javascript:alert(1)")
        assert "http" in str(caught.value), "the refusal should name what is accepted"


class TestYouTube:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "http://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLx",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=42",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "www.youtube.com/watch?v=dQw4w9WgXcQ",
        ],
    )
    def test_every_shape_people_paste_resolves_to_the_same_video(self, url: str) -> None:
        link = parse_video_url(url)
        assert link.provider == "youtube"
        assert link.embed_url == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
        assert link.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert link.is_embeddable

    def test_the_embed_is_the_no_cookie_host(self) -> None:
        """Students are shown a video chosen by their tutor; the nocookie host
        is YouTube's own way of not setting tracking cookies until play."""
        assert "youtube-nocookie.com" in parse_video_url("https://youtu.be/dQw4w9WgXcQ").embed_url

    def test_a_thumbnail_is_offered(self) -> None:
        link = parse_video_url("https://youtu.be/dQw4w9WgXcQ")
        assert link.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"

    def test_a_channel_page_is_not_a_video(self) -> None:
        """`/@someone` has no 11-character id, so it must not be framed as one."""
        link = parse_video_url("https://www.youtube.com/@sometutor")
        assert link.provider == "other"
        assert link.embed_url is None


class TestVimeo:
    @pytest.mark.parametrize(
        "url",
        [
            "https://vimeo.com/76979871",
            "https://player.vimeo.com/video/76979871",
            "https://vimeo.com/channels/staffpicks/76979871",
            "https://vimeo.com/76979871?share=copy",
        ],
    )
    def test_the_page_url_becomes_the_player_url(self, url: str) -> None:
        link = parse_video_url(url)
        assert link.provider == "vimeo"
        assert link.embed_url == "https://player.vimeo.com/video/76979871"
        assert link.is_embeddable

    def test_no_thumbnail_is_invented(self) -> None:
        """Vimeo's still needs an API call. Returning a guessed URL would put a
        broken image on the page; None lets the interface show a badge."""
        assert parse_video_url("https://vimeo.com/76979871").thumbnail_url is None


class TestZoomAndDrive:
    def test_a_zoom_share_page_is_framed_as_it_is(self) -> None:
        link = parse_video_url("https://lait.zoom.us/rec/share/abc123")
        assert link.provider == "zoom"
        assert link.embed_url == link.url
        assert link.is_embeddable

    def test_a_drive_file_gets_its_preview_address(self) -> None:
        link = parse_video_url("https://drive.google.com/file/d/1A2B3C4D5E/view?usp=sharing")
        assert link.provider == "google_drive"
        assert link.embed_url == "https://drive.google.com/file/d/1A2B3C4D5E/preview"


class TestDirectFilesAndUnknownHosts:
    @pytest.mark.parametrize("suffix", [".mp4", ".webm", ".m3u8", ".MOV"])
    def test_a_media_file_is_played_by_the_browser(self, suffix: str) -> None:
        link = parse_video_url(f"https://cdn.example.org/lectures/week1{suffix}")
        assert link.provider == "direct"
        assert link.is_direct_file
        assert link.embed_url is None

    def test_an_unknown_host_is_a_link_not_a_refusal(self) -> None:
        """A tutor may share a lecture hosted somewhere we have never heard of.
        Refusing it would be wrong; framing it would show a blank box."""
        link = parse_video_url("https://lectures.some-university.ac.uk/watch/123")
        assert link.provider == "other"
        assert link.is_embeddable is False
        assert link.is_direct_file is False
        assert link.url.startswith("https://lectures.some-university.ac.uk/")


def test_validate_returns_the_canonical_form() -> None:
    assert validate_video_url("youtu.be/dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
