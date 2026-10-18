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

        { type: "heading", text: "Contacting teachers and school staff" },
        {
          type: "paragraph",
          text: "To protect student privacy and ensure safe communication channels, personal phone numbers and email addresses are protected. You can contact your student's tutors and administrative staff directly through the integrated **Messages** tab.",
        },

        { type: "heading", text: "Understanding Guardian Access and Student Independence" },
        {
          type: "paragraph",
          text: "The Guardian portal is designed to provide family visibility into attendance, coursework, and grades while preserving the student's independent learning responsibility:",
        },
        {
          type: "table",
          columns: ["Academic Area", "How It Operates"],
          rows: [
            ["Coursework Submissions", "Students submit their own assignments and quizzes through their student accounts."],
            ["Grading & Evaluation", "Instructors grade submissions objectively according to accredited academic schemes."],
            ["Attendance Registers", "Class attendance is recorded live by the instructor during each session."],
            ["Course Enrollment", "Enrollments onto new academic terms and courses are coordinated with the school registry."],
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
