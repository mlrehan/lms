"""How a percentage is arrived at, and what it is called (spec §6, §7, §13).

Two things lived nowhere before this module, and their absence is why the grade
book's "weighted average" was a straight average:

* **The weighting policy.** `gradebook_entries.weight` existed and every synced
  row was written with `1`, because there was no table saying what a weight
  should be. §6 requires "Assignments 15%, Examinations 45%..." to be
  configurable per course, and explicitly forbids hard-coding it.
* **The grade scale.** `grade_bands` was a single flat global table, so every
  course was scored on the same A+/A/B ladder with no way to override it.

A **scheme** answers both at once, because they are the same decision: an
institution that weights examinations at 45% and one that grades on a 4.0 GPA
are describing one academic policy, and splitting it across two unrelated
configuration screens invites the two halves to be edited out of step.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sqlalchemy import text

from backend.models.base import Base, PublicIdMixin
from backend.utils.enums import (
    GradeComponentType,
    GradeScaleType,
    MissingMarkPolicy,
)

from .helpers import bool_column, utc_datetime_column


class GradingScheme(Base, PublicIdMixin):
    """One academic policy: what counts, how much, and what to call the result.

    Institution-wide by default. A course may point at a different one
    (`courses.grading_scheme_id`), which is §13's "a Course may optionally
    override the system default".
    """

    __tablename__ = "grading_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    scale_type: Mapped[GradeScaleType] = mapped_column(
        SQLEnum(GradeScaleType, name="grade_scale_type", native_enum=False),
        nullable=False,
        default=GradeScaleType.PERCENTAGE,
        server_default=GradeScaleType.PERCENTAGE.value,
    )

    # What the engine does with a component that has no mark yet. Configurable
    # because institutions genuinely differ and the wrong default produces a
    # confidently wrong number -- see `MissingMarkPolicy`.
    missing_mark_policy: Mapped[MissingMarkPolicy] = mapped_column(
        SQLEnum(MissingMarkPolicy, name="missing_mark_policy", native_enum=False),
        nullable=False,
        default=MissingMarkPolicy.EXCLUDE,
        server_default=MissingMarkPolicy.EXCLUDE.value,
    )

    # The overall mark a student must reach. Separate from a component's own
    # passing mark: passing every assignment and failing the course overall is
    # a coherent outcome, and so is the reverse.
    passing_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("50"), server_default="50"
    )

    # Exactly one scheme is the institution's default. Enforced by the partial
    # unique index below rather than by convention, because two defaults is a
    # state in which no code can say which one applies.
    is_default: Mapped[bool] = bool_column(
        default=False, comment="The institution-wide scheme. Exactly one row may set this."
    )
    is_active: Mapped[bool] = bool_column(default=True)

    created_at: Mapped[datetime] = utc_datetime_column(nullable=False)
    updated_at: Mapped[Optional[datetime]] = utc_datetime_column(onupdate=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    components: Mapped[List["GradingSchemeComponent"]] = relationship(
        "GradingSchemeComponent",
        back_populates="scheme",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="GradingSchemeComponent.component_type",
    )
    # `GradeBand` stays in `gradebook.py`, where it already lived; it gained a
    # `scheme_id` rather than being moved, so nothing that imports it breaks.
    bands: Mapped[List["GradeBand"]] = relationship(  # noqa: F821
        "GradeBand",
        back_populates="scheme",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="GradeBand.min_score.desc()",
    )

    __table_args__ = (
        # Exactly one default, enforced by the database. A partial unique index
        # over a boolean is the standard shape: it constrains only the rows
        # where `is_default` is true, so any number of non-default schemes may
        # exist. Two defaults is a state in which no code can say which scheme
        # applies to a course that has not overridden one.
        Index(
            "uq_grading_schemes_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index("ix_grading_schemes_active", "is_active"),
    )


class GradingSchemeComponent(Base, PublicIdMixin):
    """One weighted slice of a scheme: "Examinations are 45%".

    Weights are stored as percentages out of 100 rather than fractions, because
    that is how they are written down, discussed and audited -- and a stored
    `0.45` displayed as `45%` is one formatting mistake away from being read as
    forty-five hundredths of a percent.

    The total is **not** constrained to 100 in the database. A scheme is edited
    one row at a time, so a constraint would refuse every intermediate state and
    make the editor unusable; the service validates the total when the scheme is
    activated, which is the moment it starts affecting anybody.
    """

    __tablename__ = "grading_scheme_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grading_schemes.id", ondelete="CASCADE"), nullable=False
    )
    component_type: Mapped[GradeComponentType] = mapped_column(
        SQLEnum(GradeComponentType, name="grade_component_type", native_enum=False),
        nullable=False,
    )
    # Shown in the drill-down (§37), so it is worth being able to say
    # "Coursework" rather than "ASSIGNMENT" in a transcript.
    label: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    weight_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0"
    )

    # A component may be required to pass in its own right ("you must pass the
    # final examination regardless of your coursework").
    is_mandatory: Mapped[bool] = bool_column(default=False)
    passing_percentage: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )

    scheme: Mapped[GradingScheme] = relationship(GradingScheme, back_populates="components")

    __table_args__ = (
        # One weighting per component per scheme. Two rows for ASSIGNMENT would
        # make the total ambiguous and the drill-down wrong.
        UniqueConstraint("scheme_id", "component_type", name="uq_scheme_component"),
        CheckConstraint(
            "weight_percentage >= 0 AND weight_percentage <= 100",
            name="ck_scheme_component_weight_range",
        ),
    )

