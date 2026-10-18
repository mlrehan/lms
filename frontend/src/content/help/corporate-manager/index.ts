import type { Guide } from "../types";
import { communication } from "./communication";
import { gettingStarted } from "./getting-started";
import { learningAndResults } from "./learning-and-results";
import { troubleshooting } from "./troubleshooting";
import { yourPeople } from "./your-people";

/**
 * The Corporate Manager guide.
 *
 * Covers the verified Corporate Manager role workflows and features:
 * - Workforce Command Center (6 KPIs, Intervention Desk, Risk Matrix, Nudges)
 * - Workforce roster (My team, Organizations, Manager assignments)
 * - Academic tracking (Courses, Batches & Cohort enrollment modal, Enrollments register,
 *   Timetable sessions, Attendance registers, Coursework assignments, Quizzes, Examinations,
 *   Performance weighted standing so far, and Reports with CSV exports)
 * - Care-Circle communication (Announcements, Discussions, Messages, Notifications, Shared with me)
 * - Account configuration (Timezone preferences, credential management)
 * - Diagnostic workflows and institutional escalation pathways
 */
export const corporateManagerGuide: Guide = {
  slug: "corporate-manager",
  role: "Corporate Manager",
  title: "Corporate Manager User Guide",
  intro:
    "Executive guide to workforce training oversight: tracking attendance, monitoring performance velocity, managing cohort enrollments, triaging learner intervention alerts, and exporting compliance audit reports.",
  audience:
    "For corporate managers, L&D directors, and team leaders managing sponsored workforce training cohorts.",
  updated: "2026-10-18",
  sections: [gettingStarted, yourPeople, learningAndResults, communication, troubleshooting],
};
