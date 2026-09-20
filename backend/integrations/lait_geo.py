"""Resolve LAIT's free-text country and city against our reference tables.

LAIT sends `CountryName: "United Kingdom"` and `City: "Hitchin"` as plain
strings. Our `countries` (250 rows, ISO-coded) and `cities` (34k rows, from
GeoNames) are curated reference data, so the job here is matching, with two
asymmetric rules:

* **A country is never created.** `countries.code` is a required, unique
  2-letter ISO code. A name we could not match would need a code invented for
  it, and a made-up code in a table other lookups are keyed on is worse than
  an empty field. An unmatched country leaves `country_id` empty and is
  counted for review -- with 250 real countries seeded, an unmatched name is
  nearly always an alias or a typo, and aliases are handled below.
* **A city may be created, but only under a resolved country and only if it
  looks like a place.** `cities.country_id` is NOT NULL, so no country means
  no city. Values that are plainly not places (`N/A`, a postcode, an email,
  a name with digits) are rejected rather than becoming a permanent entry in
  every city dropdown in the console.

Matching order, cheapest and most certain first: alias -> exact
case-insensitive -> trigram similarity (`pg_trgm`, already installed) above a
threshold. A tie between two different candidates is treated as no match
rather than a coin toss. "Semantic search" is read as fuzzy string matching,
not embeddings.

`city` is always searched *within* the resolved country: there are two
Londons in the table, and only one of them is in the United Kingdom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.geo import City

SIMILARITY_THRESHOLD = 0.6
_TIE_MARGIN = 0.05

# alias (normalised, see `norm`) -> ISO 3166-1 alpha-2. Keyed by *code*, so it
# keeps working whatever our table happens to call the country.
COUNTRY_ALIASES: dict[str, str] = {
    "uk": "GB", "gb": "GB", "gbr": "GB", "great britain": "GB", "britain": "GB",
    "united kingdom of great britain and northern ireland": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "usa": "US", "us": "US", "america": "US", "united states of america": "US",
    "uae": "AE", "united arab emirates": "AE",
    "ireland": "IE", "republic of ireland": "IE", "eire": "IE",
    "holland": "NL", "netherlands": "NL", "kingdom of the netherlands": "NL",
    "czech republic": "CZ", "czechia": "CZ",
    "ivory coast": "CI", "cote d'ivoire": "CI", "côte d'ivoire": "CI", "cote divoire": "CI",
    "burma": "MM", "myanmar": "MM",
    "swaziland": "SZ", "eswatini": "SZ",
    "macedonia": "MK", "north macedonia": "MK",
    "tanzania": "TZ", "united republic of tanzania": "TZ",
    "russia": "RU", "russian federation": "RU",
    "south korea": "KR", "republic of korea": "KR", "korea south": "KR",
    "north korea": "KP", "democratic peoples republic of korea": "KP",
    "vietnam": "VN", "viet nam": "VN",
    "iran": "IR", "islamic republic of iran": "IR",
    "syria": "SY", "syrian arab republic": "SY",
    "laos": "LA", "lao pdr": "LA",
    "moldova": "MD", "republic of moldova": "MD",
    "bolivia": "BO", "venezuela": "VE", "brunei": "BN", "brunei darussalam": "BN",
    "democratic republic of the congo": "CD", "dr congo": "CD", "drc": "CD",
    "republic of the congo": "CG", "congo brazzaville": "CG",
    "cape verde": "CV", "cabo verde": "CV",
    "east timor": "TL", "timor leste": "TL",
    "palestine": "PS", "palestinian territory": "PS",
    "hong kong": "HK", "hong kong sar": "HK", "macau": "MO", "macao": "MO",
    "taiwan": "TW", "gambia": "GM", "bahamas": "BS",
    "turkey": "TR", "turkiye": "TR",
    # ISO 3166 short names written "Name, Qualifier"; `norm` turns the comma
    # into a space, so these are the normalised forms.
    "tanzania united republic of": "TZ", "korea republic of": "KR",
    "korea democratic peoples republic of": "KP", "iran islamic republic of": "IR",
    "moldova republic of": "MD", "bolivia plurinational state of": "BO",
    "venezuela bolivarian republic of": "VE", "congo democratic republic of the": "CD",
    "micronesia federated states of": "FM", "syrian arab republic": "SY",
}

# Words at the end of a city value that are really the country ("london uk").
_TRAILING_COUNTRY_TOKENS = {"uk", "england", "scotland", "wales", "usa", "us", "united kingdom"}

_JUNK_CITY_VALUES = {
    "n/a", "na", "none", "null", "nil", "-", "--", "tbc", "tba", "unknown",
    "test", "not applicable", "not known", "other", "xx", "xxx",
}
_JOINERS = {"upon", "on", "in", "the", "of", "de", "la", "le", "les", "du", "des", "sur",
            "en", "and", "under", "by", "al", "el"}


def norm(value: str) -> str:
    """Lower-case, `&`->`and`, punctuation out, whitespace collapsed, no leading 'the'."""
    text_ = value.lower().replace("&", " and ")
    # Dots are *removed*, not spaced: "U.K." must become "uk", not "u k".
    text_ = text_.replace(".", "")
    text_ = re.sub(r"[,()\[\]]", " ", text_)
    text_ = re.sub(r"\s+", " ", text_).strip()
    return text_[4:] if text_.startswith("the ") and len(text_) > 4 else text_


def city_junk_reason(value: str) -> str | None:
    """Why a city value should not be turned into a `cities` row, or None."""
    v = value.strip()
    if len(v) < 2:
        return "too short"
    if len(v) > 60:
        return "too long to be a place name"
    if v.lower() in _JUNK_CITY_VALUES:
        return "a placeholder"
    if "@" in v:
        return "looks like an email address"
    if re.search(r"\d", v):
        return "contains digits (postcode or number)"
    if not re.search(r"[^\W\d_]{2}", v):
        return "contains no letters"
    return None


def clean_city(value: str, country_name: str | None) -> str:
    """`London, UK` and `london uk` -> `london`. Only ever *removes* a trailing
    country; a city that merely starts with one (`Wales, Wisconsin`) is left
    alone by requiring something to remain."""
    v = value.split(",")[0].strip()
    words = v.split()
    tokens = set(_TRAILING_COUNTRY_TOKENS)
    if country_name:
        tokens.add(norm(country_name))
    for width in (2, 1):
        if len(words) > width and norm(" ".join(words[-width:])) in tokens:
            words = words[:-width]
            break
    return " ".join(words)


def smart_title(value: str) -> str:
    """Capitalise an all-lower or all-upper name; leave mixed case as typed."""
    if not (value.islower() or value.isupper()):
        return value
    first = True

    def cap(match: re.Match[str]) -> str:
        nonlocal first
        word = match.group(0).lower()
        result = word if (word in _JOINERS and not first) else word.capitalize()
        first = False
        return result

    return re.sub(r"[^\W\d_]+", cap, value)


def edit_distance(a: str, b: str, limit: int) -> int:
    """Optimal-string-alignment distance: insert, delete, substitute, and swap
    two adjacent letters, each costing one. Swaps matter because they are the
    commonest typing error ("Lodnon"), and plain Levenshtein counts one as two.

    Gives up (returning `limit + 1`) once the distance must exceed `limit`.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before_previous: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            cost = previous[j - 1] + (ca != cb)
            best = min(previous[j] + 1, current[j - 1] + 1, cost)
            if before_previous is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                best = min(best, before_previous[j - 2] + 1)
            current.append(best)
        if min(current) > limit:
            return limit + 1
        before_previous, previous = previous, current
    return previous[-1]


