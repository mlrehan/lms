"""Grade book, grade band and transcript endpoints (spec §15)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.core.privacy import visible_username
from backend.api.deps import CurrentUser, require_permissions
from backend.core.permissions import Action, Module, perm
from backend.db.dependencies import DBSession
from backend.models.gradebook import GradeBookEntry, Transcript
from backend.schemas.base import Page, PageParams
from backend.schemas.gradebook import (
    FinaliseTranscriptRequest,
    GenerateTranscriptsResponse,
    GradeBandCreateRequest,
    GradeBandResponse,
    GradeBandUpdateRequest,
    GradeBookEntryCreateRequest,
    GradeBookEntryResponse,
    GradeBookEntryUpdateRequest,
    GradeBookSummaryResponse,
    SyncResultResponse,
    TranscriptResponse,
)
from backend.services.gradebook_service import GradeBookService
from backend.utils.enums import GradeComponentType

router = APIRouter(tags=["Grade book"])


def _entry_response(e: GradeBookEntry) -> GradeBookEntryResponse:
    max_score = Decimal(str(e.max_score))
    pct = (
        (Decimal(str(e.score)) / max_score * Decimal("100")).quantize(Decimal("0.01"))
        if max_score > 0
        else None
    )
    return GradeBookEntryResponse(
        public_id=e.public_id,
        student_id=e.student.public_id,
        student_username=visible_username(e.student),
        batch_id=e.batch.public_id,
        batch_code=e.batch.batch_code,
        component_type=e.component_type,
        reference_id=e.reference_id,
        score=e.score,
        max_score=e.max_score,
        weight=e.weight,
        percentage=pct,
        recorded_at=e.recorded_at,
    )


def _transcript_response(t: Transcript) -> TranscriptResponse:
    return TranscriptResponse(
        public_id=t.public_id,
        student_id=t.student.public_id,
        student_username=visible_username(t.student),
        batch_id=t.batch.public_id,
        batch_code=t.batch.batch_code,
        course_id=t.course.public_id,
        course_title=t.course.title,
        gpa=t.gpa,
        overall_grade=t.overall_grade,
        generated_at=t.generated_at,
        is_final=t.is_final,
    )


# =============================================================================
# GRADE BANDS
# =============================================================================


@router.get(
    "/grade-bands",
    response_model=list[GradeBandResponse],
    summary="List the institution's grading scale",
)
async def list_grade_bands(
    session: DBSession,
    _actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))
    ],
) -> list[GradeBandResponse]:
    rows = await GradeBookService(session).list_bands()
    return [GradeBandResponse.model_validate(b) for b in rows]


@router.post(
    "/grade-bands",
    response_model=GradeBandResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a grade band",
)
async def create_grade_band(
    payload: GradeBandCreateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ACADEMIC, Action.CREATE)))
    ],
) -> GradeBandResponse:
    """Overlapping ranges are refused — two bands matching one percentage
    would make the resulting letter depend on row order."""
    return GradeBandResponse.model_validate(
        await GradeBookService(session).create_band(payload, actor=actor)
    )


@router.patch(
    "/grade-bands/{band_id}", response_model=GradeBandResponse, summary="Update a grade band"
)
async def update_grade_band(
    band_id: int,
    payload: GradeBandUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ACADEMIC, Action.UPDATE)))
    ],
) -> GradeBandResponse:
    return GradeBandResponse.model_validate(
        await GradeBookService(session).update_band(band_id, payload, actor=actor)
    )


@router.delete(
    "/grade-bands/{band_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a grade band",
)
async def delete_grade_band(
    band_id: int,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.ACADEMIC, Action.DELETE)))
    ],
) -> Response:
    await GradeBookService(session).delete_band(band_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# ENTRIES
# =============================================================================


@router.get(
    "/gradebook", response_model=Page[GradeBookEntryResponse], summary="List grade book entries"
)
async def list_entries(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))
    ],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
    component_type: Annotated[GradeComponentType | None, Query()] = None,
) -> Page[GradeBookEntryResponse]:
    """Row-scoped: a Tutor sees entries for batches they teach; a Guardian or
    Corporate Manager those of the people in their care; a Student their own."""
    rows, total = await GradeBookService(session).list_entries(
        params,
        actor=actor,
        batch_public_id=batch_id,
        student_public_id=student_id,
        component_type=component_type,
    )
    return Page.build([_entry_response(e) for e in rows], total=total, params=params)


@router.post(
    "/batches/{batch_id}/gradebook/entries",
    response_model=GradeBookEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a manual grade component",
)
async def create_entry(
    batch_id: uuid.UUID,
    payload: GradeBookEntryCreateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.UPDATE)))
    ],
) -> GradeBookEntryResponse:
    """For components with no source row to derive from — PRACTICAL marks in
    particular. Assignment, quiz, exam and attendance components come from
    `sync` instead and are not creatable here."""
    return _entry_response(
        await GradeBookService(session).create_entry(batch_id, payload, actor=actor)
    )


@router.patch(
    "/gradebook/{entry_id}",
    response_model=GradeBookEntryResponse,
    summary="Update a manual entry",
)
async def update_entry(
    entry_id: uuid.UUID,
    payload: GradeBookEntryUpdateRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.UPDATE)))
    ],
) -> GradeBookEntryResponse:
    """Refused for derived entries — an edit here would be silently reverted
    by the next sync, so the underlying mark is the thing to change."""
    return _entry_response(
        await GradeBookService(session).update_entry(entry_id, payload, actor=actor)
    )


@router.delete(
    "/gradebook/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a manual entry",
)
async def delete_entry(
    entry_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.UPDATE)))
    ],
) -> Response:
    await GradeBookService(session).delete_entry(entry_id, actor=actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/batches/{batch_id}/gradebook/sync",
    response_model=SyncResultResponse,
    summary="Rebuild derived entries from recorded marks",
)
async def sync_gradebook(
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.UPDATE)))
    ],
) -> SyncResultResponse:
    """Pulls graded assignment submissions, completed quiz attempts, recorded
    exam results and attendance into the grade book.

    Idempotent: re-running corrects existing entries rather than appending,
    so the computed GPA cannot drift on repeat runs. Unmarked work is skipped
    rather than counted as zero — a zero would penalise a student for work
    the tutor has not got to yet.
    """
    return SyncResultResponse(**await GradeBookService(session).sync_batch(batch_id, actor=actor))


@router.get(
    "/gradebook/summary",
    response_model=GradeBookSummaryResponse,
    summary="A student's standing in a batch",
)
async def gradebook_summary(
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))
    ],
    batch_id: Annotated[uuid.UUID, Query()],
    student_id: Annotated[uuid.UUID, Query()],
) -> GradeBookSummaryResponse:
    """Component breakdown plus the weighted percentage and the matching
    letter grade / GPA points.

    Component percentages are averaged rather than raw points pooled, so a
    100-mark exam does not drown out a 10-point quiz purely because of the
    scale its marks use.
    """
    return GradeBookSummaryResponse(
        **await GradeBookService(session).summarise(
            batch_public_id=batch_id, student_public_id=student_id, actor=actor
        )
    )


# =============================================================================
# TRANSCRIPTS
# =============================================================================


@router.get(
    "/transcripts", response_model=Page[TranscriptResponse], summary="List transcripts"
)
async def list_transcripts(
    session: DBSession,
    params: Annotated[PageParams, Depends()],
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))
    ],
    batch_id: Annotated[uuid.UUID | None, Query()] = None,
    student_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[TranscriptResponse]:
    """Provisional (non-final) transcripts are visible only to staff who can
    mark — a draft figure gets recomputed on every sync, and a student acting
    on one would be acting on a number that is still moving."""
    rows, total = await GradeBookService(session).list_transcripts(
        params, actor=actor, batch_public_id=batch_id, student_public_id=student_id
    )
    return Page.build([_transcript_response(t) for t in rows], total=total, params=params)


@router.get(
    "/transcripts/{transcript_id}",
    response_model=TranscriptResponse,
    summary="Get one transcript",
)
async def get_transcript(
    transcript_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.READ)))
    ],
) -> TranscriptResponse:
    return _transcript_response(
        await GradeBookService(session).get_transcript(transcript_id, actor=actor)
    )


@router.post(
    "/batches/{batch_id}/transcripts/generate",
    response_model=GenerateTranscriptsResponse,
    summary="Generate transcripts for a batch",
)
async def generate_transcripts(
    batch_id: uuid.UUID,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.UPDATE)))
    ],
) -> GenerateTranscriptsResponse:
    """Aggregates each enrolled student's grade book into a GPA and letter
    grade. Already-finalised transcripts are left untouched — regenerating
    one silently would change a figure someone has already acted on."""
    return GenerateTranscriptsResponse(
        **await GradeBookService(session).generate_transcripts(batch_id, actor=actor)
    )


@router.put(
    "/transcripts/{transcript_id}/finalise",
    response_model=TranscriptResponse,
    summary="Finalise or reopen a transcript",
)
async def finalise_transcript(
    transcript_id: uuid.UUID,
    payload: FinaliseTranscriptRequest,
    session: DBSession,
    actor: Annotated[
        CurrentUser, Depends(require_permissions(perm(Module.GRADE, Action.PUBLISH)))
    ],
) -> TranscriptResponse:
    """Finalising is what makes a transcript visible to the student, and
    freezes it against regeneration. A transcript with no GPA cannot be
    finalised."""
    return _transcript_response(
        await GradeBookService(session).set_final(transcript_id, payload.is_final, actor=actor)
    )
