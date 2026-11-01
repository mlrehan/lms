"""Who teaches a batch -- the one rule, for the Batches page and the assistant alike.

A batch has no tutor of its own. Its *classes* do (`batch_sessions.tutor_id`),
and they need not all share one. Separately, a course can name tutors
(`tutor_courses`), which grants them sight of the course; the LAIT sync never
fills that table, so for synced batches it is usually empty.

The Batches page shows the tutor who teaches the most non-cancelled classes.
That figure used to be computed twice -- once for the list, once for the
detail page -- with no tie-break in either, and the assistant had no way to
reach it at all. Asked "who teaches Maxim's batches?", it joined
`tutor_courses`, found nothing for two of three batches, and reported "no
tutor currently assigned" for batches whose every class had one.

So this module answers with **every source, labelled**, and a status that
says what the answer is worth:

* ``ASSIGNED``        -- classes exist and have a tutor; ``primary`` is the
                         Batches-page tutor.
* ``UNASSIGNED``      -- classes exist and none of them has a tutor. This is
                         the only state that may be described as "no tutor".
* ``NOT_APPLICABLE``  -- no classes scheduled yet, so there is nobody to name;
                         course-level tutors, if any, are still listed.
* ``SOURCE_CONFLICT`` -- course-level tutors are named and the class tutor is
                         not among them. Both are reported; neither wins
                         silently.

Ties on class count go to the tutor whose first class is earliest, then to the
lower id, so the same data always gives the same name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.batch import Batch, BatchSession
from backend.models.course import TutorCourse
from backend.models.identity.user import User

ASSIGNED = "ASSIGNED"
UNASSIGNED = "UNASSIGNED"
NOT_APPLICABLE = "NOT_APPLICABLE"
SOURCE_CONFLICT = "SOURCE_CONFLICT"


def _name(user: User) -> str:
    return f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unnamed account"


@dataclass
class ClassTutor:
    user_id: int
    name: str
    classes: int


@dataclass
class BatchTutors:
    batch_id: int
    status: str
    primary_id: int | None = None
    primary_name: str | None = None
    session_tutors: list[ClassTutor] = field(default_factory=list)
    course_tutors: list[str] = field(default_factory=list)
    classes_total: int = 0
    classes_without_tutor: int = 0

    def as_dict(self) -> dict[str, Any]:
        """What a tool hands the model: every source named, nothing inferred."""
        return {
            "status": self.status,
            "batch_tutor": self.primary_name,
            "batch_tutor_rule": "the tutor who teaches the most non-cancelled classes (as on the Batches page)",
            "class_tutors": [{"name": t.name, "classes": t.classes} for t in self.session_tutors],
            "course_level_tutors": self.course_tutors,
            "classes_total": self.classes_total,
            "classes_without_tutor": self.classes_without_tutor,
        }


async def tutors_for_batches(session: AsyncSession, batch_ids: Sequence[int]) -> dict[int, BatchTutors]:
    """Every source of "who teaches this batch", for many batches in three queries."""
    ids = list(dict.fromkeys(batch_ids))
    if not ids:
        return {}
    live = (BatchSession.batch_id.in_(ids), BatchSession.cancelled_at.is_(None))

    totals: dict[int, list[int]] = {bid: [0, 0] for bid in ids}
    per_tutor: dict[int, list[tuple[int, int, Any]]] = {bid: [] for bid in ids}
    rows = (await session.execute(
        select(BatchSession.batch_id, BatchSession.tutor_id, func.count(), func.min(BatchSession.session_start_time))
        .where(*live).group_by(BatchSession.batch_id, BatchSession.tutor_id)
    )).all()
    for bid, tid, n, first in rows:
        totals[bid][0] += int(n)
        if tid is None:
            totals[bid][1] += int(n)
        else:
            per_tutor[bid].append((tid, int(n), first))

    course_of = dict((await session.execute(select(Batch.id, Batch.course_id).where(Batch.id.in_(ids)))).all())
    course_rows = (await session.execute(
        select(TutorCourse.course_id, TutorCourse.tutor_id).where(TutorCourse.course_id.in_(set(course_of.values())))
    )).all()
    by_course: dict[int, set[int]] = {}
    for cid, tid in course_rows:
        by_course.setdefault(cid, set()).add(tid)

    people_ids = {t for lst in per_tutor.values() for t, _, _ in lst} | {t for s in by_course.values() for t in s}
    people = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(people_ids)))).scalars().unique()} \
        if people_ids else {}

    out: dict[int, BatchTutors] = {}
    for bid in ids:
        ranked = sorted(per_tutor[bid], key=lambda r: (-r[1], r[2] is None, r[2], r[0]))
        session_tutors = [ClassTutor(t, _name(people[t]) if t in people else "Unknown account", n) for t, n, _ in ranked]
        course_ids = by_course.get(course_of.get(bid), set())
        course_tutors = sorted(_name(people[t]) for t in course_ids if t in people)
        total, untutored = totals[bid]
        primary = session_tutors[0] if session_tutors else None
        if total == 0:
            status = NOT_APPLICABLE
        elif primary is None:
            status = UNASSIGNED
        elif course_ids and primary.user_id not in course_ids:
            status = SOURCE_CONFLICT
        else:
            status = ASSIGNED
        out[bid] = BatchTutors(
            batch_id=bid, status=status,
            primary_id=primary.user_id if primary else None, primary_name=primary.name if primary else None,
            session_tutors=session_tutors, course_tutors=course_tutors,
            classes_total=total, classes_without_tutor=untutored,
        )
    return out
