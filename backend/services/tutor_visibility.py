"""Which tutors a viewer may be shown on a course.

A student is shown *their* tutors (those who teach a batch they -- or someone in their care -- are enrolled
in), a tutor only themselves, and an administrator everyone. Showing a student every tutor assigned to a
course would list people they have no relationship with; showing a tutor their colleagues likewise.
"""

from __future__ import annotations

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.batch import Batch, BatchSession
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.services.scope import ScopeResolver
from backend.utils.enums import EnrollmentStatus

_LIVE = (EnrollmentStatus.PENDING, EnrollmentStatus.CONFIRMED, EnrollmentStatus.COMPLETED)


async def tutors_visible_to(session: AsyncSession, actor: User, course) -> list[User]:  # type: ignore[no-untyped-def]
    assigned: list[User] = list(course.tutors or [])
    if ScopeResolver.is_unrestricted(actor):
        return assigned

    visible: dict[int, User] = {t.id: t for t in assigned if t.id == actor.id}

    cared_for = (await ScopeResolver(session).enrollment_visibility(actor)).cared_for_student_ids
    if cared_for:
        rows = await session.execute(
            select(distinct(BatchSession.tutor_id))
            .join(Batch, Batch.id == BatchSession.batch_id)
            .join(Enrollments, Enrollments.batch_id == Batch.id)
            .where(Batch.course_id == course.id, Enrollments.student_id.in_(cared_for), Enrollments.status.in_(_LIVE), BatchSession.cancelled_at.is_(None))
        )
        ids = {r for (r,) in rows.all()} - set(visible)
        if ids:
            for user in (await session.execute(select(User).where(User.id.in_(ids)))).scalars():
                visible[user.id] = user
    return sorted(visible.values(), key=lambda u: (u.first_name or "", u.last_name or "", u.username))
