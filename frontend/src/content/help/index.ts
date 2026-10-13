/**
 * Every published guide, and the lookups the help pages are built from.
 *
 * A guide appears in the Help Center, in the sitemap, in search and in the
 * role's sidebar link purely by being in `GUIDES`. There is no second list to
 * keep in step.
 *
 * Guides that are not written yet are deliberately absent rather than present
 * and empty: an entry here is a promise that every article behind it is
 * finished and checked against the running system.
 */

import type { Article, Guide } from "./types";
import { corporateManagerGuide } from "./corporate-manager";
import { guardianGuide } from "./guardian";
import { individualStudentGuide } from "./individual-student";
import { managedStudentGuide } from "./managed-student";
import { superAdminGuide } from "./super-admin";
import { tutorGuide } from "./tutor";

export const GUIDES: Guide[] = [
  superAdminGuide,
  tutorGuide,
  corporateManagerGuide,
  guardianGuide,
  managedStudentGuide,
  individualStudentGuide,
];

export function guideBySlug(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}

/** Every (guide, article) pair, for static generation and the sitemap. */
export function allArticlePaths(): { role: string; article: string }[] {
  return GUIDES.flatMap((guide) =>
    guide.sections.flatMap((section) =>
      section.articles.map((article) => ({ role: guide.slug, article: article.id })),
    ),
  );
}

export function articleCount(guide: Guide): number {
  return guide.sections.reduce((n, s) => n + s.articles.length, 0);
}

/**
 * Which guide a signed-in person should be offered, from the roles the server
 * says they hold.
 *
 * Ordered most-privileged first: somebody who is both a Tutor and a Super
 * Admin is a Super Admin for this purpose, because that guide covers the
 * screens they actually see. The role names are the server's, not labels
 * typed into the console.
 */
const ROLE_TO_GUIDE: [string, string][] = [
  ["SUPER_ADMIN", "super-admin"],
  ["TUTOR", "tutor"],
  ["CORPORATE_MANAGER", "corporate-manager"],
  ["GUARDIAN", "guardian"],
  // Both student guides are written for the same STUDENT role holding the same
  // permissions -- what separates them is whether a manager or guardian is
  // linked to the account, which a student's own token cannot tell us. So one
  // mapping has to serve both, and it is the managed one: being told that
  // somebody can read your record matters more to a reader who did not know it
  // than the same page costs a reader for whom it does not apply. Revisit when
  // the Individual Student guide lands -- a chooser may serve both better.
  ["STUDENT", "managed-student"],
];

export function guideForRoles(roles: readonly string[] | null | undefined): Guide | undefined {
  // Tolerates a missing list rather than throwing. The roles come from an API
  // response, and "we do not know who this is yet" is a normal state during
  // loading -- the sidebar renders in that state, and a crash there would take
  // the whole navigation down over a help link.
  const held = new Set((roles ?? []).map((r) => r.toUpperCase()));
  for (const [role, slug] of ROLE_TO_GUIDE) {
    if (held.has(role)) {
      const guide = guideBySlug(slug);
      if (guide) return guide;
    }
  }
  return undefined;
}

export type { Article, Guide };
