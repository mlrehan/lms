import { describe, expect, it } from "vitest";
import { coordinatesText, locationStatusText, originSummary, placeName } from "./audit-origin";

const dhaka = {
  status: "OK",
  city: "Dhaka",
  region: "Dhaka Division",
  country: "Bangladesh",
  country_code: "BD",
  latitude: 23.7104,
  longitude: 90.4074,
  accuracy_km: 20,
};

describe("audit origin", () => {
  it("names the place from the most specific parts known", () => {
    expect(placeName(dhaka)).toBe("Dhaka, Dhaka Division, Bangladesh");
    expect(placeName({ status: "OK", city: "Singapore", region: null, country: "Singapore" })).toBe("Singapore");
  });

  it("tells an old row apart from a lookup that found nothing", () => {
    expect(locationStatusText({ ip_address: "127.0.0.1", ip_scope: null, location: null })).toMatch(/before locations/);
    expect(locationStatusText({ ip_address: "81.2.69.142", ip_scope: "PUBLIC", location: { status: "NOT_FOUND" } })).toMatch(
      /not in the location database/,
    );
    expect(locationStatusText({ ip_address: null, ip_scope: "UNAVAILABLE", location: { status: "NOT_APPLICABLE" } })).toMatch(
      /could not be determined/,
    );
    expect(locationStatusText({ ip_address: "10.0.0.1", ip_scope: "PRIVATE", location: { status: "NOT_APPLICABLE" } })).toMatch(
      /Private network/,
    );
    expect(locationStatusText({ ip_address: "81.2.69.142", ip_scope: "PUBLIC", location: { status: "UNAVAILABLE" } })).toMatch(
      /not configured/,
    );
  });

  it("summarises a row for the table", () => {
    expect(originSummary({ ip_address: "103.170.173.46", ip_scope: "PUBLIC", location: dhaka })).toBe(
      "Dhaka, Dhaka Division, Bangladesh",
    );
    expect(originSummary({ ip_address: null, ip_scope: null, location: null })).toBe("—");
  });

  it("states the accuracy beside the coordinates and never shows absent ones as zero", () => {
    expect(coordinatesText(dhaka)).toBe("23.71, 90.41 (within about 20 km)");
    expect(coordinatesText({ status: "OK", latitude: null, longitude: null })).toBeNull();
  });
});
