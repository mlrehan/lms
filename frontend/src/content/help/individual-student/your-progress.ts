import type { Section } from "../types";

/** Attendance, performance, and completion transcripts. */
export const yourProgress: Section = {
  id: "your-progress",
  title: "How you are getting on",
  blurb: "Your attendance records, overall weighted standing, and completion transcripts.",
  articles: [
    {
      id: "attendance",
      title: "How to check your attendance",
      summary: "Every class you have had, whether you were marked present, and your attendance rate.",
      feature: "Attendance",
      learn: [
        "Where your attendance register is",
        "What the four statuses mean",
        "Why the percentage moves slowly once you have had many classes",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Attendance** is your record of every class scheduled for your course. It shows each session date, start time, and official attendance status.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/attendance.webp",
            alt: "The Attendance screen showing session rows with status badges for Present, Late, Absent and Excused, and filter controls.",
            caption: "Your session register. Personal identifying details are blurred for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Present", detail: "You joined on time and attended the class." },
            { term: "Late", detail: "You joined after instruction began." },
            { term: "Absent", detail: "You did not attend and had not arranged it in advance." },
            {
              term: "Excused",
              detail:
                "You could not attend, but told the school beforehand and had it authorized.",
            },
          ],
        },
        {
          type: "heading",
          text: "What to do if a mark looks wrong",
        },
        {
          type: "paragraph",
          text: "Attendance is recorded by the tutor who taught the class. If you were marked absent for a class you attended, or an authorized personal absence was not marked excused, write to your tutor via **Messages** with the session date.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Check attendance weekly",
            body: "Reviewing your attendance register weekly ensures that any recording error can be resolved immediately while the session is fresh.",
          },
        },
      ],
      result: "You know your official attendance standing across all completed classes.",
      problems: [
        {
          symptom: "A class you attended is marked Absent.",
          fix: "Message your tutor using **Messages**. Give the date and the course.",
        },
        {
          symptom: "Your percentage seems low.",
          fix: "Early in a cohort, one absence moves the percentage significantly. Check the actual session rows to see your record.",
        },
      ],
      related: ["performance", "timetable", "messages"],
    },

    {
      id: "performance",
      title: "How to see your overall result",
      summary: "Your current percentage, provisional letter grade, and the arithmetic working behind it.",
      feature: "Performance",
      learn: [
        "Where your overall standing is displayed",
        "What 'so far incomplete' means",
        "How component weightings contribute to your final result",
      ],
      before: ["Choose your **Batch** from the dropdown — the screen populates once selected."],
      body: [
        {
          type: "paragraph",
          text: "**Performance** shows your weighted standing on your course: one clear percentage, a provisional letter grade, and the complete calculation breakdown.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/performance-batch.webp",
            alt: "The Performance screen for a batch showing student standing percentage, letter grade, and expandable component breakdown table.",
            caption: "Your weighted standing. Personal names are blurred for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Performance** in the left-hand menu." },
            { text: "Select your active **Batch** from the dropdown." },
            {
              text: "Click your student row to expand the component breakdown.",
              note: "This reveals each component (Assignments, Attendance, Quizzes, Examinations, Practical), its weight, and what it actually contributes.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "What 'so far incomplete' means",
            body: "During an ongoing course, the standing reflects only the components assessed to date. A provisional score reflects your current position across marked work, not a final failing grade. Final grades lock once all weighted coursework concludes.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Student privacy safeguards",
            body: "Even though cohort rankings exist in the administrative engine, your student portal strictly displays only your own standing. You cannot see your peers' results, and they cannot see yours.",
          },
        },
      ],
      result: "You understand exactly where your overall percentage comes from and how remaining work will impact your final grade.",
      tips: [
        "Expand your row before worrying about the headline percentage. One unmarked deliverable often explains the temporary gap.",
      ],
      problems: [
        {
          symptom: "The screen stays empty.",
          fix: "Ensure your active batch is selected in the batch dropdown at the top.",
        },
      ],
      related: ["attendance", "transcripts", "assignments"],
    },

    {
      id: "transcripts",
      title: "What a transcript is, and when you get one",
      summary: "The formal certified record of your course completion, issued upon cohort graduation.",
      feature: "Transcripts",
      learn: [
        "What an academic transcript represents",
        "When transcripts are finalized and issued",
        "How to request an official copy",
      ],
      body: [
        {
          type: "paragraph",
          text: "An **academic transcript** is the formal institutional record of your educational achievements on a course — bringing together your final component marks, overall percentage, letter grade, and grade points into an official certified document.",
        },
        {
          type: "definitions",
          items: [
            { term: "GPA / Standing", detail: "Your final cumulative grade points and accredited letter grade." },
            { term: "Component Breakdown", detail: "Certified scores achieved across coursework, attendance, quizzes, and exams." },
            { term: "Registry Verification", detail: "Formal sign-off and seal from the Academic Registry confirming course completion." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Transcripts are issued upon graduation",
            body: "The institution prepares and finalizes official transcripts once the cohort concludes and all marks are formally approved by the academic board. During active instruction, your live progress is tracked directly inside the **Performance** console.",
          },
        },
        {
          type: "paragraph",
          text: "Upon cohort graduation, your official completion certificate and transcript are distributed by the registry. If you require an interim letter of enrollment or attendance verification, message school administration through **Messages**.",
        },
      ],
      result: "You know how institutional transcripts are finalized and how course completion is formally accredited.",
      related: ["performance", "attendance", "privacy"],
    },
  ],
};
