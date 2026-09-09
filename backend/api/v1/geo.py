"""Geo reference data endpoints: countries, cities, timezones.

Gated on authentication only -- no dedicated permission. This is
non-confidential, non-mutable reference data every role needs equally (any
signed-in user editing their own profile needs to pick a city or timezone);
inventing a `geo.read` permission would add friction with no security benefit,
unlike `/permissions` or `/roles`, which describe the authorization system
itself and are gated accordingly.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import CurrentUser
from backend.db.dependencies import DBSession
from backend.schemas.base import Page, PageParams
from backend.schemas.geo import CityResponse, CitySummary, CountryResponse, TimeZoneResponse
from backend.services.geo_service import GeoService

router = APIRouter(prefix="/geo", tags=["Geo reference data"])


def _city_response(c) -> CityResponse:  # type: ignore[no-untyped-def]
    return CityResponse(
        public_id=c.public_id,
        name=c.name,
        population=c.population,
        timezone=c.timezone,
        latitude=c.latitude,
        longitude=c.longitude,
        country_id=c.country.public_id,
        country_name=c.country.name,
        country_code=c.country.code,
    )


@router.get("/countries", response_model=list[CountryResponse], summary="List all countries")
async def list_countries(session: DBSession, _actor: CurrentUser) -> list[CountryResponse]:
    """Unpaginated: 250 rows is the entire, fixed set -- the same reasoning
    as the role catalog."""
    rows = await GeoService(session).list_countries()
    return [CountryResponse.model_validate(c) for c in rows]


@router.get(
    "/countries/{country_id}/cities",
    response_model=Page[CitySummary],
    summary="List/search cities in a country",
)
async def list_country_cities(
    country_id: uuid.UUID,
    session: DBSession,
    _actor: CurrentUser,
    params: Annotated[PageParams, Depends()],
    query: Annotated[str | None, Query(max_length=100, description="Substring match on city name.")] = None,
) -> Page[CitySummary]:
    """Ordered by population, largest first -- a substring match on a common
    prefix can return hundreds of small villages, and population order is
    what makes this usable as a typeahead."""
    rows, total = await GeoService(session).search_cities(
        params, country_public_id=country_id, query=query
    )
    return Page.build([CitySummary.model_validate(c) for c in rows], total=total, params=params)


@router.get("/cities/{city_id}", response_model=CityResponse, summary="Get one city")
async def get_city(city_id: uuid.UUID, session: DBSession, _actor: CurrentUser) -> CityResponse:
    return _city_response(await GeoService(session).get_city(city_id))


@router.get("/timezones", response_model=list[TimeZoneResponse], summary="List/search timezones")
async def list_timezones(
    session: DBSession,
    _actor: CurrentUser,
    query: Annotated[str | None, Query(max_length=100)] = None,
) -> list[TimeZoneResponse]:
    """Unpaginated: ~350-450 IANA zone names is small enough to return
    whole; `query` narrows a client-side combobox rather than paging it."""
    rows = await GeoService(session).list_timezones(query=query)
    return [TimeZoneResponse.model_validate(t) for t in rows]
