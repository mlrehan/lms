import { describe, expect, it } from "vitest";
import {
  previewAverage,
  toEntry,
  toValue,
  type Row,
} from "@/components/domain/sessions/class-performance-sheet";

/**
 * The rule these tests exist for: **a blank cell is not a zero.**
 *
 * `Number("")` is `0`, not `NaN`, so the natural way to write this conversion
 * silently sends a zero for every criterion the tutor never touched. Those
 * zeros would be averaged into the student's class-performance figure and,
 * through the weighting, into their final result — and nothing on screen would
 * look wrong, because a grid of empty boxes looks the same either way.
 */

function row(overrides: Partial<Row> = {}): Row {
  return {
    studentId: "s-1",
    username: "Ada",
    scores: {
      participation: "",
      interaction: "",
      preparation: "",
      practical: "",
      presentation: "",
      teamwork: "",
      communication: "",
      professionalism: "",
    },
    overall: "",
    comment: "",
    state: null,
    average: null,
    ...overrides,
  };
}

describe("toValue", () => {
  it("treats an empty or whitespace cell as not assessed", () => {
    expect(toValue("")).toBeNull();
    expect(toValue("   ")).toBeNull();
  });

  it("keeps a typed zero, which is a real mark", () => {
    expect(toValue("0")).toBe(0);
  });

  it("reads ordinary and decimal marks", () => {
    expect(toValue("7")).toBe(7);
    expect(toValue("7.5")).toBe(7.5);
  });

  it("returns null rather than NaN for something unparseable", () => {
    // NaN would serialise to `null` in JSON anyway, but only by accident --
    // being explicit means a future change of serialiser cannot turn it into 0.
    expect(toValue("abc")).toBeNull();
  });
});

describe("toEntry", () => {
  it("sends null for every untouched criterion, never zero", () => {
    const entry = toEntry(row());
    for (const key of [
      "participation",
      "interaction",
      "preparation",
      "practical",
      "presentation",
      "teamwork",
      "communication",
      "professionalism",
      "overall_score",
    ]) {
      expect(entry[key], `${key} must be null when the cell is blank`).toBeNull();
    }
  });

  it("distinguishes a typed zero from a blank in the same request", () => {
    const entry = toEntry(
      row({ scores: { ...row().scores, participation: "0", teamwork: "6" } }),
    );
    expect(entry.participation).toBe(0);
    expect(entry.teamwork).toBe(6);
    expect(entry.interaction).toBeNull();
  });

  it("sends a blank comment as null rather than an empty string", () => {
    expect(toEntry(row({ comment: "   " })).comment).toBeNull();
    expect(toEntry(row({ comment: " good " })).comment).toBe("good");
  });
});

describe("previewAverage", () => {
  it("excludes blanks instead of averaging them in as zeros", () => {
    // 8 out of 10 for the one criterion assessed -- not 1.00, which is what
    // seven blank-as-zero cells would produce.
    expect(previewAverage(row({ scores: { ...row().scores, participation: "8" } }))).toBe("8.00");
  });

  it("counts a typed zero", () => {
    const scores = { ...row().scores, participation: "8", teamwork: "0" };
    expect(previewAverage(row({ scores }))).toBe("4.00");
  });

  it("prefers the tutor's own overall figure over the criteria", () => {
    const scores = { ...row().scores, participation: "2", teamwork: "2" };
    expect(previewAverage(row({ scores, overall: "9" }))).toBe("9.00");
  });

  it("shows nothing at all when nothing has been assessed", () => {
    // Null, not "0.00". An unassessed student is excluded from the weighted
    // result; showing a zero would say they were assessed and scored nothing.
    expect(previewAverage(row())).toBeNull();
  });
});
