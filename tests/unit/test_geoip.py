"""The audit trail's location lookup -- `backend/integrations/geoip.py`.

A stand-in reader returns records in GeoLite2-City's own shape; the real file
needs a MaxMind account and is installed per deployment.
"""

from __future__ import annotations

from backend.core.config import GeoIPSettings
from backend.integrations.geoip import GeoLocator, GeoStatus

DHAKA = {
    "city": {"names": {"en": "Dhaka"}},
    "country": {"iso_code": "BD", "names": {"en": "Bangladesh"}},
    "subdivisions": [{"iso_code": "C", "names": {"en": "Dhaka Division"}}],
    "location": {"latitude": 23.7104, "longitude": 90.4074, "accuracy_radius": 20},
}


class Reader:
    def __init__(self, records=None, fail=False):
        self.records = records or {}
        self.fail = fail
        self.calls = 0

    def get(self, ip):
        self.calls += 1
        if self.fail:
            raise OSError("corrupt database")
        return self.records.get(ip)


def locator(reader, **settings):
    return GeoLocator(GeoIPSettings(**settings), reader=reader, source="GeoLite2-City 2026-10-24")


def test_a_public_address_is_located_with_every_field():
    result = locator(Reader({"103.170.173.46": DHAKA})).locate("103.170.173.46", "PUBLIC")
    assert result.status == GeoStatus.OK
    assert (result.country_code, result.country, result.region, result.city) == (
        "BD", "Bangladesh", "Dhaka Division", "Dhaka",
    )
    assert (result.latitude, result.longitude, result.accuracy_km) == (23.7104, 90.4074, 20)
    assert result.source == "GeoLite2-City 2026-10-24"


def test_private_loopback_and_unknown_addresses_are_never_looked_up():
    reader = Reader({"10.0.0.1": DHAKA})
    geo = locator(reader)
    for ip, scope in (("10.0.0.1", "PRIVATE"), ("127.0.0.1", "LOOPBACK"), (None, "UNAVAILABLE")):
        assert geo.locate(ip, scope).status == GeoStatus.NOT_APPLICABLE
    assert reader.calls == 0


def test_an_address_the_database_does_not_know_is_not_found():
    assert locator(Reader()).locate("81.2.69.142", "PUBLIC").status == GeoStatus.NOT_FOUND


def test_a_broken_database_reports_an_error_instead_of_raising():
    assert locator(Reader(fail=True)).locate("81.2.69.142", "PUBLIC").status == GeoStatus.ERROR


def test_disabled_lookups_are_unavailable():
    assert locator(Reader({"81.2.69.142": DHAKA}), enabled=False).locate("81.2.69.142", "PUBLIC").status == (
        GeoStatus.UNAVAILABLE
    )


def test_a_missing_database_file_is_unavailable(tmp_path):
    geo = GeoLocator(GeoIPSettings(city_db_path=str(tmp_path / "absent.mmdb")))
    assert geo.locate("81.2.69.142", "PUBLIC").status == GeoStatus.UNAVAILABLE


def test_repeated_addresses_are_served_from_the_cache():
    reader = Reader({"103.170.173.46": DHAKA})
    geo = locator(reader)
    for _ in range(5):
        geo.locate("103.170.173.46", "PUBLIC")
    assert reader.calls == 1


def test_a_record_without_a_city_still_gives_the_country():
    result = locator(Reader({"81.2.69.142": {"country": {"iso_code": "GB", "names": {"en": "United Kingdom"}}}})).locate(
        "81.2.69.142", "PUBLIC"
    )
    assert (result.status, result.country, result.city, result.latitude) == (GeoStatus.OK, "United Kingdom", None, None)
