"""The code editors a person's own courses call for.

Authentication only, like the dashboard: the answer is derived from courses the
caller is already enrolled on or teaching, so there is nothing here to gate
that is not already scoped.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.schemas.editors import (
    CourseEditorRow,
    EditorLinkResponse,
    EditorMapping,
    SetCourseEditorsRequest,
)
from backend.services.editor_service import EDITORS, EditorService
from backend.services.editor_admin_service import EditorAdminService

router = APIRouter(tags=["Editors"])

_COURSE_UPDATE = perm(Module.COURSE, Action.UPDATE)


@router.get(
    "/editors",
    response_model=list[EditorLinkResponse],
    summary="Code editors for my courses",
)
async def my_editors(
    session: DBSession,
    actor: CurrentUser,
) -> list[EditorLinkResponse]:
    """Empty when none of the caller's courses needs one.

    A guardian or corporate manager gets nothing: they are watching somebody
    else do the work, and a link to a code editor they have no exercise in is
    a support question rather than a feature.
    """
    links = await EditorService(session).for_user(actor=actor)
    return [
        EditorLinkResponse(key=link.key, label=link.label, url=link.url)
        for link in links
    ]


@router.get(
    "/editors/mappings",
    response_model=EditorMapping,
    summary="Which categories and courses need an editor",
)
async def mappings(
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(_COURSE_UPDATE))],
) -> EditorMapping:
    """The administrable rule, and every course's effective answer."""
    return await EditorAdminService(session).mappings(actor=actor)


@router.put(
    "/editors/courses/{course_id}",
    response_model=CourseEditorRow,
    summary="Set the editors for one course",
)
async def set_course_editors(
    course_id: str,
    payload: SetCourseEditorsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(_COURSE_UPDATE))],
) -> CourseEditorRow:
    """Replaces this course's own rows.

    Sending an empty list clears the override, so the course goes back to
    inheriting its category -- which is a different state from "needs no
    editor", and the response says which one it ended up in.
    """
    return await EditorAdminService(session).set_course_editors(
        course_id, payload.editors, actor=actor
    )


@router.put(
    "/editors/categories/{category_id}",
    response_model=EditorMapping,
    summary="Set the editors a category's courses inherit",
)
async def set_category_editors(
    category_id: str,
    payload: SetCourseEditorsRequest,
    session: DBSession,
    actor: Annotated[CurrentUser, Depends(require_permissions(_COURSE_UPDATE))],
) -> EditorMapping:
    """Changes what every course in the category inherits, including ones the
    sync has not created yet. Courses with their own rows are unaffected."""
    await EditorAdminService(session).set_category_editors(
        category_id, payload.editors, actor=actor
    )
    return await EditorAdminService(session).mappings(actor=actor)


@router.get("/editors/available", response_model=list[EditorLinkResponse])
async def available_editors(actor: CurrentUser) -> list[EditorLinkResponse]:
    """The vocabulary, so an admin screen can offer the right checkboxes."""
    return [
        EditorLinkResponse(key=key, label=meta["label"], url=meta["url"])
        for key, meta in EDITORS.items()
    ]
