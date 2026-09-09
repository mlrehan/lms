"""Seed countries, cities and timezones.

Countries and cities come from bundled, version-controlled JSON snapshots
(`backend/bootstrap/data/`, see `ATTRIBUTION.md` there for provenance and
license) rather than a live third-party API call at seed time -- so a
production deploy's seeding step cannot fail because an unrelated public API
is down, rate-limited, or has changed shape, and re-seeding is always
reproducible.

Timezones come from the standard library (`zoneinfo`), backed by whatever
IANA time zone database this deployment's OS/`tzdata` package actually has --
the correct source of truth for "what timezone can a user legitimately pick
on this machine," with no file to go stale.

All three are bulk `INSERT ... ON CONFLICT DO NOTHING` via SQLAlchemy Core,
not ORM objects. 34,000+ `City` instances through the identity map would be
needlessly slow and memory-heavy for a one-time load; Core with
`insertmanyvalues` batches the round trips instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import available_timezones

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.models.geo import City, Country, TimeZone

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_json(name: str) -> list[dict]:
    with open(_DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


async def seed_countries(session: AsyncSession) -> int:
    """Insert missing countries. Returns the number inserted."""
    rows = _load_json("countries.json")

    stmt = (
        pg_insert(Country)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[Country.code])
        .returning(Country.id)
    )
    result = await session.execute(stmt)
    inserted = len(result.fetchall())
    await session.flush()
    return inserted


async def seed_cities(session: AsyncSession) -> tuple[int, int]:
    """Insert missing cities. Returns ``(inserted, skipped_unknown_country)``.

    Runs after `seed_countries` in the same transaction, so newly-inserted
    countries are visible to the id lookup below without a separate commit.
    """
    rows = _load_json("cities.json")

    country_ids: dict[str, int] = dict(
        (await session.execute(select(Country.code, Country.id))).all()
    )

    to_insert: list[dict] = []
    skipped = 0
    for row in rows:
        country_id = country_ids.get(row["country_code"])
        if country_id is None:
            skipped += 1
            continue
        to_insert.append(
            {
                "geoname_id": row["geoname_id"],
                "name": row["name"],
                "country_id": country_id,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "population": row.get("population"),
                "timezone": row.get("timezone"),
            }
        )

    inserted = 0
    if to_insert:
        # Batched rather than one INSERT for 34k rows: a single statement
        # with that many VALUES tuples risks the driver's parameter limit,
        # and batching keeps memory bounded regardless of dataset size.
        batch_size = 2000
        for i in range(0, len(to_insert), batch_size):
            batch = to_insert[i : i + batch_size]
            stmt = (
                pg_insert(City)
                .values(batch)
                .on_conflict_do_nothing(index_elements=[City.geoname_id])
                .returning(City.id)
            )
            result = await session.execute(stmt)
            inserted += len(result.fetchall())

    await session.flush()
    return inserted, skipped


async def seed_timezones(session: AsyncSession) -> int:
    """Insert missing IANA timezones from the stdlib's own database."""
    codes = sorted(available_timezones())
    rows = [{"code": code, "description": code.replace("_", " ")} for code in codes]

    stmt = (
        pg_insert(TimeZone)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[TimeZone.code])
        .returning(TimeZone.code)
    )
    result = await session.execute(stmt)
    inserted = len(result.fetchall())
    await session.flush()
    return inserted


async def seed_geo(session: AsyncSession) -> dict[str, int]:
    countries_inserted = await seed_countries(session)
    cities_inserted, cities_skipped = await seed_cities(session)
    timezones_inserted = await seed_timezones(session)

    if cities_skipped:
        # Should never happen against the bundled data (every country_code in
        # cities.json was verified to match a countries.json row when the
        # files were generated) -- a non-zero count here means the two files
        # have drifted apart and is worth investigating, not ignoring.
        logger.warning(
            "Skipped cities with no matching country", extra={"skipped": cities_skipped}
        )

    total_countries = (await session.execute(select(func.count()).select_from(Country))).scalar_one()
    total_cities = (await session.execute(select(func.count()).select_from(City))).scalar_one()
    total_timezones = (await session.execute(select(func.count()).select_from(TimeZone))).scalar_one()

    return {
        "countries_inserted": countries_inserted,
        "cities_inserted": cities_inserted,
        "cities_skipped": cities_skipped,
        "timezones_inserted": timezones_inserted,
        "countries_total": total_countries,
        "cities_total": total_cities,
        "timezones_total": total_timezones,
    }
