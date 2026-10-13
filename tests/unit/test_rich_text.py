"""What survives being written into an assignment brief or a quiz question.

The editor is a *request*. A brief is authored by one person and rendered in
the browser of everybody set the work, and the console renders it with
`dangerouslySetInnerHTML` -- which is correct only because this runs first and
nothing re-sanitises afterwards. So the allow-list is the whole control, and
both halves of it are tested: what must survive (or the feature does not
exist) and what must not (or the feature is an XSS hole).
"""

from __future__ import annotations

import pytest

from backend.services.rich_text import (
    looks_like_html,
    rich_text_to_plain,
    sanitize_rich_text,
)


@pytest.mark.parametrize(
    ("raw", "must_contain"),
    [
        ("<p>Hello <strong>world</strong></p>", "<strong>world</strong>"),
        ("<ul><li>One</li></ul>", "<li>One</li>"),
        ("<h2>Task</h2>", "<h2>Task</h2>"),
        ("<blockquote>Quoted</blockquote>", "<blockquote>"),
        # The two things an assessment needs that a message does not.
        ("<pre><code>print(1)</code></pre>", "<pre><code>print(1)</code></pre>"),
        (
            '<table><thead><tr><th colspan="2">Marks</th></tr></thead>'
            "<tbody><tr><td>A</td><td>1</td></tr></tbody></table>",
            '<th colspan="2">Marks</th>',
        ),
    ],
)
def test_the_formatting_a_brief_needs_survives(raw: str, must_contain: str) -> None:
    assert must_contain in sanitize_rich_text(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script>",
        '<p onclick="steal()">text</p>',
        '<img src=x onerror=alert(1)>',
        '<iframe src="https://evil.test"></iframe>',
        '<form action="https://evil.test"><input name="p"></form>',
        '<style>body{display:none}</style>',
        '<svg onload="alert(1)"></svg>',
    ],
)
def test_nothing_that_can_run_survives(raw: str) -> None:
    cleaned = sanitize_rich_text(raw)
    for banned in ("<script", "onclick", "onerror", "onload", "<iframe", "<form", "<style", "<svg"):
        assert banned not in cleaned.lower(), cleaned


def test_a_javascript_link_loses_its_address_but_keeps_its_words() -> None:
    """Dropping the whole element would silently delete text a tutor wrote;
    dropping the address is what makes it harmless."""
    cleaned = sanitize_rich_text('<a href="javascript:alert(1)">click me</a>')
    assert "javascript:" not in cleaned
    assert "click me" in cleaned


def test_an_ordinary_link_keeps_its_address_and_gains_its_rel() -> None:
    cleaned = sanitize_rich_text('<a href="https://example.test">docs</a>')
    assert 'href="https://example.test"' in cleaned
    assert "noopener" in cleaned


def test_styling_hooks_are_stripped_while_structure_is_kept() -> None:
    """`colspan` is structure -- a merged header that loses its span stops
    lining up with the column it describes. `class` and `style` are not, and
    are the usual way CSS-driven behaviour gets back in."""
    cleaned = sanitize_rich_text(
        '<table><tr><td class="evil" style="color:red" colspan="3">c</td></tr></table>'
    )
    assert 'colspan="3"' in cleaned
    assert "class=" not in cleaned
    assert "style=" not in cleaned


def test_nothing_at_all_is_an_empty_string_not_empty_markup() -> None:
    """The editor emits `<p></p>` for an untouched field, and storing that
    makes "has a description" true for every assignment ever created."""
    assert sanitize_rich_text(None) == ""
    assert sanitize_rich_text("   ") == ""


def test_plain_text_is_recoverable_for_exports_and_notifications() -> None:
    assert rich_text_to_plain("<p>One</p><p>Two</p>") == "One\nTwo"
    assert rich_text_to_plain(None) == ""


def test_text_written_before_the_editor_existed_is_recognised_as_text() -> None:
    """`x < 5` is an ordinary thing to write in a question, and handing it to
    an HTML renderer eats the rest of the line."""
    assert looks_like_html("<p>formatted</p>")
    assert not looks_like_html("Solve for x where x < 5")
    assert not looks_like_html("plain words")
    assert not looks_like_html(None)
