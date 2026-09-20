"""The LAIT -> LMS field mapping (backend/integrations/lait_mapping.py).

Record shapes are the samples from the sync specification.
"""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest

from backend.integrations import lait_mapping as m

LONDON = "Europe/London"

KATIE = {
    "StudentID": 34978,
    "UserName": "katie.suleiman@gmail.com",
    "UserID": "e078ac1b-2d30-45ad-9d95-93b443e980cb",
    "Title": "Mrs",
    "FirstName": "Katie",
    "LastName": "Suleiman",
    "FullName": "Mrs Katie Suleiman",
    "Email": "katie.suleiman@gmail.com",
    "CompanyName": "",
    "AddressLine1": "4 Chestnut Walk",
    "AddressLine2": "",
    "AddressLine3": "",
    "City": "Hitchin",
    "StateProvinceCounty": "",
    "PostCode": "SG4 7SS",
    "CountryID": 256,
    "CountryName": "United Kingdom",
    "ContactNumber": "07928459413",
    "RegistrationDate": "2026-09-17T15:10:20.987",
    "UserIP": "51.155.171.212",
    "StatusID": 1,
    "StatusDetails": "Active",
    "Website": None,
    "Roles": ["Student"],
}

ALISON = {
    "tutor_id": 30,
    "user_id": "13b1fa08-8741-4724-b8d1-5e9cd6820c80",
    "title": "Ms",
    "first_name": "Alison",
    "middle_name": "",
    "last_name": "Milne",
    "tutor_status": 2,
    "tutor_status_text": "Reserved",
    "is_public": True,
}


# --------------------------------------------------------------------- students


def test_student_fields_map_as_specified() -> None:
    u = m.map_student(KATIE, source_timezone=LONDON)
    assert u.guid == uuid.UUID("e078ac1b-2d30-45ad-9d95-93b443e980cb")
    assert u.external_student_id == 34978
    assert u.username == "katie.suleiman@gmail.com"
    assert u.email == "katie.suleiman@gmail.com"
    assert (u.title, u.first_name, u.last_name) == ("Mrs", "Katie", "Suleiman")
    assert u.address == "4 Chestnut Walk"
    assert u.postcode == "SG4 7SS"
    assert u.phone_number == "07928459413"
    assert u.ip_address == "51.155.171.212"
    assert u.city_name == "Hitchin"
    assert u.country_name == "United Kingdom"
    assert u.company is None and u.web is None
    assert u.roles == ["STUDENT"]
    assert u.warnings == []


def test_fields_the_spec_says_to_skip_are_not_carried() -> None:
    u = m.map_student(KATIE, source_timezone=LONDON)
    # FullName is derived, StateProvinceCounty is skipped, CountryID is not taken.
    for name in ("full_name", "state", "country_id", "status"):
        assert not hasattr(u, name)


def test_corporate_manager_student_gets_both_roles() -> None:
    u = m.map_student({**KATIE, "Roles": ["CorporateManager", "Student"]}, source_timezone=LONDON)
    assert u.roles == ["CORPORATE_MANAGER", "STUDENT"]


def test_address_lines_are_joined_and_empty_lines_skipped() -> None:
    assert m.join_address("1 High St", "", "Flat 2") == "1 High St, Flat 2"
    assert m.join_address("a", "b", "c") == "a, b, c"
    assert m.join_address("", None, "  ") is None


def test_email_is_lower_cased_and_username_follows_it() -> None:
    u = m.map_student({**KATIE, "UserName": "Katie.Suleiman@Gmail.com", "Email": "Katie.Suleiman@Gmail.com"},
                      source_timezone=LONDON)
    assert u.email == u.username == "katie.suleiman@gmail.com"


def test_a_record_with_only_an_email_still_gets_a_username() -> None:
    u = m.map_student({**KATIE, "UserName": ""}, source_timezone=LONDON)
    assert u.username == "katie.suleiman@gmail.com"


def test_an_invalid_email_is_ignored_with_a_warning_not_stored() -> None:
    u = m.map_student({**KATIE, "Email": "not-an-email", "UserName": "kate"}, source_timezone=LONDON)
    assert u.email is None
    assert any("email" in w for w in u.warnings)


# ------------------------------------------------------------ RegistrationDate


