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
    "wistia": "Wistia",
    "brightcove": "Brightcove",
    "dacast": "Dacast",
    "zoom": "Zoom",
    "google_drive": "Google Drive / Meet",
    "microsoft": "Microsoft Teams / Stream",
    "streamyard": "StreamYard",
    "zoho": "Zoho Meeting",
    "direct": "Video file",
    "other": "Video link",
}

#: Providers this build recognises, for the interface to list.
SUPPORTED_PROVIDERS = (
    "youtube", "vimeo", "wistia", "brightcove", "dacast", "zoom",
    "google_drive", "microsoft", "streamyard", "zoho", "direct",
)


@dataclass(frozen=True)
class ProviderProfile:
    """What the LMS can and cannot promise about a provider, stated to the viewer.

    The player is the provider's own, inside our frame. So whether a viewer
    can download, and whether the video plays on other sites, is decided by
    the provider and by the owner's settings *there* -- never by us. Saying so
    is the honest version of "no download button".
    """

    plays_in_lms: bool
    #: What controls downloading, in words for the person reading it.
    download: str
    #: Whether the provider can lock playback to approved domains.
    domain_restriction: str
    #: Whether a viewer must be signed in to the provider to watch.
    needs_provider_sign_in: bool = False


_PROFILES: dict[str, ProviderProfile] = {
    "youtube": ProviderProfile(
        True,
        "The YouTube player has no download button. Unlisted videos still play for anyone "
        "holding the YouTube link -- use private hosting for material that must stay inside the LMS.",
        "Not available for public or unlisted YouTube videos.",
    ),
    "vimeo": ProviderProfile(
        True,
        "Set on Vimeo: the owner turns downloads off under the video's privacy settings.",
        "Available on paid Vimeo plans (embed only on specific domains).",
    ),
    "wistia": ProviderProfile(
        True,
        "Set in Wistia: downloads are off unless the owner enables them.",
        "Available in Wistia's account security settings (domain restrictions).",
    ),
    "brightcove": ProviderProfile(
        True,
        "The Brightcove player has no download button; offline download is a separate Brightcove feature.",
        "Available through Brightcove player domain restrictions.",
    ),
    "dacast": ProviderProfile(
        True,
        "The Dacast player has no download button.",
        "Available through Dacast's referrer (domain) restrictions.",
    ),
    "zoom": ProviderProfile(
        True,
        "Set in Zoom: the recording's share settings decide whether viewers may download it. "
        "A passcode-protected recording asks for the passcode in the player.",
        "Not offered by Zoom for shared recordings.",
    ),
    "google_drive": ProviderProfile(
        True,
        "Set in Google Drive: the owner must turn off download for viewers, otherwise Drive's own "
        "player offers it. Google Meet recordings are Drive files and behave the same way.",
        "Not offered; the viewer needs access to the file in Drive.",
        needs_provider_sign_in=True,
    ),
    "microsoft": ProviderProfile(
        True,
        "Set in SharePoint/OneDrive: download follows the file's sharing permissions.",
        "The viewer must be signed in to Microsoft 365 with access to the file.",
        needs_provider_sign_in=True,
    ),
    "streamyard": ProviderProfile(
        False,
        "StreamYard does not offer an embeddable player for recordings. Publish the recording to "
        "YouTube or Vimeo and add that link to play it inside the LMS.",
        "Not available.",
    ),
    "zoho": ProviderProfile(
        False,
        "Zoho Meeting recordings open on Zoho's site; they have no embeddable player.",
        "Not available.",
        needs_provider_sign_in=True,
    ),
    "direct": ProviderProfile(
        True,
        "Plays in the LMS player with its download control hidden; the file's address can still be "
        "found by a determined viewer. Upload it to the resource library to keep it on our storage.",
        "Not applicable.",
    ),
    "other": ProviderProfile(
        False,
        "Unknown provider: it opens on the provider's site.",
        "Unknown.",
    ),
}


def provider_label(provider: str) -> str:
    return _LABELS.get(provider, "Video link")


def provider_profile(provider: str) -> ProviderProfile:
    return _PROFILES.get(provider, _PROFILES["other"])


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


_WISTIA_ID = re.compile(r"^[A-Za-z0-9]{6,20}$")


def _wistia_id(parts) -> str | None:  # noqa: ANN001
    host = _host(parts)
    if not (host.endswith("wistia.com") or host.endswith("wistia.net") or host == "wi.st"):
        return None
    segments = [x for x in (parts.path or "").split("/") if x]
    # /medias/<id>, /embed/medias/<id>(.jsonp), /embed/iframe/<id>
    for marker in ("medias", "iframe"):
        if marker in segments:
            i = segments.index(marker)
            if len(segments) > i + 1:
                candidate = segments[i + 1].split(".")[0]
                return candidate if _WISTIA_ID.match(candidate) else None
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

    wistia = _wistia_id(parts)
    if wistia:
        return VideoLink(
            provider="wistia",
            url=urlunparse(parts),
            embed_url=f"https://fast.wistia.net/embed/iframe/{wistia}",
            thumbnail_url=None,
            is_embeddable=True,
            is_direct_file=False,
        )

    if host == "players.brightcove.net" and "videoId" in parse_qs(parts.query):
        # The player page Brightcove documents for iframe embedding *is* this
        # address (`/<account>/<player>_default/index.html?videoId=...`).
        return VideoLink(
            provider="brightcove",
            url=urlunparse(parts),
            embed_url=urlunparse(parts),
            thumbnail_url=None,
            is_embeddable=True,
            is_direct_file=False,
        )

    if host == "iframe.dacast.com":
        # Dacast's documented iframe player address.
        return VideoLink(
            provider="dacast", url=urlunparse(parts), embed_url=urlunparse(parts),
            thumbnail_url=None, is_embeddable=True, is_direct_file=False,
        )
    if host.endswith("dacast.com"):
        return VideoLink(
            provider="dacast", url=urlunparse(parts), embed_url=None,
            thumbnail_url=None, is_embeddable=False, is_direct_file=False,
        )

    if host.endswith("sharepoint.com") or host in ("onedrive.live.com", "web.microsoftstream.com"):
        # Teams recordings live in SharePoint/OneDrive. Only SharePoint's own
        # `embed.aspx` address frames; anything else opens on Microsoft's site.
        embeddable = (parts.path or "").lower().endswith("/_layouts/15/embed.aspx")
        return VideoLink(
            provider="microsoft", url=urlunparse(parts),
            embed_url=urlunparse(parts) if embeddable else None,
            thumbnail_url=None, is_embeddable=embeddable, is_direct_file=False,
        )

    if host.endswith("streamyard.com"):
        return VideoLink(
            provider="streamyard", url=urlunparse(parts), embed_url=None,
            thumbnail_url=None, is_embeddable=False, is_direct_file=False,
        )

    if host.startswith("meeting.zoho.") or host.startswith("zoho.") and "meeting" in (parts.path or ""):
        return VideoLink(
            provider="zoho", url=urlunparse(parts), embed_url=None,
            thumbnail_url=None, is_embeddable=False, is_direct_file=False,
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
