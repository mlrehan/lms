"""What a tutor observed in a class (spec §11).

`GradeComponentType` has had a `PRACTICAL` member since the grade book was
built, and nothing ever produced a row behind it. This is that source.

**One row per student per session, with the criteria as columns.** The obvious
alternative -- a row per criterion -- was rejected: §11's screen is a grid where
a tutor fills in a whole class at once, so a per-criterion shape would mean
eight inserts per student and a pivot on every read, to gain flexibility nobody
asked for. Institutions that need their own criteria get `custom_scores`, a
JSON map, rather than a schema change.

**Scores are out of a stated maximum, not a fixed ten.** A tutor who marks
participation out of 5 and practical work out of 20 is doing something ordinary,
and normalising at entry time would throw away what they actually wrote.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    Text,
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, PublicIdMixin
from backend.utils.enums import ResultState

from .helpers import utc_datetime_column


class ClassPerformanceMark(Base, PublicIdMixin):
    """A tutor's assessment of one student in one class session."""

    __tablename__ = "class_performance_marks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("batch_sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # The named criteria from §11. Each is nullable because a tutor assessing
    # participation only should not be forced to invent a presentation mark --
    # and a nulled criterion is excluded from the average rather than counted
    # as zero, which is the same rule the engine applies everywhere else.
    participation: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    interaction: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    preparation: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    practical: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    presentation: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    teamwork: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    communication: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    professionalism: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)

    # Institution-specific criteria, as {name: score}. Deliberately not a
    # schema change per institution, and deliberately not where the eight named
    # criteria above live -- those are queried, aggregated and shown as columns.
    custom_scores: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    max_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("10"), server_default="10",
        comment="What each criterion above is marked out of.",
    )
    # The tutor's own overall figure for the class, if they would rather give
    # one than have it averaged from the criteria. Null means "compute it".
    overall_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)

    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Same lifecycle as every other mark (§14): a tutor's working notes are not
    # something a guardian should be reading.
    state: Mapped[ResultState] = mapped_column(
        SQLEnum(ResultState, name="result_state", native_enum=False),
        nullable=False,
        default=ResultState.DRAFT,
        server_default=ResultState.DRAFT.value,
    )

    recorded_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    recorded_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(onupdate=True)

    session: Mapped["BatchSession"] = relationship(  # noqa: F821
        "BatchSession", lazy="selectin"
    )
    student: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[student_id], lazy="selectin"
    )

    __table_args__ = (
        # One assessment per student per session. Re-entering a mark corrects
        # the row; a second row would double the student's class-performance
        # contribution, the same failure the grade book's partial indexes exist
        # to prevent.
        UniqueConstraint("session_id", "student_id", name="uq_class_perf_session_student"),
        CheckConstraint("max_score > 0", name="ck_class_perf_max_positive"),
        Index("ix_class_perf_student", "student_id"),
        Index("ix_class_perf_session", "session_id"),
    )
