"""Who an assessment is set for by name, and how it changed after publication.

Both tables hang off any of the three assessment kinds. Rather than a
polymorphic ``(kind, id)`` pair -- which no foreign key can check -- each row
carries one nullable foreign key per kind and a CHECK that exactly one is set,
so deleting an assessment or a student removes its rows instead of leaving
them pointing at nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from .helpers import utc_datetime_column

#: The column on these tables that names each assessment kind.
KIND_COLUMN = {"assignment": "assignment_id", "quiz": "quiz_id", "exam": "exam_id"}

_EXACTLY_ONE = "num_nonnulls(assignment_id, quiz_id, exam_id) = 1"


def _kind_fk(table: str) -> Mapped[Optional[int]]:
    return mapped_column(Integer, ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=True)


class AssessmentRecipient(Base):
    """One student an assessment with ``scope = STUDENTS`` is set for.

    Covers a single student and a hand-picked group alike: a group is simply
    several rows. Recipients must be enrolled on the assessment's course -- the
    service checks that, because a recipient who is not would be set work for a
    course they cannot open.
    """

    __tablename__ = "assessment_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[Optional[int]] = _kind_fk("assignments")
    quiz_id: Mapped[Optional[int]] = _kind_fk("quizzes")
    exam_id: Mapped[Optional[int]] = _kind_fk("exams")
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    __table_args__ = (
        CheckConstraint(_EXACTLY_ONE, name="ck_assessment_recipients_one_assessment"),
        *(
            Index(
                f"uq_assessment_recipients_{col}_student", col, "student_id",
                unique=True, postgresql_where=text(f"{col} IS NOT NULL"),
            )
            for col in KIND_COLUMN.values()
        ),
    )


class AssessmentRevision(Base):
    """One change made to an assessment after it was published.

    ``changes`` is ``{field: {"from": old, "to": new}}``. ``material`` marks a
    change that alters what a student must do or by when -- the deadline, the
    marks, the brief -- and those are the ones students are told about;
    ``notified`` records how many were.
    """

    __tablename__ = "assessment_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[Optional[int]] = _kind_fk("assignments")
    quiz_id: Mapped[Optional[int]] = _kind_fk("quizzes")
    exam_id: Mapped[Optional[int]] = _kind_fk("exams")
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notified: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)

    __table_args__ = (
        CheckConstraint(_EXACTLY_ONE, name="ck_assessment_revisions_one_assessment"),
        *(
            Index(
                f"uq_assessment_revisions_{col}_no", col, "revision_no",
                unique=True, postgresql_where=text(f"{col} IS NOT NULL"),
            )
            for col in KIND_COLUMN.values()
        ),
    )
