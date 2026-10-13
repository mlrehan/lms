import type { Section } from "../types";

/** The course, the timetable, the work set, and the marks given. */
export const theirLearning: Section = {
  id: "their-learning",
  title: "Their course and their work",
  blurb: "The course they are on, when classes are, the work they are set, and their marks.",
  articles: [
    {
      id: "timetable",
      title: "How to see when their classes are",
      summary: "Their classes in order, in your own timezone.",
      feature: "Timetable",
      learn: ["How to read the timetable", "How to look at a particular week"],
      body: [
        {
          type: "paragraph",
          text: "The **Timetable** lists their classes, earliest first. Times are shown in your own timezone, which is written at the top of the screen.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/timetable.webp",
            alt: "The Timetable screen listing classes with start and end times, length and where they are held.",
            caption:
              "Classes in order. This list shows times only — open a class to see its course and tutor.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Timetable** in the left-hand menu." },
            { text: "Use **From** and **To** to look at a particular week." },
            { text: "Read **Where** to see whether it is online or in a room." },
          ],
        },
      ],
      result: "You know when they are expected in class.",
      tips: [
        "Leave the date boxes empty to see everything, including classes already finished.",
      ],
      problems: [
        {
          symptom: "The timetable looks empty.",
          fix: "A date filter is probably still set. Clear **From** and **To**.",
        },
        { symptom: "The times look wrong.", fix: "Check your timezone on **My account**." },
      ],
      related: ["attendance", "course", "account"],
    },

    {
      id: "course",
      title: "How to see what they are studying",
      summary: "The course they are on, the class group, and their place on it.",
      feature: "Courses, Batches, Enrollments",
      learn: [
        "Where to see the course they are taking",
        "What a batch is",
        "How to check their place is confirmed",
      ],
      body: [
        {
          type: "paragraph",
          text: "Three screens together tell you what they are studying.",
        },
        { type: "heading", text: "Courses" },
        {
          type: "paragraph",
          text: "**Courses** is the whole catalogue of subjects the school offers, with its level and length. It is useful for seeing what a course involves, and what else is available.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/courses.webp",
            alt: "The Courses screen listing courses with status, level and hours.",
            caption: "The catalogue. Use the filters to narrow a long list.",
          },
        },
        { type: "heading", text: "Batches" },
        {
          type: "paragraph",
          text: "A **batch** is one group of students taking a course together, with its own start and end dates and its own timetable. It is the group your person is actually in.",
        },
        { type: "heading", text: "Enrollments" },
        {
          type: "paragraph",
          text: "**Enrollments** shows their place on a class group and whether it is confirmed.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/enrollments.webp",
            alt: "The Enrollments screen showing the student, their batch, status and the date they enrolled.",
            caption:
              "Their place on a class group. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "You cannot enrol anybody or change a place. If something looks wrong, message the school.",
          },
        },
      ],
      result: "You know exactly what they are taking and that their place is confirmed.",
      related: ["timetable", "work", "messages"],
    },

    {
      id: "work",
      title: "How to see the work they are set",
      summary: "Assignments, quizzes and examinations, and when they are due.",
      feature: "Assignments, Quizzes, Examinations",
      learn: [
        "Where to see work that has been set",
        "How to spot something overdue",
        "What the three kinds of work are",
      ],
      body: [
        {
          type: "paragraph",
          text: "Three screens show what the school has asked them to do.",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Assignments",
              detail:
                "Work to hand in by a date. The list shows the title, when it is due, what kind it is, whether late work is accepted, and what it is marked out of.",
            },
            {
              term: "Quizzes",
              detail:
                "Question sets marked automatically. You can see how long they have, how many attempts are allowed, and the pass mark.",
            },
            {
              term: "Examinations",
              detail:
                "Scheduled assessments, with when and where, how long, and the total and passing marks.",
            },
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/assignments.webp",
            alt: "The Assignments screen listing work with its due date, type, whether late work is accepted and the maximum score.",
            caption:
              "Work that has been set. A due date in the past with nothing handed in is what counts as overdue.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/examinations.webp",
            alt: "The Examinations screen showing an examination with its type, date, marks and whether the schedule is published.",
            caption:
              "Examinations. The **Schedule** column says whether the date has been released.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "The quickest check",
            body: "**Overdue assignments** on your dashboard and on **My team** counts this for you. You do not have to read down the list to spot missing work.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "You cannot hand work in",
            body: "Only the student can submit their own work. Your account has no way to do it for them, which is deliberate.",
          },
        },
      ],
      result: "You know what has been set and what is still outstanding.",
      tips: [
        "An examination whose schedule is not published yet simply has not been announced. The date will appear when the school releases it.",
      ],
      related: ["grades", "my-team", "course"],
    },

    {
      id: "grades",
      title: "How to see their marks",
      summary: "Every mark they have earned, and the final record for a course.",
      feature: "Grade book, Transcripts",
      learn: [
        "Where to see individual marks",
        "What the grading scale is",
        "What a transcript is",
      ],
      before: ["On the grade book, choose a **Batch** — it is empty until you do."],
      body: [
        { type: "heading", text: "Grade book" },
        {
          type: "paragraph",
          text: "The **Grade book** holds one row for every mark they have earned on a course: each assignment, quiz, the final exam, attendance and practical work.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/gradebook-batch.webp",
            alt: "The grade book Entries tab with a batch chosen, showing each component, its score, weight and when it was recorded.",
            caption:
              "Each mark, with what it is worth. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Entries",
              detail: "One row per mark, with the score, the weight and when it was recorded.",
            },
            {
              term: "Student standing",
              detail: "Their overall position, worked out from those entries.",
            },
            {
              term: "Grading scale",
              detail:
                "The bands the school uses to turn a percentage into a letter grade and GPA points.",
            },
          ],
        },
        {
          type: "paragraph",
          text: "The **weight** column is worth understanding: it says how much that piece counts towards the final result. A high mark on something with a small weight moves the overall figure less than you might expect.",
        },
        { type: "heading", text: "Transcripts" },
        {
          type: "paragraph",
          text: "A **transcript** is the formal, final record of how they did on a course — their marks brought together and turned into a grade.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/transcripts.webp",
            alt: "The Transcripts screen with columns for student, batch, GPA, overall, generated date and state.",
            caption: "Transcripts appear once the school generates them.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Transcripts appear at the end",
            body: "The school generates them once a course has finished and all the marking is done. 'No transcripts yet' part-way through a course is completely normal.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A mark you disagree with is a conversation",
            body: "You cannot change a mark, and should not expect to. If one looks wrong, message the school. There is a proper process for questioning a mark.",
          },
        },
      ],
      result: "You can see every mark, and how it contributes to the overall result.",
      tips: [
        "Look at **weight** before worrying about a single low mark. Not everything counts equally.",
      ],
      problems: [
        {
          symptom: "The grade book is empty.",
          fix: "Choose a **Batch** at the top. Nothing shows until you do.",
        },
        {
          symptom: "A piece of work has no mark.",
          fix: "It has not been marked yet. Marks appear as the tutor works through them.",
        },
      ],
      related: ["performance", "work", "messages"],
    },
  ],
};
