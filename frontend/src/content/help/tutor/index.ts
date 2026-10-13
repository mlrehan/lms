import type { Guide } from "../types";
import { assessment } from "./assessment";
import { communication } from "./communication";
import { gettingStarted } from "./getting-started";
import { teaching } from "./teaching";
import { troubleshooting } from "./troubleshooting";

/**
 * The Tutor guide.
 *
 * Written against the running console signed in as a Tutor. It deliberately
 * covers **only what a tutor can reach**: twelve screens a Super Admin sees
 * are absent from a tutor's menu, so they have no articles here. Where a
 * tutor can see a screen but not act on it -- Grading schemes, Transcripts,
 * Academic setup -- the article says so and names who to ask.
 */
export const tutorGuide: Guide = {
  slug: "tutor",
  role: "Tutor",
  title: "Tutor User Guide",
  intro:
    "Everything a tutor can do, explained step by step with pictures of the real screens. Taking the register, setting and marking work, and seeing how your students are doing.",
  audience: "For tutors, who teach classes and mark the work students hand in.",
  updated: "2026-10-12",
  sections: [gettingStarted, teaching, assessment, communication, troubleshooting],
};
