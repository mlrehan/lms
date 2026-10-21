"""RAG Search Tool for Curriculum & Course Materials.

Provides semantic search over indexed learning resources with permission-aware filtering.
"""

from __future__ import annotations

from typing import Any
from sqlalchemy import select

from backend.ai.rag.retriever import PermissionAwareRetriever
from backend.ai.security import RiskLevel, ToolPolicy
from backend.ai.tools.registry import ToolDefinition, ToolExecutionContext
from backend.core.errors import ValidationError
from backend.models.course import Course


async def handle_search_course_knowledge(
    arguments: dict[str, Any],
    context: ToolExecutionContext,
) -> dict[str, Any]:
    """Search course materials, lecture notes, and slides within caller scope."""
    query = arguments.get("query", "").strip()
    if not query:
        raise ValidationError("Search query is required.")

    course_id_int: int | None = None
    course_identifier = arguments.get("course_identifier")
    if course_identifier:
        stmt = select(Course.id).where(
            (Course.code == course_identifier)
            | (Course.public_id == course_identifier if len(course_identifier) == 36 else False)
        )
        course_id_int = (await context.session.execute(stmt)).scalar_one_or_none()

    retriever = PermissionAwareRetriever(session=context.session)
    chunks = await retriever.search(
        query=query,
        user=context.user,
        course_id=course_id_int,
        limit=int(arguments.get("limit", 4)),
    )

    if not chunks:
        return {
            "query": query,
            "results_count": 0,
            "message": "No matching authorized course materials found for this inquiry.",
            "results": [],
        }

    formatted = []
    for c in chunks:
        formatted.append({
            "resource_title": c.resource_name,
            "similarity_score": c.similarity,
            "content_excerpt": c.text,
            "chunk_index": c.chunk_index,
        })

    return {
        "query": query,
        "results_count": len(formatted),
        "results": formatted,
    }


search_course_knowledge_tool = ToolDefinition(
    name="search_course_knowledge",
    description=(
        "Search course lecture sheets, syllabus documents, and learning materials using semantic retrieval. "
        "Strictly excludes staff-restricted materials from unauthorized students and guardians."
    ),
    policy=ToolPolicy(
        name="search_course_knowledge",
        description="Semantic search over authorized curriculum documents",
        required_permissions=("resource.read",),
        risk_level=RiskLevel.LOW,
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Technical inquiry or topic to search (e.g. 'SQL foreign key cascades', 'Python decorators')",
            },
            "course_identifier": {
                "type": "string",
                "description": "Optional course code or UUID to restrict search",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of excerpts to return (default 4, max 8)",
                "default": 4,
            },
        },
        "required": ["query"],
    },
    handler=handle_search_course_knowledge,
)

