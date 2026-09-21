import { describe, expect, it } from "vitest";
import { addDays, addMonths, batchHue, dayKey, monthGrid, weekdayIndex } from "@/lib/calendar";

describe("dayKey", () => {
  it("places a late-evening UTC instant on the next day in a zone ahead of UTC", () => {
    expect(dayKey("2026-07-01T23:30:00Z", "Europe/London")).toBe("2026-07-02");
    expect(dayKey("2026-07-01T23:30:00Z", "UTC")).toBe("2026-07-01");
  });
  it("uses the display zone, not the machine's", () => {
    expect(dayKey("2026-07-01T20:00:00Z", "Asia/Dhaka")).toBe("2026-07-02");
    expect(dayKey("2026-07-01T20:00:00Z", "America/New_York")).toBe("2026-07-01");
  });
});

describe("date arithmetic", () => {
  it("crosses month and year boundaries", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addMonths("2026-12-15", 1)).toBe("2027-01-01");
    expect(addMonths("2026-01-31", -1)).toBe("2025-12-01");
  });
  it("starts the week on Monday", () => {
    expect(weekdayIndex("2026-09-21")).toBe(0); // a Monday
    expect(weekdayIndex("2026-09-27")).toBe(6);
  });
});

describe("monthGrid", () => {
  it("is always six whole weeks that begin on a Monday and contain the month", () => {
    for (const anchor of ["2026-02-10", "2026-09-21", "2027-05-01", "2026-11-30"]) {
      const grid = monthGrid(anchor, "Europe/London");
      expect(grid.days).toHaveLength(42);
      expect(weekdayIndex(grid.days[0] ?? "")).toBe(0);
      expect(grid.days).toContain(grid.month);
      expect(grid.days).toContain(addDays(addMonths(grid.month, 1), -1));
    }
  });
  it("bounds the request by the zone's midnight, so no session on the first or last square is lost", () => {
    const grid = monthGrid("2026-09-21", "Europe/London"); // BST: midnight is 23:00Z the day before
    expect(grid.from).toBe("2026-08-30T23:00:00.000Z");
    expect(new Date(grid.to).getTime() - new Date(grid.from).getTime()).toBeGreaterThan(41 * 86_400_000);
    expect(new Date(grid.to).getTime() - new Date(grid.from).getTime()).toBeLessThan(43 * 86_400_000);
  });
});

describe("batchHue", () => {
  it("is stable and spreads different codes apart", () => {
    expect(batchHue("DEMOPY-A")).toBe(batchHue("DEMOPY-A"));
    expect(batchHue("DEMOPY-A")).not.toBe(batchHue("DEMOPY-B"));
    expect(batchHue("x")).toBeGreaterThanOrEqual(0);
    expect(batchHue("x")).toBeLessThan(360);
  });
});
