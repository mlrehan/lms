import type { Section } from "../types";

/** First steps: what the account is, how to set it up, and what the home screen means. */
export const gettingStarted: Section = {
  id: "getting-started",
  title: "Getting started",
  blurb: "What your account is for, how to set it up, and how to read your home screen.",
  articles: [
    {
      id: "welcome",
      title: "Welcome: what this account is for",
      summary:
        "What you can do here, what the words mean, and what makes your account different from an ordinary student one.",
      learn: [
        "What you use this system for",
        "The handful of words that appear everywhere",
        "Why someone at your employer may be able to see your progress",
      ],
      body: [
        {
          type: "paragraph",
          text: "This is where your course lives. You use it to see when your classes are, find the work you have been set, hand that work in, take quizzes, and see your marks.",
        },
        {
          type: "heading",
          text: "Your place was arranged for you",
        },
        {
          type: "paragraph",
          text: "You are on this course because an employer, a sponsor or a family member arranged it — you did not sign yourself up. That has one consequence worth knowing from the start: **somebody may be able to see how you are getting on.** The next section explains exactly who, what they see, and how you find out.",
        },
        {
          type: "heading",
          text: "Words you will see everywhere",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Course",
              detail: "The subject itself — what is taught, at what level, over how many hours.",
            },
            {
              term: "Batch",
              detail:
                "Your actual class: one group of people taking a course together, with its own dates, its own tutor and its own timetable. A batch has a number, and you will see that number all over the system.",
            },
            {
              term: "Session",
              detail: "One class. A batch is made of sessions.",
            },
            {
              term: "Enrollment",
              detail: "Your place on a batch.",
            },
            {
              term: "Assignment",
              detail: "A piece of work you hand in by a date.",
            },
            {
              term: "Quiz",
              detail: "A set of questions marked by the system, usually with a time limit.",
            },
            {
              term: "Examination",
              detail: "A scheduled, supervised assessment.",
            },
            {
              term: "Grade book",
              detail: "Every individual mark you have earned on a course.",
            },
            {
              term: "Transcript",
              detail: "The formal, final record of how you did, produced at the end.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "You do not need to read this in order",
            body: "Every article here stands on its own. Use the search box, or jump to whichever one matches what you are trying to do.",
          },
        },
      ],
      result: "You know what the system is for and what the main words mean.",
      related: ["dashboard", "who-can-see", "account"],
    },

    {
      id: "account",
      title: "How to set up your account",
      summary:
        "Your name, your picture, your timezone and your password — and why the timezone matters more than you would expect.",
      feature: "My account",
      learn: [
        "Where your own details live",
        "How to change your password",
        "Why your timezone affects every time you see",
      ],
      body: [
        {
          type: "paragraph",
          text: "**My account** holds everything about you: your profile, your picture, your password and your preferences.",
        },
        {
          type: "screenshot",
          image: {
            src: "managed-student/account.webp",
            alt: "The My account screen showing the profile card with username, last sign-in and account created, and a section for uploading a picture.",
            caption:
              "Your own details. Your name and address are blurred in this guide for privacy; you will see them in full.",
          },
        },
        {
          type: "heading",
          text: "Set your timezone first",
        },
        {
          type: "paragraph",
          text: "Every time in the system — class times, deadlines, when a register was taken — is stored once and then shown to you in **your** timezone. If your timezone is wrong, every time you see is wrong, and you will miss a class without ever being told anything untrue.",
        },
        {
          type: "steps",
          items: [
            { text: "Click your name at the top, then **My account**." },
            { text: "Check the timezone shown against where you actually are." },
            { text: "Correct it if it is wrong, and save." },
          ],
        },
        {
          type: "heading",
          text: "Your picture",
        },
        {
          type: "paragraph",
          text: "Upload one if you like. It appears beside your name in lists, discussions and messages. It is optional.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Keep your sign-in details to yourself",
            body: "Your account can hand work in under your name. Never share your password, and never let somebody else sign in as you — including a manager or a family member. If they need to see your progress, there is a proper way to arrange that, explained in the next section.",
          },
        },
      ],
      result: "Your details are right, and the times you see match the clock on your wall.",
      tips: [
        "If class times look an hour out after a clock change, your timezone is the first thing to check.",
      ],
      related: ["welcome", "timetable", "who-can-see"],
    },

    {
      id: "dashboard",
      title: "What your dashboard shows you",
      summary: "The home screen: your next class, what is overdue, and how your attendance looks.",
      feature: "Dashboard",
      learn: [
        "What each number on the home screen means",
        "Where to find your next class",
        "How to spot work you have missed",
      ],
      body: [
        {
          type: "paragraph",
          text: "The dashboard is the first thing you see when you sign in. It is a summary, not a separate place — everything on it also lives on a screen of its own.",
        },
        {
          type: "screenshot",
          image: {
            src: "managed-student/dashboard.webp",
            alt: "The student dashboard showing unread messages and notifications, the timezone, a Your studies panel with enrolled batches, active courses, attendance and overdue assignments, and panels for next sessions and next deadlines.",
            caption: "Your home screen. The panels you get depend on what your account can see.",
          },
        },
        {
          type: "heading",
          text: "Your studies",
        },
        {
          type: "definitions",
          items: [
            { term: "Enrolled batches", detail: "How many classes you are currently in." },
            { term: "Active courses", detail: "How many subjects you are currently taking." },
            {
              term: "Attendance",
              detail:
                "The proportion of your classes you have been marked present for. Early in a course this figure moves a long way on a single absence.",
            },
            {
              term: "Overdue assignments",
              detail:
                "Work whose due date has passed and which you have not handed in. This is the number to watch.",
            },
          ],
        },
        {
          type: "heading",
          text: "Next sessions and next deadlines",
        },
        {
          type: "paragraph",
          text: "**Next sessions** lists your upcoming classes, with a **Join class** button on any that is online. **Next deadlines** lists work due soon, and marks anything already late.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Two numbers tell you most of what you need",
            body: "**Attendance** and **Overdue assignments**. If both look healthy, you are fine. If either does not, open the screen behind it before anything else.",
          },
        },
      ],
      result: "You can tell at a glance whether anything needs doing today.",
      problems: [
        {
          symptom: "Attendance says 0% but you have been going.",
          fix: "Your tutor may not have taken the register yet for recent classes. Open **Attendance** and look at the dates before worrying.",
        },
        {
          symptom: "The dashboard looks empty.",
          fix: "Give it a moment on first load. If it stays empty, you may not be enrolled on a batch yet — ask whoever arranged your place.",
        },
      ],
      related: ["attendance", "assignments", "timetable"],
    },
  ],
};
