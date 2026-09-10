import { describe, expect, it } from "vitest";
import {
  formatDateTime,
  fromLocalInputValue,
  parseApiInstant,
  toLocalInputValue,
} from "./datetime";

describe("parseApiInstant", () => {
  // The backend stores UTC and some columns serialise without a trailing
  // `Z`. Read as local time, every such value is wrong by the viewer's
  // offset -- which looks like bad data rather than bad parsing.
  it("treats an offset-less timestamp as UTC, not local", () => {
    const withZ = parseApiInstant("2026-06-15T09:00:00Z");
    const without = parseApiInstant("2026-06-15T09:00:00");
    expect(without?.toISOString()).toBe(withZ?.toISOString());
    expect(without?.toISOString()).toBe("2026-06-15T09:00:00.000Z");
  });

  it("keeps an explicit offset", () => {
    expect(parseApiInstant("2026-06-15T09:00:00+02:00")?.toISOString()).toBe(
      "2026-06-15T07:00:00.000Z",
    );
  });

  it("handles the space-separated form Postgres sometimes emits", () => {
    expect(parseApiInstant("2026-06-15 09:00:00")?.toISOString()).toBe("2026-06-15T09:00:00.000Z");
  });

  it("returns null rather than an Invalid Date", () => {
    expect(parseApiInstant(null)).toBeNull();
    expect(parseApiInstant("")).toBeNull();
    expect(parseApiInstant("not a date")).toBeNull();
  });
});

describe("timezone display", () => {
  it("renders the same instant differently in two zones", () => {
    const instant = "2026-06-15T09:00:00Z";
    expect(formatDateTime(instant, { timeZone: "UTC" })).toContain("09:00");
    // Europe/London is UTC+1 in June.
    expect(formatDateTime(instant, { timeZone: "Europe/London" })).toContain("10:00");
    // Asia/Kolkata is UTC+5:30 all year.
    expect(formatDateTime(instant, { timeZone: "Asia/Kolkata" })).toContain("14:30");
  });

  it("shows a dash rather than an empty cell for a missing value", () => {
    expect(formatDateTime(null, { timeZone: "UTC" })).toBe("—");
  });
});

describe("datetime-local round trip", () => {
  // The reason this is not `new Date(value)`: the offset differs across a
  // DST boundary, so "09:00 in London" is a different instant in January
  // and in June. A tutor scheduling 09:00 means 09:00 both times.
  it("anchors wall-clock time to the display zone across DST", () => {
    const winter = fromLocalInputValue("2026-01-15T09:00", "Europe/London");
    const summer = fromLocalInputValue("2026-06-15T09:00", "Europe/London");
    expect(winter).toBe("2026-01-15T09:00:00.000Z"); // GMT
    expect(summer).toBe("2026-06-15T08:00:00.000Z"); // BST, UTC+1
  });

  it("round-trips through the input format unchanged", () => {
    for (const zone of ["UTC", "Europe/London", "Asia/Kolkata", "America/New_York"]) {
      for (const wall of ["2026-01-15T09:00", "2026-06-15T23:45", "2026-03-29T13:30"]) {
        const instant = fromLocalInputValue(wall, zone);
        expect(instant).not.toBeNull();
        expect(toLocalInputValue(instant, zone)).toBe(wall);
      }
    }
  });

  it("handles a half-hour offset zone", () => {
    expect(fromLocalInputValue("2026-06-15T09:00", "Asia/Kolkata")).toBe(
      "2026-06-15T03:30:00.000Z",
    );
  });

  it("renders midnight as 00:00, never 24:00", () => {
    expect(toLocalInputValue("2026-06-15T00:00:00Z", "UTC")).toBe("2026-06-15T00:00");
  });

  it("returns null for an empty or malformed input", () => {
    expect(fromLocalInputValue("", "UTC")).toBeNull();
    expect(fromLocalInputValue("15/06/2026", "UTC")).toBeNull();
  });
});
