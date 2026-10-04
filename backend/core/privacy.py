"""Who may see other people's contact details.

The rule, in one place: **only a holder of `user.view_contact` (the Super Admin) sees another person's
email address, phone number or login name; everyone else sees names.** Seeing your *own* details is always
allowed. Being related to someone does not change this -- a tutor does not get a student's email because the
student is in their batch, and a student does not get their tutor's.

Why login names are covered too: a synced account's username *is* its email address (54 of 77 today), so
hiding the `email` field while returning `username` would leak exactly the thing being protected. Wherever
a response used to carry `user.username` for display it now carries `visible_username(user)`, which is the
person's full name for a viewer who may not see the login name.

How the viewer is known: `api/deps.get_current_user` records who is asking in a context variable for the
duration of the request, so a response mapper deep in a router does not need the actor passed to it. With no
viewer recorded (a CLI job, a background task) the answer is *deny*: forgetting to set one hides details, it
never reveals them.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

CONTACT_PERMISSION = "user.view_contact"
PRICING_PERMISSION = "course.view_pricing"


@dataclass(frozen=True)
class Viewer:
    user_id: int
    public_id: uuid.UUID
    can_view_contact: bool
    can_view_pricing: bool = False


_viewer: ContextVar[Viewer | None] = ContextVar("privacy_viewer", default=None)


def set_viewer(user: Any) -> None:
    """Record who is making this request. `user.roles[*].permissions` must be loaded."""
    held = {p.name for role in (user.roles or []) for p in (role.permissions or [])}
    _viewer.set(
        Viewer(
            user_id=user.id,
            public_id=user.public_id,
            can_view_contact=CONTACT_PERMISSION in held,
            can_view_pricing=PRICING_PERMISSION in held,
        )
    )


def clear_viewer() -> None:
    _viewer.set(None)


def current_viewer() -> Viewer | None:
    return _viewer.get()


def may_see_contact(owner_public_id: uuid.UUID | None = None, owner_id: int | None = None) -> bool:
    """May the current viewer see the contact details of the person identified by either id?"""
    viewer = _viewer.get()
    if viewer is None:
        return False
    if viewer.can_view_contact:
        return True
    return (owner_public_id is not None and owner_public_id == viewer.public_id) or (owner_id is not None and owner_id == viewer.user_id)


def _full_name(user: Any) -> str:
    return getattr(user, "full_name", None) or getattr(user, "username", "") or ""


def visible_username(user: Any) -> str:
    """The login name for a viewer who may see it, otherwise the person's full name."""
    if user is None:
        return ""
    return user.username if may_see_contact(user.public_id, user.id) else _full_name(user)


def visible_email(user: Any) -> str | None:
    if user is None:
        return None
    return user.email if may_see_contact(user.public_id, user.id) else None


def visible_phone(user: Any, value: str | None) -> str | None:
    return value if user is not None and may_see_contact(user.public_id, user.id) else None


def may_see_pricing() -> bool:
    """May the current viewer see commercial terms?

    Nothing to own here, unlike contact details: a course price belongs to
    the institution, not to the person reading it, so there is no "your own"
    exception. Same fail-closed default -- no recorded viewer means no.
    """
    viewer = _viewer.get()
    return viewer is not None and viewer.can_view_pricing


def visible_price(value: Any) -> Any:
    """A course price for a viewer entitled to it, otherwise `None`.

    `None` rather than `0`: a course that costs nothing and a course whose
    price you may not see are different facts, and only one of them should
    read as "free".
    """
    return value if may_see_pricing() else None
