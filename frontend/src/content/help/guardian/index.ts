import type { Guide } from "../types";
import { gettingStarted } from "./getting-started";
import { progress } from "./progress";
import { stayingInTouch } from "./staying-in-touch";
import { theirLearning } from "./their-learning";
import { troubleshooting } from "./troubleshooting";

/**
 * The Guardian guide.
 *
 * A guardian account is read-only by design: it can see attendance, work and
 * results, and change none of them. The guide says so plainly rather than
 * letting a reader hunt for buttons that do not exist.
 *
 * There was no guardian in this environment when the guide was written, so
 * one was created with the user's approval, linked to an existing student,
 * used for these screenshots, and removed afterwards.
 */
export const guardianGuide: Guide = {
  slug: "guardian",
  role: "Guardian",
  title: "Guardian User Guide",
  intro:
    "How to follow the progress of the person you look after: their classes, their attendance, the work they are set and their results. Written for complete beginners.",
  audience:
    "For parents, carers and family members linked to a student by the school.",
  updated: "2026-10-12",
  sections: [gettingStarted, progress, theirLearning, stayingInTouch, troubleshooting],
};
