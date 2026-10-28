"""What a tool result may carry, decided once, for every tool.

Each tool is written to return only what its caller may see, and most now do.
This is the net under them: every result passes through `redact_tool_result`
before it reaches the model, the browser's stream or saved history -- so one
tool forgetting the rule leaks nothing, and a new tool cannot leak by omission.

The rule is `core/privacy.py`'s, unchanged: only a holder of
`user.view_contact` (the Super Admin) sees other people's email addresses,
phone numbers or login names. For everyone else:

* fields named for contact details are removed outright;
* email-shaped text inside any other string is replaced. Login names here are
  frequently email addresses, and a message such as "enrolled jane@corp.com"
  carries one in prose where no field name gives it away.

The caller's own details are withheld too. That costs nothing -- a person does
not need the assistant to tell them their own email -- and a filter that tried
to tell "yours" from "someone else's" inside free text would get it wrong.
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.privacy import current_viewer

# Fields whose value is a contact detail or a login name.
CONTACT_KEYS = frozenset({
    "email",
    "emails",
    "user_email",
    "student_email",
    "employee_email",
    "parent_email",
    "guardian_email",
    "tutor_email",
    "phone",
    "phone_number",
    "mobile",
    "mobile_number",
    "emergency_contact",
    "emergency_contact_name",
    "emergency_contact_phone",
    "username",
    "student_username",
    "guardian_username",
    "tutor_username",
    "login",
})

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
WITHHELD = "[contact withheld]"


def _may_see_contact() -> bool:
    viewer = current_viewer()
    return viewer is not None and viewer.can_view_contact


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if str(k).lower() not in CONTACT_KEYS}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return _EMAIL.sub(WITHHELD, value)
    return value


def redact_tool_result(result: Any) -> Any:
    """Return `result` as the current viewer may see it.

    No recorded viewer means redact: forgetting to set one hides details, it
    never reveals them -- the same default as `core/privacy.py`.
    """
    if _may_see_contact():
        return result
    return _scrub(result)
