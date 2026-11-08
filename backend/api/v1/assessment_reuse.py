"""Operations every assessment kind shares: reuse, named recipients, revisions.

One router over ``/assessments/{kind}/{id}`` rather than three copies of each
route. ``kind`` is ``assignments``, ``quizzes`` or ``exams``. Every route
loads the assessment through that kind's own service ``get``, so the
visibility rules (a colleague's work, another batch's work) answer 404 here
exactly as they do on the kind's own pages.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, status
from sqlalchemy import select

from backend.api.deps import CurrentUser, resolve_permissions
from backend.core.errors import AuthorizationError, ValidationError
from backend.core.notification_types import NotificationType
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession, commit_before_responding
from backend.models.assessment_links import KIND_COLUMN, AssessmentRevision
from backend.models.identity.user import User
from backend.schemas.assessment_reuse import (
    AssessmentCopyRef,
    AssessmentCopyRequest,
    AssessmentCopyResponse,
    NameableStudent,
    RecipientRef,
    RecipientsResponse,
    RecipientsUpdateRequest,
    RevisionResponse,
)
from backend.services import audit_service
from backend.services.assessment_access import AssessmentAccess
from backend.services.assessment_reuse import AssessmentReuseService, CopyTarget
from backend.services.assessment_scope import AssessmentScopeResolver
from backend.services.notification_service import NotificationService
from backend.services.audit_service import AuditAction
from backend.utils.enums import AssessmentScope, AssessmentState

router = APIRouter(tags=["Assessment reuse"])

Kind = Literal["assignments", "quizzes", "exams"]
_MODULE = {"assignments": Module.ASSIGNMENT, "quizzes": Module.QUIZ, "exams": Module.EXAM}
_PUBLISHED_TYPE = {
    "assignments": NotificationType.ASSIGNMENT_PUBLISHED,
    "quizzes": NotificationType.QUIZ_PUBLISHED,
    "exams": NotificationType.EXAM_SCHEDULED,
}
_LINK = {"assignments": "assignment_id", "quizzes": "quiz_id", "exams": "exam_id"}


def _require(actor: User, kind: Kind, action: str) -> None:
    needed = perm(_MODULE[kind], action)
    if needed not in resolve_permissions(actor):
        raise AuthorizationError(f"You need the {needed} permission.")


async def _load(session: Any, kind: Kind, public_id: uuid.UUID, actor: User) -> Any:
    if kind == "assignments":
        from backend.services.assignment_service import AssignmentService

        return await AssignmentService(session).get(public_id, actor=actor)
    if kind == "quizzes":
        from backend.services.quiz_service import QuizService

        return await QuizService(session).get(public_id, actor=actor)
    from backend.services.exam_service import ExamService

    return await ExamService(session).get(public_id, actor=actor)


def _published(row: Any) -> bool:
    state = getattr(row, "state", None)
    if state is not None:
        return state is AssessmentState.PUBLISHED
    return bool(getattr(row, "is_published", False))


def _name(user: User) -> str:
    # Names only: a login name is usually an email address.
    return " ".join(p for p in (user.first_name, user.last_name) if p) or "Unnamed account"


@router.post(
    "/assessments/{kind}/{assessment_id}/copies",
    response_model=AssessmentCopyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reuse an assessment for other batches, sessions, courses or students",
)
async def copy_assessment(
    kind: Kind, assessment_id: uuid.UUID, payload: AssessmentCopyRequest,
    session: DBSession, actor: CurrentUser,
) -> AssessmentCopyResponse:
    """Each target gets its own copy -- own recipients, deadline, state,
    submissions and marks -- linked back through `copied_from_id`. All or
    nothing. Drafts unless `publish` is true; a published copy notifies its
    own students, and only them."""
    _require(actor, kind, Action.CREATE)
    targets = [
        CopyTarget(scope=t.scope, course_id=t.course_id, batch_id=t.batch_id,
                   session_id=t.session_id, student_ids=t.student_ids)
        for t in payload.targets
    ]
    reuse = AssessmentReuseService(session)
    if kind == "assignments":
        rows = await reuse.copy_assignment(
            assessment_id, targets, actor=actor, due_date=payload.due_date, publish=payload.publish)
    elif kind == "quizzes":
        if payload.publish:
            _require(actor, kind, Action.PUBLISH)
        rows = await reuse.copy_quiz(assessment_id, targets, actor=actor, publish=payload.publish)
    else:
        if payload.publish:
            _require(actor, kind, Action.PUBLISH)
        rows = await reuse.copy_exam(
            assessment_id, targets, actor=actor, scheduled_at=payload.scheduled_at, publish=payload.publish)
    response = AssessmentCopyResponse(copies=[
        AssessmentCopyRef(public_id=r.public_id, title=r.title, scope=r.scope, published=_published(r))
        for r in rows
    ])
    await commit_before_responding(session)
    return response


@router.get(
    "/assessments/nameable-students",
    response_model=list[NameableStudent],
    summary="Students the caller may set work for by name on a course",
)
async def nameable_students(course_id: uuid.UUID, session: DBSession, actor: CurrentUser) -> list[NameableStudent]:
    """The picker for scope STUDENTS, drawn by the same rule the write applies:
    an active seat on the course, in a class the caller teaches (any class for
    an unrestricted caller). Names and the caller's own class codes only."""
    from backend.models.batch import Batch
    from backend.models.course import Course
    from backend.models.enrollment import Enrollments
    from backend.repositories.enrollment import ACTIVE_STATUSES
    from backend.services.scope import ScopeResolver

    perms = resolve_permissions(actor)
    if not {perm(m, Action.CREATE) for m in _MODULE.values()} & perms:
        raise AuthorizationError("You cannot set coursework.")
    stmt = (
        select(User, Batch.batch_code)
        .join(Enrollments, Enrollments.student_id == User.id)
        .join(Batch, Batch.id == Enrollments.batch_id)
        .join(Course, Course.id == Batch.course_id)
        .where(Course.public_id == course_id, Enrollments.status.in_(ACTIVE_STATUSES))
    )
    if not ScopeResolver.is_unrestricted(actor):
        taught = (await ScopeResolver(session).enrollment_visibility(actor)).taught_batch_ids
        stmt = stmt.where(Batch.id.in_(taught or {-1}))
    people: dict[int, NameableStudent] = {}
    for user, code in (await session.execute(stmt.limit(2000))).all():
        entry = people.setdefault(user.id, NameableStudent(public_id=user.public_id, name=_name(user), batch_codes=[]))
        if code and code not in entry.batch_codes:
            entry.batch_codes.append(code)
    return sorted(people.values(), key=lambda p: p.name.lower())


