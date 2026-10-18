"""What the sidebar badge endpoint returns."""

from __future__ import annotations

from pydantic import Field

from backend.schemas.base import APIModel


class SidebarCountsResponse(APIModel):
    """Badge counts, keyed by menu item.

    A free-form mapping rather than a field per badge, deliberately: a key is
    present only when the caller is entitled to that number, and a model with
    fourteen optional integers would make "not entitled" and "happens to be
    null" the same thing on the wire.

    Keys, where the caller is entitled to them: `courses`, `batches`,
    `sessions`, `enrollments`, `assignments`, `quizzes`, `exams`,
    `announcements`, `messages`, `notifications`, `users`, `roles`,
    `permissions`, `guardians`.
    """

    counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Badge counts the caller may see. A missing key means the caller is "
            "not entitled to that number, or it does not apply to them -- it does "
            "not mean zero, and the console shows no badge for it."
        ),
    )
