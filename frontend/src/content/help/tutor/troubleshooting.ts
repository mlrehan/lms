import type { Section } from "../types";

/** The problems that send a tutor hunting through the whole guide. */
export const troubleshooting: Section = {
  id: "troubleshooting",
  title: "Solving problems",
  blurb: "The questions tutors ask most often.",
  articles: [
    {
      id: "common-problems",
      title: "Common problems and how to solve them",
      summary: "What to check first, and when to ask an administrator.",
      learn: [
        "What to check when something is missing",
        "Which problems you can fix yourself",
        "When to ask an administrator",
      ],
      body: [
        { type: "heading", text: "A student is missing from my class" },
        {
          type: "steps",
          items: [
            { text: "Open **Enrollments** and search for their name." },
            {
              text: "If they are not there, they are not enrolled. Only an administrator can add them.",
            },
            {
              text: "If they are there but on a different batch, ask an administrator to transfer them.",
            },
          ],
        },

        { type: "heading", text: "A screen looks empty" },
        {
          type: "bullets",
          items: [
            "**A filter is still set from last time.** This is by far the most common cause. Clear the search box and set every filter back to 'Any'.",
            "**Some screens need a batch or course chosen first.** Grade book, Performance, Transcripts and Assignments all show nothing until you choose one.",
            "**A date range is excluding everything.** Clear **From** and **To** on the Timetable.",
            "**Give it a moment.** Some lists take a second or two to load and show the word 'Loading' while they do.",
          ],
        },

        { type: "heading", text: "The class I need to mark is not listed" },
        {
          type: "paragraph",
          text: "On **Attendance**, the list defaults to the **Last 7 days**. Change that, or click **All**. You can also reach any class from its batch: open the batch, go to **Sessions**, and use the **Register** action.",
        },

        { type: "heading", text: "Students say they cannot see the work I set" },
        {
          type: "bullets",
          items: [
            "**An assignment may be unpublished**, or its **Opens** date may still be in the future.",
            "**A quiz starts unpublished.** Turn on the **Published** switch at the top of the quiz.",
            "**An examination's schedule is published separately** from its results.",
            "**An announcement outside its date window** is stored but not shown.",
          ],
        },

        { type: "heading", text: "A mark or a result looks wrong" },
        {
          type: "steps",
          items: [
            {
              text: "Open the **Grade book**, choose the batch and the student, and look at **Entries**. A missing or mistyped entry is the usual cause.",
            },
            { text: "Use **Sync from marks** — the mark may exist but not have been brought in." },
            {
              text: "Remember that a percentage marked **so far incomplete** is out of the work done so far, not the whole course.",
            },
            {
              text: "If the weighting itself looks wrong, that is the grading scheme. Only a Super Admin can change it.",
            },
          ],
        },

        { type: "heading", text: "The times are all wrong" },
        {
          type: "paragraph",
          text: "Times are stored the same way for everybody and shown in your own timezone. Open **My account** and check yours. It is also written on your dashboard.",
        },

        { type: "heading", text: "A button I expected is not there" },
        {
          type: "paragraph",
          text: "Several things are deliberately not part of a tutor account. These are not faults:",
        },
        {
          type: "table",
          columns: ["Missing", "Why"],
          rows: [
            ["New course, New batch", "Only an administrator creates these."],
            ["Adding or removing a student", "Enrolment is an administrator's job."],
            ["New scheme on Grading schemes", "Only a Super Admin changes what counts."],
            ["Generate for batch on Transcripts", "An administrator generates transcripts."],
            ["Export CSV on Reports", "Ask an administrator for a spreadsheet."],
            ["The fee on a batch", "Course prices are Super Admin only."],
          ],
        },

        { type: "heading", text: "When to ask an administrator" },
        {
          type: "bullets",
          items: [
            "A student needs enrolling, removing or moving to another batch.",
            "A course or batch needs creating or correcting.",
            "The grading scheme is wrong for your course.",
            "You need a report as a spreadsheet.",
            "Your account is locked, or you cannot sign in.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "When you ask, say which batch and which student. It saves a round of questions.",
          },
        },
      ],
      related: ["attendance", "gradebook", "enrollments", "account"],
    },
  ],
};
