"""Turning what a browser sent into HTML that is safe to show to everybody it is sent to.

A message body is authored by one person and rendered in the browser of every recipient (and put in an email),
so it is treated as hostile: whatever the composer produced, the server re-parses it and keeps only a short list
of formatting tags. Scripts, event handlers, styles, iframes, forms, images and `javascript:` links do not
survive; a link keeps only an http(s) or mailto address and is forced to `rel="noopener noreferrer nofollow"`.

The sanitised HTML is what is stored. Nothing downstream re-sanitises it, so this is the one place that matters.
"""

from __future__ import annotations

import html
import re

import nh3

ALLOWED_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "s", "strike", "ul", "ol", "li", "a", "blockquote", "h1", "h2", "h3", "pre", "code", "hr"}
ALLOWED_ATTRIBUTES = {"a": {"href"}}
ALLOWED_SCHEMES = {"http", "https", "mailto"}
MAX_BODY_CHARS = 200_000
SUBJECT_MAX = 250

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]")
_BLOCK_END = re.compile(r"</(p|div|li|h[1-6]|blockquote|pre|tr)>|<br\s*/?>|<hr\s*/?>", re.IGNORECASE)


def sanitize_html(raw: str | None) -> str:
    text = _CONTROL.sub("", (raw or "")[: MAX_BODY_CHARS * 2])
    cleaned = nh3.clean(
        text,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )
    return cleaned[:MAX_BODY_CHARS]


def to_text(clean_html: str) -> str:
    """Plain text from already-sanitised HTML: block ends become newlines, tags go, entities are decoded."""
    spaced = _BLOCK_END.sub("\n", clean_html)
    stripped = nh3.clean(spaced, tags=set())
    text = html.unescape(stripped)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_subject(raw: str | None) -> str:
    """One line, no control or bidirectional-override characters (they can disguise or split a header)."""
    one_line = _CONTROL.sub("", (raw or "")).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", one_line).strip()[:SUBJECT_MAX]


def snippet(text: str, length: int = 140) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"
