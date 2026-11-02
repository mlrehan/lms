"""What every assessment response says about the caller's rights over it.

`can_manage` is filled per caller by `ownership_fields`, so the console can
decide whether to offer Edit, Publish/Unpublish and Delete without guessing
from a role. The server still checks each of those on the write; this only
decides what is offered.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AssessmentOwnershipFields(BaseModel):
    can_manage: bool = Field(
        default=False,
        description="The caller wrote it (or is unrestricted): may edit, publish, unpublish and delete it.",
    )


def ownership_fields(row: Any, actor: Any) -> dict[str, Any]:
    """The values above for one row and one caller."""
    from backend.services.assessment_access import AssessmentAccess

    return {"can_manage": AssessmentAccess.may_manage(row, actor)}
