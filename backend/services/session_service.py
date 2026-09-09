"""Class session scheduling (spec §8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.batch import BatchSession
from backend.models.identity.user import User
from backend.repositories.session import SessionRepository
from backend.schemas.base import PageParams
from backend.schemas.session import SessionCreateRequest, SessionUpdateRequest
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.batch_service import BatchService
from backend.services.scope import ScopeResolver
from backend.utils.enums import Roles


class SessionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sessions = SessionRepository(session)
        self.batches = BatchService(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_sessions(
        self,
        params: PageParams,
        *,
        actor: User,
        batch_public_id: uuid.UUID | None = None,
        starts_after: datetime | None = None,
        starts_before: datetime | None = None,
        mine_only: bool = False,
    ) -> tuple[Sequence[BatchSession], int]:
        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.batches.get(batch_public_id, actor=actor)).id

        scope = await self.scopes.visible_session_ids(actor)
        return await self.sessions.search(
            params,
            scope=scope,
            batch_id=batch_id,
            tutor_id=actor.id if mine_only else None,
            starts_after=starts_after,
            starts_before=starts_before,
        )

    async def get(self, public_id: uuid.UUID, *, actor: User) -> BatchSession:
        row = await self.sessions.get_by_public_id_full(public_id)
        if row is None:
            raise NotFoundError("Session not found.")

        scope = await self.scopes.visible_session_ids(actor)
        if not scope.allows(row.id):
            raise NotFoundError("Session not found.")
        return row

    # -- writes --------------------------------------------------------------

    async def create(
        self, batch_public_id: uuid.UUID, payload: SessionCreateRequest, *, actor: User
    ) -> BatchSession:
        batch = await self.batches.get(batch_public_id, actor=actor)
        tutor = await self._resolve_tutor(payload.tutor_id)

        await self._assert_tutor_free(
            tutor_id=tutor.id,
            start=payload.session_start_time,
            end=payload.session_end_time,
        )

        row = BatchSession(
            batch_id=batch.id,
            tutor_id=tutor.id,
            session_start_time=payload.session_start_time,
            session_end_time=payload.session_end_time,
            duration_minutes=payload.duration_minutes or self._derive_duration(payload),
            platform=payload.platform,
            classroom=payload.classroom,
            meeting_link=payload.meeting_link,
            tutor_notes=payload.tutor_notes,
        )
        await self.sessions.add_and_flush(row)

        audit_service.record(
            self.session,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={
                "batch": batch.batch_code,
                "tutor": tutor.username,
                "starts": payload.session_start_time.isoformat(),
            },
        )
        return await self.sessions.get_by_public_id_full(row.public_id)  # type: ignore[return-value]

    async def update(
        self, public_id: uuid.UUID, payload: SessionUpdateRequest, *, actor: User
    ) -> BatchSession:
        row = await self.get(public_id, actor=actor)
        changes = payload.model_dump(exclude_unset=True)

        if "tutor_id" in changes and changes["tutor_id"] is not None:
            tutor = await self._resolve_tutor(changes.pop("tutor_id"))
            row.tutor_id = tutor.id

        # A PATCH may move only one endpoint, so the pair is re-checked
        # against stored values -- the schema can only validate what it was
        # sent.
        start = changes.get("session_start_time", row.session_start_time)
        end = changes.get("session_end_time", row.session_end_time)
        if start and end and end <= start:
            raise ConflictError("session_end_time must be after session_start_time.")

        if ("session_start_time" in changes or "session_end_time" in changes) and start:
            await self._assert_tutor_free(
                tutor_id=row.tutor_id, start=start, end=end, exclude_session_id=row.id
            )

        for field, value in changes.items():
            setattr(row, field, value)

        audit_service.record(
            self.session,
            action=AuditAction.UPDATE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=row.id,
            details={"fields": sorted(changes)},
        )
        return row

    async def delete(self, public_id: uuid.UUID, *, actor: User) -> None:
        row = await self.get(public_id, actor=actor)

        marked = await self.sessions.count_attendance(row.id)
        if marked:
            # Deleting a session cascades its attendance rows away
            # (`ondelete="CASCADE"`), silently rewriting every affected
            # student's attendance record. A session that actually happened
            # is history, not a scheduling mistake.
            raise ConflictError(
                "This session already has attendance recorded and cannot be deleted.",
                details={"attendance_records": marked},
            )

        entity_id = row.id
        await self.session.delete(row)

        audit_service.record(
            self.session,
            action=AuditAction.DELETE,
            actor_user_id=actor.id,
            actor_email=actor.email,
            entity_type="batch_session",
            entity_id=entity_id,
        )

    # -- guards --------------------------------------------------------------

    @staticmethod
    def _derive_duration(payload: SessionCreateRequest) -> int | None:
        if payload.session_end_time is None:
            return None
        delta = payload.session_end_time - payload.session_start_time
        return int(delta.total_seconds() // 60) or None

    async def _resolve_tutor(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")

        # Assigning a session tutor is an authorization write: it grants that
        # person access to this batch's students (see `services/scope.py`,
        # which reads `batch_sessions.tutor_id` as one of the two routes a
        # tutor reaches a batch).
        if not any((r.name or "").upper() == Roles.TUTOR.value for r in (user.roles or [])):
            raise ValidationError(
                "This user does not hold the TUTOR role.",
                details={"username": user.username},
            )
        return user

    async def _assert_tutor_free(
        self,
        *,
        tutor_id: int,
        start: datetime,
        end: datetime | None,
        exclude_session_id: int | None = None,
    ) -> None:
        clash = await self.sessions.overlapping_for_tutor(
            tutor_id=tutor_id, start=start, end=end, exclude_session_id=exclude_session_id
        )
        if clash is not None:
            raise ConflictError(
                "That tutor is already teaching another session at this time.",
                details={
                    "conflicting_batch": clash.batch.batch_code if clash.batch else None,
                    "starts": clash.session_start_time.isoformat()
                    if clash.session_start_time
                    else None,
                },
            )
