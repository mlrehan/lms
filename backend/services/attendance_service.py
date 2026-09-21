"""Attendance recording and reporting (spec §9)."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.models.attendance import Attendance
from backend.models.batch import BatchSession
from backend.models.enrollment import Enrollments
from backend.models.identity.user import User
from backend.repositories.attendance import AttendanceRepository
from backend.repositories.enrollment import ACTIVE_STATUSES
from backend.repositories.session import SessionRepository
from backend.schemas.attendance import AttendanceEntry, AttendanceSummaryResponse
from backend.schemas.base import PageParams
from backend.services import audit_service
from backend.services.audit_service import AuditAction
from backend.services.metrics import attendance_rate
from backend.services.scope import ScopeResolver
from backend.services.session_service import SessionService
from backend.utils.enums import AttendanceStatus


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.attendance = AttendanceRepository(session)
        self.sessions = SessionRepository(session)
        self.session_service = SessionService(session)
        self.scopes = ScopeResolver(session)

    # -- reads ---------------------------------------------------------------

    async def list_attendance(
        self,
        params: PageParams,
        *,
        actor: User,
        session_public_id: uuid.UUID | None = None,
        student_public_id: uuid.UUID | None = None,
        batch_public_id: uuid.UUID | None = None,
        status: AttendanceStatus | None = None,
    ) -> tuple[Sequence[Attendance], int]:
        session_id = None
        if session_public_id is not None:
            session_id = (await self.session_service.get(session_public_id, actor=actor)).id

        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.session_service.batches.get(batch_public_id, actor=actor)).id

        visibility = await self.scopes.attendance_visibility(actor)
        return await self.attendance.search(
            params,
            visibility=visibility,
            session_id=session_id,
            student_id=student_id,
            batch_id=batch_id,
            status=status,
        )

    async def summarise(
        self,
        *,
        actor: User,
        student_public_id: uuid.UUID | None = None,
        batch_public_id: uuid.UUID | None = None,
    ) -> AttendanceSummaryResponse:
        student_id = None
        if student_public_id is not None:
            student_id = (await self._load_user(student_public_id)).id

        batch_id = None
        if batch_public_id is not None:
            batch_id = (await self.session_service.batches.get(batch_public_id, actor=actor)).id

        visibility = await self.scopes.attendance_visibility(actor)
        counts = await self.attendance.summarise(
            visibility=visibility, student_id=student_id, batch_id=batch_id
        )

        present = counts.get(AttendanceStatus.PRESENT, 0)
        late = counts.get(AttendanceStatus.LATE, 0)
        absent = counts.get(AttendanceStatus.ABSENT, 0)
        excused = counts.get(AttendanceStatus.EXCUSED, 0)
        total = present + late + absent + excused

        # The rate itself lives in `services/metrics.py`, because the §18
        # reports and the dashboard quote the same figure. Three copies of
        # "what counts as attendance" is three numbers the institution can
        # disagree with itself about.
        rate = attendance_rate(present=present, late=late, absent=absent, excused=excused)

        return AttendanceSummaryResponse(
            present=present,
            late=late,
            absent=absent,
            excused=excused,
            total=total,
            attendance_rate=rate,
        )

    # -- writes --------------------------------------------------------------

    async def mark(
        self,
        session_public_id: uuid.UUID,
        entries: Sequence[AttendanceEntry],
        *,
        actor: User,
    ) -> list[Attendance]:
        """Record or correct a whole register in one call.

        Upserts: an entry for a student already marked updates that row
        rather than inserting a second one. Beyond being the behaviour a
        tutor expects when fixing a mistake, `uq_attendances_session_student`
        would refuse the duplicate anyway.
        """
        # The same authority, sheet and audit trail as the attendance workflow: only the session's assigned tutor
        # (or the Super Admin, on their behalf) may mark a register, and it is recorded as a submission or an edit.
        # A partial register is still accepted here, as this endpoint always did.
        from backend.schemas.attendance_sheet import SaveSheetRequest, SheetEntry
        from backend.services.attendance_sheet_service import AttendanceSheetService

        request = SaveSheetRequest(entries=[SheetEntry(student_id=e.student_id, status=e.status, remarks=e.remarks) for e in entries], submit=True)
        await AttendanceSheetService(self.session).save(actor, session_public_id, request, require_complete=False)
        batch_session = await self.session_service.get(session_public_id, actor=actor)
        return await self.attendance.list_for_session(batch_session.id)

    # -- helpers -------------------------------------------------------------

    async def _enrolled_student_ids(self, batch_id: int) -> set[int]:
        stmt = select(Enrollments.student_id).where(
            Enrollments.batch_id == batch_id,
            Enrollments.status.in_(ACTIVE_STATUSES),
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _resolve_students(
        self, public_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, User]:
        stmt = select(User).where(User.public_id.in_(list(public_ids)))
        found = {u.public_id: u for u in (await self.session.execute(stmt)).scalars().unique()}

        missing = set(public_ids) - set(found)
        if missing:
            raise ValidationError(
                "Unknown user(s).",
                details={"unknown_users": sorted(str(m) for m in missing)},
            )
        return found

    async def _load_user(self, public_id: uuid.UUID) -> User:
        stmt = select(User).where(User.public_id == public_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        return user
