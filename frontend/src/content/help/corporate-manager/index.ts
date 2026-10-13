import type { Guide } from "../types";
import { communication } from "./communication";
import { gettingStarted } from "./getting-started";
import { learningAndResults } from "./learning-and-results";
import { troubleshooting } from "./troubleshooting";
import { yourPeople } from "./your-people";

/**
 * The Corporate Manager guide.
 *
 * Covers the corporate-manager role only. The account used to write it also
 * held the Student role, so it could open Announcements, Discussions and
 * Resources -- none of which the corporate-manager role grants. Those are
 * deliberately absent here, and the sidebar article explains why a reader
 * might see them anyway.
 */
export const corporateManagerGuide: Guide = {
  slug: "corporate-manager",
  role: "Corporate Manager",
  title: "Corporate Manager User Guide",
  intro:
    "How to follow the staff your company has sent on a course: their attendance, the work they are set, their results, and how to enrol somebody onto a class.",
  audience:
    "For managers whose company sponsors staff to take courses with the training provider.",
  updated: "2026-10-12",
  sections: [gettingStarted, yourPeople, learningAndResults, communication, troubleshooting],
};
