import type { Section } from "../types";

/** Attendance, marks, overall standing and the final record. */
export const yourProgress: Section = {
  id: "your-progress",
  title: "How you are getting on",
  blurb: "Your attendance, your marks, your overall standing, and the record you get at the end.",
  articles: [
    {
      id: "attendance",
      title: "How to check your attendance",
      summary: "Every class, what you were marked, and who marked it.",
      feature: "Attendance",
      learn: [
        "How to see your attendance class by class",
        "What each status means",
        "What to do if one is wrong",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Attendance** shows the registers that concern you: one row per class, with what you were marked and when it was recorded.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/attendance.webp",
            alt: "The Attendance screen listing three sessions with columns for session time, batch, student, status, remarks and when the register was recorded.",
            caption:
              "Your own registers. The student column and the tutor's name are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Present", detail: "You were there, on time." },
            { term: "Late", detail: "You were there, after the class started." },
            {
              term: "Absent",
              detail: "You were not there, and it had not been agreed beforehand.",
            },
            { term: "Excused", detail: "You were not there, and it had been agreed beforehand." },
            {
              term: "Remarks",
              detail: "Anything the tutor added. A dash means nothing was added.",
            },
            { term: "Recorded", detail: "When the register was taken, and by which tutor." },
          ],
        },
        { type: "heading", text: "If a mark is wrong" },
        {
          type: "paragraph",
          text: "You cannot change a register — it is your tutor's record of who was in the class. If you were there and are marked absent, or an absence was agreed in advance and is not marked excused, message your tutor and say which class you mean.",
        },
        {
          type: "steps",
          items: [
            { text: "Click **Attendance** in the left-hand menu." },
            { text: "Use **Status** to show only absences if the list is long." },
            { text: "Note the session date and the batch number." },
            { text: "Message your tutor with both." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Attendance can count towards your result",
            body: "On some courses it is a graded component in its own right — you will see it as a row in your **Grade book** if so. It is worth keeping an eye on even when the course is going well.",
          },
        },
      ],
      result: "You know exactly which classes you have been marked present for.",
      tips: [
        "Check this after a class you joined late or left early — those are the ones most likely to be recorded differently from how you remember them.",
      ],
      problems: [
        {
          symptom: "A recent class is not listed.",
          fix: "The register may not have been taken yet. It is recorded after the class, sometimes a day or two later.",
        },
        {
          symptom: "Your percentage looks worse than you expected.",
          fix: "Early in a course one absence moves the figure a long way. Count the actual rows before worrying.",
        },
      ],
      related: ["grades", "timetable", "messages"],
    },

    {
      id: "grades",
      title: "How to see your marks",
      summary:
        "Every individual mark, what each is worth, and the scale that turns them into a grade.",
      feature: "Grade book",
      learn: [
        "Where your individual marks live",
        "What 'weight' means and why it matters",
        "How a percentage becomes a letter grade",
      ],
      before: ["Choose a **Batch** at the top — the screen is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "The **Grade book** holds one row for every mark you have earned on a course: each assignment, each quiz, attendance, practical work and the final exam.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/gradebook-batch.webp",
            alt: "The grade book Entries tab with a batch selected, showing components with their score out of the maximum, a percentage, a weight and when each was recorded.",
            caption:
              "Each mark, with what it is worth. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Entries",
              detail:
                "One row per mark: what it was, your score, its weight and when it was recorded.",
            },
            {
              term: "Student standing",
              detail: "Your overall position, worked out from those entries.",
            },
            {
              term: "Grading scale",
              detail:
                "The bands the school uses to turn a percentage into a letter grade and GPA points.",
            },
          ],
        },
        { type: "heading", text: "Weight is the column people misread" },
        {
          type: "paragraph",
          text: "**Weight** says how much a piece counts towards your final result. A low mark on something lightly weighted moves your overall figure far less than you would fear — and a high mark on it helps less than you would hope. Look at the weight before drawing a conclusion from any single row.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Use the component filter",
            body: "The **Every component** control at the top narrows the list to just assignments, or just quizzes, which is easier to read than everything at once.",
          },
        },
      ],
      result: "You can see every mark you have earned and what each contributes.",
      problems: [
        {
          symptom: "The grade book is empty.",
          fix: "Choose a **Batch** at the top. Nothing shows until you do.",
        },
        {
          symptom: "A piece of work has no mark.",
          fix: "It has not been marked yet, or the mark has not been published. Both are normal part-way through a course.",
        },
      ],
      related: ["performance", "submit", "transcripts"],
    },

    {
      id: "performance",
      title: "How to see your overall result",
      summary: "Your current percentage and grade, and the arithmetic behind it.",
      feature: "Performance",
      learn: [
        "Where your overall standing is",
        "What 'so far incomplete' means",
        "Why you see only your own row",
      ],
      before: ["Choose a **Batch** — the screen is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "**Performance** shows your weighted standing on a course: one percentage, one grade, and the working behind it.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/performance-batch.webp",
            alt: "The Performance screen for a batch showing a single student row with a percentage, a status of so far incomplete and a letter grade.",
            caption:
              "Your standing on the course. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Performance** in the left-hand menu." },
            { text: "Choose your **Batch**." },
            {
              text: "Click your row to open it.",
              note: "This is the useful part: every component, its weight, and what it actually contributed.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "What 'so far incomplete' means",
            body: "Your course is not finished. The percentage is out of the work assessed so far, so it will move — often a lot — as more is marked. A low figure early on usually means unmarked work, not a bad result.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "You see only yourself",
            body: "Even though this screen is organised by class group, your account shows only your own standing. Your classmates' results are never shown to you, and yours are not shown to them.",
          },
        },
      ],
      result: "You understand where your overall figure comes from.",
      tips: [
        "Open your row before worrying about the headline number. One unmarked piece of work can explain the whole gap.",
      ],
      problems: [
        {
          symptom: "The screen stays empty.",
          fix: "No batch is chosen, or no marks have been recorded yet.",
        },
      ],
      related: ["grades", "transcripts", "privacy"],
    },

    {
      id: "transcripts",
      title: "What a transcript is, and when you get one",
      summary: "The formal record of how you did, produced at the end of a course.",
      feature: "Transcripts",
      learn: ["What a transcript is", "When it appears", "Why yours may be empty"],
      body: [
        {
          type: "paragraph",
          text: "A **transcript** is the formal, final record of how you did on a course — your marks brought together into a GPA and an overall result. It is the document to ask for if you need to show somebody what you achieved.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/transcripts.webp",
            alt: "The Transcripts screen with columns for student, batch, GPA, overall result, when it was generated and its state, showing no transcripts yet.",
            caption: "'No transcripts yet' is the normal view part-way through a course.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Transcripts come at the end",
            body: "The school produces your transcript once the course has finished and the marking is complete, and then **finalises** it. It appears here only after that last step — before then it is a draft that only staff can see. An empty screen during a course, or shortly after it ends, is expected rather than a fault.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "GPA", detail: "Your grade points, averaged." },
            { term: "Overall", detail: "Your final percentage." },
            { term: "Generated", detail: "When the record was produced." },
            {
              term: "State",
              detail:
                "Whether it is a draft or finalised. A finalised transcript is not changed by later regeneration.",
            },
          ],
        },
      ],
      result: "You know what a transcript is and when to expect yours.",
      problems: [
        {
          symptom: "Your course has finished and there is still no transcript.",
          fix: "They are generated by the school, not automatically. Message the office and ask.",
        },
      ],
      related: ["grades", "performance", "messages"],
    },
  ],
};
