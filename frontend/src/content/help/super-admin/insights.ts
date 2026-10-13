import type { Section } from "../types";

/** Reports, the audit trail, security and system health. */
export const insights: Section = {
  id: "insights",
  title: "Reports and oversight",
  blurb: "Figures for the institution, the record of what changed, and system health.",
  articles: [
    {
      id: "reports",
      title: "How to use reports",
      summary: "Six ready-made reports, and how to export one to a spreadsheet.",
      feature: "Reports",
      learn: ["What each report shows", "How to export a report"],
      body: [
        {
          type: "paragraph",
          text: "**Reports** are figures worked out by the system. There are six, each on its own tab.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/reports.webp",
            alt: "The Reports screen showing the Attendance, Enrollment, Performance, Coursework, Distribution and Grading queue tabs with an Export CSV button.",
            caption: "Six reports. Each has its own filters and an export button.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Attendance",
              detail:
                "Present, late, absent and excused counts per course, with an attendance rate.",
            },
            { term: "Enrollment", detail: "How many students are enrolled, and where." },
            { term: "Performance", detail: "How students are doing overall." },
            { term: "Coursework", detail: "Assignments set and handed in." },
            { term: "Distribution", detail: "How marks are spread — how many got each grade." },
            {
              term: "Grading queue",
              detail: "Work waiting to be marked. The one to check weekly.",
            },
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
            body: "Once a report is on your computer the system cannot control who sees it. Exports can contain student information, so store and share them carefully.",
          },
        },
      ],
      result: "The report appears on screen, and the export downloads as a spreadsheet file.",
      tips: [
        "Check **Grading queue** every week. It is the earliest warning that marking is slipping.",
      ],
      related: ["performance", "attendance", "gradebook"],
    },

    {
      id: "audit-log",
      title: "How to use the audit log",
      summary: "The permanent record of who changed what, and when.",
      feature: "Audit log",
      learn: ["What the audit log records", "How to find a particular change"],
      body: [
        {
          type: "paragraph",
          text: "The **Audit log** records what happened in the system: who did it, what they changed, when, and whether it worked.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/audit-log.webp",
            alt: "The Audit log screen listing entries with when, action, actor and entity, plus filters and an Export CSV button.",
            caption:
              "The audit log. Who did what, and when. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Nothing can be edited or removed",
            body: "The audit log is append-only. Entries cannot be changed or deleted by anybody — including you, and including anybody who got hold of your password. That is what makes it trustworthy.",
          },
        },
        { type: "heading", text: "Find a change" },
        {
          type: "steps",
          items: [
            { text: "Click **Audit log** in the left-hand menu." },
            { text: "Type a name or a record into the search box." },
            { text: "Narrow it with **Any action**, **Any entity** or **Any outcome**." },
            { text: "Set a date range if you know roughly when it happened." },
            { text: "Click **Details** on a row to see exactly what changed." },
          ],
        },
      ],
      result: "You can answer 'who changed this, and when?' with evidence.",
      tips: [
        "Filter by outcome to find failed attempts — they often explain a confused colleague.",
      ],
      related: ["security", "users"],
    },

    {
      id: "security",
      title: "How to deal with sign-in problems",
      summary: "Locked accounts, who is signed in now, and recent sign-in failures.",
      feature: "Security",
      learn: ["How to unlock an account", "How to see who is signed in", "Where to see failures"],
      body: [
        {
          type: "paragraph",
          text: "**Security** is for responding to a problem now: somebody cannot get in, or you are worried about an account. It is deliberately separate from the audit log, which is the whole history.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/security.webp",
            alt: "The Security screen showing the Locked accounts, Sessions and Events tabs.",
            caption:
              "Three tabs. Names and emails are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Locked accounts",
              detail:
                "Accounts locked by too many wrong passwords, with how many attempts and until when.",
            },
            { term: "Sessions", detail: "Who is signed in right now." },
            { term: "Events", detail: "Recent sign-in failures and lockouts." },
          ],
        },
        { type: "heading", text: "Unlock somebody" },
        {
          type: "steps",
          items: [
            { text: "Click **Security** in the left-hand menu." },
            { text: "Stay on **Locked accounts**." },
            { text: "Find the person and use the action on their row to unlock them." },
            {
              text: "Tell them to type their password carefully, and check Caps Lock.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Make sure it is really them",
            body: "Before unlocking an account or resetting a password, confirm you are talking to the right person. Asking to be let in is exactly what an attacker does too.",
          },
        },
      ],
      result: "The account is unlocked and the person can sign in again.",
      tips: [
        "A lockout usually clears by itself after a short time — waiting is often enough.",
        "Many failures on one account in a short period is worth investigating, not just unlocking.",
      ],
      problems: [
        {
          symptom: "You unlocked the account and they still cannot sign in.",
          fix: "Check the account is active on the **Users** screen, and that they are using the right username.",
        },
      ],
      related: ["users", "audit-log", "sign-in"],
    },

    {
      id: "operations",
      title: "How to check system health",
      summary: "Whether the system is healthy — mainly for your technical team.",
      feature: "Operations",
      learn: ["What the three tabs show", "When to look at this screen"],
      body: [
        {
          type: "paragraph",
          text: "**Operations** shows how the system itself is running. It is a technical screen. You do not need it day to day, but it is useful to look at before reporting a problem.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/operations.webp",
            alt: "The Operations screen showing the Health, Request metrics and Database tabs with a Refresh button.",
            caption: "Health, request metrics and database diagnostics.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Health", detail: "Whether the system and the things it depends on are responding." },
            { term: "Request metrics", detail: "How many requests have been handled, and how quickly." },
            { term: "Database", detail: "Diagnostics about the database." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "The figures reset when the system restarts",
            body: "These counts are since the last restart, and each server answers about itself. Low numbers after a restart are normal, not a problem.",
          },
        },
      ],
      result: "You can tell your technical team what the system reported.",
      tips: [
        "Take a screenshot of this screen before reporting a fault. It saves a round of questions.",
      ],
      related: ["sync-data"],
    },
  ],
};
