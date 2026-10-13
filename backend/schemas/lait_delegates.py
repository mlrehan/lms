"""What the console is told about LAIT's corporate managers and their students.

These are **read-through** views of the external system, not stored records:
nothing here is persisted, and the shapes mirror what LAIT returns rather than
what this database holds. The LMS's own equivalent is `manager_students`,
which is a different thing -- an administrator's assertion about who looks
after whom, used for access control. These two endpoints answer "what does
the upstream system currently say?", which is the question somebody
reconciling the two actually has.

**The email address is the decision in this file.** A manager row carries
`username`, which is their email. It is returned only to a caller holding
`user.view_contact` and is `None` for everybody else, the same rule
`core/privacy.py` applies to every other directory in this console. The field
exists in the schema either way, so a client does not have to guess whether
an absent key means "no address" or "not allowed"; `None` means withheld.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from backend.schemas.base import APIModel


class DelegateManagerResponse(APIModel):
    """One corporate manager, as LAIT holds them."""

    customer_id: int = Field(
        description="LAIT's own id, and the key the delegates endpoint takes."
    )
    unique_key: str | None = Field(default=None, description="LAIT's GUID for this manager.")
    full_name: str | None = Field(
        default=None, description="Title, first, middle and last, as one line."
    )
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    designation: str | None = Field(default=None, description="Their job title at that company.")
    is_active: bool | None = None
    date_created: datetime | None = None
    date_modified: datetime | None = None
    email: str | None = Field(
        default=None,
        description=(
            "Only for callers holding `user.view_contact`. `None` means "
            "withheld, not absent -- the same rule every other directory in "
            "this console follows."
        ),
    )


class DelegateResponse(APIModel):
    """One student under a manager, as LAIT holds them."""

    customer_id: int = Field(description="The manager this delegate belongs to.")
    student_id: int | None = Field(default=None, description="LAIT's own student id.")
    unique_key: str | None = Field(default=None, description="LAIT's GUID for this delegate.")
    delegate_name: str | None = None
    status_id: int | None = None
    status_details: str | None = Field(
        default=None, description='LAIT\'s own wording, e.g. "Active".'
    )
    date_added: datetime | None = None


class DelegateListResponse(APIModel):
    """A manager's delegates, with the manager named.

    Wrapped rather than returned as a bare list so that "this manager has
    nobody" is expressible. A bare `[]` would be indistinguishable from a
    manager LAIT has never heard of -- and upstream *does* distinguish them,
    answering 404 for the second.
    """

    customer_id: int
    count: int
    delegates: list[DelegateResponse] = Field(default_factory=list)
