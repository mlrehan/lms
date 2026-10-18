"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";

/**
 * The numbers beside the menu.
 *
 * One request for every badge, because fourteen would mean fourteen round
 * trips on every page load and after every realtime hint.
 *
 * **A missing key is not zero.** The server omits a count the caller is not
 * entitled to, or that does not apply to them -- a guardian is watching
 * somebody else do the work, so "assignments waiting" is not a number they can
 * act on and they are sent none. `badgeFor` returns `undefined` for a missing
 * key and the sidebar renders nothing, which is different from rendering `0`.
 *
 * Refetching is driven by three things together, because no one of them is
 * enough: the realtime stream invalidates `sidebar-counts` on any event
 * addressed to this person (see `AFFECTED` in `realtime.ts`), the window
 * regaining focus catches anything that notified nobody, and `staleTime` stops
 * a tab that is being clicked around from asking on every navigation.
 */

export type SidebarCounts = Record<string, number>;

interface CountsPayload {
  counts?: SidebarCounts;
}

export function useSidebarCounts(enabled: boolean) {
  return useQuery<SidebarCounts>({
    queryKey: ["sidebar-counts"],
    queryFn: async () => {
      const payload = await api.get<CountsPayload>("/sidebar/counts");
      return payload.counts ?? {};
    },
    enabled,
    // Long enough that moving between screens does not re-ask; short enough
    // that a badge cannot sit wrong for a working session. Realtime events and
    // window focus are what actually keep it current.
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    // A failed count is not worth a retry storm: the badge simply does not
    // render until the next event or focus.
    retry: 1,
  });
}

/** Which badge key belongs to which menu href. */
const BY_HREF: Record<string, string> = {
  "/courses": "courses",
  "/batches": "batches",
  "/sessions": "sessions",
  "/enrollments": "enrollments",
  "/assignments": "assignments",
  "/quizzes": "quizzes",
  "/exams": "exams",
  "/announcements": "announcements",
  "/messages": "messages",
  "/notifications": "notifications",
  "/users": "users",
  "/roles": "roles",
  "/permissions": "permissions",
  "/guardians": "guardians",
};

/**
 * The number to show beside a menu item, or `undefined` for no badge.
 *
 * Zero returns `undefined` too: a badge reading "0" is clutter on every screen
 * a person has nothing waiting on, and the absence says the same thing.
 */
export function badgeFor(href: string, counts: SidebarCounts | undefined): number | undefined {
  const key = BY_HREF[href];
  if (!key || !counts) return undefined;
  const value = counts[key];
  return typeof value === "number" && value > 0 ? value : undefined;
}
