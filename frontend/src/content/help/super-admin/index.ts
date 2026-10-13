import type { Guide } from "../types";
import { administration } from "./administration";
import { assessment } from "./assessment";
import { contentCommunity } from "./content-community";
import { gettingStarted } from "./getting-started";
import { insights } from "./insights";
import { learning } from "./learning";
import { people } from "./people";
import { troubleshooting } from "./troubleshooting";

/**
 * The Super Admin guide.
 *
 * Section order is reading order: the previous/next links at the foot of every
 * article follow it, so somebody who starts at the top and keeps clicking
 * **Next** is taken through the whole system in a sensible sequence --
 * sign in, teach, assess, communicate, administer, oversee.
 *
 * Every article was written against the running console signed in as a Super
 * Admin, and every screenshot is of the screen it sits beside. Personal data
 * in those screenshots is blurred, because these pages are public.
 */
export const superAdminGuide: Guide = {
  slug: "super-admin",
  role: "Super Admin",
  title: "Super Admin User Guide",
  intro:
    "Everything a Super Admin can do, explained step by step with pictures of the real screens. Written for people who have never used a system like this before — no technical knowledge needed.",
  audience:
    "For people with a Super Admin account, who look after the whole institution.",
  updated: "2026-10-12",
  sections: [
    gettingStarted,
    learning,
    assessment,
    contentCommunity,
    people,
    administration,
    insights,
    troubleshooting,
  ],
};
