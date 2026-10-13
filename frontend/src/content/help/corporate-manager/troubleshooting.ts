import type { Section } from "../types";

/** The questions corporate managers ask most. */
export const troubleshooting: Section = {
  id: "troubleshooting",
  title: "Solving problems",
  blurb: "The questions that come up most often, and who to ask.",
  articles: [
    {
      id: "common-problems",
      title: "Common problems and how to solve them",
      summary: "What to check first, and when to contact the training provider.",
      learn: [
        "What to check when somebody is missing",
        "Which problems you can solve yourself",
        "When to contact the training provider",
      ],
      body: [
        { type: "heading", text: "Somebody from my company is missing" },
        {
          type: "paragraph",
          text: "This is the most common question, and it almost always has the same answer: **employing somebody does not let you see them**. Two separate things are needed.",
        },
        {
          type: "steps",
          items: [
            {
              text: "Open **Manager assignments** and check whether they are listed against your name.",
            },
            {
              text: "If they are not, ask the training provider to assign them to you. You cannot do this yourself.",
            },
            { text: "Separately, check they are on the **Employees** tab of your company." },
          ],
        },

        { type: "heading", text: "A screen looks empty" },
        {
          type: "bullets",
          items: [
            "**A filter is still set from last time.** Clear the search box and set every filter back to 'Any'.",
            "**Some screens need a batch or course chosen first.** Grade book, Performance and Assignments show nothing until you choose one.",
            "**A date range is excluding everything.** Clear **From** and **To** on the Timetable.",
            "**Give it a moment.** Some lists show the word 'Loading' for a second or two.",
          ],
        },

        { type: "heading", text: "The attendance figure looks wrong" },
        {
          type: "paragraph",
          text: "Attendance is recorded by the tutor, class by class. Open **Attendance**, filter to that person, and look at the individual classes. A single missed class early on moves a percentage a long way. If a particular class looks wrong, raise it with the training provider; you cannot change a register.",
        },

        { type: "heading", text: "A result looks lower than expected" },
        {
          type: "bullets",
          items: [
            "**'So far incomplete' means the course is not finished.** The percentage is out of the work assessed so far, and it moves.",
            "**Unmarked work can count as zero** until it is marked, depending on how the course is set up.",
            "**Attendance may itself be part of the mark** on some courses.",
          ],
        },

        { type: "heading", text: "I cannot find an email address or phone number" },
        {
          type: "paragraph",
          text: "That is deliberate. Contact details are never shown on these screens, to anybody. Use **Messages** to contact somebody through the system.",
        },

        { type: "heading", text: "A button I expected is not there" },
        {
          type: "paragraph",
          text: "Most of the system is read-only for a corporate manager. None of these is a fault:",
        },
        {
          type: "table",
          columns: ["Missing", "Why"],
          rows: [
            ["New course, New batch", "The training provider creates these."],
            ["Take attendance", "Registers are the tutor's record."],
            ["New assignment, New quiz, Schedule examination", "Tutors set work."],
            [
              "Assign a student on Manager assignments",
              "An administrator decides who you may see.",
            ],
            ["Generate for batch on Transcripts", "An administrator generates them."],
            ["Course prices", "Not shown on your account. Ask the provider."],
          ],
        },
        {
          type: "paragraph",
          text: "The one thing you *can* change is enrolling one of your people onto a class group, from that batch's **Enrollments** tab.",
        },

        { type: "heading", text: "When to contact the training provider" },
        {
          type: "bullets",
          items: [
            "Somebody needs assigning to you, or removing.",
            "Somebody needs an account creating.",
            "A register or a mark looks wrong.",
            "You need a transcript that has not been generated.",
            "You cannot sign in, or your account is locked.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "When you get in touch, say which person and which course. It saves a round of questions.",
          },
        },
      ],
      related: ["manager-assignments", "my-team", "attendance", "account"],
    },
  ],
};