def test_summer_registration_is_converted_from_bst_to_utc() -> None:
    # 15:10 BST is 14:10 UTC.
    u = m.map_student(KATIE, source_timezone=LONDON)
    assert u.registered_at is not None
    assert u.registered_at.utcoffset() == timezone.utc.utcoffset(None)
    assert u.registered_at.isoformat() == "2026-09-17T14:10:20.987000+00:00"


def test_winter_registration_is_already_utc() -> None:
    # GMT == UTC, so January is unchanged -- the conversion is not a flat "-1h".
    assert m.parse_registered_at("2026-01-15T09:00:00", LONDON).isoformat() == "2026-01-15T09:00:00+00:00"


def test_the_repeated_autumn_hour_resolves_to_its_first_occurrence() -> None:
    # 01:30 on 25 Oct 2026 happens twice; fold=0 is the BST one, 00:30 UTC.
    assert m.parse_registered_at("2026-10-25T01:30:00", LONDON).isoformat() == "2026-10-25T00:30:00+00:00"


def test_the_skipped_spring_hour_does_not_raise() -> None:
    result = m.parse_registered_at("2026-03-29T01:30:00", LONDON)
    assert result is not None and result.tzinfo is not None


def test_a_value_with_an_explicit_offset_is_trusted() -> None:
    assert m.parse_registered_at("2026-09-17T15:10:20+02:00", LONDON).isoformat() == "2026-09-17T13:10:20+00:00"


def test_seven_digit_fractional_seconds_from_sql_server_parse() -> None:
    assert m.parse_registered_at("2026-09-17T15:10:20.9870000", LONDON) is not None


@pytest.mark.parametrize("bad", [None, "", "yesterday", "17/09/2026"])
def test_an_unparseable_registration_date_is_none_not_an_error(bad: object) -> None:
    assert m.parse_registered_at(bad, LONDON) is None


def test_the_configured_source_timezone_is_honoured() -> None:
    assert m.parse_registered_at("2026-09-17T15:00:00", "UTC").isoformat() == "2026-09-17T15:00:00+00:00"


# --------------------------------------------------------------------- roles


@pytest.mark.parametrize(
    "spelling",
    ["Admin", "ADMIN", "admin", "Administrator", "SuperAdmin", "Super Admin", "super_admin", "SUPER_ADMIN", "root"],
)
def test_sync_can_never_grant_an_administrator_role(spelling: str) -> None:
    """The safety property of the whole feature: whatever the payload says."""
    granted, unknown = m.map_roles([spelling, "Student"])
    assert granted == ["STUDENT"]
    assert unknown == [spelling[:40]]
    assert not (set(granted) & {"ADMIN", "SUPER_ADMIN"})


def test_the_grantable_set_excludes_administrators() -> None:
    assert m.SYNC_GRANTABLE_ROLES == {"STUDENT", "TUTOR", "CORPORATE_MANAGER", "GUARDIAN"}


def test_role_matching_ignores_case_spaces_and_underscores() -> None:
    assert m.map_roles(["corporate manager", "CORPORATE_MANAGER", "CorporateManager"])[0] == ["CORPORATE_MANAGER"]


def test_no_roles_means_no_roles() -> None:
    assert m.map_roles(None) == ([], [])
    assert m.map_roles([]) == ([], [])


# ------------------------------------------------------------- lengths and text


def test_a_long_title_now_fits_but_only_up_to_twenty() -> None:
    assert m.map_student({**KATIE, "Title": "Professor"}, source_timezone=LONDON).title == "Professor"
    u = m.map_student({**KATIE, "Title": "Distinguished Visiting Professor"}, source_timezone=LONDON)
    assert u.title is not None and len(u.title) <= 20
    assert any("title truncated" in w for w in u.warnings)  # never silent


def test_an_overlong_free_text_field_is_shortened_and_reported() -> None:
    u = m.map_student({**KATIE, "FirstName": "x" * 80}, source_timezone=LONDON)
    assert len(u.first_name or "") == 50
    assert any("first_name truncated from 80 to 50" in w for w in u.warnings)


def test_username_length_and_whitespace_are_reported_not_truncated() -> None:
    assert m.username_problem("a" * 51) is not None
    assert m.username_problem("has space@x.com") is not None
    assert m.username_problem(None) is not None
    assert m.username_problem("katie.suleiman@gmail.com") is None


