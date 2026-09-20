"""The database-free parts of the geography resolver.

Matching against the real `countries` / `cities` tables is exercised live
(scripts and the sync run); this file covers the rules that decide *what is
worth looking up or creating* -- the ones that stop junk becoming a city.
"""

from __future__ import annotations

import pytest

from backend.integrations import lait_geo as g


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("United Kingdom", "united kingdom"),
        ("U.K.", "uk"),
        ("  The Netherlands ", "netherlands"),
        ("Bosnia & Herzegovina", "bosnia and herzegovina"),
        ("Côte d'Ivoire", "côte d'ivoire"),
    ],
)
def test_norm(raw: str, expected: str) -> None:
    assert g.norm(raw) == expected


def test_common_aliases_resolve_to_iso_codes_not_names() -> None:
    for alias, code in [("uk", "GB"), ("england", "GB"), ("great britain", "GB"),
                        ("usa", "US"), ("uae", "AE"), ("tanzania", "TZ"), ("burma", "MM")]:
        assert g.COUNTRY_ALIASES[g.norm(alias)] == code


def test_every_alias_key_is_already_in_normalised_form() -> None:
    """An alias that does not survive `norm` could never be looked up."""
    for key in g.COUNTRY_ALIASES:
        assert g.norm(key) == key, key


# ------------------------------------------------------------- what is not a city


@pytest.mark.parametrize(
    "junk",
    ["N/A", "n/a", "none", "-", "--", "TBC", "unknown", "test", "SG4 7SS", "E4 9XD",
     "12", "London 2", "kate@example.com", "x", "", "  ", "a" * 61, "!!", "12 34"],
)
def test_values_that_are_not_places_are_rejected(junk: str) -> None:
    assert g.city_junk_reason(junk) is not None


@pytest.mark.parametrize("real", ["Hitchin", "london", "St. Albans", "Newcastle upon Tyne",
                                  "Stoke-on-Trent", "Zürich", "Dar es Salaam", "O'Fallon"])
def test_real_place_names_are_accepted(real: str) -> None:
    assert g.city_junk_reason(real) is None


# ---------------------------------------------------------------- cleaning a city


@pytest.mark.parametrize(
    "raw,country,expected",
    [
        ("London, UK", "United Kingdom", "London"),
        ("london uk", "United Kingdom", "london"),
        ("Hitchin England", "United Kingdom", "Hitchin"),
        ("Leeds United Kingdom", "United Kingdom", "Leeds"),
        ("Hitchin", "United Kingdom", "Hitchin"),
        # Only a *trailing* country is removed, and something must remain.
        ("Wales", "United Kingdom", "Wales"),
        ("UK", "United Kingdom", "UK"),
    ],
)
def test_a_trailing_country_is_stripped_from_a_city(raw: str, country: str, expected: str) -> None:
    assert g.clean_city(raw, country) == expected


# ------------------------------------------------------------------- capitalising


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hitchin", "Hitchin"),
        ("HITCHIN", "Hitchin"),
        ("newcastle upon tyne", "Newcastle upon Tyne"),
        ("stoke-on-trent", "Stoke-on-Trent"),
        ("o'fallon", "O'Fallon"),
        ("the hague", "The Hague"),
        # Mixed case was typed deliberately and is left alone.
        ("McDonald", "McDonald"),
        ("Hitchin", "Hitchin"),
    ],
)
def test_smart_title(raw: str, expected: str) -> None:
    assert g.smart_title(raw) == expected


# ---------------------------------------------------------------- typo matching


def test_edit_distance_basics() -> None:
    assert g.edit_distance("hitchin", "hitchin", 2) == 0
    assert g.edit_distance("hitchen", "hitchin", 2) == 1
    assert g.edit_distance("unted kingdm", "united kingdom", 3) == 2
    # Gives up early once it must exceed the limit.
    assert g.edit_distance("london", "manchester", 2) > 2
    assert g.edit_distance("a", "abcdef", 2) > 2


def test_an_adjacent_swap_costs_one_edit_not_two() -> None:
    assert g.edit_distance("lodnon", "london", 2) == 1
    assert g.edit_distance("teh", "the", 2) == 1
    assert g.choose_match("lodnon", [(1, "london", 0.4)]) == (1, False)


@pytest.mark.parametrize("length,allowed", [(3, 1), (6, 1), (7, 2), (12, 2), (13, 3), (30, 3)])
def test_allowed_distance_scales_with_length(length: int, allowed: int) -> None:
    assert g.allowed_distance(length) == allowed


def test_a_one_letter_typo_matches_even_though_trigram_similarity_is_low() -> None:
    """`Hitchen` is only ~0.45 similar to `Hitchin` -- below the 0.6 bar -- so
    without the edit-distance test it was being *created* as a new city."""
    chosen, ambiguous = g.choose_match("hitchen", [(7, "hitchin", 0.45), (9, "hatchet", 0.3)])
    assert (chosen, ambiguous) == (7, False)


def test_a_high_similarity_candidate_wins_outright() -> None:
    assert g.choose_match("newcastle upon tyn", [(1, "newcastle upon tyne", 0.9)]) == (1, False)


def test_the_closest_candidate_beats_a_farther_one() -> None:
    # Both are below the similarity bar; "springfeld" is 0 edits away, "springfield" is 1.
    assert g.choose_match("springfeld", [(1, "springfield", 0.55), (2, "springfeld", 0.55)]) == (2, False)


def test_two_candidates_at_the_same_edit_distance_are_ambiguous() -> None:
    chosen, ambiguous = g.choose_match("bat", [(1, "bar", 0.4), (2, "bad", 0.4)])
    assert (chosen, ambiguous) == (None, True)


def test_a_near_tie_in_similarity_is_ambiguous() -> None:
    assert g.choose_match("united", [(1, "united kingdom", 0.62), (2, "united states", 0.61)]) == (None, True)


def test_a_different_first_letter_is_never_a_typo() -> None:
    # "reeds" is one edit from "leeds", but typos rarely change the first letter.
    assert g.choose_match("reeds", [(1, "leeds", 0.4)]) == (None, False)


def test_too_many_edits_is_no_match() -> None:
    assert g.choose_match("narnia", [(1, "namibia", 0.3)]) == (None, False)


def test_no_candidates_is_no_match_and_not_ambiguous() -> None:
    assert g.choose_match("x", []) == (None, False)
