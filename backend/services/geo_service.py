"""Geo reference data lookups. Pure reads -- no business rules, no audit
trail entries; nothing here is sensitive or mutable through the API."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import NotFoundError
from backend.models.geo import City, Country, TimeZone
from backend.repositories.geo import CityRepository, CountryRepository, TimeZoneRepository
from backend.schemas.base import PageParams


class GeoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.countries = CountryRepository(session)
        self.cities = CityRepository(session)
        self.timezones = TimeZoneRepository(session)

    async def list_countries(self) -> list[Country]:
        return await self.countries.list_all()

    async def get_country(self, public_id: uuid.UUID) -> Country:
        country = await self.countries.get_by_public_id(public_id)
        if country is None:
            raise NotFoundError("Country not found.")
        return country

    async def search_cities(
        self,
        params: PageParams,
        *,
        country_public_id: uuid.UUID | None = None,
        query: str | None = None,
    ) -> tuple[Sequence[City], int]:
        country_id = None
        if country_public_id is not None:
            country_id = (await self.get_country(country_public_id)).id
        return await self.cities.search(params, country_id=country_id, query=query)

    async def get_city(self, public_id: uuid.UUID) -> City:
        city = await self.cities.get_by_public_id_full(public_id)
        if city is None:
            raise NotFoundError("City not found.")
        return city

    async def list_timezones(self, *, query: str | None = None) -> list[TimeZone]:
        return await self.timezones.list_all(query=query)
