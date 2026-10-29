"""The Super Admin's administrative tools, against a real database.

Each tool is driven the way the registry drives it: authorised by policy, the
preview built, its bound parameters merged in, the handler run. The actors are
accounts this fixture creates -- the real Super Admin is never acted on.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.ai.security import SecurityPolicyEngine
from backend.ai.tools.admin_tools import handle_get_system_overview, handle_manage_user, preview_manage_user
from backend.ai.tools.registry import BOUND_PREFIX, ToolExecutionContext
from backend.ai.tools.superadmin_tools import (
    SUPERADMIN_TOOLS,
    handle_create_user,
    handle_find_users,
    handle_manage_enrollment,
    handle_search_audit_log,
    handle_unlock_account,
    handle_update_system_setting,
    handle_get_system_settings,
    preview_create_user,
    preview_manage_enrollment,
    preview_unlock_account,
    preview_update_system_setting,
)
from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, ConflictError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import CourseStatus, EnrollmentStatus, UserStatus


@pytest.fixture()
def env():  # noqa: ANN201
    tag = "sat" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="ai-superadmin-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def build(s):  # noqa: ANN001, ANN202
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}

        def person(kind: str, *role_names: str) -> User:
            return User(username=f"{tag}.{kind}", slug=f"{tag}-{kind}", email=f"{tag}.{kind}@t.test",
                        first_name=kind.title(), last_name=tag, hashed_password="x",
                        status=UserStatus.ACTIVE, roles=[roles[r] for r in role_names])

        people = {
            "sa": person("sa", "SUPER_ADMIN"), "admin": person("admin", "ADMIN"),
            "tutor": person("tutor", "TUTOR"), "student": person("student", "STUDENT"),
        }
        course = Course(title=f"{tag} course", code=f"{tag}-C", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*people.values(), course])
        await s.flush()
        batch = Batch(batch_code=f"{tag}-B", course_id=course.id, is_active=True, capacity=10)
        batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
        s.add(batch)
        await s.flush()
        return {k: v.id for k, v in people.items()}

    def call(who, fn, commit=False):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory() as s:
                user = await s.get(User, ids[who])
                try:
                    result = await fn(ToolExecutionContext(user=user, session=s))
                    if commit:
                        await s.commit()
                    return result
                finally:
                    await s.rollback()
        return loop.run_until_complete(go())

    try:
        ids = run(build)
        yield type("Env", (), dict(tag=tag, ids=ids, call=staticmethod(call), run=staticmethod(run)))
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                p = {"u": f"{tag}%", "c": f"{tag}-%", "k": f"{tag}.%"}
                people = "(SELECT id FROM users WHERE username LIKE :u OR email LIKE :u)"
                for sql in (
                    f"DELETE FROM notifications WHERE user_id IN {people}",
                    f"DELETE FROM tokens WHERE user_id IN {people}",
                    "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)",
                    "DELETE FROM batches WHERE batch_code LIKE :c",
                    "DELETE FROM courses WHERE code LIKE :c",
                    "DELETE FROM system_settings WHERE key LIKE :k",
                    f"DELETE FROM user_roles WHERE user_id IN {people}",
                    "DELETE FROM users WHERE username LIKE :u OR email LIKE :u",
                ):
                    try:
                        async with s.begin_nested():
                            await s.execute(text(sql), p)
                    except Exception:  # noqa: BLE001 -- a table this run did not touch
                        pass
        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


def _confirm(preview, args):  # noqa: ANN001, ANN202
    return args | {f"{BOUND_PREFIX}{k}": v for k, v in (preview.bound_parameters or {}).items()}


@pytest.mark.parametrize("who", ["admin", "tutor"])
def test_every_new_tool_is_super_admin_only(env, who):  # noqa: ANN001
    async def check(c):  # noqa: ANN001, ANN202
        refused = []
        for tool in SUPERADMIN_TOOLS:
            try:
                SecurityPolicyEngine.authorize_tool_invocation(tool_policy=tool.policy, user=c.user)
            except AuthorizationError:
                refused.append(tool.name)
        return refused
    assert sorted(env.call(who, check)) == sorted(t.name for t in SUPERADMIN_TOOLS)


def test_create_user_goes_through_the_service_with_sign_in_disabled(env):  # noqa: ANN001
    args = {"first_name": "Jane", "last_name": "Tester", "email": f"{env.tag}.jane@example.com", "roles": ["TUTOR"]}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_create_user(args, c)
        assert "Sign-in starts disabled" in preview.summary
        return await handle_create_user(_confirm(preview, args), c)

    result = env.call("sa", go, commit=True)
    assert result["account"]["roles"] == ["TUTOR"] and result["account"]["can_login"] is False

    async def check(s):  # noqa: ANN001, ANN202
        user = (await s.execute(select(User).where(User.email == f"{env.tag}.jane@example.com"))).scalar_one()
        audited = (await s.execute(text(
            "SELECT count(*) FROM audit_logs WHERE entity_type='user' AND action='CREATE' AND entity_id=:i"),
            {"i": user.id})).scalar_one()
        return user, audited
    user, audited = env.run(check)
    assert user.can_login is False
    assert user.hashed_password.startswith("$argon2")  # a real hash, not a raw SQL insert
    assert audited == 1


def test_create_user_refuses_administrator_roles(env):  # noqa: ANN001
    with pytest.raises(ConflictError):
        env.call("sa", lambda c: preview_create_user(
            {"first_name": "X", "email": f"{env.tag}.x@example.com", "roles": ["ADMIN"]}, c))


def test_create_user_refuses_details_changed_after_confirmation(env):  # noqa: ANN001
    args = {"first_name": "Jane", "email": f"{env.tag}.j2@example.com", "roles": ["STUDENT"]}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_create_user(args, c)
        return await handle_create_user(_confirm(preview, args) | {"roles": ["TUTOR"]}, c)

    with pytest.raises(ConflictError):
        env.call("sa", go)


def test_manage_user_removes_a_role_and_switches_sign_in(env):  # noqa: ANN001
    args = {"user_identifier": f"{env.tag}.tutor@t.test", "new_role": "STUDENT", "remove_role": "TUTOR",
            "can_login": True}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_manage_user(args, c)
        assert "remove the TUTOR role" in preview.summary and "allow sign-in" in preview.summary
        return await handle_manage_user(_confirm(preview, args), c)

    result = env.call("sa", go, commit=True)
    assert result["roles"] == ["STUDENT"] and result["can_login"] is True


def test_removing_a_persons_only_role_is_refused(env):  # noqa: ANN001
    with pytest.raises(ConflictError):
        env.call("sa", lambda c: preview_manage_user(
            {"user_identifier": f"{env.tag}.tutor@t.test", "remove_role": "TUTOR"}, c))


def test_unlock_clears_the_lock_without_touching_status(env):  # noqa: ANN001
    async def lock(s):  # noqa: ANN001, ANN202
        u = await s.get(User, env.ids["tutor"])
        u.is_locked, u.failed_login_attempts, u.locked_until = True, 5, datetime.now(UTC) + timedelta(hours=1)
        u.status = UserStatus.SUSPENDED
    env.run(lock)
    args = {"user": f"{env.tag}.tutor@t.test"}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_unlock_account(args, c)
        assert "who is locked out" in preview.summary
        return await handle_unlock_account(_confirm(preview, args), c)

    assert env.call("sa", go, commit=True)["was_locked"] is True

    async def check(s):  # noqa: ANN001, ANN202
        return await s.get(User, env.ids["tutor"])
    u = env.run(check)
    assert u.is_locked_out is False and (u.failed_login_attempts or 0) == 0
    assert u.status is UserStatus.SUSPENDED  # unlock is not a status change


def test_enrol_then_drop_through_the_enrolment_service(env):  # noqa: ANN001
    enrol = {"action": "enroll", "student": f"{env.tag}.student@t.test", "batch_code": f"{env.tag}-B"}

    async def go(c, args):  # noqa: ANN001, ANN202
        preview = await preview_manage_enrollment(args, c)
        return await handle_manage_enrollment(_confirm(preview, args), c)

    assert env.call("sa", lambda c: go(c, enrol), commit=True)["status"] == "CONFIRMED"
    drop = {**enrol, "action": "set_status", "status": "DROPPED"}
    assert env.call("sa", lambda c: go(c, drop), commit=True)["status"] == "DROPPED"

    async def check(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Enrollments.status).join(Batch).where(Batch.batch_code == f"{env.tag}-B"))).scalars().all()
    assert env.run(check) == [EnrollmentStatus.DROPPED]


def test_enrolling_a_non_student_reports_the_services_reason(env):  # noqa: ANN001
    args = {"action": "enroll", "student": f"{env.tag}.tutor@t.test", "batch_code": f"{env.tag}-B"}

    async def go(c):  # noqa: ANN001, ANN202
        preview = await preview_manage_enrollment(args, c)
        return await handle_manage_enrollment(_confirm(preview, args), c)

    with pytest.raises(Exception) as exc:
        env.call("sa", go)
    assert "student" in str(exc.value).lower()


def test_a_setting_change_shows_old_and_new_and_is_bound(env):  # noqa: ANN001
    key = f"{env.tag}.flag"
    first = {"key": key, "value": "on"}

    async def go(c, args, tamper=None):  # noqa: ANN001, ANN202
        preview = await preview_update_system_setting(args, c)
        return preview, await handle_update_system_setting(_confirm(preview, args) | (tamper or {}), c)

    preview, result = env.call("sa", lambda c: go(c, first), commit=True)
    assert "(a new setting)" in preview.summary and result["value"] == "on"
    second = {"key": key, "value": "off"}
    preview, _ = env.call("sa", lambda c: go(c, second), commit=True)
    assert "from 'on' to 'off'" in preview.summary
    with pytest.raises(ConflictError):
        env.call("sa", lambda c: go(c, {"key": key, "value": "x"}, tamper={"value": "y"}))
    assert env.call("sa", lambda c: handle_get_system_settings({"key": key}, c))["value"] == "off"


def test_audit_search_and_find_users(env):  # noqa: ANN001
    found = env.call("sa", lambda c: handle_find_users({"query": env.tag, "role": "TUTOR"}, c))
    assert [u["username"] for u in found["users"]] == [f"{env.tag}.tutor"]
    events = env.call("sa", lambda c: handle_search_audit_log({"actions": ["LOGIN_FAILED"], "limit": 5}, c))
    assert events["shown"] <= 5 and all(e["action"] == "LOGIN_FAILED" for e in events["events"])


def test_health_overview_states_facts_not_a_verdict(env):  # noqa: ANN001
    result = env.call("sa", lambda c: handle_get_system_overview({}, c))
    assert "platform_health" not in result and "Healthy" not in str(result)
    assert result["needs_attention"] and result["users"]["total"] >= 4


def test_bad_details_are_refused_before_confirmation(env):  # noqa: ANN001
    from backend.core.errors import ValidationError as AppValidationError

    with pytest.raises(AppValidationError) as exc:
        env.call("sa", lambda c: preview_create_user(
            {"first_name": "Bad", "email": f"{env.tag}.bad@localhost", "roles": ["STUDENT"]}, c))
    assert "cannot be created" in exc.value.message


def test_a_failed_latest_sync_is_reported_as_needing_attention(env):  # noqa: ANN001
    """Planted inside a transaction that is rolled back: the shared database's
    real sync history is never changed."""
    from backend.models.sync_pipeline import SyncPipelineRun

    async def go(c):  # noqa: ANN001, ANN202
        run = SyncPipelineRun(trigger_type="MANUAL", status="FAILED",
                              started_at=datetime.now(UTC) + timedelta(minutes=5), failure_reason=f"{env.tag} upstream down")
        run.jobs = []
        c.session.add(run)
        await c.session.flush()
        return await handle_get_system_overview({}, c)

    result = env.call("sa", go)  # call() rolls back
    assert any("did not complete" in a and env.tag in a for a in result["needs_attention"])


def test_values_the_account_already_has_are_not_offered_as_changes(env):  # noqa: ANN001
    """The tutor fixture cannot sign in (can_login defaults to false) and is ACTIVE."""
    args = {"user_identifier": f"{env.tag}.tutor@t.test", "new_role": "STUDENT", "can_login": False, "new_status": "ACTIVE"}
    preview = env.call("sa", lambda c: preview_manage_user(args, c))
    assert "sign-in" not in preview.summary and "status" not in preview.summary
    assert "add the STUDENT role" in preview.summary


def test_a_closed_course_is_refused_before_confirmation(env):  # noqa: ANN001
    async def close(s):  # noqa: ANN001, ANN202
        course = (await s.execute(select(Course).where(Course.code == f"{env.tag}-C"))).scalar_one()
        course.status = CourseStatus.COMPLETED
    env.run(close)
    with pytest.raises(ConflictError) as exc:
        env.call("sa", lambda c: preview_manage_enrollment(
            {"action": "enroll", "student": f"{env.tag}.student@t.test", "batch_code": f"{env.tag}-B"}, c))
    assert "COMPLETED" in exc.value.message
