import type { Guide } from "../types";
import { gettingStarted } from "./getting-started";
import { stayingInTouch } from "./staying-in-touch";
import { troubleshooting } from "./troubleshooting";
import { whoCanSee } from "./who-can-see";
import { yourCourse } from "./your-course";
import { yourProgress } from "./your-progress";
import { yourWork } from "./your-work";

/**
 * The Managed Student guide.
 *
 * A managed student holds exactly the same role, and exactly the same twenty-seven
 * permissions, as any other student. What makes them different is contextual: an
 * employer's manager or a guardian has been linked to their account and can read
 * their attendance, their work and their results.
 *
 * That is why the second section exists, and why it says the uncomfortable part
 * out loud -- the student has no screen listing who is linked to them. They are
 * notified at the moment a link is created and never again, so the guide tells
 * them to read that notification and, failing that, to ask.
 */
export const managedStudentGuide: Guide = {
  slug: "managed-student",
  role: "Managed Student",
  title: "Managed Student User Guide",
  intro:
    "How to use your course: when your classes are, the work you have been set, how to hand it in, and how you are getting on. Written for complete beginners.",
  audience:
    "For students whose place was arranged by an employer, a sponsor or a family member — someone who can see how you are getting on.",
  updated: "2026-10-18",
  sibling: {
    slug: "individual-student",
    label: "read the Individual Student guide instead",
    when: "If nobody at an employer or at home follows your progress,",
  },
  sections: [
    gettingStarted,
    whoCanSee,
    yourCourse,
    yourWork,
    yourProgress,
    stayingInTouch,
    troubleshooting,
  ],
};