def allowed_distance(length: int) -> int:
    """How many typos a name of this length may contain and still be the same
    place: one in a short name, two in a medium one, three in a long one."""
    return 1 if length <= 6 else 2 if length <= 12 else 3


def choose_match(
    query: str, candidates: list[tuple[int, str, float]]
) -> tuple[int | None, bool]:
    """Pick the candidate that is the same place as `query`, or refuse.

    `candidates` are `(id, lower-cased name, trigram similarity)` rows, best
    first. Returns `(id, ambiguous)`. `ambiguous` means two different places
    were equally plausible -- the caller must not *create* one in that case,
    because the honest answer is "one of these", not "neither".

    Two tests, in order. Trigram similarity catches reordered and extended
    names; edit distance catches the typo that similarity scores too low
    (`Hitchen` vs `Hitchin` is only 0.45 similar, yet one letter apart).
    """
    if not candidates:
        return None, False

    top = candidates[0]
    if top[2] >= SIMILARITY_THRESHOLD:
        runner = candidates[1] if len(candidates) > 1 else None
        if runner and top[2] - runner[2] < _TIE_MARGIN and top[2] < 0.99:
            return None, True
        return top[0], False

    limit = allowed_distance(len(query))
    scored = [
        (edit_distance(query, name, limit), cid)
        for cid, name, _sim in candidates
        if name[:1] == query[:1]  # a typo rarely changes the first letter
    ]
    scored = [(d, cid) for d, cid in scored if d <= limit]
    if not scored:
        return None, False
    best = min(d for d, _ in scored)
    winners = [cid for d, cid in scored if d == best]
    return (winners[0], False) if len(winners) == 1 else (None, True)


@dataclass
class GeoStats:
    countries_matched: int = 0
    countries_unmatched: int = 0
    unmatched_country_names: set[str] = field(default_factory=set)
    cities_matched: int = 0
    cities_created: int = 0
    cities_would_create: int = 0
    cities_rejected: int = 0
    cities_ambiguous: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "countries_matched": self.countries_matched,
            "countries_unmatched": self.countries_unmatched,
            "unmatched_country_names": sorted(self.unmatched_country_names)[:25],
            "cities_matched": self.cities_matched,
            "cities_created": self.cities_created,
            "cities_would_create": self.cities_would_create,
            "cities_rejected": self.cities_rejected,
            "cities_ambiguous": self.cities_ambiguous,
        }


