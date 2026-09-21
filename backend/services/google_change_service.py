"""Deciding on enrolment changes proposed from Google Calendar.

A proposal is approved or rejected by a person, in the LMS. Approval does not reach into the
tables: it calls the *same* `EnrollmentService` the Enrol and Drop buttons use, so capacity,
"batch is open", "already enrolled", notifications, webhooks, audit and permissions all apply
exactly as if the administrator had done it by hand.

If the enrolment rules refuse (the batch is full, say) the request stays pending with the
reason recorded, rather than failing the whole request: the reason is what the person needs to
see next to the row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import AppError, ConflictError, NotFoundError
from backend.core.privacy import may_see_contact
from backend.models.batch import Batch
from backend.models.enrollment import Enrollments
from backend.models.google_connection import GoogleChangeRequest
from backend.models.identity.user import User
from backend.repositories.enrollment import EnrollmentRepository
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.enrollment_service import EnrollmentService
from backend.utils.enums import EnrollmentStatus


class GoogleChangeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_count(self) -> int:
        return int((await self.session.execute(select(func.count()).select_from(GoogleChangeRequest).where(GoogleChangeRequest.status == "PENDING"))).scalar_one())

    async def list(self, *, status: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        where = [GoogleChangeRequest.status == status] if status else []
        total = int((await self.session.execute(select(func.count()).select_from(GoogleChangeRequest).where(*where))).scalar_one())
        rows = (await self.session.execute(
            select(GoogleChangeRequest, Batch.public_id, Batch.batch_code, User.first_name, User.last_name, User.username)
            .join(Batch, Batch.id == GoogleChangeRequest.batch_id)
            .outerjoin(User, User.id == GoogleChangeRequest.user_id)
            .where(*where).order_by(GoogleChangeRequest.detected_at.desc()).limit(limit).offset(offset)
        )).all()
        decided_by = {}
        ids = {r[0].decided_by_user_id for r in rows if r[0].decided_by_user_id}
        if ids:
            decided_by = {i: u for i, u in (await self.session.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()}
        items = [
            {
                "public_id": req.public_id, "kind": req.kind, "status": req.status, "email": req.email if may_see_contact() else None, "note": req.note,
                "batch_id": batch_public, "batch_code": batch_code,
                "student_name": " ".join(p for p in (first, last) if p) or username,
                "detected_at": req.detected_at, "decided_at": req.decided_at,
                "decided_by": decided_by.get(req.decided_by_user_id), "last_error": req.last_error,
            }
            for req, batch_public, batch_code, first, last, username in rows
        ]
        return items, total

    async def _get(self, public_id: uuid.UUID) -> GoogleChangeRequest:
        req = (await self.session.execute(select(GoogleChangeRequest).where(GoogleChangeRequest.public_id == public_id))).scalar_one_or_none()
        if req is None:
            raise NotFoundError("Change request not found.")
        return req

    async def approve(self, public_id: uuid.UUID, *, actor: User) -> GoogleChangeRequest:
        req = await self._get(public_id)
        if req.status != "PENDING":
            raise ConflictError(f"This request was already {req.status.lower()}.")

        batch_public = (await self.session.execute(select(Batch.public_id).where(Batch.id == req.batch_id))).scalar_one()
        student_public = (await self.session.execute(select(User.public_id).where(User.id == req.user_id))).scalar_one_or_none()
        if student_public is None:
            req.last_error = "The student account no longer exists."
            return req

        service = EnrollmentService(self.session)
        try:
            # A savepoint: if the enrolment rules refuse half way, nothing they did is kept.
            async with self.session.begin_nested():
                if req.kind == "ENROL_ADD":
                    await service.enroll(student_public_id=student_public, batch_public_id=batch_public, confirmed=True, actor=actor)
                else:
                    active = await EnrollmentRepository(self.session).get_active(student_id=req.user_id, batch_id=req.batch_id)
                    if active is None:
                        raise ConflictError("The student is not enrolled in this batch any more.")
                    await service.set_status(active.public_id, EnrollmentStatus.DROPPED, actor=actor)
        except AppError as exc:
            req.last_error = str(exc.message if hasattr(exc, "message") else exc)[:300]
            return req  # still PENDING, with the reason beside it

        req.status, req.decided_at, req.decided_by_user_id, req.last_error = "APPROVED", datetime.now(timezone.utc), actor.id, None
        audit_service.record(self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email,
                             entity_type="google_change_request", entity_id=req.id, details={"decision": "approved", "kind": req.kind, "email": req.email})
        return req

    async def reject(self, public_id: uuid.UUID, *, actor: User) -> GoogleChangeRequest:
        req = await self._get(public_id)
        if req.status != "PENDING":
            raise ConflictError(f"This request was already {req.status.lower()}.")
        req.status, req.decided_at, req.decided_by_user_id = "REJECTED", datetime.now(timezone.utc), actor.id
        audit_service.record(self.session, action=AuditAction.UPDATE, actor_user_id=actor.id, actor_email=actor.email,
                             entity_type="google_change_request", entity_id=req.id, details={"decision": "rejected", "kind": req.kind, "email": req.email})
        return req
