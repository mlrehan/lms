import { describe, expect, it } from "vitest";
import { suggestBatchCode } from "@/components/domain/new-batch-dialog";

describe("suggestBatchCode", () => {
  it("offers the first unused letter, ignoring case", () => {
    expect(suggestBatchCode("PY101", [])).toBe("PY101-A");
    expect(suggestBatchCode("PY101", ["PY101-A", "py101-b"])).toBe("PY101-C");
  });
  it("fills a gap rather than always appending", () => {
    expect(suggestBatchCode("PY101", ["PY101-B"])).toBe("PY101-A");
  });
  it("strips characters the API would refuse, and offers nothing without a code", () => {
    expect(suggestBatchCode("PY 101!", [])).toBe("PY101-A");
    expect(suggestBatchCode(null, [])).toBe("");
  });
  it("falls back to a number once the alphabet is used up", () => {
    const all = Array.from({ length: 26 }, (_, i) => `X-${String.fromCharCode(65 + i)}`);
    expect(suggestBatchCode("X", all)).toBe("X-27");
  });
});