class GeoResolver:
    """One per run: results are cached, so 500 students in the same town cost
    one lookup, and a city created for the first is found by the second.

    **It owns its own sessions.** A city is created in a transaction of its
    own, committed immediately, rather than inside the transaction of the user
    row that asked for it. Otherwise a record that failed and rolled back
    would leave the cache pointing at a city that no longer exists, and the
    next record in the same town would fail on a foreign key. A created city
    is valid reference data whatever happens to any one account.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, dry_run: bool = False) -> None:
        self._factory = session_factory
        self._dry_run = dry_run
        self.stats = GeoStats()
        self._countries: dict[str, int | None] = {}
        self._country_names: dict[int, str] = {}
        self._cities: dict[tuple[int, str], int | None] = {}

    # -- country ---------------------------------------------------------------

    async def country(self, name: str | None) -> int | None:
        if not name:
            return None
        key = norm(name)
        if not key:
            return None
        if key in self._countries:
            return self._countries[key]

        country_id = await self._match_country(key)
        self._countries[key] = country_id
        if country_id is None:
            self.stats.countries_unmatched += 1
            self.stats.unmatched_country_names.add(name.strip()[:60])
        else:
            self.stats.countries_matched += 1
        return country_id

    async def _match_country(self, key: str) -> int | None:
        async with self._factory() as session:
            code = COUNTRY_ALIASES.get(key)
            if code:
                row = (await session.execute(
                    text("SELECT id, name FROM countries WHERE code = :c"), {"c": code}
                )).first()
                if row:
                    self._country_names[row[0]] = row[1]
                    return row[0]

            row = (await session.execute(
                text("SELECT id, name FROM countries WHERE lower(name) = :n LIMIT 1"), {"n": key}
            )).first()
            if row:
                self._country_names[row[0]] = row[1]
                return row[0]

            rows = (await session.execute(
                text(
                    "SELECT id, name, similarity(lower(name), :n) AS s FROM countries "
                    "WHERE similarity(lower(name), :n) >= 0.3 ORDER BY s DESC LIMIT 15"
                ),
                {"n": key},
            )).all()
        chosen, _ambiguous = choose_match(key, [(r[0], r[1].lower(), r[2]) for r in rows])
        if chosen is None:
            return None  # ambiguous or unknown: never guess a country
        self._country_names[chosen] = next(r[1] for r in rows if r[0] == chosen)
        return chosen

    # -- city --------------------------------------------------------------------

    async def city(self, country_id: int | None, raw_name: str | None) -> int | None:
        """Resolve, or (outside a dry run) create, a city within `country_id`."""
        if not raw_name or country_id is None:
            return None

        name = clean_city(raw_name, self._country_names.get(country_id))
        junk = city_junk_reason(name)
        if junk:
            self.stats.cities_rejected += 1
            return None

        key = (country_id, name.lower())
        if key in self._cities:
            return self._cities[key]

        city_id, ambiguous = await self._match_city(country_id, name.lower())
        if ambiguous:
            # Two plausible places: leave the field empty rather than pick one
            # or add a third.
            self.stats.cities_ambiguous += 1
            city_id = None
        elif city_id is not None:
            self.stats.cities_matched += 1
        elif self._dry_run:
            self.stats.cities_would_create += 1
        else:
            async with self._factory.begin() as session:
                city = City(name=smart_title(name), country_id=country_id)  # geoname_id stays NULL
                session.add(city)
                await session.flush()
                city_id = city.id
            self.stats.cities_created += 1

        self._cities[key] = city_id
        return city_id

    async def _match_city(self, country_id: int, lowered: str) -> tuple[int | None, bool]:
        async with self._factory() as session:
            row = (await session.execute(
                text(
                    "SELECT id FROM cities WHERE country_id = :c AND lower(name) = :n "
                    "ORDER BY population DESC NULLS LAST, id LIMIT 1"
                ),
                {"c": country_id, "n": lowered},
            )).first()
            if row:
                return row[0], False

            rows = (await session.execute(
                text(
                    "SELECT id, lower(name), similarity(lower(name), :n) AS s FROM cities "
                    "WHERE country_id = :c AND (similarity(lower(name), :n) >= 0.3 "
                    # Trigrams miss short transposition typos ("lodnon" vs
                    # "london" share almost none), so also offer anything that
                    # starts alike and is about as long; choose_match then
                    # decides by edit distance.
                    "OR (left(lower(name), 1) = left(:n, 1) AND abs(length(name) - :len) <= 3)) "
                    "ORDER BY s DESC, population DESC NULLS LAST, id LIMIT 200"
                ),
                {"c": country_id, "n": lowered, "len": len(lowered)},
            )).all()
        return choose_match(lowered, [(r[0], r[1], r[2]) for r in rows])
