"""The body sanitiser and the small text helpers: a message body is hostile until proven otherwise."""

from __future__ import annotations

import pytest

from backend.services.mail_html import clean_subject, sanitize_html, snippet, to_text
from backend.services.mail_service import safe_filename


@pytest.mark.parametrize("dangerous, must_not_contain", [
    ("<script>alert(1)</script>hello", "script"),
    ('<p onclick="steal()">hi</p>', "onclick"),
    ('<img src=x onerror="steal()">', "onerror"),
    ('<a href="javascript:steal()">click</a>', "javascript:"),
    ('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>', "data:"),
    ('<iframe src="https://evil.example"></iframe>', "iframe"),
    ('<form action="https://evil.example"><input name=pw></form>', "form"),
    ('<style>body{display:none}</style>x', "style"),
    ('<p style="position:fixed;inset:0">cover</p>', "style="),
    ("<svg onload=steal()></svg>", "svg"),
    ('<object data="x"></object>', "object"),
    ("<!-- <script>x</script> -->text", "<!--"),
])
def test_dangerous_markup_does_not_survive(dangerous: str, must_not_contain: str) -> None:
    assert must_not_contain not in sanitize_html(dangerous).lower()


def test_ordinary_formatting_is_kept() -> None:
    src = "<p>Hi <strong>there</strong>, <em>this</em> is <u>fine</u></p><ul><li>one</li></ul><blockquote>q</blockquote>"
    assert sanitize_html(src) == src


def test_links_keep_only_safe_schemes_and_are_forced_to_noopener() -> None:
    out = sanitize_html('<a href="https://ok.example/x" target="_blank" onclick="x()">ok</a> <a href="mailto:a@b.c">m</a> <a href="javascript:x()">bad</a>')
    assert 'href="https://ok.example/x"' in out and 'rel="noopener noreferrer nofollow"' in out
    assert "target" not in out and "onclick" not in out and "javascript" not in out and "mailto:a@b.c" in out


def test_control_and_bidi_override_characters_are_stripped() -> None:
    assert sanitize_html("a\x00b\u202ec") == "abc"
    assert clean_subject("Hi\u202e there\r\nBcc: victim@example.com") == "Hi there Bcc: victim@example.com"  # one line: no second header


def test_the_subject_is_one_bounded_line() -> None:
    assert "\n" not in clean_subject("a\nb\r\nc") and len(clean_subject("x" * 1000)) == 250


def test_plain_text_is_derived_with_line_breaks_and_no_markup() -> None:
    text = to_text(sanitize_html("<p>First &amp; second</p><p>Third<br>fourth</p><ul><li>a</li><li>b</li></ul>"))
    assert text == "First & second\nThird\nfourth\na\nb"


def test_snippet_is_flat_and_bounded() -> None:
    assert snippet("a\n\n b  c") == "a b c" and snippet("x" * 500).endswith("…") and len(snippet("x" * 500)) == 140


@pytest.mark.parametrize("raw, expected", [
    ("report.pdf", "report.pdf"), ("../../etc/passwd", "passwd"), ("C:\\Users\\me\\notes.txt", "notes.txt"), ("  ..hidden.txt.. ", "hidden.txt"),
    ("evil\u202egnp.exe", "evilgnp.exe"), ("", "attachment"), (None, "attachment"), ("a\x00b.txt", "ab.txt"),
])
def test_attachment_names_are_bare_and_printable(raw, expected) -> None:  # noqa: ANN001
    assert safe_filename(raw) == expected
