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
        const reachable =
          (!item.permission || granted.has(item.permission)) &&
          (!item.alsoRequires || granted.has(item.alsoRequires));
        expect({ label: item.label, shown: labels.has(item.label) }).toEqual({
          label: item.label,
          shown: reachable,
        });
      }
    }
  });

  /**
   * Uploading and sharing is the Super Admin's, an Administrator's and a
   * Tutor's job. Everyone else gets "Shared with me" -- the files somebody
   * sent them -- and no way into the library, whose every control would
   * answer 403.
   *
   * Written out per role rather than left to the matrix above, because the
   * matrix only proves the link matches *whatever* permission the item
   * names. Changing that permission back to `resource.read` would keep the
   * matrix green and put the library in front of every student again.
   */
  it.each([
    "SUPER_ADMIN",
    "ADMIN",
    "TUTOR",
    "STUDENT",
    "GUARDIAN",
    "CORPORATE_MANAGER",
  ] as const)("offers %s the user directory only if they administer users", (role) => {
    renderFor(ROLE_GRANTS[role] ?? []);
    // Browsing everyone is an administrator's screen. Reading *one* person --
    // which a Tutor, Guardian and Corporate Manager all need, and which the
    // pickers across the console depend on -- is `user.read` and is untouched.
    expect(visibleLabels().includes("Users")).toBe(
      ["SUPER_ADMIN", "ADMIN"].includes(role),
    );
  });

  it.each([
    ["SUPER_ADMIN", true],
    ["ADMIN", true],
    ["TUTOR", true],
    ["STUDENT", false],
    ["GUARDIAN", false],
    ["CORPORATE_MANAGER", false],
  ] as const)("offers %s the resource library: %s", (role, expected) => {
    renderFor(ROLE_GRANTS[role] ?? []);
    const labels = visibleLabels();
    expect(labels.includes("Resources")).toBe(expected);
    // Everyone keeps the files that were shared with them.
    expect(labels).toContain("Shared with me");
  });

  it.each([
    "SUPER_ADMIN",
    "ADMIN",
    "TUTOR",
    "GUARDIAN",
    "CORPORATE_MANAGER",
    "STUDENT",
  ] as const)("offers %s the enrolment register only if they administer people", (role) => {
    const granted = ROLE_GRANTS[role] ?? [];
    renderFor(granted);
    // Every role here holds `enrollment.read` -- a student holds it to see
    // their own -- so the grant that separates them is `user.read`.
    expect(granted).toContain("enrollment.read");
    expect(visibleLabels().includes("Enrollments")).toBe(granted.includes("user.read"));
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
    // Not Enrollments. The screen is the register of everybody else's, and
    // its filters are people pickers a student cannot use; their own
    // enrolments are reachable through Courses and Batches. `enrollment.read`
    // alone could not tell them from a tutor, which is what `alsoRequires`
    // exists for.
    expect(labels).not.toContain("Enrollments");
    expect(labels).not.toContain("Users");
    expect(labels).not.toContain("Roles");
    expect(labels).not.toContain("Audit log");
    expect(labels).not.toContain("Security");
    expect(labels).not.toContain("Integrations");
    expect(labels).not.toContain("Reports");
  });

  it("gives a Guardian read screens and no write screen", () => {
    const granted = ROLE_GRANTS.GUARDIAN ?? [];
    // A guardian can look someone up -- scoped by the server to their wards --
    // but the directory itself is an administrator's screen, so the nav gates
    // on `user.update` and they do not get the link.
    expect(granted).toContain("user.read");
    expect(granted).not.toContain("user.update");

    renderFor(granted);
    const labels = visibleLabels();
    expect(labels).not.toContain("Users");
    expect(labels).toContain("Guardians");
    expect(labels).not.toContain("Roles");
    expect(labels).not.toContain("System settings");
    expect(labels).not.toContain("Audit log");
    expect(labels).not.toContain("Discussions"); // no discussion.read grant
  });

  it("gives a Corporate Manager their roster and not the ability to write it", () => {
    const granted = ROLE_GRANTS.CORPORATE_MANAGER ?? [];
    // Reading their own assignments is theirs; choosing them is not. The
    // screen appears either way -- `managed_student.read` is what opens it --
    // and the Assign button is what the write grant controls.
    expect(granted).toContain("managed_student.read");
    expect(granted).not.toContain("managed_student.create");

    renderFor(granted);
    const labels = visibleLabels();
    expect(labels).toContain("Manager assignments");
    expect(labels).not.toContain("Guardians");
    expect(labels).not.toContain("System settings");
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
