import { describe, expect, it } from "vitest";
import { describeSelection } from "./share-dialog";

describe("describeSelection", () => {
  it("names a single file or folder as such", () => {
    expect(describeSelection(1, 0)).toBe("this file");
    expect(describeSelection(0, 1)).toBe("this folder");
  });

  it("counts several, and mixes files and folders", () => {
    expect(describeSelection(12, 0)).toBe("12 files");
    expect(describeSelection(0, 3)).toBe("3 folders");
    expect(describeSelection(2, 1)).toBe("2 files and 1 folder");
    expect(describeSelection(1, 2)).toBe("1 file and 2 folders");
  });
});
