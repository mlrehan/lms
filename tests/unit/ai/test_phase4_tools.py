"""Phase 4: the communication and grade book tools.

Each test pins the property that makes the tool safe to hand to a model:
a message is only ever drafted, an announcement and a mark sheet only ever
staged first, and nothing resolves a person outside the caller's reach.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ai.tools.communication_tools import _text_to_html, handle_draft_message
from backend.ai.tools.gradebook_tools import handle_get_batch_gradebook
from backend.ai.tools.registry import ToolExecutionContext, get_tool_registry
from backend.ai.workflows.confirmation_service import ConfirmationExecutionService
from backend.core.errors import ValidationError
from backend.core.permissions import ROLE_PERMISSIONS
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.mail import MailPerson
from backend.utils.enums import GradeComponentType, Roles


def make_user(role_name: str, *, user_id: int = 2718) -> User:
    role = Role(id=1, name=role_name)
    role.permissions = [
        Permission(id=i, name=name)
        for i, name in enumerate(sorted(ROLE_PERMISSIONS[role_name]), start=1)
    ]
    user = User(id=user_id, public_id=uuid.uuid4(), username=f"{role_name.lower()}@example.com",
                first_name="Test", last_name=role_name.title(), timezone="UTC")
    user.roles = [role]
    return user


def person(name: str, role: str = "Student") -> MailPerson:
    return MailPerson(public_id=uuid.uuid4(), name=name, role=role)


# --------------------------------------------------------------------------
# draft_message
# --------------------------------------------------------------------------


def test_a_message_is_saved_as_a_draft_and_never_sent():
    ana = person("Ana Lee")

    async def run():
        ctx = ToolExecutionContext(user=make_user(Roles.TUTOR.value), session=AsyncMock())
        with patch("backend.services.mail_service.MailService.directory", new_callable=AsyncMock, return_value=[ana]), \
             patch("backend.services.mail_service.MailService.save", new_callable=AsyncMock) as save:
            save.return_value = MagicMock(public_id=uuid.uuid4())
            res = await handle_draft_message(
                {"recipients": ["Ana Lee"], "subject": "Catch-up", "body": "Hi Ana,\n\nSee you Monday."},
                ctx,
            )
        assert save.await_args.kwargs["send"] is False
        payload = save.await_args.args[1]
        assert payload.to == [ana.public_id]
        assert payload.email_copy is False
        assert res["status"] == "DRAFT_SAVED"
        assert "Nothing has been sent" in res["message"]

    asyncio.run(run())


def test_an_ambiguous_or_unknown_recipient_saves_nothing():
    """Two Sarahs: the tool asks rather than guessing which one gets the message."""
    async def run():
        ctx = ToolExecutionContext(user=make_user(Roles.TUTOR.value), session=AsyncMock())
        directory = AsyncMock(side_effect=[[person("Sarah Khan"), person("Sarah Jones")], []])
        with patch("backend.services.mail_service.MailService.directory", directory), \
             patch("backend.services.mail_service.MailService.save", new_callable=AsyncMock) as save:
            res = await handle_draft_message(
                {"recipients": ["Sarah", "Nobody Here"], "subject": "s", "body": "b"}, ctx
            )
            save.assert_not_awaited()
        assert res["success"] is False
        assert res["status"] == "NEEDS_CLARIFICATION"
        assert [u["requested"] for u in res["unresolved"]] == ["Sarah", "Nobody Here"]
        assert len(res["unresolved"][0]["candidates"]) == 2
        assert res["unresolved"][1]["candidates"] == []

    asyncio.run(run())


def test_model_text_is_escaped_before_it_becomes_a_message_body():
    out = _text_to_html('<script>alert(1)</script>\nline two\n\n<b>para</b>')
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert out == "<p>&lt;script&gt;alert(1)&lt;/script&gt;<br>line two</p><p>&lt;b&gt;para&lt;/b&gt;</p>"


# --------------------------------------------------------------------------
# post_announcement
# --------------------------------------------------------------------------


def test_an_announcement_is_staged_and_only_posted_on_confirmation():
    async def run():
        tutor = make_user(Roles.TUTOR.value)
        session = AsyncMock()
        batch = MagicMock(public_id=uuid.uuid4(), batch_code="B1")
        session.execute.return_value = MagicMock(**{"scalar_one_or_none.return_value": batch})
        ctx = ToolExecutionContext(user=tutor, session=session)
        svc = "backend.services.announcement_service.AnnouncementService"
        with patch(f"{svc}._resolve_batch", new_callable=AsyncMock, return_value=9), \
             patch(f"{svc}._assert_may_target", new_callable=AsyncMock) as may_target, \
             patch(f"{svc}.create", new_callable=AsyncMock) as create:
            staged = await get_tool_registry().execute_tool(
                name="post_announcement",
                arguments={"title": "Room change", "content": "We meet in 4B.", "batch_code": "B1"},
                context=ctx,
            )
            create.assert_not_awaited()
            # The targeting rule was checked before the person was asked.
            may_target.assert_awaited()
            assert staged["status"] == "REQUIRES_CONFIRMATION"
            assert staged["preview_summary"] == "Post the announcement 'Room change' to batch B1?"

            create.return_value = MagicMock(public_id=uuid.uuid4(), title="Room change")
            res = await ConfirmationExecutionService(session).execute_ticket(ticket_id=staged["ticket_id"], actor=tutor)
            create.assert_awaited_once()
            assert create.await_args.args[0].batch_id == batch.public_id
            assert res["success"] is True

    asyncio.run(run())


def test_a_tutor_who_may_not_target_the_batch_is_refused_before_any_ticket():
    from backend.core.errors import AuthorizationError

    async def run():
        session = AsyncMock()
        session.execute.return_value = MagicMock(
            **{"scalar_one_or_none.return_value": MagicMock(public_id=uuid.uuid4(), batch_code="B9")}
        )
        ctx = ToolExecutionContext(user=make_user(Roles.TUTOR.value), session=session)
        svc = "backend.services.announcement_service.AnnouncementService"
        with patch(f"{svc}._resolve_batch", new_callable=AsyncMock, return_value=9), \
             patch(f"{svc}._assert_may_target", new_callable=AsyncMock, side_effect=AuthorizationError("not yours")), \
             patch("backend.ai.tickets.ConfirmationTicketManager.create_ticket", new_callable=AsyncMock) as issue:
            with pytest.raises(AuthorizationError):
                await get_tool_registry().execute_tool(
                    name="post_announcement",
                    arguments={"title": "t", "content": "c", "batch_code": "B9"},
                    context=ctx,
                )
            issue.assert_not_awaited()

    asyncio.run(run())


# --------------------------------------------------------------------------
# record_exam_marks
# --------------------------------------------------------------------------


def _exam_context(candidates: list[User], total=Decimal("100")):
    tutor = make_user(Roles.TUTOR.value)
    session = AsyncMock()
    exam = MagicMock(public_id=uuid.uuid4(), title="Midterm", total_marks=total)

    def execute(stmt, *_a, **_k):
        text = str(stmt)
        if "FROM exams" in text:
            return MagicMock(**{"scalar_one_or_none.return_value": exam})
        return MagicMock(**{"scalars.return_value.unique.return_value": candidates})

    session.execute = AsyncMock(side_effect=execute)
    return ToolExecutionContext(user=tutor, session=session), exam


def _student(first: str, last: str, sid: int) -> User:
    return User(id=sid, public_id=uuid.uuid4(), username=f"{first}@x.test", first_name=first, last_name=last)


def test_the_mark_sheet_preview_lists_every_mark_and_confirmation_records_exactly_that():
    ana, bo = _student("Ana", "Lee", 1), _student("Bo", "Kim", 2)

    async def run():
        ctx, exam = _exam_context([ana, bo])
        svc = "backend.services.exam_service.ExamService"
        with patch(f"{svc}.get", new_callable=AsyncMock, return_value=exam), \
             patch(f"{svc}._eligible_student_ids", new_callable=AsyncMock, return_value={1, 2}), \
             patch(f"{svc}.record_results", new_callable=AsyncMock) as record:
            staged = await get_tool_registry().execute_tool(
                name="record_exam_marks",
                arguments={"exam_id": str(exam.public_id),
                           "marks": [{"student": "Ana Lee", "marks_obtained": 72},
                                     {"student": "bo kim", "marks_obtained": 65.5}]},
                context=ctx,
            )
            record.assert_not_awaited()
            assert staged["preview_summary"] == "Record marks for 'Midterm' (out of 100): Ana Lee 72, Bo Kim 65.5?"

            record.return_value = [MagicMock(), MagicMock()]
            res = await ConfirmationExecutionService(ctx.session).execute_ticket(
                ticket_id=staged["ticket_id"], actor=ctx.user
            )
            entries = record.await_args.args[1]
            assert [(e.student_id, e.marks_obtained) for e in entries] == [
                (ana.public_id, Decimal("72")), (bo.public_id, Decimal("65.5")),
            ]
            assert res["success"] is True

    asyncio.run(run())


@pytest.mark.parametrize(
    "marks, reason",
    [
        ([{"student": "Ana Lee", "marks_obtained": 72}, {"student": "Zed Outsider", "marks_obtained": 50}],
         "not a candidate"),
        ([{"student": "Sam Park", "marks_obtained": 70}], "more than one candidate"),
        ([{"student": "Ana Lee", "marks_obtained": 120}], "outside 0-100"),
        ([{"student": "Ana Lee", "marks_obtained": 70}, {"student": "Ana Lee", "marks_obtained": 71}], "twice"),
    ],
)
def test_any_problem_refuses_the_whole_sheet(marks, reason):
    """A sheet that silently drops a name is worse than one that fails visibly."""
    ana = _student("Ana", "Lee", 1)
    sams = [_student("Sam", "Park", 2), _student("Sam", "Park", 3)]

    async def run():
        ctx, exam = _exam_context([ana, *sams])
        svc = "backend.services.exam_service.ExamService"
        with patch(f"{svc}.get", new_callable=AsyncMock, return_value=exam), \
             patch(f"{svc}._eligible_student_ids", new_callable=AsyncMock, return_value={1, 2, 3}), \
             patch(f"{svc}.record_results", new_callable=AsyncMock) as record:
            with pytest.raises(ValidationError, match=reason):
                await get_tool_registry().execute_tool(
                    name="record_exam_marks",
                    arguments={"exam_id": str(exam.public_id), "marks": marks},
                    context=ctx,
                )
            record.assert_not_awaited()

    asyncio.run(run())


# --------------------------------------------------------------------------
# get_batch_gradebook
# --------------------------------------------------------------------------


def test_gradebook_reads_through_the_scoped_service_and_computes_percentages():
    async def run():
        guardian = make_user(Roles.GUARDIAN.value)
        session = AsyncMock()
        batch = MagicMock(public_id=uuid.uuid4(), batch_code="B1")
        session.execute.return_value = MagicMock(**{"scalar_one_or_none.return_value": batch})
        entry = MagicMock(score=Decimal("18"), max_score=Decimal("24"), component_type=GradeComponentType.QUIZ)
        entry.student = _student("Ana", "Lee", 1)
        with patch("backend.services.gradebook_service.GradeBookService.list_entries",
                   new_callable=AsyncMock, return_value=([entry], 1)) as listing:
            res = await handle_get_batch_gradebook({"batch_code": "B1"}, ToolExecutionContext(user=guardian, session=session))
        # The scoping is the service's: it is handed the caller, not a filter of ours.
        assert listing.await_args.kwargs["actor"] is guardian
        assert listing.await_args.kwargs["batch_public_id"] == batch.public_id
        assert res["entries"] == [
            {"student": "Ana Lee", "component": "QUIZ", "score": 18.0, "max_score": 24.0, "percentage": 75.0}
        ]

    asyncio.run(run())


def test_new_tools_reach_exactly_the_intended_roles():
    def offered(role):
        return {t.name for t in get_tool_registry().list_tools_for_caller(make_user(role))}

    staff_only = {"post_announcement", "record_exam_marks"}
    for role in (Roles.STUDENT.value, Roles.GUARDIAN.value, Roles.CORPORATE_MANAGER.value):
        assert not (staff_only & offered(role)), role
        assert {"draft_message", "get_batch_gradebook"} <= offered(role), role
    for role in (Roles.TUTOR.value, Roles.ADMIN.value, Roles.SUPER_ADMIN.value):
        assert staff_only <= offered(role), role
