"""Country, city and timezone queries -- read-heavy reference data."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from backend.models.geo import City, Country, TimeZone
from backend.repositories.base import BaseRepository
from backend.schemas.base import PageParams


class CountryRepository(BaseRepository[Country]):
    model = Country

    async def list_all(self) -> list[Country]:
        stmt = select(Country).order_by(Country.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_code(self, code: str) -> Country | None:
        # `get_by_public_id` (the API-facing lookup) is inherited from
        # BaseRepository; this one exists for `city.country_code`-style
        # lookups where the caller has an ISO alpha-2 code, not a public_id.
        stmt = select(Country).where(Country.code == code.upper())
        return (await self.session.execute(stmt)).scalar_one_or_none()


class CityRepository(BaseRepository[City]):
    model = City

    def _base(self):
        return select(City).options(selectinload(City.country))

    async def get_by_public_id_full(self, public_id: uuid.UUID) -> City | None:
        stmt = self._base().where(City.public_id == public_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, city_id: int) -> City | None:
        stmt = self._base().where(City.id == city_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def search(
        self,
        params: PageParams,
        *,
        country_id: int | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[City], int]:
        stmt = self._base()

        if country_id is not None:
            stmt = stmt.where(City.country_id == country_id)
        if query:
            like = f"%{query.strip().lower()}%"
            stmt = stmt.where(func.lower(City.name).like(like))

        # Largest first: with a substring match potentially returning
        # hundreds of small villages that happen to share a prefix with a
        # capital, population order is what makes a typeahead usable.
        stmt = stmt.order_by(City.population.desc().nulls_last(), City.name)
        return await self.paginate(stmt, params)  # type: ignore[return-value]


class TimeZoneRepository(BaseRepository[TimeZone]):
    model = TimeZone

    async def list_all(self, *, query: str | None = None) -> list[TimeZone]:
        stmt = select(TimeZone)
        if query:
            like = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(TimeZone.code).like(like),
                    func.lower(TimeZone.description).like(like),
                )
            )
        stmt = stmt.order_by(TimeZone.code)
        return list((await self.session.execute(stmt)).scalars().all())

    async def exists(self, code: str) -> bool:
        stmt = select(TimeZone.code).where(TimeZone.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None
