"""What the console may render in place, and what it must only hand over.

This allowlist is a security decision with no test until now. It decides which
uploaded bytes the browser is asked to open, and the two halves of it are
reasoned about in opposite directions:

* `image/svg+xml` and `text/html` are **excluded even though browsers render
  them perfectly** -- both can carry script, and served inline they execute in
  this origin, turning "preview the file a tutor shared" into session theft.
* the two OOXML types are **included even though browsers cannot render them**
  -- the console unzips and parses them itself, builds elements from the
  result, and hands nothing to `innerHTML`, so there is nothing for the browser
  to interpret.

Which means neither half can be derived from the other, and a future edit that
"tidies" the list by adding the obvious renderable types would reintroduce the
hole. Hence the explicit exclusions below.
"""

from __future__ import annotations

import pytest

from backend.services.resource_service import ResourceService

#: Rendered inline by the browser itself, from a `src`.
NATIVE = [
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "video/mp4",
    "video/webm",
    "text/plain",
    "text/csv",
]

#: Read by the console's own parsers, never by the browser.
PARSED = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/tab-separated-values",
]


@pytest.mark.parametrize("mime", NATIVE + PARSED)
def test_the_viewer_can_open_what_it_claims_to(mime: str) -> None:
    assert ResourceService.is_previewable(mime)


@pytest.mark.parametrize("mime", ["image/svg+xml", "text/html", "application/xhtml+xml"])
def test_a_type_that_can_carry_script_is_never_rendered(mime: str) -> None:
    """The whole reason this is an allowlist.

    An SVG is a document, not a picture: served inline it runs its own script
    at this origin, with this session's cookies. Both are still downloadable --
    withheld from the viewer, not from the person.
    """
    assert not ResourceService.is_previewable(mime)


@pytest.mark.parametrize(
    "mime",
    [
        # The legacy binary formats are not ZIPs, so the console's readers
        # cannot open them. Admitting them would replace a clear "download this
        # to open it" with a parse error.
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
        "application/octet-stream",
    ],
)
def test_a_type_nothing_can_render_is_offered_as_a_download(mime: str) -> None:
    assert not ResourceService.is_previewable(mime)


def test_a_charset_parameter_does_not_defeat_the_check() -> None:
    """Browsers send `text/plain; charset=utf-8`, and a naive membership test
    would refuse every text file that arrived with its encoding stated."""
    assert ResourceService.is_previewable("text/plain; charset=utf-8")
    assert ResourceService.is_previewable("  TEXT/CSV  ")
    # And the parameter cannot be used to smuggle an excluded type past it.
    assert not ResourceService.is_previewable("text/html; charset=utf-8")


def test_an_unknown_or_missing_type_is_refused() -> None:
    assert not ResourceService.is_previewable(None)
    assert not ResourceService.is_previewable("")
