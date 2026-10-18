"""Maintaining the course-to-editor mapping.

Separate from `EditorService` because the two answer different questions and
have different audiences: one is "what should I see in my menu", asked on every
page load by everybody, and this one is "what is the rule", asked occasionally
by somebody who maintains the curriculum.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.errors import NotFoundError, ValidationError
from backend.models.administration import Category, CategoryEditor, CourseEditor
from backend.models.course import Course
from backend.models.identity.user import User
from backend.schemas.editors import CategoryEditorRow, CourseEditorRow, EditorMapping
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.editor_service import EDITORS


class EditorAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def mappings(self, *, actor: User) -> EditorMapping:
        categories = list(
            (
                await self.session.execute(select(Category).order_by(Category.name))
            ).scalars()
        )
        by_category: dict[int, list[str]] = {}
        for category_id, editor in await self.session.execute(
            select(CategoryEditor.category_id, CategoryEditor.editor)
        ):
            by_category.setdefault(category_id, []).append(editor)

        courses = list(
            (
                await self.session.execute(
                    select(Course)
                    .options(selectinload(Course.category))
                    .where(Course.is_deleted.is_(False))
                    .order_by(Course.title)
                )
            ).scalars()
        )
        by_course: dict[int, list[str]] = {}
        for course_id, editor in await self.session.execute(
            select(CourseEditor.course_id, CourseEditor.editor)
        ):
            by_course.setdefault(course_id, []).append(editor)

        # A course that names *any* editor of its own states its whole answer,
        # so "overridden" is membership of the override table, not whether the
        # list came back non-empty. Otherwise "this course needs no editor"
        # would be indistinguishable from "nothing set" and would silently
        # inherit the category it was overriding.
        overridden = set(by_course)

        return EditorMapping(
            categories=[
                CategoryEditorRow(
                    public_id=c.public_id,
                    name=c.name,
                    editors=sorted(by_category.get(c.id, [])),
                )
                for c in categories
            ],
            courses=[
                CourseEditorRow(
                    public_id=c.public_id,
                    title=c.title,
                    category=getattr(c.category, "name", None),
                    editors=sorted(
                        by_course.get(c.id)
                        if c.id in overridden
                        else by_category.get(c.category_id or -1, [])
                    ),
                    inherited=c.id not in overridden,
                )
                for c in courses
            ],
        )

    async def set_course_editors(
        self, course_public_id: str, editors: list[str], *, actor: User
    ) -> CourseEditorRow:
        course = await self._course(course_public_id)
        self._validate(editors)

        await self.session.execute(
            delete(CourseEditor).where(CourseEditor.course_id == course.id)
        )
        for editor in dict.fromkeys(editors):  # de-duplicate, keep order
            self.session.add(CourseEditor(course_id=course.id, editor=editor))

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="course_editors",
            entity_id=course.id,
            details={"editors": sorted(editors), "course": str(course.public_id)},
        )
        await self.session.flush()

        inherited_from_category = await self.session.execute(
            select(CategoryEditor.editor).where(
                CategoryEditor.category_id == course.category_id
            )
        )
        return CourseEditorRow(
            public_id=course.public_id,
            title=course.title,
            category=getattr(course.category, "name", None),
            editors=sorted(editors) if editors else sorted(inherited_from_category.scalars()),
            inherited=not editors,
        )

    async def set_category_editors(
        self, category_public_id: str, editors: list[str], *, actor: User
    ) -> None:
        category = (
            await self.session.execute(
                select(Category).where(Category.public_id == uuid.UUID(category_public_id))
            )
        ).scalar_one_or_none()
        if category is None:
            raise NotFoundError("Category not found.")
        self._validate(editors)

        await self.session.execute(
            delete(CategoryEditor).where(CategoryEditor.category_id == category.id)
        )
        for editor in dict.fromkeys(editors):
            self.session.add(CategoryEditor(category_id=category.id, editor=editor))

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="category_editors",
            entity_id=category.id,
            details={"editors": sorted(editors), "category": category.name},
        )

    async def _course(self, public_id: str) -> Course:
        row = (
            await self.session.execute(
                select(Course)
                .options(selectinload(Course.category))
                .where(Course.public_id == uuid.UUID(public_id))
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Course not found.")
        return row

    @staticmethod
    def _validate(editors: list[str]) -> None:
        unknown = [e for e in editors if e not in EDITORS]
        if unknown:
            # The column's CHECK would refuse these too; saying so here names
            # the offending value instead of surfacing a constraint violation.
            raise ValidationError(
                f"Unknown editor(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(sorted(EDITORS))}."
            )