def test_control_characters_and_runs_of_space_are_cleaned() -> None:
    assert m.clean("  Ka\x00tie \n\t Sule\x07iman ") == "Ka tie Sule iman"
    assert m.clean("   ") is None and m.clean(None) is None


# --------------------------------------------------------------------- website


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.com", "https://example.com"),
        ("http://example.co.uk/x", "http://example.co.uk/x"),
        ("example.com", "https://example.com"),
        ("javascript:alert(1)", None),
        ("JAVASCRIPT:alert(1)", None),
        ("data:text/html,<script>alert(1)</script>", None),
        ("ftp://example.com", None),
        ("not a url", None),
        (None, None),
    ],
)
def test_web_is_sanitised_to_http_or_https(value: object, expected: str | None) -> None:
    assert m.safe_web(value, []) == expected


# ---------------------------------------------------------------------- tutors


def test_tutor_fields_map_as_specified() -> None:
    u = m.map_tutor(ALISON)
    assert u.guid == uuid.UUID("13b1fa08-8741-4724-b8d1-5e9cd6820c80")
    assert u.external_tutor_id == 30
    assert (u.title, u.first_name, u.last_name) == ("Ms", "Alison", "Milne")
    assert u.is_public is True
    assert u.roles == ["TUTOR"]
    assert u.username is None and u.email is None  # not in the list payload


def test_a_tutors_middle_name_goes_in_front_of_the_surname() -> None:
    u = m.map_tutor({**ALISON, "first_name": "Abul", "middle_name": "Bashar", "last_name": "Sardar"})
    assert (u.first_name, u.last_name) == ("Abul", "Bashar Sardar")


def test_a_reserved_tutor_is_still_mapped_as_a_tutor() -> None:
    # "Reserved" (tutor_status 2) becomes an ACTIVE tutor: status is not read.
    assert m.map_tutor({**ALISON, "tutor_status": 2, "tutor_status_text": "Reserved"}).roles == ["TUTOR"]


def test_tutor_detail_supplies_the_email_and_username() -> None:
    u = m.map_tutor(ALISON)
    m.apply_tutor_detail(u, {"email_id": "Alison.Milne@Example.com"})
    assert u.email == u.username == "alison.milne@example.com"


def test_tutor_detail_without_a_usable_email_changes_nothing() -> None:
    u = m.map_tutor(ALISON)
    m.apply_tutor_detail(u, {"email_id": ""})
    m.apply_tutor_detail(u, None)
    assert u.email is None and u.username is None


def test_fallback_username_is_first_dot_last() -> None:
    assert m.fallback_username("Alison", "Milne") == "alison.milne"
    assert m.fallback_username("Zoë", "O'Neil") == "zoe.oneil"
    assert m.fallback_username(None, None) is None


# ------------------------------------------------------------------------ slugs


def test_slug_is_name_based_not_email_based() -> None:
    slug = m.slug_base("Katie", "Suleiman", "katie.suleiman@gmail.com")
    assert slug == "katie-suleiman"
    assert "gmail" not in slug


def test_slug_falls_back_to_the_username_local_part_then_a_constant() -> None:
    assert m.slug_base(None, None, "katie.suleiman@gmail.com") == "katie-suleiman"
    assert m.slug_base(None, None, None) == "user"


def test_collision_suffix_is_deterministic_and_from_the_guid() -> None:
    guid = uuid.UUID("e078ac1b-2d30-45ad-9d95-93b443e980cb")
    assert m.slug_with_suffix("katie-suleiman", guid) == "katie-suleiman-e078ac"
    assert m.slug_with_suffix("katie-suleiman", guid) == m.slug_with_suffix("katie-suleiman", guid)
    assert len(m.slug_with_suffix("x" * 200, guid)) <= 100  # fits the column


# ------------------------------------------------------------------ bad records


@pytest.mark.parametrize("bad", [None, "", "not-a-guid", "../../admin", 12345])
def test_an_invalid_guid_is_an_error_and_the_message_never_echoes_it(bad: object) -> None:
    with pytest.raises(m.MappingError) as info:
        m.map_student({**KATIE, "UserID": bad}, source_timezone=LONDON)
    assert "admin" not in str(info.value)
    with pytest.raises(m.MappingError):
        m.map_tutor({**ALISON, "user_id": bad})
