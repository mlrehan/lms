import type { Guide } from "../types";
import { gettingStarted } from "./getting-started";
import { stayingInTouch } from "./staying-in-touch";
import { troubleshooting } from "./troubleshooting";
import { yourCourse } from "./your-course";
import { yourProgress } from "./your-progress";
import { yourRecord } from "./your-record";
import { yourWork } from "./your-work";

/**
 * The Individual Student guide.
 *
 * Same STUDENT role and the same twenty-seven permissions as the managed
 * student, and the same seventeen screens. The account this was written from
 * has no manager, no guardian and no employer membership, so the difference is
 * one of situation rather than of software: nobody outside the school follows
 * this student's progress, and nobody is going to chase them about a deadline.
 *
 * The guide leans on that throughout -- the dashboard does the chasing -- and
 * the second section resists the easy claim that the record is private to
 * them. Tutors and administrators can read it, and a link can be created
 * later, so both are stated plainly instead.
 */
export const individualStudentGuide: Guide = {
  slug: "individual-student",
  role: "Individual Student",
  title: "Individual Student User Guide",
  intro:
    "How to use your course: when your classes are, the work you have been set, how to hand it in, and how you are getting on. Written for complete beginners.",
  audience:
    "For students studying on their own account, with no employer or family member following their progress.",
  updated: "2026-10-13",
  sibling: {
    slug: "managed-student",
    label: "read the Managed Student guide instead",
    when: "If an employer or a family member can see how you are getting on,",
  },
  sections: [
    gettingStarted,
    yourRecord,
    yourCourse,
    yourWork,
    yourProgress,
    stayingInTouch,
    troubleshooting,
  ],
};
