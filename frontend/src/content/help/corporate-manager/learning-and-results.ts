import type { Section } from "../types";

/** Everything a manager can look at about courses, classes and results. */
export const learningAndResults: Section = {
  id: "learning-and-results",
  title: "Courses, classes and results",
  blurb:
    "The catalogue, your people's classes and attendance, the work they are set, and their results.",
  articles: [
    {
      id: "courses",
      title: "How to browse the course catalogue",
      summary: "Every course the training provider offers, and what the statuses mean.",
      feature: "Courses",
      learn: ["How to browse and filter courses", "What each status means"],
      body: [
        {
          type: "paragraph",
          text: "**Courses** shows the whole catalogue — not only the ones your people are on. Use it to see what is available before asking about a place.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/courses.webp",
            alt: "The Courses screen listing courses with status, level and hours, plus search and filters.",
            caption: "The catalogue. Use the search box and the three filters to narrow it.",
          },
        },
        {
          type: "table",
          columns: ["Status", "What it means"],
          rows: [
            ["Draft", "Still being prepared. Not open to students."],
            ["Published", "Open and ready."],
            ["Running", "Teaching is under way."],
            ["Completed", "Teaching has finished."],
            ["Archived", "No longer offered."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "Course prices are not shown on your account. Ask the training provider about costs.",
          },
        },
      ],
      result: "You can see what is on offer and its level.",
      related: ["batches", "enrollments"],
    },

    {
      id: "batches",
      title: "How to see a class group and enrol somebody",
      summary:
        "Open a batch to see its classes and who is on it — and add one of your people.",
      feature: "Batches",
      learn: [
        "What a batch is",
        "How to open one",
        "How to enrol one of your people onto it",
      ],
      before: [
        "The person must already have an account with the training provider.",
        "You can only enrol onto batches you can see.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **batch** is one group of students taking one course together, with its own dates and timetable. You see the batches that concern your people.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/batches.webp",
            alt: "The Batches screen listing groups with schedule, dates, method, sessions, enrolled and state.",
            caption: "The class groups you can see.",
          },
        },
        { type: "heading", text: "Open a batch" },
        {
          type: "steps",
          items: [
            { text: "Click **Batches** in the left-hand menu." },
            { text: "Click anywhere on the batch's row." },
          ],
        },
        {
          type: "paragraph",
          text: "The workspace has three tabs: **Overview** (its details), **Sessions** (every class with its time and place) and **Enrollments** (who is on it).",
        },
        { type: "heading", text: "Enrol one of your people" },
        {
          type: "paragraph",
          text: "This is the one action on your account that changes something. It puts one of your people onto a class group.",
        },
        {
          type: "steps",
          items: [
            { text: "Open the batch they are joining." },
            { text: "Click the **Enrollments** tab." },
            {
              text: "Click **Enroll**.",
              image: {
                src: "corporate-manager/dialog-enroll.webp",
                alt: "The Enroll a student dialog, showing which batch it is for and a single Student box.",
                caption:
                  "The dialog names the batch you are enrolling into, so you can check before confirming.",
              },
            },
            { text: "Choose the **Student**. It is the only box." },
            { text: "Click **Enroll student**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Check the batch before you confirm",
            body: "The dialog tells you which batch you are enrolling into. A person put on the wrong group has to be moved by an administrator, so it is worth a second's check.",
          },
        },
      ],
      result:
        "The person appears on the batch's **Enrollments** tab and on your **My team** screen.",
      tips: [
        "If the person you want is not in the **Student** list, they do not have an account yet. Ask the training provider to create one.",
      ],
      problems: [
        {
          symptom: "There is no **Enroll** button.",
          fix: "You are on the wrong tab. It is on the **Enrollments** tab of the batch, not on the Enrollments screen in the main menu.",
        },
        {
          symptom: "The batch you want is not listed.",
          fix: "You can only see batches that concern your people. Ask the training provider.",
        },
      ],
      related: ["enrollments", "timetable", "my-team", "courses"],
    },

    {
      id: "enrollments",
      title: "How to check who is on which class",
      summary: "Every place your people hold, and whether it is confirmed.",
      feature: "Enrollments",
      learn: ["Where to check somebody's place", "What the statuses mean"],
      body: [
        {
          type: "paragraph",
          text: "**Enrollments** lists the places your people hold: who is on which batch, and in what state.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/enrollments.webp",
            alt: "The Enrollments screen listing students, their batch, status and enrolled date.",
            caption: "Your people's places. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Enrollments** in the left-hand menu." },
            { text: "Use **Batch** to see one group." },
            { text: "Use **Student** to check one person." },
            { text: "Use **Status** to show only confirmed places." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "Adding somebody is done from the batch itself, not here. See the batches article.",
          },
        },
      ],
      result: "You can confirm somebody has a place before the course starts.",
      related: ["batches", "my-team"],
    },

    {
      id: "timetable",
      title: "How to see when classes are",
      summary: "Your people's classes in order, in your own timezone.",
      feature: "Timetable",
      learn: ["How to read the timetable", "How to filter it"],
      body: [
        {
          type: "paragraph",
          text: "The **Timetable** lists the classes that concern you, earliest first. Times are shown in your own timezone, written at the top.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/timetable.webp",
            alt: "The Timetable screen listing sessions with start and end times and filters for dates, batch, tutor and student.",
            caption: "Classes in order.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Timetable** in the left-hand menu." },
            { text: "Use **From** and **To** to choose a range of dates." },
            { text: "Use **Batch** or **Student** to narrow it." },
          ],
        },
      ],
      result: "You know when your people are expected in class.",
      tips: ["Leave the date boxes empty to see everything."],
      problems: [
        {
          symptom: "The timetable looks empty.",
          fix: "A date filter is probably still set. Clear **From** and **To**.",
        },
        { symptom: "The times look wrong.", fix: "Check your timezone on **My account**." },
      ],
      related: ["batches", "attendance", "account"],
    },

    {
      id: "attendance",
      title: "How to check attendance",
      summary: "Every register that concerns your people, and who marked it.",
      feature: "Attendance",
      learn: ["How to check whether somebody attended", "What each status means"],
      body: [
        {
          type: "paragraph",
          text: "**Attendance** shows the registers that concern you: one row per person per class, with what they were marked and who recorded it.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/attendance.webp",
            alt: "The Attendance screen listing session, batch, student, status, remarks and when it was recorded and by whom.",
            caption:
              "Registers that concern your people. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Present", detail: "They attended, on time." },
            { term: "Late", detail: "They attended, after the class started." },
            { term: "Absent", detail: "They did not attend, and it was not agreed." },
            { term: "Excused", detail: "They did not attend, and it was agreed beforehand." },
          ],
        },
        {
          type: "steps",
          items: [
            { text: "Click **Attendance** in the left-hand menu." },
            { text: "Use **Batch** or **Student** to narrow the list." },
            { text: "Use **Status** to show only absences, for example." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "You cannot change a register",
            body: "The register is the tutor's record. If something looks wrong, raise it with the training provider rather than assuming the person did not attend.",
          },
        },
      ],
      result: "You can see exactly which classes somebody attended, and which they missed.",
      tips: [
        "Filter by **Absent** to see every missed class in one list. It is the quickest way to spot a pattern.",
      ],
      related: ["my-team", "timetable", "reports"],
    },

    {
      id: "work-and-results",
      title: "How to see the work set and the marks given",
      summary:
        "Assignments, quizzes and examinations your people are set, and the marks they receive.",
      feature: "Assignments, Quizzes, Examinations, Grade book",
      learn: [
        "Where to see work that has been set",
        "Where to see marks",
        "Why you cannot change anything here",
      ],
      body: [
        {
          type: "paragraph",
          text: "Four screens show you what your people are asked to do and how they did. All four are read-only for you — setting and marking work belongs to the tutor.",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Assignments",
              detail:
                "Work your people have been set and must hand in. Choose a course to see the list.",
            },
            {
              term: "Quizzes",
              detail:
                "Question sets marked automatically. You can see the quiz, its duration, attempts allowed and pass mark.",
            },
            {
              term: "Examinations",
              detail:
                "Scheduled assessments, with when they are, how long, and the total and passing marks.",
            },
            {
              term: "Grade book",
              detail:
                "Every mark a student has earned on a batch. Choose a **Batch** first — it is empty until you do.",
            },
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/gradebook-batch.webp",
            alt: "The grade book with a batch chosen, showing entries for each student and component.",
            caption:
              "The grade book, with a batch chosen. Names are blurred in this guide for privacy.",
          },
        },
        { type: "heading", text: "The grade book's three tabs" },
        {
          type: "definitions",
          items: [
            {
              term: "Entries",
              detail:
                "One row per contribution: each assignment, quiz, attendance, practical and the final exam.",
            },
            {
              term: "Student standing",
              detail: "Each student's overall position, worked out from the entries.",
            },
            {
              term: "Grading scale",
              detail: "The bands that turn a percentage into a letter grade and GPA points.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A mark you disagree with is a conversation, not a correction",
            body: "You cannot change marks, and should not expect to. If a mark looks wrong, raise it with the training provider — there is an appeals process for that, and the audit trail records every change.",
          },
        },
      ],
      result: "You can see what was set, what was handed in, and what it scored.",
      tips: [
        "**Overdue assignments** on your dashboard is a faster way to spot missing work than opening each assignment.",
      ],
      problems: [
        {
          symptom: "The grade book is empty.",
          fix: "Choose a **Batch** at the top. Nothing shows until you do.",
        },
        {
          symptom: "The assignments list is empty.",
          fix: "Choose a **Course** first. The list fills in once you do.",
        },
      ],
      related: ["performance", "transcripts", "my-team"],
    },

    {
      id: "performance",
      title: "How to see overall results",
      summary:
        "Every student in a class group with their current percentage and grade.",
      feature: "Performance",
      learn: ["How to see a whole group at once", "What 'so far incomplete' means"],
      before: ["Choose a **Batch** — the screen is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "**Performance** shows everybody in a class group with their current standing, and lets you open a row to see the working behind the number.",
        },
        {
          type: "steps",
          items: [
            { text: "Click **Performance** in the left-hand menu." },
            {
              text: "Choose a **Batch**.",
              image: {
                src: "corporate-manager/performance-batch.webp",
                alt: "The Performance screen for a batch, listing students with a percentage, a status of so far incomplete, and a letter grade.",
                caption:
                  "Each student with their percentage and grade. Names are blurred in this guide for privacy.",
              },
            },
            {
              text: "Click a student's row to see every component, its weight and what it contributed.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "What 'so far incomplete' means",
            body: "Not everything has been assessed yet. The percentage is out of the work done so far and will move as the course goes on. It is not a final result, and a low early figure is often just unmarked work.",
          },
        },
      ],
      result: "You can see how your people are doing compared with the rest of the group.",
      tips: [
        "Wait until a course is well under way before drawing conclusions. Early percentages move a lot.",
      ],
      related: ["work-and-results", "transcripts", "my-team"],
    },

    {
      id: "transcripts",
      title: "How to find a transcript",
      summary: "The final, formal record of how somebody did on a course.",
      feature: "Transcripts",
      learn: ["What a transcript is", "How to find one"],
      body: [
        {
          type: "paragraph",
          text: "A **transcript** is the final record of a student's standing on a batch: their marks brought together and turned into a grade.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/transcripts.webp",
            alt: "The Transcripts screen with student, batch, GPA, overall, generated date and state columns.",
            caption:
              "Transcripts, with filters for batch and student.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Transcripts** in the left-hand menu." },
            { text: "Filter by **Batch** or **Student**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Transcripts appear only when they are made",
            body: "An administrator generates them, usually once a course has finished and its marking is complete. If the screen says there are none yet, that is normal mid-course.",
          },
        },
      ],
      result: "You can see the formal result for a completed course.",
      related: ["performance", "work-and-results"],
    },

    {
      id: "reports",
      title: "How to use reports and export them",
      summary: "Six ready-made reports, and how to download one as a spreadsheet.",
      feature: "Reports",
      learn: ["What each report shows", "How to export one"],
      body: [
        {
          type: "paragraph",
          text: "**Reports** are figures worked out by the system, covering only the people you are allowed to see.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/reports.webp",
            alt: "The Reports screen showing six tabs, filters, a chart and a table, with the Export CSV button.",
            caption: "Six reports. Each has its own filters and an export button.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Attendance",
              detail: "Present, late, absent and excused counts, and the resulting rate.",
            },
            { term: "Enrollment", detail: "How many people are enrolled, and where." },
            { term: "Performance", detail: "How your people are doing overall." },
            { term: "Coursework", detail: "Work set and handed in." },
            { term: "Distribution", detail: "How marks are spread across grades." },
            { term: "Grading queue", detail: "Work waiting to be marked." },
          ],
        },
        { type: "heading", text: "Export to a spreadsheet" },
        {
          type: "steps",
          items: [
            { text: "Open the report you want." },
            { text: "Set the filters, such as the course or the date range." },
            { text: "Click **Export CSV**." },
            {
              text: "Open the downloaded file in Excel, Numbers or Google Sheets.",
              note: "CSV is a plain table format every spreadsheet program can open.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "An exported file is no longer protected",
            body: "Once a report is on your computer the system cannot control who sees it. Exports contain information about named people, so store and share them carefully, and in line with your company's own data rules.",
          },
        },
      ],
      result: "You have the figures on screen, or as a spreadsheet for your own reporting.",
      tips: [
        "The **Attendance** report is the one most companies want monthly. Set the date range and export it.",
      ],
      related: ["attendance", "performance", "my-team"],
    },
  ],
};
