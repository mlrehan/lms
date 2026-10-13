import type { Section } from "../types";

/** The questions guardians ask most. */
export const troubleshooting: Section = {
  id: "troubleshooting",
  title: "Solving problems",
  blurb: "The questions that come up most often, and when to contact the school.",
  articles: [
    {
      id: "common-problems",
      title: "Common problems and how to solve them",
      summary: "What to check first, and when to message the school.",
      learn: [
        "What to check when something is missing",
        "Which worries usually turn out to be nothing",
        "When to contact the school",
      ],
      body: [
        { type: "heading", text: "I cannot see the person I look after" },
        {
          type: "steps",
          items: [
            {
              text: "Open **Guardians** and check they are listed against your name.",
            },
            {
              text: "If they are not, the link has not been set up. Ask the school to create it.",
            },
            {
              text: "If you look after more than one person, each needs its own link.",
            },
          ],
        },

        { type: "heading", text: "A screen looks empty" },
        {
          type: "bullets",
          items: [
            "**Give it a moment.** Some screens show the word 'Loading' for a second or two, especially the first time you open them.",
            "**Some screens need a class group chosen first.** Grade book and Performance show nothing until you choose a **Batch**.",
            "**A date range may be excluding everything.** Clear **From** and **To** on the Timetable.",
            "**A filter may still be set from last time.** Set filters back to 'Any'.",
          ],
        },

        { type: "heading", text: "The attendance figure looks wrong" },
        {
          type: "paragraph",
          text: "Attendance is recorded by the tutor after each class. Open **Attendance** and look at the individual classes and their dates. Two things explain most surprises: recent classes may not have been marked yet, and early in a course a single absence moves the percentage a long way.",
        },

        { type: "heading", text: "The result looks low" },
        {
          type: "bullets",
          items: [
            "**'So far incomplete' means the course is not finished.** The figure is out of the work marked so far, and it moves.",
            "**Unmarked work may count as nothing yet.** It is not a zero the student earned.",
            "**Not everything counts equally.** Check the **weight** column in the grade book before worrying about one mark.",
            "**Attendance may itself be part of the result** on some courses.",
          ],
        },

        { type: "heading", text: "I cannot find a phone number or email address" },
        {
          type: "paragraph",
          text: "That is deliberate. Contact details are never shown on these screens, to anybody. Use **Messages** to contact the school through the system.",
        },

        { type: "heading", text: "There is no button to do the thing I want" },
        {
          type: "paragraph",
          text: "A guardian account is for watching, not for doing. None of these is a fault:",
        },
        {
          type: "table",
          columns: ["Missing", "Why"],
          rows: [
            ["Any way to change attendance", "The register is the tutor's record."],
            ["Any way to hand work in", "Only the student can submit their own work."],
            ["Any way to change a mark", "Marking belongs to the tutor."],
            ["Any way to enrol somebody", "The school arranges places."],
            ["Link a guardian on the Guardians screen", "The school creates links."],
            ["A Reports screen", "Guardians do not have one. Use My team and Performance."],
          ],
        },

        { type: "heading", text: "When to contact the school" },
        {
          type: "bullets",
          items: [
            "You cannot see the person you look after, or somebody is missing.",
            "An attendance record or a mark looks wrong.",
            "You want to know why work is overdue.",
            "You cannot sign in, or your account is locked.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "When you message, say which student, which course and which class or piece of work. It gets you a useful answer first time.",
          },
        },
      ],
      related: ["guardians", "my-team", "attendance", "messages"],
    },
  ],
};
