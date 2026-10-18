import { describe, expect, it } from "vitest";
import { PERMISSION_NAMES } from "./permission-names";
import { permissionSet, VIEW_ALL } from "./permissions";
import { NAVIGATION, alsoRequiresForPath, permissionForPath } from "@/lib/navigation";

describe("permissionSet", () => {
  it("answers for a permission the caller holds", () => {
    const permissions = permissionSet(["user.read", "user.create"]);
    expect(permissions.has("user.read")).toBe(true);
    expect(permissions.has("user.delete")).toBe(false);
  });

  // The important direction. A caller with nothing must be refused
  // everything -- an empty list must never read as "unrestricted".
  it("denies everything when the caller holds nothing", () => {
    const permissions = permissionSet([]);
    for (const name of PERMISSION_NAMES) {
      expect(permissions.has(name)).toBe(false);
    }
    expect(permissions.hasAny(...PERMISSION_NAMES)).toBe(false);
  });

  it("denies everything when the server sent no permissions at all", () => {
    const permissions = permissionSet(undefined);
    expect(permissions.has("user.read")).toBe(false);
    expect(permissions.all).toEqual([]);
  });

  it("hasAny needs one, hasAll needs every one", () => {
    const permissions = permissionSet(["course.read", "batch.read"]);
    expect(permissions.hasAny("course.read", "user.delete")).toBe(true);
    expect(permissions.hasAny("user.delete", "role.delete")).toBe(false);
    expect(permissions.hasAll("course.read", "batch.read")).toBe(true);
    expect(permissions.hasAll("course.read", "user.delete")).toBe(false);
  });

  it("does not treat a scope modifier as a capability", () => {
    // `institution.view_all` widens which rows are visible; it grants no
    // write of any kind, and nothing here should imply otherwise.
    const permissions = permissionSet([VIEW_ALL]);
    expect(permissions.has(VIEW_ALL)).toBe(true);
    expect(permissions.has("user.update")).toBe(false);
    expect(permissions.has("course.create")).toBe(false);
  });
});

describe("route permission map", () => {
  // A typo here would silently hide a screen from everyone, for ever, with
  // nothing reporting a problem: `permissions.has("cours.read")` is simply
  // always false.
  it("only references permissions the backend catalog defines", () => {
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        if (item.permission) {
          expect(PERMISSION_NAMES).toContain(item.permission);
        }
        if (item.alsoRequires) {
          expect(PERMISSION_NAMES).toContain(item.alsoRequires);
        }
        for (const name of item.anyPermission ?? []) {
          expect(PERMISSION_NAMES).toContain(name);
        }
      }
    }
  });

  it("resolves secondary required permissions correctly", () => {
    expect(alsoRequiresForPath("/academic")).toBe("academic.create");
    expect(alsoRequiresForPath("/gradebook")).toBe("grade.update");
    expect(alsoRequiresForPath("/transcripts")).toBe("transcript.generate");
    expect(alsoRequiresForPath("/enrollments")).toBe("user.read");
    expect(alsoRequiresForPath("/manager-links")).toBeUndefined();
    expect(alsoRequiresForPath("/courses")).toBeUndefined();
  });

  it("matches the longest prefix, so a detail route inherits its list's gate", () => {
    expect(permissionForPath("/courses")).toBe("course.read");
    expect(permissionForPath("/courses/abc-123")).toBe("course.read");
    // The directory and its detail pages are gated on `user.update`: a
    // Tutor or Guardian reads the people they are responsible for through
    // /team, not by browsing everyone.
    expect(permissionForPath("/users/abc-123")).toBe("user.update");
  });

  it("leaves unlisted routes ungated here, because the server gates them", () => {
    expect(permissionForPath("/account")).toBeUndefined();
    expect(permissionForPath("/account/sessions")).toBeUndefined();
    expect(permissionForPath("/")).toBeUndefined();
  });

  it("does not let the dashboard's root entry swallow every other route", () => {
    // `/` is a prefix of everything; if it were matched by prefix rather than
    // excluded, no screen would ever require its own permission.
    expect(permissionForPath("/security")).toBe("security.read");
  });
});
