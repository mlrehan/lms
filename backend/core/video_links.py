"""Understanding a video URL somebody pasted in.

Two jobs, and the first one is the security job.

**Validation.** A link a tutor types is stored and later handed to a browser,
as an `<iframe src>`, a `<video src>` or an `href`. `javascript:` and `data:`
URLs in any of those positions execute script in the page, so the scheme is
checked against an allowlist rather than a blocklist, and everything that is
not plainly `http`/`https` is refused. Credentials in the authority
(`https://user:pass@host/`) are refused too: they are almost never a genuine
teaching link and are the classic way to make a hostile host read as a
familiar one.

**Normalisation.** The URL a person copies from the address bar is usually
*not* the one that embeds. YouTube's watch page, a Vimeo project page and a
Zoom share page are web pages; the embeddable player lives at a different
address for the first two and nowhere at all for some providers. Pasting the
page URL into an iframe and hoping is what "share a video" degenerates into,
and the result is a blank box the tutor cannot diagnose. So each supported
provider is recognised and its documented embed endpoint is built, and a
provider with no embeddable form is marked as such so the interface can offer
a link instead of a frame that will never fill.

Nothing here performs network I/O. Resolving a URL to find out what it is
would make a tutor's paste into a request from this server to an address they
chose, which is the shape of an SSRF; and a thumbnail is only produced where
the provider's URL scheme is documented and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse, urlunparse

#: Longer than this and it is not a link somebody typed.
MAX_URL_LENGTH = 2048

#: The only schemes that may reach an `href`, `iframe src` or `video src`.
ALLOWED_SCHEMES = ("http", "https")

#: Extensions a browser can play directly in a `<video>` element.
_DIRECT_VIDEO_SUFFIXES = (".mp4", ".webm", ".ogg", ".ogv", ".m4v", ".mov", ".m3u8")

#: A YouTube id is 11 characters of base64url. Pinning the shape stops a
#: query string full of tracking parameters being mistaken for an id.
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIMEO_ID = re.compile(r"^\d{6,12}$")

#: "scheme:" per RFC 3986, with or without the "//" that follows it.
_HAS_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


class VideoLinkError(ValueError):
    """The URL cannot be used as a video link, with a reason for the person."""


@dataclass(frozen=True)
class VideoLink:
    """What we worked out about a pasted URL."""

    provider: str
    #: The address to store and to open in a new tab.
    url: str
    #: The address to put in an iframe, or None when the provider has none.
    embed_url: str | None
    #: A still image, only where the provider documents a deterministic one.
    thumbnail_url: str | None
    #: True when `embed_url` is a player we can frame.
    is_embeddable: bool
    #: True when the browser can play the URL itself in a `<video>` element.
    is_direct_file: bool

    @property
    def provider_label(self) -> str:
        return _LABELS.get(self.provider, "Video link")


_LABELS = {
    "youtube": "YouTube",
    "vimeo": "Vimeo",
    "zoom": "Zoom",
    "google_drive": "Google Drive",
    "direct": "Video file",
    "other": "Video link",
}

#: Providers this build recognises, for the interface to list.
SUPPORTED_PROVIDERS = ("youtube", "vimeo", "zoom", "google_drive", "direct")


def _clean(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise VideoLinkError("Enter a video link.")
    if len(url) > MAX_URL_LENGTH:
        raise VideoLinkError(f"That link is too long (limit {MAX_URL_LENGTH} characters).")
    if any(ch in url for ch in "\r\n\t") or any(ord(ch) < 32 for ch in url):
        raise VideoLinkError("That link contains characters that are not allowed.")
    # A bare "youtube.com/watch?v=..." is what people paste most often, so a
    # missing scheme is filled in. It must not be filled in over a scheme that
    # is already there, though: "javascript:alert(1)" has no "//", and
    # prepending to it produces "https://javascript:alert(1)", which is
    # refused for the wrong reason and would stop being refused the moment
    # that host check changed. Anything already carrying a scheme is left
    # alone so the allowlist below is what judges it.
    if not _HAS_SCHEME.match(url):
        url = "https://" + url
    return url


def _parsed(url: str):  # noqa: ANN202
    try:
        parts = urlparse(url)
    except ValueError as exc:  # pragma: no cover - urlparse is forgiving
        raise VideoLinkError("That does not look like a web address.") from exc

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise VideoLinkError(
            "Only links beginning http:// or https:// can be used. "
            f"This one begins {parts.scheme or 'nothing'}:."
        )
    if not parts.netloc:
        raise VideoLinkError("That does not look like a web address.")
    if "@" in parts.netloc:
        raise VideoLinkError("A link with a username or password in it cannot be used.")
    if not parts.hostname or "." not in parts.hostname:
        raise VideoLinkError("That web address has no site name in it.")
    return parts


def _host(parts) -> str:  # noqa: ANN001
    return (parts.hostname or "").lower().removeprefix("www.")


def _youtube_id(parts) -> str | None:  # noqa: ANN001
    host, path = _host(parts), parts.path or ""
    if host == "youtu.be":
        candidate = path.strip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if path.startswith(("/embed/", "/v/", "/shorts/", "/live/")):
            candidate = path.split("/")[2] if len(path.split("/")) > 2 else ""
        else:
            candidate = (parse_qs(parts.query).get("v") or [""])[0]
    else:
        return None
    return candidate if _YOUTUBE_ID.match(candidate or "") else None


def _vimeo_id(parts) -> str | None:  # noqa: ANN001
    host, path = _host(parts), (parts.path or "").strip("/")
    if not (host == "vimeo.com" or host.endswith(".vimeo.com")):
        return None
    # vimeo.com/76979871, player.vimeo.com/video/76979871, vimeo.com/channels/x/76979871
    for segment in reversed(path.split("/")):
        if _VIMEO_ID.match(segment):
            return segment
    return None


def _drive_id(parts) -> str | None:  # noqa: ANN001
    if _host(parts) != "drive.google.com":
        return None
    segments = (parts.path or "").strip("/").split("/")
    if "d" in segments:
        index = segments.index("d")
        if len(segments) > index + 1:
            return segments[index + 1]
    return (parse_qs(parts.query).get("id") or [None])[0]


def parse_video_url(raw: str) -> VideoLink:
    """Validate a pasted URL and work out how to show it.

    Raises :class:`VideoLinkError` with a message written for the person who
    typed it, not for a log.
    """
    url = _clean(raw)
    parts = _parsed(url)
    host = _host(parts)

    youtube = _youtube_id(parts)
    if youtube:
        return VideoLink(
            provider="youtube",
            url=f"https://www.youtube.com/watch?v={youtube}",
            embed_url=f"https://www.youtube-nocookie.com/embed/{youtube}",
            thumbnail_url=f"https://i.ytimg.com/vi/{youtube}/hqdefault.jpg",
            is_embeddable=True,
            is_direct_file=False,
        )

    vimeo = _vimeo_id(parts)
    if vimeo:
        return VideoLink(
            provider="vimeo",
            url=f"https://vimeo.com/{vimeo}",
            embed_url=f"https://player.vimeo.com/video/{vimeo}",
            # Vimeo's still is only available through its oEmbed API, and
            # fetching it here would mean a network call per paste.
            thumbnail_url=None,
            is_embeddable=True,
            is_direct_file=False,
        )

    drive = _drive_id(parts)
    if drive:
        return VideoLink(
            provider="google_drive",
            url=f"https://drive.google.com/file/d/{drive}/view",
            embed_url=f"https://drive.google.com/file/d/{drive}/preview",
            thumbnail_url=None,
            is_embeddable=True,
            is_direct_file=False,
        )

    if host.endswith("zoom.us") or host.endswith("zoom.com"):
        # Zoom share pages are framed as they are: there is no separate player
        # address, and the recording may additionally be passcode-protected,
        # which only Zoom can decide.
        return VideoLink(
            provider="zoom",
            url=urlunparse(parts),
            embed_url=urlunparse(parts),
            thumbnail_url=None,
            is_embeddable=True,
            is_direct_file=False,
        )

    path_lower = (parts.path or "").lower()
    if path_lower.endswith(_DIRECT_VIDEO_SUFFIXES):
        return VideoLink(
            provider="direct",
            url=urlunparse(parts),
            embed_url=None,
            thumbnail_url=None,
            is_embeddable=False,
            is_direct_file=True,
        )

    # A real web address, but not one we know how to play. Offered as a link
    # rather than refused: a tutor may legitimately share a lecture hosted
    # somewhere this build has never heard of, and a frame that stays blank
    # would be worse than an honest "opens in a new tab".
    return VideoLink(
        provider="other",
        url=urlunparse(parts),
        embed_url=None,
        thumbnail_url=None,
        is_embeddable=False,
        is_direct_file=False,
    )


def validate_video_url(raw: str) -> str:
    """Refuse an unusable or unsafe URL; return the canonical form.

    For callers that only need the safety check -- the session recording
    field, which stores whatever the tutor entered.
    """
    return parse_video_url(raw).url