@router.get(
    "/assessments/{kind}/{assessment_id}/recipients",
    response_model=RecipientsResponse,
    summary="Who an assessment set for named students is for",
)
async def list_recipients(
    kind: Kind, assessment_id: uuid.UUID, session: DBSession, actor: CurrentUser,
) -> RecipientsResponse:
    """Staff only: a student is not shown who else was set the same work."""
    _require(actor, kind, Action.UPDATE)
    row = await _load(session, kind, assessment_id, actor)
    ids = await AssessmentScopeResolver(session).recipients_of(row)
    users = (await session.execute(select(User).where(User.id.in_(ids or [-1])))).scalars().all()
    return RecipientsResponse(
        scope=row.scope,
        recipients=sorted((RecipientRef(public_id=u.public_id, name=_name(u)) for u in users),
                          key=lambda r: r.name.lower()),
    )


@router.put(
    "/assessments/{kind}/{assessment_id}/recipients",
    response_model=RecipientsResponse,
    summary="Replace the students an assessment is set for",
)
async def replace_recipients(
    kind: Kind, assessment_id: uuid.UUID, payload: RecipientsUpdateRequest,
    session: DBSession, actor: CurrentUser,
) -> RecipientsResponse:
    """Only for scope STUDENTS, only by the author (or an unrestricted caller).
    Recorded as a revision; on published work, students newly added are told
    it has been set for them. Students removed keep anything they already
    submitted -- their work and marks are never deleted."""
    _require(actor, kind, Action.UPDATE)
    row = await _load(session, kind, assessment_id, actor)
    if not AssessmentAccess.may_manage(row, actor):
        raise AuthorizationError("Only the tutor who set this can change who it is for.")
    if row.scope is not AssessmentScope.STUDENTS:
        raise ValidationError("Only work set for named students has a list of students to change.")
    targets = AssessmentScopeResolver(session)
    before = set(await targets.recipients_of(row))
    after = await targets.recipient_ids(row.course_id, payload.student_ids, actor=actor)
    await targets.set_recipients(row, after, actor_id=actor.id)
    added = sorted(set(after) - before)
    if before != set(after):
        column = getattr(AssessmentRevision, KIND_COLUMN[_LINK[kind].removesuffix("_id")])
        last = (await session.execute(
            select(AssessmentRevision.revision_no).where(column == row.id)
            .order_by(AssessmentRevision.revision_no.desc()).limit(1)
        )).scalar_one_or_none()
        notified = 0
        if _published(row) and added:
            notified = await NotificationService(session).notify_many(
                added, type_=_PUBLISHED_TYPE[kind], title=f"Set for you: {row.title}",
                body="This was set for you by your tutor. Open it for the details.",
                meta={_LINK[kind]: str(row.public_id)},
            )
        session.add(AssessmentRevision(
            **{KIND_COLUMN[_LINK[kind].removesuffix("_id")]: row.id},
            revision_no=(last or 0) + 1, changed_by=actor.id,
            changes={"recipients": {"from": len(before), "to": len(after),
                                    "added": len(added), "removed": len(before - set(after))}},
            material=False, notified=notified,
        ))
        audit_service.record(
            session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email,
            entity_type=_LINK[kind].removesuffix("_id"), entity_id=row.id,
            details={"recipients": len(after), "added": len(added), "removed": len(before - set(after))},
        )
    await session.flush()
    response = await list_recipients(kind, assessment_id, session, actor)
    await commit_before_responding(session)
    return response


@router.get(
    "/assessments/{kind}/{assessment_id}/revisions",
    response_model=list[RevisionResponse],
    summary="What changed after publication, from what to what",
)
async def list_revisions(
    kind: Kind, assessment_id: uuid.UUID, session: DBSession, actor: CurrentUser,
) -> list[RevisionResponse]:
    _require(actor, kind, Action.UPDATE)
    row = await _load(session, kind, assessment_id, actor)
    column = getattr(AssessmentRevision, KIND_COLUMN[_LINK[kind].removesuffix("_id")])
    revisions = (await session.execute(
        select(AssessmentRevision, User)
        .outerjoin(User, User.id == AssessmentRevision.changed_by)
        .where(column == row.id)
        .order_by(AssessmentRevision.revision_no.desc())
    )).all()
    return [
        RevisionResponse(
            revision_no=r.revision_no, changed_at=r.created_at, changed_by=_name(u) if u else None,
            material=r.material, notified=r.notified, changes=r.changes,
        )
        for r, u in revisions
    ]
