# Bundled reference data — provenance and license

These files are static, version-controlled snapshots fetched once from public
sources, not generated or approximated. Bundling them (instead of the more
common pattern of fetching from a live third-party API during seeding) is a
deliberate choice: it means a production deploy's seed step cannot fail
because an unrelated public API is down, rate-limited, or has changed its
schema, and re-seeding always produces the same result.

Both licenses require attribution wherever this data (or a derivative of it)
is displayed or served — including through this platform's own `/geo/*` API,
since that serves the data back to callers. Attribution is what this file is.

## `countries.json` — 250 rows

Source: [mledoze/countries](https://github.com/mledoze/countries), fetched
2026-09-08 from `dist/countries.json` (commit at time of fetch).
License: **Open Database License (ODbL) v1.0**.
Fields kept: `name` (common name), `code` (ISO 3166-1 alpha-2).

## `cities.json` — 34,134 rows

Source: [GeoNames](https://www.geonames.org/), `cities15000.txt` (every
populated place with population ≥ 15,000), downloaded 2026-09-08 from
`https://download.geonames.org/export/dump/cities15000.zip`.
License: **Creative Commons Attribution 4.0 International (CC BY 4.0)**.
Fields kept: `geoname_id`, `name` (ASCII name), `country_code` (ISO 3166-1
alpha-2, matches `countries.json`), `latitude`, `longitude`, `population`,
`timezone` (IANA zone name).

## Timezones — not a bundled file

Seeded at runtime from Python's own standard library
(`zoneinfo.available_timezones()`), backed by the IANA Time Zone Database
that ships with the OS/`tzdata` package. No network call, no file to go
stale — the set is exactly whatever this deployment's own timezone database
knows about, which is the correct source of truth for "what timezone can a
user legitimately pick."
