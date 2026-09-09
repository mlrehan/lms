"""Geo reference data schemas: countries, cities, timezones.

Read-only from the API's perspective -- these are seeded, not managed
through CRUD endpoints. A tenant that needs a country/city the bundled
GeoNames snapshot doesn't have is an edge case for a later pass, not a
reason to build a full management surface for reference data today.
"""

from __future__ import annotations

import uuid

from backend.schemas.base import APIModel


class CountryResponse(APIModel):
    public_id: uuid.UUID
    name: str
    code: str


class CitySummary(APIModel):
    public_id: uuid.UUID
    name: str
    population: int | None = None
    timezone: str | None = None


class CityResponse(CitySummary):
    latitude: float | None = None
    longitude: float | None = None
    country_id: uuid.UUID
    country_name: str | None = None
    country_code: str | None = None


class TimeZoneResponse(APIModel):
    code: str
    description: str | None = None
