import type { Section } from "../types";

/** What you are studying, which group you are in, and when your classes are. */
export const yourCourse: Section = {
  id: "your-course",
  title: "Your course and your classes",
  blurb: "What you are studying, which group you are in, and when you need to be there.",
  articles: [
    {
      id: "course",
      title: "What you are studying, and where to find it",
      summary: "The difference between a course and a batch, and why the batch number matters.",
      feature: "Courses, Batches",
      learn: [
        "The difference between a course and a batch",
        "How to find your own class group",
        "What the batch details tell you",
      ],
      body: [
        {
          type: "paragraph",
          text: "Two screens describe what you are taking, and the difference between them is worth getting straight early.",
        },
        { type: "heading", text: "Courses — the subject" },
        {
          type: "paragraph",
          text: "**Courses** is the catalogue of subjects the school teaches. Each one has a level and a number of hours. It describes the subject, not your class.",
        },
        {
          type: "screenshot",
          image: {
            src: "managed-student/courses.webp",
            alt: "The Courses screen listing courses with columns for course, status, level and hours, and filters for status, level and category.",
            caption: "The catalogue. Use the filters at the top to narrow a long list.",
          },
        },
        { type: "heading", text: "Batches — your actual class" },
        {
          type: "paragraph",
          text: "A **batch** is one group of people taking a course together. It has its own tutor, its own start and end dates, its own timetable, and a number. That number is your class, and you will see it on your attendance, your grade book and your timetable.",
        },
        {
          type: "screenshot",
          image: {
            src: "managed-student/batches.webp",
            alt: "The Batches screen showing one batch with its number, course, tutor, weekly schedule, dates, delivery method, session count, enrolled numbers and state.",
            caption:
              "Your class group. The tutor's name is blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Batch", detail: "The number that identifies your class group." },
            { term: "Tutor", detail: "Who teaches it." },
            { term: "Schedule", detail: "Which days it runs, and how long each class is." },
            { term: "Dates", detail: "When the course starts and finishes." },
            {
              term: "Method",
              detail: "Whether it is online — and on which platform — or in a room.",
            },
            { term: "Sessions", detail: "How many classes there are, and when the next one is." },
            { term: "Enrolled", detail: "How many people are in the group, out of the places available." },
            { term: "State", detail: "Whether the group is active, finished or not yet started." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Open a batch by clicking its row",
            body: "The batch number is not a link — click anywhere on the row to open it. Inside you will find its sessions and its timetable.",
          },
        },
      ],
      result: "You know your batch number, who teaches it, and when it runs.",
      tips: ["Make a note of your batch number. Several screens ask you to choose it."],
      problems: [
        {
          symptom: "No batch is listed.",
          fix: "You may not have been enrolled yet. Ask whoever arranged your place on the course.",
        },
      ],
      related: ["timetable", "join-class", "performance"],
    },

    {
      id: "timetable",
      title: "How to see when your classes are",
      summary: "Every class in order, in your own timezone, with the finished ones marked.",
      feature: "Timetable",
      learn: [
        "How to read the timetable",
        "How to look at a particular week",
        "Why the times are in your timezone",
      ],
      body: [
        {
          type: "paragraph",
          text: "The **Timetable** lists your classes, earliest first. The timezone they are shown in is written at the top of the screen.",
        },
        {
          type: "screenshot",
          image: {
            src: "managed-student/timetable.webp",
            alt: "The Timetable screen listing sessions with columns for start time, end time, length in minutes and where the class is held, with From, To and Batch filters above.",
            caption:
              "Classes in order. Finished ones say 'Class has ended' instead of offering a join button.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Starts / Ends", detail: "When the class runs, in your timezone." },
            { term: "Minutes", detail: "How long it lasts." },
            {
              term: "Where",
              detail:
                "Online and on which platform, or the room. A class already finished says 'Class has ended' here.",
            },
          ],
        },
        {
          type: "steps",
          items: [
            { text: "Click **Timetable** in the left-hand menu." },
            { text: "Use **From** and **To** to look at a particular week." },
            { text: "Use **Batch** if you are taking more than one course." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "This list shows times only",
            body: "It deliberately does not repeat the course and tutor on every row. Open a session to see those.",
          },
        },
      ],
      result: "You know when you are expected in class.",
      tips: [
        "Leave the date boxes empty to see everything, including classes that have already happened.",
      ],
      problems: [
        {
          symptom: "The timetable looks empty.",
          fix: "A date filter is probably still set from last time. Clear **From** and **To**.",
        },
        {
          symptom: "The times look an hour out.",
          fix: "Check your timezone on **My account**. Every time here is converted into it.",
        },
      ],
      related: ["join-class", "attendance", "account"],
    },

    {
      id: "join-class",
      title: "How to join an online class",
      summary: "Where the join button is, and what to do when it is not there.",
      feature: "Dashboard, Timetable",
      learn: ["Where to find the join button", "When it appears", "What to do if it is missing"],
      body: [
        {
          type: "paragraph",
          text: "If your class is online, the system gives you a **Join class** button. You do not need a link sent to you separately.",
        },
        {
          type: "steps",
          items: [
            {
              text: "Look at **Next sessions** on your dashboard, or open the **Timetable**.",
            },
            { text: "Find the class that is starting." },
            { text: "Click **Join class**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Join from the dashboard",
            body: "Your next class appears on the home screen with its join button right there. It is the quickest route, and the one to use if you are in a hurry.",
          },
        },
        {
          type: "heading",
          text: "If there is no join button",
        },
        {
          type: "bullets",
          items: [
            "**The class has already ended.** The **Where** column says so instead of offering a button.",
            "**The class is not online.** It is held in a room, and the room is named instead.",
            "**The tutor has not added the link yet.** It can appear close to the start time.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Being there is recorded separately",
            body: "Joining the call does not mark you present. Your tutor takes the register, and it may be some time after the class. See **How to check your attendance**.",
          },
        },
      ],
      result: "You are in the class.",
      problems: [
        {
          symptom: "The button does nothing, or the link does not open.",
          fix: "Message your tutor — the link may be wrong or not yet set. Do not wait in silence; say something while the class is still running.",
        },
      ],
      related: ["timetable", "attendance", "messages"],
    },
  ],
};
