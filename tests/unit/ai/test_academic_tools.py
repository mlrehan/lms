"""Unit tests for Academic Assessment AI tools."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.tools.academic_tools import handle_create_assessment_draft
from backend.ai.tools.registry import ToolExecutionContext
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.models.identity.user import User


def test_create_assessment_draft_validates_title():
    async def run_test():
        ctx = ToolExecutionContext(user=MagicMock(), session=MagicMock())
        with pytest.raises(ValidationError) as exc:
            await handle_create_assessment_draft({"title": ""}, ctx)
        assert "title is required" in str(exc.value).lower()

    asyncio.run(run_test())


def test_create_assessment_draft_validates_course_id():
    async def run_test():
        ctx = ToolExecutionContext(user=MagicMock(), session=MagicMock())
        with pytest.raises(ValidationError) as exc:
            await handle_create_assessment_draft({"title": "Quiz 1", "course_id": ""}, ctx)
        assert "course id is required" in str(exc.value).lower()

    asyncio.run(run_test())


def test_create_assessment_draft_validates_questions_present():
    async def run_test():
        mock_course = MagicMock(id=1, public_id="course-uuid")
        with patch("backend.ai.tools.academic_tools.CourseService") as mock_cs_cls:
            mock_cs = MagicMock()
            mock_cs.get_by_id_or_public_id = AsyncMock(return_value=mock_course)
            mock_cs_cls.return_value = mock_cs

            with patch("backend.ai.tools.academic_tools.ScopeResolver") as mock_sr_cls:
                mock_sr = MagicMock()
                mock_scope = MagicMock()
                mock_scope.allows.return_value = True
                mock_sr.visible_course_ids = AsyncMock(return_value=mock_scope)
                mock_sr_cls.return_value = mock_sr

                ctx = ToolExecutionContext(user=MagicMock(), session=MagicMock())
                with pytest.raises(ValidationError) as exc:
                    await handle_create_assessment_draft({
                        "title": "Quiz 1",
                        "course_id": "course-uuid",
                        "questions": [],
                    }, ctx)
                assert "at least one question" in str(exc.value).lower()

    asyncio.run(run_test())
