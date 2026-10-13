"""Sanitising the formatted text a tutor writes into an assessment.

An assignment brief and a quiz question are authored by one person and
rendered in the browser of everybody who is set them, so the same rule as a
message body applies: whatever the editor produced is a *request*, the server
re-parses it, and only the stored result is ever shown. Nothing downstream
re-sanitises, so this is the one place that matters.

**Why not just reuse `mail_html`.** A brief needs two things a message does
not -- tables, because a mark scheme or a data set is a table and writing one
as indented text is how it becomes unreadable, and code blocks with the
structure intact. Widening the mail allow-list to suit would widen it for
email too, where the narrower list is deliberate. So the primitives are shared
and the allow-list is not.

What still does not survive, for the same reasons as there: scripts, event
handlers, styles, iframes, forms, images and `javascript:` links. A link keeps
only an http(s) or mailto address and is forced to
`rel="noopener noreferrer nofollow"`.
"""

from __future__ import annotations

import nh3

from backend.services.mail_html import (
    ALLOWED_SCHEMES,
    MAX_BODY_CHARS,
    _CONTROL,
    to_text,
)

__all__ = ["sanitize_rich_text", "rich_text_to_plain", "RICH_TAGS"]

#: Everything the mail list allows, plus tables, the full heading range, and
#: the elements a code block is made of. `pre`/`code` were already there; what
#: is new is that the editor can now produce them deliberately.
RICH_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "strike",
    "ul", "ol", "li", "a", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "code", "hr",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
}

#: `colspan`/`rowspan` are structure, not styling -- a merged header cell that
#: loses its span stops lining up with the column it describes. They are
#: integers as far as the parser is concerned; `nh3` drops anything else.
#: `class` is deliberately absent: it is the usual way styling, and with it
#: CSS-driven behaviour, gets back in.
RICH_ATTRIBUTES = {
    "a": {"href"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "col": {"span"},
    "colgroup": {"span"},
    # The language a code block was written in, which is what a highlighter
    # reads. Restricted to `code` so it cannot be used as a styling hook on
    # anything else.
    "code": {"data-language"},
}


def sanitize_rich_text(raw: str | None) -> str:
    """Clean formatted HTML for storage. Returns `""` for nothing at all."""
    text = _CONTROL.sub("", (raw or "")[: MAX_BODY_CHARS * 2])
    if not text.strip():
        return ""
    cleaned = nh3.clean(
        text,
        tags=RICH_TAGS,
        attributes=RICH_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
    return cleaned[:MAX_BODY_CHARS]


def rich_text_to_plain(clean_html: str | None) -> str:
    """The same text with no markup, for search, exports and notifications.

    Shares `mail_html.to_text` rather than repeating it: turning block ends
    into newlines and decoding entities is the same problem, and solving it
    twice is how two screens end up disagreeing about where a line broke.
    """
    return to_text(clean_html or "")


def looks_like_html(value: str | None) -> bool:
    """Whether a stored value is formatted text or the plain text that
    predates this.

    Every assignment and question written before the editor existed holds
    plain text, and rendering that as HTML would silently eat anything with
    an angle bracket in it -- `x < 5` is ordinary in a question. Callers use
    this to decide whether to render or to print.
    """
    return bool(value) and "<" in value and ">" in value
