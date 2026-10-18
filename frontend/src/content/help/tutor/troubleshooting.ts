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
      summary: "What to check first, and how to coordinate with academic administration.",
      learn: [
        "What to check when something is missing",
        "Which settings you can adjust directly",
        "Academic coordination and registry support",
      ],
      body: [
        { type: "heading", text: "A student is missing from my class" },
        {
          type: "steps",
          items: [
            { text: "Open **Enrollments** and search for their name." },
            {
              text: "If they are not listed, their enrollment is pending confirmation with the admissions office.",
            },
            {
              text: "If they are enrolled on a different cohort, request a batch transfer with the registrar.",
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

        { type: "heading", text: "Faculty Roles & Academic Coordination" },
        {
          type: "paragraph",
          text: "The Tutor portal is tailored specifically for instructional delivery, student engagement, and assessment marking. Institutional governance workflows are supported by Academic Administration:",
        },
        {
          type: "table",
          columns: ["Faculty Request", "Administrative Coordination"],
          rows: [
            ["New syllabus, course or batch creation", "Curriculum scheduling is coordinated through the Academic Office."],
            ["Student admissions and batch transfers", "Student registry operations are processed centrally by Admissions."],
            ["Institutional grading scheme updates", "Institutional assessment frameworks are accredited by Academic Affairs."],
            ["Official certified transcripts", "Degree and module transcripts are officially validated and sealed by Registry."],
          ],
        },

        { type: "heading", text: "Institutional Administration & Registry Support" },
        {
          type: "bullets",
          items: [
            "Official student admissions, enrollments, or batch transfers (Registrar's Office).",
            "Master course catalog and batch lifecycle scheduling (Curriculum Committee).",
            "Accredited grading scheme adjustments (Academic Affairs).",
            "Comprehensive institution-wide CSV analytics exports (Institutional Research).",
            "Account security or password reset assistance (IT Services).",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "When coordinating with administration, include the batch number and course code to accelerate processing.",
          },
        },
      ],
      related: ["attendance", "gradebook", "enrollments", "account"],
    },
  ],
};
