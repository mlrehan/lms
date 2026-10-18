import type { Section } from "../types";

/** Diagnostic workflows and enterprise escalation procedures for corporate managers. */
export const troubleshooting: Section = {
  id: "troubleshooting",
  title: "Diagnostics and Support",
  blurb: "Step-by-step problem resolution, data verification, and institutional escalation workflows.",
  articles: [
    {
      id: "common-problems",
      title: "Common problems and how to solve them",
      summary: "Step-by-step diagnostic workflows for missing employees, empty screens, and attendance discrepancies.",
      feature: "Troubleshooting",
      learn: [
        "What to check when an employee or enrollment is not visible",
        "How to reset filters and date ranges when screens appear empty",
        "How attendance and provisional performance calculations work",
        "When to triage risks directly versus contacting instructors",
      ],
      body: [
        { type: "heading", text: "1. An employee does not appear on your roster or dashboard" },
        {
          type: "paragraph",
          text: "Visibility into employees is governed by your authorized corporate organization and supervisory assignments to maintain strict data protection and confidentiality. If a team member does not appear on your dashboard or roster:",
        },
        {
          type: "steps",
          items: [
            {
              text: "Open **Manager assignments** (`/manager-links`) in the left-hand menu to review your actively assigned employees.",
            },
            {
              text: "Open **Organizations** (`/organizations`) and inspect the **Employees** tab to verify that the employee is registered under your corporate profile.",
            },
            {
              text: "If a newly hired employee is registered but not linked to you as a Line Manager, request a supervisory link assignment from your Corporate Training Coordinator.",
            },
          ],
        },

        { type: "heading", text: "2. A screen or table appears empty" },
        {
          type: "bullets",
          items: [
            "**A search filter or status chip is active.** Clear the search box and verify that status chips (e.g. All, Active, Pending) are set to display all records.",
            "**A course or batch selector is required first.** Workspaces such as **Performance**, **Assignments**, and **Quizzes** require you to select an active cohort batch from the dropdown before records display.",
            "**Date filters are excluding sessions.** On the **Timetable** (`/sessions`) or **Reports** screen, check that the start and end date pickers encompass your cohort's active term.",
            "**Data synchronization latency.** Large cohort data tables may take one to two seconds to populate upon initial page load.",
          ],
        },

        { type: "heading", text: "3. Attendance records or percentages look unexpected" },
        {
          type: "paragraph",
          text: "Session registers are updated by instructors after each scheduled class. If an attendance metric appears inaccurate:",
        },
        {
          type: "steps",
          items: [
            {
              text: "Navigate to **Attendance** (`/attendance`) in the left-hand menu.",
            },
            {
              text: "Filter the register by the specific student's name to view individual session-by-session records.",
            },
            {
              text: "Review the session status chips (**Present**, **Late**, **Absent**, or **Excused**).",
            },
            {
              text: "If an excused medical absence or authorized corporate travel was misrecorded as absent, contact the course instructor via **Messages** with the session date.",
            },
          ],
        },

        { type: "heading", text: "4. A grade or performance score appears lower than anticipated" },
        {
          type: "bullets",
          items: [
            "**Courses in progress reflect provisional Standing So Far.** Cumulative percentages are calculated based on work graded to date and adjust as remaining assessments are completed.",
            "**Unsubmitted or pending coursework.** Assignments and quizzes awaiting submission or tutor evaluation do not yet contribute points to the weighted component total.",
            "**Component breakdown weighting.** Review the **Performance** console to examine how assignments, attendance, quizzes, and exams are weighted for that specific curriculum.",
          ],
        },

        { type: "heading", text: "5. Timetable session times appear incorrect" },
        {
          type: "paragraph",
          text: "All scheduled session times are automatically converted to your configured display timezone. If session times look shifted by hours, open **Account** (`/account`) from the top-right user menu and verify that your **Timezone** preference matches your current physical location.",
        },
      ],
      result: "You can quickly isolate whether an issue is caused by active filters, pending data entry, or configuration settings.",
      tips: [
        "Use the Workforce Intervention Desk on your Dashboard to quickly identify employees requiring immediate check-ins.",
      ],
      related: ["dashboard", "my-team", "attendance", "performance", "escalations"],
    },

    {
      id: "escalations",
      title: "How to request cohort changes and enterprise support",
      summary: "Procedures for onboarding roster adjustments, bespoke cohorts, grade reviews, and support tickets.",
      feature: "Support",
      learn: [
        "How to request cohort schedule adjustments and private batches",
        "How to request roster expansions and employee additions",
        "How to resolve grade disputes and request official transcripts",
        "Who to contact for technical and billing support",
      ],
      body: [
        {
          type: "paragraph",
          text: "Your Corporate Manager portal gives you extensive self-service oversight, enrollment capabilities, and direct intervention tools. For institutional workflows that require administrative authorization, follow the structured escalation pathways below.",
        },
        {
          type: "table",
          columns: ["Operational Need", "Responsible Team", "Escalation Pathway"],
          rows: [
            [
              "New employee onboarding to roster",
              "Corporate Onboarding",
              "Use **Add employee** under **Organizations** > **Employees**, or message your Training Coordinator.",
            ],
            [
              "Private cohort or customized schedule",
              "Account Management",
              "Submit a cohort scheduling request to your Dedicated Training Account Executive.",
            ],
            [
              "Tailored corporate curriculum additions",
              "Academic Affairs",
              "Schedule a curriculum consultation to map corporate competencies into course modules.",
            ],
            [
              "Excused absence verification",
              "Lead Instructor",
              "Send an internal message with official documentation via **Messages** citing session date.",
            ],
            [
              "Final grade audit or academic appeal",
              "Academic Registry",
              "Submit a formal grade review request within 14 business days of batch completion.",
            ],
            [
              "Sealed institutional transcripts & certs",
              "Registrar's Office",
              "Formal completion certificates and sealed transcripts are issued upon batch closure.",
            ],
            [
              "Contract renewal or billing inquiries",
              "Corporate Partnerships",
              "Contact your Enterprise Billing Representative directly.",
            ],
          ],
        },
        { type: "heading", text: "Submitting an inquiry via Messages" },
        {
          type: "steps",
          items: [
            { text: "Open **Messages** from the left-hand navigation." },
            { text: "Click **Compose**." },
            {
              text: "Select your **Training Coordinator** or **Lead Instructor** as the recipient.",
            },
            {
              text: "Include the **Batch ID**, **Course Name**, and affected **Employee Name** in the subject line.",
            },
            {
              text: "State the operational request clearly and click **Send**.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Expedited request handling",
            body: "Always quote the 5-digit Batch ID (e.g. Batch 11429) and employee full name. Providing these identifiers allows the support desk to locate the cohort register immediately.",
          },
        },
      ],
      result: "Your inquiry is delivered directly to the designated department with complete audit documentation.",
      related: ["common-problems", "manager-assignments", "reports", "messages"],
    },
  ],
};
