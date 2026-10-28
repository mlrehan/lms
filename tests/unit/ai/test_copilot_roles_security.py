"""Zero-Trust Security & Role Separation Tests for LMS AI Copilots.

Verifies strict object-level authorization, role boundaries, tool availability,
cross-user denial, and SQL safety for Corporate Manager, Guardian, and Student.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ai.agents.corporate import CorporateManagerAgent
from backend.ai.agents.guardian import GuardianAgent
from backend.ai.agents.student import StudentAgent
from backend.ai.security import SecurityPolicyEngine
from backend.ai.tools.database_tools import validate_sql_safety
from backend.ai.tools.registry import get_tool_registry
from backend.core.errors import AuthorizationError
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def build_test_user(*, role_name: str, permissions: list[str]) -> User:
    u = User(
        id=42,
        username=f"user_{role_name.lower()}",
        slug=f"user_{role_name.lower()}",
        hashed_password="pw",
        timezone="UTC",
    )
    r = Role(id=10, name=role_name)
    r.permissions = [Permission(id=i, name=p) for i, p in enumerate(permissions, 1)]
    u.roles = [r]
    return u


class TestRoleToolSeparation:
    @pytest.fixture
    def registry(self):
        return get_tool_registry()

    @pytest.fixture
    def student_user(self):
        perms = [
            "academic.read", "assignment.read", "assignment.submit",
            "attendance.read", "course.read", "enrollment.read",
            "quiz.read", "session.read", "resource.read",
        ]
        return build_test_user(role_name=Roles.STUDENT.value, permissions=perms)

    @pytest.fixture
    def guardian_user(self):
        perms = [
            "academic.read", "assignment.read", "attendance.read",
            "course.read", "enrollment.read", "guardian.read",
            "quiz.read", "session.read",
        ]
        return build_test_user(role_name=Roles.GUARDIAN.value, permissions=perms)

    @pytest.fixture
    def corporate_user(self):
        perms = [
            "academic.read", "assignment.read", "attendance.read",
            "course.read", "enrollment.create", "enrollment.read",
            "grade.read", "managed_student.read", "organization.enroll",
            "organization.read", "quiz.read", "report.read",
            "session.read", "team.read",
        ]
        return build_test_user(role_name=Roles.CORPORATE_MANAGER.value, permissions=perms)

    def test_student_tool_availability(self, registry, student_user):
        tools = registry.list_tools_for_caller(student_user)
        tool_names = {t.name for t in tools}

        # Must have student-appropriate tools
        assert "get_student_assessments_and_deadlines" in tool_names
        assert "get_student_enrolled_courses" in tool_names
        # Students submit their own work; the assistant is not offered the tool.
        assert "submit_assignment_solution" not in tool_names
        assert "execute_database_query" not in tool_names
        assert "inspect_database_schema" not in tool_names
        assert "get_attendance_summary" in tool_names
        assert "get_my_schedule" in tool_names

        # Must NOT have administrative or tutor creation tools
        assert "enroll_corporate_employee" not in tool_names
        assert "get_guardian_dependents" not in tool_names
        assert "create_assessment_draft" not in tool_names
        assert "publish_assessment" not in tool_names
        assert "sync_all_data" not in tool_names
        assert "delete_inactive_users" not in tool_names

    def test_guardian_tool_availability(self, registry, guardian_user):
        tools = registry.list_tools_for_caller(guardian_user)
        tool_names = {t.name for t in tools}

        # Must have guardian-appropriate tools
        assert "get_guardian_dependents" in tool_names
        assert "get_student_assessments_and_deadlines" in tool_names
        assert "get_student_enrolled_courses" in tool_names
        assert "get_attendance_summary" in tool_names
        assert "get_my_schedule" in tool_names

        # Must NOT have mutation or management tools
        assert "submit_assignment_solution" not in tool_names
        assert "enroll_corporate_employee" not in tool_names
        assert "create_assessment_draft" not in tool_names
        assert "publish_assessment" not in tool_names
        assert "mark_session_attendance" not in tool_names

    def test_corporate_manager_tool_availability(self, registry, corporate_user):
        tools = registry.list_tools_for_caller(corporate_user)
        tool_names = {t.name for t in tools}

        # Must have corporate manager tools
        assert "get_corporate_training_progress" in tool_names
        assert "enroll_corporate_employee" in tool_names
        assert "get_attendance_summary" in tool_names
        assert "get_student_assessments_and_deadlines" in tool_names
        assert "get_student_enrolled_courses" in tool_names
        assert "generate_institution_report" in tool_names

        # Must NOT have guardian or tutor authoring tools
        assert "get_guardian_dependents" not in tool_names
        assert "submit_assignment_solution" not in tool_names
        assert "create_assessment_draft" not in tool_names
        assert "publish_assessment" not in tool_names


class TestStrictPolicyAuthorizations:
    def test_student_cannot_invoke_tutor_publish(self):
        registry = get_tool_registry()
        publish_tool = registry.get("publish_assessment")
        assert publish_tool is not None

        student = build_test_user(role_name=Roles.STUDENT.value, permissions=["course.read"])
        with pytest.raises(AuthorizationError):
            SecurityPolicyEngine.authorize_tool_invocation(
                tool_policy=publish_tool.policy,
                user=student,
            )

    def test_assignment_submission_tool_is_not_registered(self):
        """Nobody -- student, guardian or admin -- can have the AI hand work in."""
        assert get_tool_registry().get("submit_assignment_solution") is None

    @pytest.mark.parametrize(
        "role_name",
        [Roles.STUDENT.value, Roles.GUARDIAN.value, Roles.TUTOR.value, Roles.CORPORATE_MANAGER.value, Roles.ADMIN.value],
    )
    def test_raw_sql_tools_are_super_admin_only(self, role_name):
        """Raw SQL bypasses row-level scoping, so only the Super Admin is offered it --
        even a caller who holds `institution.view_all` (an Administrator) is refused."""
        registry = get_tool_registry()
        user = build_test_user(role_name=role_name, permissions=["institution.view_all"])
        offered = {t.name for t in registry.list_tools_for_caller(user)}
        assert "execute_database_query" not in offered
        assert "inspect_database_schema" not in offered
        for name in ("execute_database_query", "inspect_database_schema"):
            with pytest.raises(AuthorizationError):
                SecurityPolicyEngine.authorize_tool_invocation(
                    tool_policy=registry.get(name).policy, user=user
                )

    def test_raw_sql_tools_are_offered_to_super_admin(self):
        registry = get_tool_registry()
        user = build_test_user(role_name=Roles.SUPER_ADMIN.value, permissions=["institution.view_all"])
        offered = {t.name for t in registry.list_tools_for_caller(user)}
        assert {"execute_database_query", "inspect_database_schema"} <= offered

    def test_student_cannot_invoke_corporate_enrollment(self):
        registry = get_tool_registry()
        enroll_tool = registry.get("enroll_corporate_employee")
        assert enroll_tool is not None

        student = build_test_user(
            role_name=Roles.STUDENT.value,
            permissions=["enrollment.create", "organization.enroll"],
        )
        with pytest.raises(AuthorizationError):
            SecurityPolicyEngine.authorize_tool_invocation(
                tool_policy=enroll_tool.policy,
                user=student,
            )


class TestSQLSafetyBoundaries:
    def test_student_restricted_tables(self):
        student_roles = {Roles.STUDENT.value}

        # Restricted admin/operational tables
        for tbl in ["audit_logs", "system_settings", "sync_pipeline_runs", "exam_results"]:
            valid, err, _ = validate_sql_safety(f"SELECT * FROM {tbl}", student_roles)
            assert valid is False
            assert "restricted" in (err or "").lower() or "denied" in (err or "").lower()

    def test_student_private_work_table_unfiltered_denial(self):
        student_roles = {Roles.STUDENT.value}

        # Unfiltered queries on personal submission tables must be rejected
        valid, err, _ = validate_sql_safety("SELECT * FROM quiz_attempts", student_roles)
        assert valid is False
        assert "unfiltered" in (err or "").lower()

        valid, err, _ = validate_sql_safety("SELECT * FROM assignment_submissions", student_roles)
        assert valid is False
        assert "unfiltered" in (err or "").lower()

        # Query WITH authorized student filter is permitted
        valid, err, sanitized = validate_sql_safety(
            "SELECT * FROM quiz_attempts WHERE student_id = 42", student_roles
        )
        assert valid is True
        assert err is None
        assert "LIMIT" in sanitized

    def test_mutating_sql_forbidden(self):
        manager_roles = {Roles.CORPORATE_MANAGER.value}
        valid, err, _ = validate_sql_safety(
            "UPDATE users SET email = 'hacked@hack.com' WHERE id = 1", manager_roles
        )
        assert valid is False
        assert "read-only" in (err or "").lower() or "prohibited" in (err or "").lower()
