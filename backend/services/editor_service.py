"""Which code editors to offer this person, and why.

**The decision is stored, never guessed from a title.** Matching course names
for "python" or "sql" is the obvious implementation and is wrong in both
directions: "Agentic AI & Automation", "Teens Coding" and "Power BI for
Business" carry no usable word, while a course called "Python-free Data
Literacy" would be matched exactly backwards. Which tool a course needs is a
curriculum fact, so somebody who knows the curriculum records it.

**Two levels, because courses arrive on their own.** The sync pipeline creates
courses from LAIT on a schedule. A per-course decision would be permanently
out of date for anything new, so the rule lives on the category -- structured
metadata an administrator already maintains -- and a course inherits it.
`course_editors` is the exception, for a course with no category or one whose
category is right about its siblings and wrong about it.

**An editor is offered for courses you are actually doing or teaching**, not
for the catalogue. A guardian and a corporate manager are watching somebody
else do the work; they are offered nothing, because a link to a code editor
they have no exercise in is a support question waiting to happen.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.administration import CategoryEditor, CourseEditor
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.services.scope import ScopeResolver
from backend.utils.enums import EnrollmentStatus

#: The editors this build knows how to open, and where they live.
#:
#: Constants rather than settings: they are the institution's own tools at
#: fixed addresses, and a deployment that needed different ones would need a
#: different mapping vocabulary too -- the `editor` column's CHECK constraint
#: names these two, so a new editor is a migration either way.
EDITORS: dict[str, dict[str, str]] = {
    "sql": {"label": "SQL Editor", "url": "https://sql.lait.co/"},
    "python": {"label": "Python Editor", "url": "https://py.lait.co/"},
}


@dataclass(frozen=True)
class EditorLink:
    key: str
    label: str
    url: str


class EditorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.scopes = ScopeResolver(session)

    async def for_user(self, *, actor: User) -> list[EditorLink]:
        """The editors this person's own courses call for.

        One query for the course ids, one for the mappings -- the resolution
        between them is a set operation rather than a lookup per course, so a
        student on two courses and an administrator over forty cost the same
        two round trips.
        """
        course_ids = await self._working_course_ids(actor)
        if course_ids is None:  # unrestricted: any mapped course counts
            keys = set(
                (await self.session.execute(select(CourseEditor.editor))).scalars()
            ) | set(
                (await self.session.execute(select(CategoryEditor.editor))).scalars()
            )
        elif not course_ids:
            return []
        else:
            keys = await self._editors_for(course_ids)

        return [
            EditorLink(key=key, label=EDITORS[key]["label"], url=EDITORS[key]["url"])
            for key in ("sql", "python")
            if key in keys
        ]

    async def _working_course_ids(self, actor: User) -> set[int] | None:
        """Courses this person studies or teaches. `None` means "all of them".

        Not `visible_course_ids`: that answers which courses' *internals* are
        the caller's business, which includes a corporate manager's roster. The
        question here is narrower -- whose exercises are these.
        """
        if ScopeResolver.is_unrestricted(actor):
            return None

        studying = select(Batch.course_id).join(
            Enrollments, Enrollments.batch_id == Batch.id
        ).where(
            Enrollments.student_id == actor.id,
            Enrollments.status == EnrollmentStatus.CONFIRMED,
        )
        teaching = select(Batch.course_id).join(
            BatchSession, BatchSession.batch_id == Batch.id
        ).where(BatchSession.tutor_id == actor.id)

        rows = await self.session.execute(union(studying, teaching))
        return {cid for (cid,) in rows if cid is not None}

    async def _editors_for(self, course_ids: set[int]) -> set[str]:
        """A course's own rows win; otherwise it inherits its category's."""
        overridden = await self.session.execute(
            select(CourseEditor.course_id, CourseEditor.editor).where(
                CourseEditor.course_id.in_(course_ids)
            )
        )
        by_course: dict[int, set[str]] = {}
        for course_id, editor in overridden:
            by_course.setdefault(course_id, set()).add(editor)

        inherited = await self.session.execute(
            select(Course.id, CategoryEditor.editor)
            .join(CategoryEditor, CategoryEditor.category_id == Course.category_id)
            .where(Course.id.in_(course_ids))
        )
        keys: set[str] = set()
        for course_id, editor in inherited:
            # The override is per course, not per editor: a course that names
            # any editor of its own is stating its whole answer, so inheriting
            # the rest would make "this course needs only Python" impossible to
            # express for a course in an SQL category.
            if course_id not in by_course:
                keys.add(editor)
        for editors in by_course.values():
            keys |= editors
        return keys
