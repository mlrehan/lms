"""Shared schema conventions.

Response shape, decided once here so every endpoint is consistent:

* A single resource is returned **bare** -- `{"public_id": ..., "name": ...}`,
  not wrapped in a `{"data": ...}` envelope. The envelope buys uniformity at
  the cost of a level of nesting on every read, and errors are already
  distinguishable by status code plus the `{code, message}` body from
  `core/errors.py`, so a client never has to guess which shape it got.

* A collection is returned as :class:`Page`, which carries the items plus the
  paging metadata a client needs to render "showing 51-100 of 2,431" without
  a second request.

Identifiers exposed here are always `public_id` (UUID). The integer primary
key never crosses the API boundary -- it is sequential and therefore
enumerable, and leaking it invites `?id=1,2,3...` scraping.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIModel(BaseModel):
    """Base for every response schema.

    `from_attributes=True` lets a router return an ORM object directly and
    have FastAPI serialise it through the schema, so there is no hand-written
    model->dict mapping layer to fall out of sync with the model.
    """

    model_config = ConfigDict(from_attributes=True)


class RequestModel(BaseModel):
    """Base for every request body.

    `extra="forbid"` makes a misspelled field a loud 422 instead of a silently
    ignored one -- the difference between a client learning it sent
    `frist_name` and a user wondering why their edit didn't save.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TimestampedModel(APIModel):
    created_at: datetime
    updated_at: datetime | None = None


# =============================================================================
# PAGINATION
# =============================================================================

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class PageParams:
    """Pagination query parameters, as a FastAPI dependency.

    The hard `MAX_PAGE_SIZE` cap is the point: without it, `?limit=1000000`
    is a one-request denial of service against a table the spec expects to
    hold 10,000+ students.
    """

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Total rows matching the query, ignoring paging.")
    limit: int
    offset: int

    @classmethod
    def build(cls, items: list[T], *, total: int, params: PageParams) -> "Page[T]":
        return cls(items=items, total=total, limit=params.limit, offset=params.offset)


class PublicIdRef(APIModel):
    """A minimal reference to another resource, for embedding in responses
    where the full object would be wasteful (or would recurse)."""

    public_id: uuid.UUID
