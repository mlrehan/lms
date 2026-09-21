import { describe, expect, it } from "vitest";
import { generatePassword, passwordStrength, suggestUsername, PASSWORD_MIN } from "./create-user-dialog";
import { pictureProblem } from "./avatar-uploader";
import { initialsOf } from "./user-avatar";

describe("suggestUsername", () => {
  it("uses the local part, lower-cased, within the server's character set", () => {
    expect(suggestUsername("Priya.Nair@Example.com")).toBe("priya.nair");
    expect(suggestUsername("o'brien+tag@x.org")).toBe("obrientag");
    expect(suggestUsername("@nothing")).toBe("");
    expect(suggestUsername("a".repeat(80) + "@x.org")).toHaveLength(50);
  });
});

describe("generatePassword", () => {
  it("meets the server minimum and contains every character class, every time", () => {
    for (let i = 0; i < 200; i++) {
      const p = generatePassword();
      expect(p.length).toBeGreaterThanOrEqual(PASSWORD_MIN);
      expect(p).toMatch(/[a-z]/);
      expect(p).toMatch(/[A-Z]/);
      expect(p).toMatch(/\d/);
      expect(p).toMatch(/[^A-Za-z0-9]/);
    }
  });

  it("does not repeat", () => {
    expect(new Set(Array.from({ length: 50 }, () => generatePassword())).size).toBe(50);
  });

  it("avoids look-alike characters", () => {
    for (let i = 0; i < 200; i++) expect(generatePassword()).not.toMatch(/[0OIl1]/);
  });
});

describe("passwordStrength", () => {
  it("is empty for nothing and weak below the server minimum", () => {
    expect(passwordStrength("").score).toBe(0);
    expect(passwordStrength("Ab1!").score).toBeLessThanOrEqual(1);
  });
  it("caps obviously bad passwords however long", () => {
    expect(passwordStrength("aaaaaaaaaaaaaaaaaaaa").score).toBeLessThanOrEqual(1);
    expect(passwordStrength("Password123456!!").score).toBeLessThanOrEqual(1);
  });
  it("rates a long mixed password strong", () => {
    expect(passwordStrength(generatePassword(20)).score).toBe(4);
  });
});

describe("pictureProblem", () => {
  it("accepts JPEG, PNG and WebP", () => {
    for (const type of ["image/jpeg", "image/png", "image/webp"]) {
      expect(pictureProblem({ type, size: 1000 })).toBeNull();
    }
  });
  it("refuses SVG, GIF, oversize and empty files", () => {
    expect(pictureProblem({ type: "image/svg+xml", size: 100 })).not.toBeNull();
    expect(pictureProblem({ type: "image/gif", size: 100 })).not.toBeNull();
    expect(pictureProblem({ type: "image/png", size: 5 * 1024 * 1024 + 1 })).toMatch(/5 MB/);
    expect(pictureProblem({ type: "image/png", size: 0 })).not.toBeNull();
  });
});

describe("initialsOf", () => {
  it("takes at most two initials and never returns empty", () => {
    expect(initialsOf("Priya Nair")).toBe("PN");
    expect(initialsOf("S. M. Kamruzzaman")).toBe("SM");
    expect(initialsOf("  ")).toBe("?");
    expect(initialsOf(null)).toBe("?");
  });
});
