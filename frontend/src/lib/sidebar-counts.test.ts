import { describe, expect, it } from "vitest";

import { badgeFor } from "./sidebar-counts";

/**
 * What the sidebar shows beside a menu item.
 *
 * The rule worth protecting is that **absent and zero are different**. The
 * server omits a count the caller may not see -- a guardian is watching
 * somebody else do the work, so "assignments waiting" is not their number and
 * they are sent none. If a missing key ever rendered as `0`, a guardian would
 * be told they have no work waiting, which is not the same statement and is
 * not ours to make.
 */
describe("badgeFor", () => {
  it("shows the number when there is one", () => {
    expect(badgeFor("/assignments", { assignments: 3 })).toBe(3);
  });

  it("shows nothing when the caller was sent no such count", () => {
    // A guardian: the key is absent, not zero.
    expect(badgeFor("/assignments", { batches: 2 })).toBeUndefined();
  });

  it("shows nothing for zero, because a row of 0s is clutter", () => {
    expect(badgeFor("/messages", { messages: 0 })).toBeUndefined();
  });

  it("shows nothing before the counts have loaded", () => {
    expect(badgeFor("/messages", undefined)).toBeUndefined();
  });

  it("shows nothing for a menu item that has no badge", () => {
    expect(badgeFor("/account", { users: 117 })).toBeUndefined();
    expect(badgeFor("/", { users: 117 })).toBeUndefined();
  });

  it("maps every badged menu item to its own count", () => {
    const counts = {
      courses: 39, batches: 38, sessions: 80, enrollments: 66,
      assignments: 3, quizzes: 5, exams: 1,
      announcements: 2, messages: 4, notifications: 16,
      users: 117, roles: 6, permissions: 127, guardians: 1,
    };
    const pairs: [string, number][] = [
      ["/courses", 39], ["/batches", 38], ["/sessions", 80], ["/enrollments", 66],
      ["/assignments", 3], ["/quizzes", 5], ["/exams", 1],
      ["/announcements", 2], ["/messages", 4], ["/notifications", 16],
      ["/users", 117], ["/roles", 6], ["/permissions", 127], ["/guardians", 1],
    ];
    for (const [href, expected] of pairs) {
      expect(badgeFor(href, counts), href).toBe(expected);
    }
  });

  it("ignores a negative, which would mean the server is wrong", () => {
    expect(badgeFor("/messages", { messages: -1 })).toBeUndefined();
  });
});
