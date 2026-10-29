"""Assignments and submissions (spec §12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import UploadFile

from backend.core.logging import get_logger
from backend.core.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from backend.models.assignment import (
    Assignment,
    AssignmentSubmission,
    AssignmentSubmissionFile,
)
from backend.models.enrollment import Enrollments
from backend.models.batch import Batch
from backend.models.identity.user import User
from backend.repositories.assignment import AssignmentRepository, SubmissionRepository
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentUpdateRequest,
    GradeSubmissionRequest,
    SubmitAssignmentRequest,
)
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.rich_text import sanitize_rich_text
from backend.storage import get_storage
from backend.storage.base import build_key
from backend.core.notification_types import NotificationType
from backend.services.audit_service import AuditAction
from backend.services.integration_service import WebhookEvent, WebhookService
from backend.services.gradebook_service import GradeBookService
from backend.services.notification_service import NotificationService
from backend.services.course_service import CourseService
from backend.services.assessment_scope import (
    AssessmentScopeResolver,
    AssessmentTarget,
    validate as validate_scope,
)
from backend.services.scope import ScopeResolver
from backend.utils.enums import (
    AssessmentScope,
    AssessmentState,
    GradeComponentType,
    SubmissionState,
    SubmissionType,
)


logger = get_logger(__name__)

#: Work a mark has already been put against. Replacing or withdrawing any of
#: it would silently invalidate that mark, so all three paths -- re-submit,
#: attach, remove -- ask the same question of the same set.
_MARKED_STATES = frozenset(
    {SubmissionState.GRADED, SubmissionState.PUBLISHED, SubmissionState.REASSESSED}
)



class AssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assignments = AssignmentRepository(session)
        self.submissions = SubmissionRepository(session)
        self.courses = CourseService(session)
        self.scopes = ScopeResolver(session)
        # §3's shared eligibility rule. Assignments, quizzes and examinations
        # all resolve their audience through this one resolver rather than
        # each keeping a copy that can drift.
        self.targets = AssessmentScopeResolver(session)

    # -- assignments ---------------------------------------------------------

    async def list_assignments(
        self,
        params: PageParams,
        *,
        actor: User,
        course_public_id: uuid.UUID | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[Assignment], int]:
        course_id = None
        if course_public_id is not None:
            course_id = (await self.courses.get(course_public_id, actor=actor)).id

        scope = await self.scopes.visible_course_ids(actor)
        return await self.assignments.search(params, scope=scope, course_id=course_id, query=query)

    async def get(self, public_id: uuid.UUID, *, actor: User) -> Assignment:
        row = await self.assignments.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Assignment not found.")

        scope = await self.scopes.visible_course_ids(actor)
        if not scope.allows(row.course_id):
            raise NotFoundError("Assignment not found.")
        return row

    async def create(
        self, course_public_id: uuid.UUID, payload: AssignmentCreateRequest, *, actor: User
    ) -> Assignment:
        course = await self.courses.get(course_public_id, actor=actor)

        # Reading an assignment is scoped by `visible_course_ids` and creating one was not, so a tutor could set
        # coursework on a colleague's course and then neither see nor delete it -- `get`, `update` and `delete`
        # all answer 404 for exactly that row -- while its students were notified. Same predicate as the reads,
        # which is the point: a write must not reach further than the read that would show its result.
        #
        # 403 rather than the reads' 404: the course catalogue is deliberately unscoped (see
        # `ScopeResolver.visible_course_ids`), so the course's existence is already public and there is nothing
        # to conceal. What the caller lacks is standing to teach it, and saying so is actionable.
        scope = await self.scopes.visible_course_ids(actor)
        if not scope.allows(course.id):
            raise AuthorizationError("You can only set coursework on a course you teach.")

        # §3: an assignment may be set for the whole course, one batch, or one
        # class. The scope is resolved (and its ids derived) before the row is
        # built, so a session-scoped assignment cannot end up carrying a course
        # id from a different course.
        target = await self.targets.resolve_ids(
            scope=payload.scope,
            course_id=course.id,
            batch_id=await self.targets.batch_id(payload.batch_id),
            session_id=await self.targets.session_id(payload.session_id),
        )
        validate_scope(target)
        if target.course_id != course.id:
            # The batch or session named belongs to a different course than the
            # one this assignment is being created under. Refusing is the only
            # safe answer: silently following the derived course would put the
            # work on a roster the tutor never chose.
            raise ValidationError("That batch or session belongs to a different course.")

        row = Assignment(
            course_id=course.id,
            scope=target.scope,
            batch_id=target.batch_id,
            session_id=target.session_id,
            state=payload.state,
            publish_at=payload.publish_at,
            available_from=payload.available_from,
            passing_score=payload.passing_score,
            weight=payload.weight,
            allowed_file_types=payload.allowed_file_types,
            max_upload_mb=payload.max_upload_mb,
            allow_multiple_submissions=payload.allow_multiple_submissions,
            allow_resubmission=payload.allow_resubmission,
            late_penalty_percent_per_day=payload.late_penalty_percent_per_day,
            title=payload.title,
            # Formatted text, so it is re-parsed here rather than trusted.
            # The console composes it; the server decides what is stored, and
            # nothing downstream re-sanitises -- `rich_text` is the one place.
            description=sanitize_rich_text(payload.description) or None,
            instructions_path=payload.instructions_path,
            due_date=payload.due_date,
            max_score=payload.max_score,
            submission_type=payload.submission_type,
            rubric=payload.rubric,
            allow_late_submissions=payload.allow_late_submissions,
        )
        await self.assignments.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=row.id,
            details={"title": row.title, "course": course.title},
        )

        # A draft is not announced. §8 allows saving work before it is ready,
        # and announcing it the moment it is saved would defeat the point --
        # `publish` sends the notification when the tutor is ready.
        if row.state is not AssessmentState.PUBLISHED:
            roster = []

        # The one fan-out in the system, and it is bounded by a course
        # roster. An announcement is the mechanism for anything wider -- see
        # `MAX_FANOUT` in the notification service for where the line is.
        # Only the students it is actually set for. Notifying the whole course
        # about batch-scoped work is how a student learns about an assignment
        # they cannot open -- and it was unavoidable while every assignment was
        # course-wide.
        roster = sorted(await self.targets.eligible_student_ids(target))
        notifications = NotificationService(self.session)
        await notifications.notify_many(
            roster,
            type_=NotificationType.ASSIGNMENT_PUBLISHED,
            title=f"New assignment: {row.title}",
            body=f"{course.title} — due {row.due_date:%d %b %Y}.",
            meta={"assignment_id": str(row.public_id), "course_id": str(course.public_id)},
        )
        await notifications.notify_guardians_of(
            roster,
            type_=NotificationType.WARD_ASSIGNMENT_PUBLISHED,
            title=f"New assignment for {{student}}: {row.title}",
            body=f"{course.title} — due {row.due_date:%d %b %Y}.",
            meta={"assignment_id": str(row.public_id), "course_id": str(course.public_id)},
        )

        # One webhook for the event, where the notification above fanned out
        # to the roster: a receiver wants to know the assignment exists, not
        # to be told once per enrolled student.
        await WebhookService(self.session).enqueue(
            WebhookEvent.ASSIGNMENT_PUBLISHED,
            {
                "event": WebhookEvent.ASSIGNMENT_PUBLISHED,
                "assignment_id": str(row.public_id),
                "course_id": str(course.public_id),
                "title": row.title,
                "due_date": row.due_date.isoformat() if row.due_date else None,
            },
        )

        return await self.assignments.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: AssignmentUpdateRequest, *, actor: User
    ) -> Assignment:
        row = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        new_max = changes.get("max_score")
        if new_max is not None:
            # Lowering max_score below a mark already awarded would leave a
            # submission scoring more than the assignment is worth.
            highest = (
                await self.session.execute(
                    select(AssignmentSubmission.grade)
                    .where(
                        AssignmentSubmission.assignment_id == row.id,
                        AssignmentSubmission.grade.is_not(None),
                    )
                    .order_by(AssignmentSubmission.grade.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if highest is not None and Decimal(new_max) < Decimal(highest):
                raise ConflictError(
                    "max_score cannot be lower than a grade already awarded.",
                    details={"highest_awarded": str(highest), "requested_max": str(new_max)},
                )

        if "description" in changes:
            changes["description"] = sanitize_rich_text(changes["description"]) or None

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        return row

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)

        count = await self.assignments.count_submissions(row.id)
        if count:
            # Submissions carry students' work and their marks; deleting the
            # assignment out from under them destroys both.
            raise ConflictError(
                "This assignment already has submissions and cannot be deleted.",
                details={"submissions": count},
            )

        entity_id = row.id
        await self.session.delete(row)
        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=entity_id,
        )

    # -- submissions ---------------------------------------------------------

    async def list_submissions(
        self,
        params: PageParams,
        *,
        actor: User,
        assignment_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
        graded: bool | None = None,
    ) -> tuple[Sequence[AssignmentSubmission], int]:
        assignment_id = None
        if assignment_public_id is not None:
            assignment_id = (await self.get(assignment_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        visibility = await self.scopes.work_visibility(actor)
        return await self.submissions.search(
            params,
            visibility=visibility,
            assignment_id=assignment_id,
            student_id=student_id,
            graded=graded,
        )

    async def get_submission(
        self, public_id: uuid.UUID, *, actor: User
    ) -> AssignmentSubmission:
        row = await self.submissions.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Submission not found.")

        visibility = await self.scopes.work_visibility(actor)
        if not visibility.unrestricted:
            reachable = (
                row.assignment.course_id in visibility.taught_course_ids
                or row.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Submission not found.")
        return row

    # -- attachments ---------------------------------------------------------

    async def files_for_submissions(
        self, submission_ids: Sequence[int]
    ) -> dict[int, list[AssignmentSubmissionFile]]:
        """`{submission_id: [files]}` for a page of submissions, in one query.

        A per-row lookup would be one query per student on a roster of forty,
        which is the shape of the problem `performance_service` was rewritten
        to avoid.
        """
        if not submission_ids:
            return {}
        rows = (
            await self.session.execute(
                select(AssignmentSubmissionFile)
                .where(AssignmentSubmissionFile.submission_id.in_(list(submission_ids)))
                .order_by(AssignmentSubmissionFile.uploaded_at)
            )
        ).scalars().all()

        found: dict[int, list[AssignmentSubmissionFile]] = {}
        for row in rows:
            if row.submission_id is not None:
                found.setdefault(row.submission_id, []).append(row)
        return found

    async def attach_file(
        self, assignment_public_id: uuid.UUID, *, upload: UploadFile, actor: User
    ) -> AssignmentSubmissionFile:
        """Store one file against the caller's own work on this assignment.

        Uploaded *before* the submission exists, because that is the order a
        student does it in: attach, check, submit. The row is claimed when
        they submit.

        The caller is always the owner -- there is no student id in the
        request -- and the storage key is generated here, so nothing about
        where the bytes live comes from the client. That is the whole reason
        this replaced a JSON column of caller-supplied paths.
        """
        assignment = await self.get(assignment_public_id, actor=actor)

        if not await self.targets.is_eligible(AssessmentTarget.of(assignment), actor.id):
            raise ConflictError("This assignment was not set for you.")
        if assignment.state is not AssessmentState.PUBLISHED:
            raise ConflictError("This assignment is not open for submission.")
        if assignment.submission_type is SubmissionType.TEXT:
            # Offering an upload box on a text-only assignment and then
            # refusing the file is worse than not offering it; the console
            # hides it, and this is the half that cannot be bypassed.
            raise ValidationError("This assignment takes a written answer, not files.")

        existing = await self.submissions.get_for_student(
            assignment_id=assignment.id, student_id=actor.id
        )
        if existing is not None and existing.state in _MARKED_STATES:
            raise ConflictError("This submission has already been graded and cannot be changed.")

        data = await self._read_attachment(upload, assignment)
        key = build_key(
            prefix=f"submissions/{assignment.public_id}/{actor.public_id}",
            filename=upload.filename,
        )
        stored = await get_storage().save(key, data, content_type=upload.content_type)

        row = AssignmentSubmissionFile(
            assignment_id=assignment.id,
            student_id=actor.id,
            # Claimed now if the work is already in, so replacing a file on an
            # ungraded submission does not leave the new one unattached.
            submission_id=existing.id if existing is not None else None,
            filename=(upload.filename or "attachment")[:255],
            path=stored.key,
            mime_type=stored.mime_type,
            size=stored.size,
            uploaded_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _read_attachment(self, upload: UploadFile, assignment: Assignment) -> bytes:
        """The platform's upload rules, then the assignment's own.

        A tutor may narrow both -- "PDF only, 5 MB" -- and those are the
        limits a student was told about, so they are the ones whose refusal
        has to name them.
        """
        from backend.services.resource_service import ResourceService  # circular at module scope

        data = await ResourceService(self.session)._read_and_validate(upload)

        if assignment.max_upload_mb:
            cap = assignment.max_upload_mb * 1024 * 1024
            if len(data) > cap:
                raise ValidationError(
                    f"This assignment accepts files up to {assignment.max_upload_mb} MB.",
                    details={"max_bytes": cap, "received_bytes": len(data)},
                )

        allowed = [
            part.strip().lower().lstrip(".")
            for part in (assignment.allowed_file_types or "").split(",")
            if part.strip()
        ]
        if allowed:
            name = (upload.filename or "").lower()
            extension = name.rsplit(".", 1)[-1] if "." in name else ""
            if extension not in allowed:
                raise ValidationError(
                    "That file type is not accepted for this assignment.",
                    details={"allowed": allowed, "given": extension or None},
                )
        return data

    async def attachments_for(
        self, assignment_public_id: uuid.UUID, *, actor: User
    ) -> Sequence[AssignmentSubmissionFile]:
        """The caller's own attachments on this assignment, submitted or not."""
        assignment = await self.get(assignment_public_id, actor=actor)
        rows = await self.session.execute(
            select(AssignmentSubmissionFile)
            .where(
                AssignmentSubmissionFile.assignment_id == assignment.id,
                AssignmentSubmissionFile.student_id == actor.id,
            )
            .order_by(AssignmentSubmissionFile.uploaded_at)
        )
        return rows.scalars().all()

    async def remove_attachment(self, file_public_id: uuid.UUID, *, actor: User) -> None:
        """Withdraw a file. The student's own, and only before it is marked."""
        row = await self._attachment(file_public_id)
        if row.student_id != actor.id:
            # Not 403: whether somebody else's attachment exists is not this
            # caller's to learn.
            raise NotFoundError("Attachment not found.")

        if row.submission_id is not None:
            submission = await self.submissions.get_by_id(row.submission_id)
            if submission is not None and submission.state in _MARKED_STATES:
                raise ConflictError("This work has been marked and cannot be changed.")

        await get_storage().delete(row.path)
        await self.session.delete(row)

    async def resolve_attachment(
        self, file_public_id: uuid.UUID, *, actor: User
    ) -> AssignmentSubmissionFile:
        """Authorise a download: the student who wrote it, or whoever may mark it.

        `get(assignment)` is the marker's half -- it is already scoped to the
        courses the caller teaches and answers 404 for anything else -- so a
        tutor cannot reach a colleague's cohort through an attachment id.
        """
        row = await self._attachment(file_public_id)
        if row.student_id == actor.id:
            return row

        # The same predicate `get_submission` uses, and it has to be: an
        # attachment *is* part of a submission, so anything that could reach
        # the submission can reach its files and nothing else can.
        #
        # The first version of this asked `get(assignment)` instead, reasoning
        # that it is scoped to the courses a caller teaches. It is not scoped
        # that way for a *student* -- their own assignment is one they can get
        # -- so a classmate set the same work could download anybody's
        # coursework. Caught by the test below, not by reading it.
        visibility = await self.scopes.work_visibility(actor)
        if not visibility.unrestricted:
            assignment = await self.assignments.get_by_id(row.assignment_id)
            reachable = assignment is not None and (
                assignment.course_id in visibility.taught_course_ids
                or row.student_id in visibility.cared_for_student_ids
            )
            if not reachable:
                raise NotFoundError("Attachment not found.")
        return row

    async def _attachment(self, file_public_id: uuid.UUID) -> AssignmentSubmissionFile:
        row = (
            await self.session.execute(
                select(AssignmentSubmissionFile).where(
                    AssignmentSubmissionFile.public_id == file_public_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Attachment not found.")
        return row

    async def submit(
        self, assignment_public_id: uuid.UUID, payload: SubmitAssignmentRequest, *, actor: User
    ) -> AssignmentSubmission:
        """Create or replace the caller's own submission.

        The student is always the caller -- there is no `student_id` in the
        request body. Submitting on someone else's behalf is not a feature
        anyone asked for, and accepting a caller-supplied student id would
        make it one.
        """
        assignment = await self.get(assignment_public_id, actor=actor)

        # §3: eligibility now follows the assignment's own scope. A student in
        # batch B is refused work set for batch A, which the course-wide check
        # this replaced could not express.
        if not await self.targets.is_eligible(AssessmentTarget.of(assignment), actor.id):
            raise ConflictError("This assignment was not set for you.")

        if assignment.state is not AssessmentState.PUBLISHED:
            # A draft or archived assignment accepts nothing. Without this a
            # student who kept a link could submit to work the tutor withdrew.
            raise ConflictError("This assignment is not open for submission.")

        now = datetime.now(UTC)
        if assignment.available_from and now < assignment.available_from:
            raise ConflictError(
                "This assignment has not opened yet.",
                details={"opens_at": assignment.available_from.isoformat()},
            )

        is_late = now > assignment.due_date
        if is_late and not assignment.allow_late_submissions:
            raise ConflictError(
                "The deadline for this assignment has passed.",
                details={"due_date": assignment.due_date.isoformat()},
            )

        existing = await self.submissions.get_for_student(
            assignment_id=assignment.id, student_id=actor.id
        )

        # "Something was submitted" used to be a rule on the request body, and
        # cannot be any more: the files are uploaded separately, so the body
        # is only ever the written part. Asked here, where both halves are
        # visible -- otherwise an empty submission marks the student as having
        # submitted and hands the tutor nothing to grade.
        attached = (
            await self.session.execute(
                select(AssignmentSubmissionFile.id).where(
                    AssignmentSubmissionFile.assignment_id == assignment.id,
                    AssignmentSubmissionFile.student_id == actor.id,
                )
            )
        ).first()
        if not (payload.content or "").strip() and attached is None:
            raise ValidationError(
                "Write an answer or attach a file before submitting."
            )

        if existing is not None:
            # Replacing marked work would silently invalidate the grade beside
            # it -- unless the tutor asked for a resubmission, which is the
            # whole point of that state.
            marked = existing.state in _MARKED_STATES
            invited = existing.state is SubmissionState.RESUBMISSION_REQUIRED
            if marked and not invited:
                raise ConflictError(
                    "This submission has already been graded and cannot be replaced."
                )
            if not invited and not assignment.allow_multiple_submissions and existing.grade is None:
                # Not an error by default -- replacing an ungraded draft is the
                # behaviour this system has always had, and tightening it would
                # break a workflow students rely on.
                pass

            existing.content = payload.content
            existing.submitted_at = now
            existing.attempt_number = (existing.attempt_number or 1) + 1 if invited else existing.attempt_number
            existing.state = SubmissionState.LATE if is_late else SubmissionState.SUBMITTED
            row = existing
        else:
            row = AssignmentSubmission(
                assignment_id=assignment.id,
                student_id=actor.id,
                submitted_at=now,
                content=payload.content,
                # Recorded at submission time, not derived on read: whether
                # work was late is a fact about when it arrived, and a due date
                # the tutor later extends must not retroactively rewrite it.
                state=SubmissionState.LATE if is_late else SubmissionState.SUBMITTED,
            )
            await self.submissions.add_and_flush(row)

        await self.session.flush()
        # Claim the files uploaded before this moment. They were written with
        # no submission -- a student attaches, then submits -- and this is
        # what binds them to the work. Scoped to this student on this
        # assignment, so nothing anybody else uploaded can be swept in.
        await self.session.execute(
            update(AssignmentSubmissionFile)
            .where(
                AssignmentSubmissionFile.assignment_id == assignment.id,
                AssignmentSubmissionFile.student_id == actor.id,
                AssignmentSubmissionFile.submission_id.is_(None),
            )
            .values(submission_id=row.id)
        )

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE if existing is not None else AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment_submission",
            entity_id=row.id,
            details={"assignment": assignment.title, "late": is_late},
        )

        return await self.submissions.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def grade(
        self, public_id: uuid.UUID, payload: GradeSubmissionRequest, *, actor: User
    ) -> AssignmentSubmission:
        row = await self.get_submission(public_id, actor=actor)

        if payload.grade > row.assignment.max_score:
            raise ValidationError(
                "Grade exceeds the assignment's maximum score.",
                details={
                    "max_score": str(row.assignment.max_score),
                    "given": str(payload.grade),
                },
            )

        # A mark that changes needs a reason (§24). Recorded on the row itself,
        # beside the mark, where whoever queries the grade will see it -- the
        # audit log records *that* it happened, this records what and why.
        previous = row.grade
        is_override = previous is not None and previous != payload.grade
        if is_override and not payload.override_reason:
            raise ValidationError(
                "Changing a mark that has already been given requires a reason.",
                details={"previous": str(previous)},
            )

        # The raw mark is kept separately from the one that counts, so the
        # drill-down can show a late penalty as arithmetic rather than as a
        # number nobody can account for.
        row.raw_grade = payload.grade
        penalty = self._late_penalty(row)
        row.late_penalty_applied = penalty
        row.grade = max(Decimal("0"), payload.grade - penalty) if penalty else payload.grade

        row.feedback = payload.feedback
        row.graded_by_id = actor.id
        row.graded_at = datetime.now(UTC)
        # GRADED, not PUBLISHED: marking and releasing are separate acts (§14),
        # and a student must not see a mark the moment a tutor enters it.
        row.state = payload.state or SubmissionState.GRADED

        if is_override:
            row.override_reason = payload.override_reason
            row.overridden_by_id = actor.id
            row.overridden_at = datetime.now(UTC)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment_submission",
            entity_id=row.id,
            details={
                "grade": str(row.grade),
                "raw_grade": str(payload.grade),
                "late_penalty": str(penalty) if penalty else None,
                "previous_grade": str(previous) if previous is not None else None,
                "override_reason": payload.override_reason,
                "state": row.state.value,
            },
        )

        await self._record_in_gradebook(row, row.assignment)

        # The student hears about it when it is released, not when it is
        # entered. Publishing is what sends this.
        if row.state.is_visible_to_student:
            await self._announce_grade(row)

        await WebhookService(self.session).enqueue(
            WebhookEvent.SUBMISSION_GRADED,
            {
                "event": WebhookEvent.SUBMISSION_GRADED,
                "submission_id": str(row.public_id),
                "assignment_id": str(row.assignment.public_id),
                "grade": str(payload.grade),
                "max_score": str(row.assignment.max_score),
            },
        )

        # `graded_by_id` was just reassigned, so the already-loaded `grader`
        # relationship is stale -- the same trap fixed in user/course
        # services. Refresh so the response names the real grader.
        await self.session.flush()
        await self.session.refresh(row, attribute_names=["grader"])
        return row

    # -- releasing marks (spec §14) -----------------------------------------

    async def publish_results(
        self, assignment_public_id: uuid.UUID, *, actor: User, student_ids: Sequence[int] | None = None
    ) -> int:
        """Release graded marks to the students they belong to.

        Separate from grading because they are separate acts. A tutor marks
        thirty scripts over a week and releases them together; releasing each
        one as it is marked tells the first student their result days before
        the last, which is exactly what an institution's review step exists to
        prevent.

        Returns how many were released, so a caller can say "24 results
        published" rather than "done".
        """
        assignment = await self.get(assignment_public_id, actor=actor)
        rows = await self.submissions.list_for_assignment(assignment.id)

        released = 0
        for row in rows:
            if row.state is not SubmissionState.GRADED:
                # Only marked work is releasable. Skipping rather than failing
                # is deliberate: a tutor publishing a batch should not be
                # blocked by the three students who have not submitted.
                continue
            if student_ids is not None and row.student_id not in student_ids:
                continue
            row.state = SubmissionState.PUBLISHED
            row.published_at = datetime.now(UTC)
            await self._announce_grade(row)
            released += 1

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="assignment",
            entity_id=assignment.id,
            details={"published_results": released, "title": assignment.title},
        )
        return released

    async def request_resubmission(
        self, public_id: uuid.UUID, *, actor: User, reason: str
    ) -> AssignmentSubmission:
        """Hand work back for another attempt.

        A distinct state rather than deleting the mark: the student needs to
        know they were asked, the tutor needs to see it was asked, and the
        engine needs to know this component is not finished.
        """
        row = await self.get_submission(public_id, actor=actor)
        if not row.assignment.allow_resubmission:
            raise ConflictError("This assignment does not allow resubmission.")

        row.state = SubmissionState.RESUBMISSION_REQUIRED
        row.feedback = reason

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="assignment_submission", entity_id=row.id,
            details={"state": row.state.value, "reason": reason},
        )
        await NotificationService(self.session).notify(
            user_id=row.student_id,
            type_=NotificationType.SUBMISSION_GRADED,
            title=f"Resubmission requested: {row.assignment.title}",
            body=reason,
            meta={"assignment_id": str(row.assignment.public_id),
                  "submission_id": str(row.public_id)},
        )
        return row

    async def set_submission_state(
        self, public_id: uuid.UUID, *, actor: User, state: SubmissionState, reason: str | None = None
    ) -> AssignmentSubmission:
        """Record absence or an exemption.

        Neither is a mark, and neither is a missing submission. §38 requires
        them to be distinguishable from a zero, and this is where a tutor says
        which one applies.
        """
        if state not in {SubmissionState.ABSENT, SubmissionState.EXEMPTED,
                         SubmissionState.UNDER_REVIEW, SubmissionState.PENDING}:
            raise ValidationError("That state cannot be set directly.")

        row = await self.get_submission(public_id, actor=actor)
        row.state = state
        if reason:
            row.override_reason = reason
        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id, actor_email=actor.email,
            entity_type="assignment_submission", entity_id=row.id,
            details={"state": state.value, "reason": reason},
        )
        return row

    # -- helpers -------------------------------------------------------------

    async def _record_in_gradebook(
        self, submission: AssignmentSubmission, assignment: Assignment
    ) -> None:
        """Put a marked submission into the grade book straight away (§47).

        The grade book was a materialised view that only `sync_batch`
        refreshed, so between a tutor marking work and somebody pressing Sync
        it disagreed with the marks it derives from, and nothing said so. The
        quiz path was wired first; this is the same hook for coursework.

        **The row the sweep would have written**, through the same
        `record_component`, so running `sync_batch` afterwards finds it
        unchanged rather than rewriting it -- out of the assignment's own
        `max_score`, matching `_sync_assignments`.

        **Reached only with a mark set.** `grade` assigns `row.grade` from a
        required, non-null payload field immediately above the call, so a
        `grade is None` guard here would be unreachable -- one was written,
        and no test could tell it from its absence. A caller added later that
        does not hold that invariant must check before calling, as the exam
        path does.

        Fail-open: the mark has been given, and losing a derived row must not
        undo it. `sync_batch` remains the reconciler.
        """
        try:
            await GradeBookService(self.session).record_component(
                student_id=submission.student_id,
                course_id=assignment.course_id,
                batch_id=assignment.batch_id,
                component_type=GradeComponentType.ASSIGNMENT,
                reference_id=submission.id,
                score=Decimal(str(submission.grade)),
                max_score=Decimal(str(assignment.max_score)),
            )
        except Exception:  # noqa: BLE001 - a derived row must not undo a mark
            logger.exception(
                "Failed to record submission in the grade book",
                extra={"submission_id": submission.id},
            )

    @staticmethod
    def _late_penalty(row: AssignmentSubmission) -> Decimal:
        """Marks deducted for lateness, as a figure that can be shown.

        Zero unless the assignment configures a per-day rate *and* the work
        actually arrived late. Capped at the full mark: a submission three
        weeks late at 10% a day would otherwise produce a negative grade.
        """
        assignment = row.assignment
        rate = assignment.late_penalty_percent_per_day
        if not rate or row.state is not SubmissionState.LATE:
            return Decimal("0")
        if not row.submitted_at or not assignment.due_date:
            return Decimal("0")

        days = (row.submitted_at - assignment.due_date).days + 1
        if days <= 0:
            return Decimal("0")
        deduction = (Decimal(assignment.max_score) * Decimal(rate) * Decimal(days)) / Decimal("100")
        return min(deduction, Decimal(assignment.max_score))

    async def _announce_grade(self, row: AssignmentSubmission) -> None:
        """Tell one student their mark is available, and their care circle.

        Both fan-outs live here rather than inline in `grade`, which is what
        makes "a mark is announced when it is released, not when it is entered"
        true of every path -- grading with an explicit PUBLISHED state, and
        `publish_results`, both arrive here and nowhere else.
        """
        meta = {
            "assignment_id": str(row.assignment.public_id),
            "submission_id": str(row.public_id),
        }
        notifications = NotificationService(self.session)
        await notifications.notify(
            user_id=row.student_id,
            type_=NotificationType.SUBMISSION_GRADED,
            title=f"Graded: {row.assignment.title}",
            body=f"You scored {row.grade} out of {row.assignment.max_score}.",
            meta=meta,
        )
        await notifications.notify_guardians_of(
            [row.student_id],
            type_=NotificationType.WARD_SUBMISSION_GRADED,
            title=f"Graded: {row.assignment.title}",
            body=f"{{student}} scored {row.grade} out of {row.assignment.max_score}.",
            meta=meta,
        )


    async def _assert_enrolled_in_course(self, student: User, course_id: int) -> None:
        """A student may only submit to a course they are actually taking."""
        stmt = (
            select(Enrollments.enrollment_id)
            .join(Batch, Batch.id == Enrollments.batch_id)
            .where(
                Enrollments.student_id == student.id,
                Batch.course_id == course_id,
                Enrollments.status.in_(ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if (await self.session.execute(stmt)).scalar_one_or_none() is None:
            raise ConflictError("You are not enrolled in this course.")

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user
