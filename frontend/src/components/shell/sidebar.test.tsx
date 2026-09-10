import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { SidebarContent } from "./sidebar";
import { NAVIGATION } from "@/lib/navigation";
import { ROLE_GRANTS } from "@/test/role-grants";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

// `vi.hoisted` runs before imports, so the holder must not reference one.
const sessionMock = vi.hoisted(() => ({ granted: [] as readonly string[] }));

vi.mock("@/lib/auth/session", async () => {
  const actual = await import("@/lib/auth/permissions");
  return { useSession: () => ({ permissions: actual.permissionSet(sessionMock.granted) }) };
});

function renderFor(granted: readonly string[]) {
  sessionMock.granted = granted;
  return render(<SidebarContent />);
}

function visibleLabels(): string[] {
  return screen
    .getAllByRole("link")
    .map((link) => link.textContent?.trim() ?? "")
    .filter(Boolean);
}

/**
 * The RBAC navigation matrix.
 *
 * What a role *sees*, which is a UX property and not a security one -- the
 * server re-checks every request these screens make. It earns its place by
 * catching the two failures nothing else would: a screen gated on a
 * permission nobody holds (unreachable for everyone, silently), and a screen
 * gated on nothing (offered to people whose first request will be a 403).
 *
 * The expectations below are written against the backend's *actual* grants,
 * not against a reading of the spec prose. Writing them from the prose first
 * produced four failures, and the implementation was right in all four: an
 * Administrator holds `setting.read` and `permission.read` (they may look,
 * not change), a Student holds `enrollment.read` (their own enrollments), and
 * both Tutors and Guardians hold `user.read` (to look up the people they are
 * responsible for). Read access and write access are separate grants, and the
 * sidebar gates on read.
 */
describe("sidebar navigation matrix", () => {
  beforeEach(() => {
    sessionMock.granted = [];
  });

  it("shows a caller with no permissions only the always-available entries", () => {
    renderFor([]);
    const labels = visibleLabels();
    // Dashboard and "Shared with me" need authentication only.
    expect(labels.sort()).toEqual(["Dashboard", "Shared with me"]);
  });

  it("shows a Super Admin every screen in the map", () => {
    renderFor(ROLE_GRANTS.SUPER_ADMIN ?? []);
    const labels = visibleLabels();
    for (const section of NAVIGATION) {
      for (const item of section.items) {
        expect(labels).toContain(item.label);
      }
    }
  });

  /**
   * The invariant that actually matters, checked for every role at once: a
   * link appears if and only if the caller holds the permission that screen's
   * first request needs. A link shown without it is a guaranteed 403; a link
   * hidden despite it is a feature nobody can reach.
   */
  it.each(Object.keys(ROLE_GRANTS))("shows %s exactly the screens it can open", (role) => {
    const granted = new Set(ROLE_GRANTS[role] ?? []);
    renderFor(ROLE_GRANTS[role] ?? []);
    const labels = new Set(visibleLabels());

    for (const section of NAVIGATION) {
      for (const item of section.items) {
        const reachable = !item.permission || granted.has(item.permission);
        expect({ label: item.label, shown: labels.has(item.label) }).toEqual({
          label: item.label,
          shown: reachable,
        });
      }
    }
  });

  it("gives an Administrator the read-only administration screens but not the write-only ones", () => {
    // Spec section 2: an Administrator runs daily operations and cannot
    // modify system settings or manage permissions. They can *read* both, so
    // the screens appear -- and their write controls are gated separately.
    const granted = ROLE_GRANTS.ADMIN ?? [];
    expect(granted).toContain("setting.read");
    expect(granted).not.toContain("setting.update");
    expect(granted).toContain("permission.read");
    expect(granted).not.toContain("permission.manage");

    renderFor(granted);
    const labels = visibleLabels();
    expect(labels).toContain("System settings");
    expect(labels).toContain("Permissions");
    expect(labels).toContain("Users");
    expect(labels).toContain("Reports");
  });

  it("gives a Tutor teaching screens and no institution administration", () => {
    renderFor(ROLE_GRANTS.TUTOR ?? []);
    const labels = visibleLabels();
    expect(labels).toContain("Courses");
    expect(labels).toContain("Attendance");
    expect(labels).toContain("Assignments");
    expect(labels).toContain("Reports");
    expect(labels).not.toContain("Roles");
    expect(labels).not.toContain("Permissions");
    expect(labels).not.toContain("Audit log");
    expect(labels).not.toContain("Security");
    expect(labels).not.toContain("System settings");
    expect(labels).not.toContain("Integrations");
    expect(labels).not.toContain("Organizations");
  });

  it("gives a Student their own learning and nothing administrative", () => {
    renderFor(ROLE_GRANTS.STUDENT ?? []);
    const labels = visibleLabels();
    expect(labels).toContain("Courses");
    expect(labels).toContain("Enrollments"); // their own; the server scopes the rows
    expect(labels).not.toContain("Users");
    expect(labels).not.toContain("Roles");
    expect(labels).not.toContain("Audit log");
    expect(labels).not.toContain("Security");
    expect(labels).not.toContain("Integrations");
    expect(labels).not.toContain("Reports");
  });

  it("gives a Guardian read screens and no write screen", () => {
    const granted = ROLE_GRANTS.GUARDIAN ?? [];
    // A guardian can look someone up -- scoped by the server to their wards.
    expect(granted).toContain("user.read");
    expect(granted).not.toContain("user.update");

    renderFor(granted);
    const labels = visibleLabels();
    expect(labels).toContain("Users");
    expect(labels).toContain("Guardians");
    expect(labels).not.toContain("Roles");
    expect(labels).not.toContain("System settings");
    expect(labels).not.toContain("Audit log");
    expect(labels).not.toContain("Discussions"); // no discussion.read grant
  });

  it("hides a whole section when none of its screens are reachable", () => {
    renderFor(["course.read"]);
    expect(visibleLabels()).toContain("Courses");
    // An empty group heading reads as a broken screen, so the section itself
    // must disappear rather than render a label with nothing under it.
    expect(screen.queryByText("People")).toBeNull();
    expect(screen.getByText("Learning")).toBeInTheDocument();
  });
});
