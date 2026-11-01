"""Who decides that examinations are 45% (spec §6, §13).

The most consequential configuration in the academic system: saving a scheme
silently changes every affected student's result at once. That is why it needs
`grading_scheme.manage`, why that permission belongs to the Super Admin alone,
and why activation is a deliberate step rather than a side effect of editing.

**A scheme is validated when it is activated, not on every edit.** Weights are
entered one row at a time, so a "must total 100" constraint on the table would
refuse every intermediate state and make the editor unusable. The check runs at
the moment the scheme starts affecting people, which is the moment it matters.

**The institution's default is created empty by the migration, on purpose.**
Inventing "examinations are 45%" on an institution's behalf would re-grade
everybody the instant they upgraded. An empty scheme makes the engine report
"not yet configured" -- true and actionable -- rather than a confident wrong
number.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.core.performance import Band, ComponentWeight, Scheme
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.gradebook import GradeBand
from backend.models.grading import GradingScheme, GradingSchemeComponent
from backend.models.identity.user import User
from backend.services import audit_service
from backend.services.audit_service import AuditAction

_HUNDRED = Decimal("100")
#: Floating-point-free, but weights are entered by hand and "99.99" is a typo,
#: not a policy. A tolerance of a hundredth lets a scheme built from thirds
#: (33.33 × 3) activate without the operator hunting for the missing penny.
_TOLERANCE = Decimal("0.05")


class SchemeSource(str, Enum):
    """Where a batch's scheme came from -- shown beside it, so nobody has to guess."""

    BATCH = "BATCH"
    COURSE = "COURSE"
    DEFAULT = "DEFAULT"
    NONE = "NONE"


class GradingSchemeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reading -------------------------------------------------------------

    async def list_schemes(self) -> Sequence[GradingScheme]:
        stmt = select(GradingScheme).order_by(
            GradingScheme.is_default.desc(), GradingScheme.name
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def get(self, public_id: uuid.UUID) -> GradingScheme:
        row = (
            await self.session.execute(
                select(GradingScheme).where(GradingScheme.public_id == public_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Grading scheme not found.")
        return row

    async def default_scheme(self) -> GradingScheme | None:
        return (
            await self.session.execute(
                select(GradingScheme).where(GradingScheme.is_default.is_(True))
            )
        ).scalar_one_or_none()

    async def resolve(
        self, *, course_id: int, batch_id: int | None = None
    ) -> tuple[GradingScheme | None, SchemeSource]:
        """The scheme a batch (or a course) is graded under, and where it came from.

        Batch override, then course override, then the institution's default.
        Resolved in exactly one place so that results, reports and transcripts
        cannot come to disagree about which scheme a student is marked under.

        An override pointing at an inactive scheme is skipped rather than
        honoured: an inactive scheme has not had its weights checked.
        """
        if batch_id is not None:
            row = (
                await self.session.execute(
                    select(GradingScheme)
                    .join(Batch, Batch.grading_scheme_id == GradingScheme.id)
                    .where(Batch.id == batch_id, GradingScheme.is_active.is_(True))
                )
            ).scalar_one_or_none()
            if row is not None:
                return row, SchemeSource.BATCH

        row = (
            await self.session.execute(
                select(GradingScheme)
                .join(Course, Course.grading_scheme_id == GradingScheme.id)
                .where(Course.id == course_id, GradingScheme.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if row is not None:
            return row, SchemeSource.COURSE

        row = await self.default_scheme()
        return row, (SchemeSource.DEFAULT if row is not None else SchemeSource.NONE)

    async def for_course(self, course_id: int) -> GradingScheme | None:
        """The course's own scheme, or the institution's -- ignoring batch overrides."""
        return (await self.resolve(course_id=course_id))[0]

    async def for_batch(self, batch_id: int) -> GradingScheme | None:
        course_id = (
            await self.session.execute(select(Batch.course_id).where(Batch.id == batch_id))
        ).scalar_one_or_none()
        if course_id is None:
            raise NotFoundError("Batch not found.")
        return (await self.resolve(course_id=course_id, batch_id=batch_id))[0]

    # -- assigning -----------------------------------------------------------

    async def _assignable(self, scheme_public_id: uuid.UUID | None) -> GradingScheme | None:
        if scheme_public_id is None:
            return None
        row = await self.get(scheme_public_id)
        if not row.is_active:
            # An inactive scheme's weights have never been checked against 100,
            # and `resolve` would skip it anyway -- accepting it would record an
            # assignment that silently does nothing.
            raise ConflictError("Activate the scheme before assigning it.")
        return row

    async def assign_to_course(
        self, course_public_id: uuid.UUID, scheme_public_id: uuid.UUID | None, *, actor: User
    ) -> Course:
        """Point a course at a scheme, or back at the institution default (None)."""
        course = (
            await self.session.execute(select(Course).where(Course.public_id == course_public_id))
        ).scalar_one_or_none()
        if course is None or course.deleted_at is not None:
            raise NotFoundError("Course not found.")
        scheme = await self._assignable(scheme_public_id)
        previous = await self._name_of(course.grading_scheme_id)
        course.grading_scheme_id = scheme.id if scheme else None
        await self.session.flush()
        audit_service.record(
            self.session, action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="course", entity_id=course.id,
            details={"grading_scheme": scheme.name if scheme else None, "previous": previous},
        )
        return course

    async def assign_to_batch(
        self, batch_public_id: uuid.UUID, scheme_public_id: uuid.UUID | None, *, actor: User
    ) -> Batch:
        """Point a batch at a scheme, or back at its course's (None)."""
        batch = (
            await self.session.execute(select(Batch).where(Batch.public_id == batch_public_id))
        ).scalar_one_or_none()
        if batch is None:
            raise NotFoundError("Batch not found.")
        scheme = await self._assignable(scheme_public_id)
        previous = await self._name_of(batch.grading_scheme_id)
        batch.grading_scheme_id = scheme.id if scheme else None
        await self.session.flush()
        audit_service.record(
            self.session, action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="batch", entity_id=batch.id,
            details={"grading_scheme": scheme.name if scheme else None, "previous": previous},
        )
        return batch

    async def _name_of(self, scheme_id: int | None) -> str | None:
        if scheme_id is None:
            return None
        return (
            await self.session.execute(select(GradingScheme.name).where(GradingScheme.id == scheme_id))
        ).scalar_one_or_none()

    async def usage(self, scheme_id: int) -> tuple[list[tuple], list[tuple]]:
        """The courses and batches that name this scheme as their own.

        Columns, not entities: both models eager-load a great deal, and this
        only needs a label to show beside the scheme.
        """
        courses = (
            await self.session.execute(
                select(Course.public_id, Course.title)
                .where(Course.grading_scheme_id == scheme_id, Course.deleted_at.is_(None))
                .order_by(Course.title)
            )
        ).all()
        batches = (
            await self.session.execute(
                select(Batch.public_id, Batch.batch_code, Course.title)
                .join(Course, Course.id == Batch.course_id)
                .where(Batch.grading_scheme_id == scheme_id)
                .order_by(Batch.batch_code)
            )
        ).all()
        return list(courses), list(batches)

    # -- the engine's view ---------------------------------------------------

    async def as_engine_scheme(self, row: GradingScheme | None) -> Scheme:
        """Translate a stored scheme into what `core.performance` expects.

        The engine deliberately knows nothing about SQLAlchemy -- it takes
        plain values so it can be tested without a database. This is the one
        place that bridges the two, so the translation cannot drift between
        callers.
        """
        if row is None:
            # No scheme at all. The engine reports `unconfigured` rather than
            # returning zero, and every screen then says so.
            return Scheme(components=[], bands=[])

        return Scheme(
            components=[
                ComponentWeight(
                    component_type=c.component_type,
                    weight_percentage=Decimal(c.weight_percentage),
                    label=c.label,
                    is_mandatory=c.is_mandatory,
                    passing_percentage=(
                        Decimal(c.passing_percentage) if c.passing_percentage is not None else None
                    ),
                )
                for c in (row.components or [])
            ],
            bands=[
                Band(
                    min_score=Decimal(b.min_score),
                    max_score=Decimal(b.max_score),
                    letter_grade=b.letter_grade,
                    gpa_points=Decimal(b.gpa_points),
                    is_pass=b.is_pass,
                )
                for b in (row.bands or [])
            ],
            passing_percentage=Decimal(row.passing_percentage),
            missing_mark_policy=row.missing_mark_policy,
        )

    # -- writing -------------------------------------------------------------

    async def create(
        self, *, actor: User, name: str, description: str | None = None, **fields
    ) -> GradingScheme:
        existing = (
            await self.session.execute(select(GradingScheme).where(GradingScheme.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("A grading scheme with that name already exists.")

        row = GradingScheme(
            name=name,
            description=description,
            created_at=datetime.now(UTC),
            created_by=actor.id,
            # Never default on creation. Becoming the institution's default is
            # a separate, deliberate act -- a new scheme silently taking over
            # every course would re-grade the institution by accident.
            is_default=False,
            # And never active. A new scheme has no components yet, so it can
            # only produce "unconfigured"; `activate` is where the weights are
            # checked and where it becomes usable.
            #
            # Defaulted here rather than by the route passing `is_active=False`.
            # A route compensating for a service default is fragile: anything
            # calling the service directly -- a script, a fixture, a future
            # caller -- silently got an active scheme, which is exactly how
            # this was found.
            is_active=fields.pop("is_active", False),
            **fields,
        )
        row.components = []
        row.bands = []
        self.session.add(row)
        await self.session.flush()

        audit_service.record(
            self.session, action=AuditAction.CREATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="grading_scheme", entity_id=row.id,
            details={"name": name},
        )
        return row

    async def set_components(
        self, public_id: uuid.UUID, components: Sequence[dict], *, actor: User
    ) -> GradingScheme:
        """Replace the scheme's weightings wholesale.

        Wholesale rather than one at a time because the set is what has to add
        up: applying five edits individually means four intermediate states
        that do not total 100, and a concurrent reader would see one of them.
        """
        row = await self.get(public_id)

        seen: set = set()
        for c in components:
            if c["component_type"] in seen:
                raise ValidationError(
                    "Each component may appear only once.",
                    details={"component": str(c["component_type"])},
                )
            seen.add(c["component_type"])

        previous = {c.component_type: str(c.weight_percentage) for c in (row.components or [])}
        row.components.clear()
        for c in components:
            row.components.append(
                GradingSchemeComponent(
                    component_type=c["component_type"],
                    label=c.get("label"),
                    weight_percentage=Decimal(str(c["weight_percentage"])),
                    is_mandatory=bool(c.get("is_mandatory", False)),
                    passing_percentage=(
                        Decimal(str(c["passing_percentage"]))
                        if c.get("passing_percentage") is not None
                        else None
                    ),
                )
            )
        row.updated_at = datetime.now(UTC)
        await self.session.flush()

        audit_service.record(
            self.session, action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="grading_scheme", entity_id=row.id,
            details={
                "weights": {str(k): v for k, v in previous.items()},
                "new_weights": {
                    str(c.component_type): str(c.weight_percentage) for c in row.components
                },
                "total": str(self.total_weight(row)),
            },
        )
        return row

    @staticmethod
    def total_weight(row: GradingScheme) -> Decimal:
        return sum((Decimal(c.weight_percentage) for c in (row.components or [])), Decimal("0"))

    async def activate(self, public_id: uuid.UUID, *, actor: User) -> GradingScheme:
        """Make a scheme usable, refusing one whose weights do not add up.

        This is the moment a scheme starts deciding people's results, so it is
        the moment the total is checked. Refusing earlier would make the editor
        unusable; refusing later would mean never.
        """
        row = await self.get(public_id)
        total = self.total_weight(row)

        if not row.components:
            raise ValidationError(
                "A scheme with no components cannot be activated — every student "
                "would score nothing."
            )
        if abs(total - _HUNDRED) > _TOLERANCE:
            raise ValidationError(
                "The component weights must total 100%.",
                details={"total": str(total), "short_by": str(_HUNDRED - total)},
            )

        row.is_active = True
        row.updated_at = datetime.now(UTC)
        audit_service.record(
            self.session, action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="grading_scheme", entity_id=row.id,
            details={"activated": True, "total": str(total)},
        )
        return row

    async def make_default(self, public_id: uuid.UUID, *, actor: User) -> GradingScheme:
        """Hand the institution's default over to this scheme.

        The previous default is cleared first, in the same transaction: the
        partial unique index permits exactly one, so setting the new one before
        clearing the old would be refused by the database.
        """
        row = await self.get(public_id)
        if not row.is_active:
            raise ConflictError("Activate the scheme before making it the default.")

        current = await self.default_scheme()
        if current is not None and current.id != row.id:
            current.is_default = False
            await self.session.flush()

        row.is_default = True
        audit_service.record(
            self.session, action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="grading_scheme", entity_id=row.id,
            details={"made_default": True,
                     "previous": current.name if current else None},
        )
        return row

    async def set_bands(
        self, public_id: uuid.UUID, bands: Sequence[dict], *, actor: User
    ) -> GradingScheme:
        """Replace the grade ladder.

        Overlapping bands are refused: a mark of 80 falling into both "A" and
        "B" makes the grade depend on row order, which is not a decision
        anybody made.
        """
        row = await self.get(public_id)

        ordered = sorted(bands, key=lambda b: Decimal(str(b["min_score"])))
        for lower, upper in zip(ordered, ordered[1:]):
            if Decimal(str(lower["max_score"])) >= Decimal(str(upper["min_score"])):
                raise ValidationError(
                    "Grade bands must not overlap.",
                    details={"overlap": f"{lower['letter_grade']} and {upper['letter_grade']}"},
                )

        row.bands.clear()
        for b in ordered:
            row.bands.append(
                GradeBand(
                    min_score=Decimal(str(b["min_score"])),
                    max_score=Decimal(str(b["max_score"])),
                    letter_grade=b["letter_grade"],
                    gpa_points=Decimal(str(b["gpa_points"])),
                    is_pass=bool(b.get("is_pass", True)),
                )
            )
        await self.session.flush()

        audit_service.record(
            self.session, action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="grading_scheme", entity_id=row.id,
            details={"bands": len(row.bands)},
        )
        return row
