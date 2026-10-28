"""Unit tests for Permission-Aware RAG Retriever."""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ai.rag.retriever import (
    PermissionAwareRetriever,
    _cosine_similarity,
)
from backend.models.ai_embedding import ResourceEmbedding
from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.utils.enums import Roles


def test_cosine_similarity_math():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine_similarity([], []) == 0.0
    assert round(_cosine_similarity([1.0, 1.0], [1.0, 0.0]), 4) == 0.7071


def test_retriever_excludes_restricted_materials_for_students():
    async def run_test():
        # Setup student user
        student = User(id=5, username="student1", slug="student1", hashed_password="pw")
        r_student = Role(id=2, name=Roles.STUDENT.value)
        r_student.permissions = [Permission(id=1, name="resource.read")]  # No view_restricted!
        student.roles = [r_student]

        # Candidate chunks
        chunk_public = ResourceEmbedding(
            id=1,
            public_id=uuid.uuid4(),
            resource_id=10,
            chunk_index=0,
            chunk_text="Public Python Loops Lesson",
            embedding=[1.0, 0.0],
            is_restricted=False,
            course_id=101,
        )
        chunk_restricted = ResourceEmbedding(
            id=2,
            public_id=uuid.uuid4(),
            resource_id=11,
            chunk_index=0,
            chunk_text="Staff Answer Key & Solutions",
            embedding=[1.0, 0.0],
            is_restricted=True,
            course_id=101,
        )

        mock_session = MagicMock()
        # Mock query return: only public chunk returned by SQL because caller is not staff
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (chunk_public, uuid.uuid4(), "Public Python Notes"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_client = MagicMock()
        mock_client.create_embeddings = AsyncMock(return_value=[[1.0, 0.0]])

        # Each candidate file is admitted by ResourceService.get, the rule the
        # Resources screen uses; here it admits, so the test is about the SQL
        # filter on the live staff-only column.
        with patch("backend.ai.rag.retriever.ResourceService.get", new_callable=AsyncMock):

            retriever = PermissionAwareRetriever(session=mock_session, client=mock_client)
            results = await retriever.search(
                query="Python loops",
                user=student,
                course_id=101,
            )

            assert len(results) == 1
            # Students are filtered on the live resources.is_restricted, not the
            # copy taken into the index when it was built.
            sql = str(mock_session.execute.call_args[0][0]).lower()
            assert "resources.is_restricted is false" in sql
            assert results[0].resource_name == "Public Python Notes"
            assert results[0].is_restricted is False
            assert "Public" in results[0].text

    asyncio.run(run_test())


def test_retriever_allows_restricted_materials_for_staff():
    async def run_test():
        tutor = User(id=2, username="tutor1", slug="tutor1", hashed_password="pw")
        r_tutor = Role(id=1, name=Roles.TUTOR.value)
        r_tutor.permissions = [
            Permission(id=1, name="resource.read"),
            Permission(id=2, name="resource.view_restricted"),  # Holds view_restricted!
        ]
        tutor.roles = [r_tutor]

        chunk_restricted = ResourceEmbedding(
            id=2,
            public_id=uuid.uuid4(),
            resource_id=11,
            chunk_index=0,
            chunk_text="Staff Marking Guidance",
            embedding=[1.0, 0.0],
            is_restricted=True,
            course_id=101,
        )

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (chunk_restricted, uuid.uuid4(), "Staff Marking Guide"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_client = MagicMock()
        mock_client.create_embeddings = AsyncMock(return_value=[[1.0, 0.0]])

        # Each candidate file is admitted by ResourceService.get, the rule the
        # Resources screen uses; here it admits, so the test is about the SQL
        # filter on the live staff-only column.
        with patch("backend.ai.rag.retriever.ResourceService.get", new_callable=AsyncMock):

            retriever = PermissionAwareRetriever(session=mock_session, client=mock_client)
            results = await retriever.search(
                query="Marking rubric",
                user=tutor,
                course_id=101,
            )

            assert len(results) == 1
            assert "is_restricted is false" not in str(mock_session.execute.call_args[0][0]).lower()
            assert results[0].is_restricted is True
            assert "Staff Marking" in results[0].text

    asyncio.run(run_test())

