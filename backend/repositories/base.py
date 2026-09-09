"""Generic async repository.

Repositories own *query construction*; services own business rules. The split
matters at this size: without it, "which rows may this caller see" gets
re-derived slightly differently in every endpoint that asks, and one of those
derivations is eventually wrong in the direction that leaks data.

Deliberately **not** a generic auto-CRUD API generator. Each domain gets its
own repository subclass with the queries that domain actually needs, because
the useful queries here are things like "batches this tutor teaches" -- which
no amount of generic `list(model)` machinery can express, and which is
precisely where the authorization rules live.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.base import Base
from backend.schemas.base import PageParams

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Query helpers shared by every repository.

    Subclasses set :attr:`model` and add their own domain queries.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads ---------------------------------------------------------------

    async def get_by_id(self, entity_id: int) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_by_public_id(self, public_id: uuid.UUID) -> ModelT | None:
        """Look up by the externally-visible identifier.

        Every route that accepts an id from a client resolves it through
        here, so the integer primary key stays an internal detail.
        """
        stmt = select(self.model).where(self.model.public_id == public_id)  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def paginate(
        self,
        stmt: Select[Any],
        params: PageParams,
    ) -> tuple[Sequence[Any], int]:
        """Run ``stmt`` for one page and return ``(rows, total)``.

        The count reuses the caller's exact statement as a subquery rather
        than rebuilding the filters, so the total can never describe a
        different query than the rows do -- the classic pagination bug where
        "1 of 400" is shown above an empty table.

        `order_by` is stripped from the count: sorting a result set nobody
        reads is wasted work, and Postgres rejects an ORDER BY over a column
        not in the select list of some aggregate forms.
        """
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        page_stmt = stmt.limit(params.limit).offset(params.offset)
        rows = (await self.session.execute(page_stmt)).scalars().unique().all()
        return rows, int(total)

    # -- writes --------------------------------------------------------------

    def add(self, entity: ModelT) -> ModelT:
        """Stage a new row.

        No commit here, and no `flush` unless a caller needs the generated
        id: the transaction boundary belongs to the request (see
        `db/dependencies.py`), so a service can make several repository calls
        and have them succeed or fail as one unit.
        """
        self.session.add(entity)
        return entity

    async def add_and_flush(self, entity: ModelT) -> ModelT:
        """Stage a row and flush, so server-generated values (the primary
        key, server defaults) are populated -- without committing."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Hard delete. Most domains should soft-delete instead; this exists
        for the join rows (role grants, tag links) where there is no history
        worth keeping and a tombstone would just complicate every query."""
        await self.session.delete(entity)
