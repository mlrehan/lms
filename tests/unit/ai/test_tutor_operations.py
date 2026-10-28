"""Unit tests for Tutor AI Assistant operations and instructional workflows."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

from backend.ai.agents.base import AgentResponse
from backend.ai.agents.tutor import TutorAgent
from backend.ai.tools.academic_tools import (
    handle_create_assignment_draft,
    handle_create_examination_draft,
    handle_get_pending_submissions,
    handle_get_quiz_evaluation_summary,
    handle_suggest_submission_grade,
)
from backend.ai.tools.attendance_tools import handle_get_my_schedule
from backend.ai.tools.reporting_tools import handle_get_batch_student_performance_and_gaps
from backend.ai.tools.registry import ToolExecutionContext
from backend.models.assignment import Assignment, AssignmentSubmission
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.core.permissions import ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.quiz import Quiz, QuizAttempt
from backend.utils.enums import AssessmentScope, Roles, SubmissionState


def make_tutor_user() -> User:
    role = Role(id=3, name=Roles.TUTOR.value, description="Tutor")
    # The tutor's real grants from the catalogue. Without them the only tools
    # this tutor was ever offered were the two raw-SQL tools, which required no
    # permission at all -- so the agent-loop tests were passing on those.
    role.permissions = [
        Permission(id=i, name=name)
        for i, name in enumerate(sorted(ROLE_PERMISSIONS[Roles.TUTOR.value]), start=1)
    ]
    user = User(
        id=636,
        public_id=uuid.uuid4(),
        username="younus.kazi",
        email="younus.kazi@londonacademyofit.co.uk",
        first_name="Younus",
        last_name="Kazi",
        timezone="UTC",
    )
    user.roles = [role]
    return user


def make_sample_course() -> Course:
    return Course(
        id=101,
        public_id=uuid.uuid4(),
        code="PY-ADV",
        title="Python Intermediate to Advanced",
        is_deleted=False,
    )


def make_sample_batch(sample_course: Course) -> Batch:
    return Batch(
        id=202,
        public_id=uuid.uuid4(),
        batch_code="11602",
        course_id=sample_course.id,
        course=sample_course,
        is_active=True,
    )


def test_tutor_schedule_next_class_retrieval():
    """Verify tutor schedule retrieval identifies next upcoming class without stalling."""
    async def run():
        tutor_user = make_tutor_user()
        sample_course = make_sample_course()
        sample_batch = make_sample_batch(sample_course)
        session_mock = AsyncMock()

        now = datetime.now(UTC)
        mock_session = BatchSession(
            id=501,
            public_id=uuid.uuid4(),
            batch_id=sample_batch.id,
            tutor_id=tutor_user.id,
            session_start_time=now + timedelta(days=1),
            session_end_time=now + timedelta(days=1, hours=4),
            classroom="Room 402",
            cancelled_at=None,
        )
        mock_session.batch = sample_batch

        with patch("backend.services.session_service.SessionService.calendar", new_callable=AsyncMock) as mock_cal:
            mock_cal.return_value = [mock_session]
            ctx = ToolExecutionContext(user=tutor_user, session=session_mock)

            res = await handle_get_my_schedule({"timeframe": "When will my first class start?"}, ctx)

            assert res["has_upcoming_class"] is True
            assert res["next_upcoming_class"] is not None
            assert res["next_upcoming_class"]["course_title"] == "Python Intermediate to Advanced"
            assert res["next_upcoming_class"]["batch_code"] == "11602"
            assert "Next upcoming class:" in res["summary"]

    asyncio.run(run())


def test_tutor_create_assignment_draft():
    """Verify tutor can draft an assignment with a grading rubric."""
    async def run():
        tutor_user = make_tutor_user()
        sample_course = make_sample_course()
        session_mock = AsyncMock()
        ctx = ToolExecutionContext(user=tutor_user, session=session_mock)

        with patch("backend.ai.tools.academic_tools._resolve_course", new_callable=AsyncMock) as mock_c, \
             patch("backend.services.scope.ScopeResolver.visible_course_ids", new_callable=AsyncMock) as mock_vis, \
             patch("backend.services.assignment_service.AssignmentService.create", new_callable=AsyncMock) as mock_create:

            mock_c.return_value = sample_course
            scope_mock = MagicMock()
            scope_mock.allows.return_value = True
            mock_vis.return_value = scope_mock

            created_asmt = Assignment(
                id=701,
                public_id=uuid.uuid4(),
                title="Data Structures Project",
                course_id=sample_course.id,
                max_score=Decimal("100.0"),
                due_date=datetime.now(UTC) + timedelta(days=10),
                rubric={"criteria": [{"criterion": "Accuracy", "weight": 50}]},
                state=SubmissionState.DRAFT if hasattr(SubmissionState, "DRAFT") else "DRAFT",
            )
            mock_create.return_value = created_asmt

            res = await handle_create_assignment_draft({
                "course_id": str(sample_course.public_id),
                "title": "Data Structures Project",
                "max_score": 100.0,
                "rubric": {"criteria": [{"criterion": "Accuracy", "weight": 50}]},
            }, ctx)

            assert res["success"] is True
            assert res["title"] == "Data Structures Project"
            assert res["max_score"] == 100.0
            assert "created in DRAFT state" in res["summary"]

    asyncio.run(run())


def test_tutor_create_examination_draft():
    """Verify tutor can prepare a 60-minute examination draft."""
    async def run():
        tutor_user = make_tutor_user()
        sample_course = make_sample_course()
        session_mock = AsyncMock()
        ctx = ToolExecutionContext(user=tutor_user, session=session_mock)

        with patch("backend.ai.tools.academic_tools._resolve_course", new_callable=AsyncMock) as mock_c, \
             patch("backend.services.scope.ScopeResolver.visible_course_ids", new_callable=AsyncMock) as mock_vis, \
             patch("backend.services.exam_service.ExamService.create", new_callable=AsyncMock) as mock_create:

            mock_c.return_value = sample_course
            scope_mock = MagicMock()
            scope_mock.allows.return_value = True
            mock_vis.return_value = scope_mock

            exam = MagicMock()
            exam.public_id = uuid.uuid4()
            exam.title = "Midterm Exam"
            exam.duration_minutes = 60
            exam.total_marks = Decimal("100.0")
            exam.passing_marks = Decimal("50.0")
            exam.is_published = False
            exam.scheduled_at = datetime.now(UTC) + timedelta(days=7)
            mock_create.return_value = exam

            res = await handle_create_examination_draft({
                "course_id": str(sample_course.public_id),
                "title": "Midterm Exam",
                "duration_minutes": 60,
                "total_marks": 100.0,
            }, ctx)

            assert res["success"] is True
            assert res["duration_minutes"] == 60
            assert res["total_marks"] == 100.0
            assert res["is_published"] is False

    asyncio.run(run())


def test_tutor_suggest_submission_grade():
    """Verify tutor can evaluate a submission and propose rubric-based grades."""
    async def run():
        tutor_user = make_tutor_user()
        sample_course = make_sample_course()
        session_mock = AsyncMock()
        ctx = ToolExecutionContext(user=tutor_user, session=session_mock)

        sub = MagicMock()
        sub.public_id = uuid.uuid4()
        asmt = MagicMock()
        asmt.course_id = sample_course.id
        asmt.max_score = Decimal("100.0")
        student = MagicMock()
        student.username = "anna.student@example.com"
        student.first_name = "Anna"
        student.last_name = "Student"

        exec_result = MagicMock()
        exec_result.first.return_value = (sub, asmt, student)
        session_mock.execute.return_value = exec_result

        with patch("backend.services.scope.ScopeResolver.visible_course_ids", new_callable=AsyncMock) as mock_vis:
            scope_mock = MagicMock()
            scope_mock.allows.return_value = True
            mock_vis.return_value = scope_mock

            res = await handle_suggest_submission_grade({
                "submission_id": str(sub.public_id),
                "suggested_grade": 88.0,
                "feedback": "Strong logic and well-documented solution.",
            }, ctx)

            assert res["status"] == "PROPOSED_FOR_REVIEW"
            assert res["suggested_grade"] == 88.0
            assert res["student_name"] == "Anna Student"
            assert "Nothing has been recorded" in res["summary"]

    asyncio.run(run())


def test_tutor_conversational_stall_prevention():
    """Ensure BaseAgent detects conversational promises ('I will look up') and nudges the model to execute tools."""
    async def run():
        tutor_user = make_tutor_user()
        mock_client = AsyncMock()

        # Turn 0: Model stalls with conversational filler
        msg_stall = MagicMock()
        msg_stall.tool_calls = None
        msg_stall.content = "I'll look up your next scheduled session now."
        msg_stall.model_dump.return_value = {"role": "assistant", "content": msg_stall.content}

        # Turn 1: After nudge, model executes tool
        tc = MagicMock()
        tc.id = "call_123"
        tc.function.name = "get_my_schedule"
        tc.function.arguments = '{"timeframe": "next class"}'

        msg_tool = MagicMock()
        msg_tool.tool_calls = [tc]
        msg_tool.content = None
        msg_tool.model_dump.return_value = {"role": "assistant", "tool_calls": [{"id": "call_123"}]}

        # Final response
        msg_final = MagicMock()
        msg_final.tool_calls = None
        msg_final.content = "Your next class is Python Intermediate to Advanced on Oct 22 at 10:00 UTC."

        resp_0 = MagicMock(choices=[MagicMock(message=msg_stall)])
        resp_1 = MagicMock(choices=[MagicMock(message=msg_tool)])
        resp_2 = MagicMock(choices=[MagicMock(message=msg_final)])

        mock_client.chat_completion.side_effect = [resp_0, resp_1, resp_2]

        agent = TutorAgent(user=tutor_user, session=AsyncMock(), client=mock_client)

        with patch.object(agent.tool_registry, "execute_tool", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "has_upcoming_class": True,
                "summary": "Next class on Oct 22",
            }

            resp = await agent.execute_turn(prompt="When will my first class start?")

            assert "Oct 22" in resp.text
            assert "I'll look up" not in resp.text

    asyncio.run(run())


def test_tutor_personal_data_protection_email_refusal():
    """Ensure Tutor asking for student email address receives immediate permission denial without querying DB."""
    async def run():
        tutor_user = make_tutor_user()
        mock_client = AsyncMock()
        session = AsyncMock()

        agent = TutorAgent(user=tutor_user, session=session, client=mock_client)

        resp = await agent.execute_turn(
            prompt="Give me the email address of the student named Anna Róza Medzihradszky."
        )

        assert resp.success is True
        assert resp.role == "TUTOR"
        assert resp.text == "You don't have permission to access this student's email address."
        assert len(resp.tool_calls_made) == 0
        # Ensure LLM was not even invoked to query the DB
        assert mock_client.chat_completion.await_count == 0

    asyncio.run(run())


def test_tutor_personal_data_protection_phone_refusal():
    """Ensure Tutor asking for student phone number receives immediate permission denial."""
    async def run():
        tutor_user = make_tutor_user()
        mock_client = AsyncMock()
        session = AsyncMock()

        agent = TutorAgent(user=tutor_user, session=session, client=mock_client)

        resp = await agent.execute_turn(
            prompt="Can you give me the phone number for student Anna Medzi?"
        )

        assert resp.success is True
        assert resp.text == "You don't have permission to access this student's phone number."
        assert mock_client.chat_completion.await_count == 0

    asyncio.run(run())


def test_sql_safety_blocks_tutor_from_querying_email():
    """Ensure validate_sql_safety blocks non-admin callers from querying email or contact PII."""
    from backend.ai.tools.database_tools import validate_sql_safety

    # Tutor query attempting to select email must fail
    query = "SELECT id, email, first_name FROM users WHERE first_name ILIKE '%Anna%'"
    is_valid, err, _ = validate_sql_safety(query, {Roles.TUTOR.value})
    assert is_valid is False
    assert "private personal contact information" in err.lower() or "restricted" in err.lower()

    # SuperAdmin query selecting email must succeed
    is_valid_sa, err_sa, cleaned_sa = validate_sql_safety(query, {Roles.SUPER_ADMIN.value})
    assert is_valid_sa is True
    assert err_sa is None


def test_sanitize_final_response_removes_status_traces():
    """Ensure sanitize_final_response cleanly removes internal (Executing...) prefixes."""
    raw_status_response = (
        "(Executing database query to find the student record...)\n\n"
        "The student's attendance rate is 92.5%."
    )
    cleaned = TutorAgent.sanitize_final_response(raw_status_response)
    assert cleaned == "The student's attendance rate is 92.5%."
    assert "Executing database query" not in cleaned

    only_status = "(Inspecting batch and tutor-course schema...)"
    cleaned_only = TutorAgent.sanitize_final_response(only_status)
    assert cleaned_only == "Task completed."
    assert "Inspecting batch" not in cleaned_only

