import type { Section } from "../types";

/**
 * Enterprise-grade Corporate Manager User Guide: Getting Started
 * Verified against live running application interface.
 */
export const gettingStarted: Section = {
  id: "getting-started",
  title: "Getting started",
  blurb: "Sign in, navigate the console, and master your Workforce Command Center.",
  articles: [
    {
      id: "welcome",
      title: "Welcome — what a corporate manager account can do",
      summary:
        "Executive oversight, workforce capabilities, attendance tracking, and cohort compliance intelligence.",
      learn: [
        "What your executive account is for",
        "Key workforce capabilities available to your organization",
        "How employee rosters and data privacy governance work",
      ],
      body: [
        {
          type: "paragraph",
          text: "This guide is for **Corporate Managers**. When your company sponsors employees to undertake professional development and corporate training with our institute, your manager account provides executive oversight, operational diagnostics, and direct cohort management.",
        },
        {
          type: "paragraph",
          text: "The portal is designed for non-technical business managers, department heads, and HR leaders. Every workflow is straightforward, secure, and accompanied by exact instructions.",
        },
        { type: "heading", text: "Executive Workforce Capabilities" },
        {
          type: "definitions",
          items: [
            {
              term: "Workforce Performance Intelligence",
              detail:
                "Real-time monitoring of session attendance velocity, deliverable submissions, examination scores, and overall cohort progression across all sponsored staff.",
            },
            {
              term: "At-Risk Early Warning Radar",
              detail:
                "Instant identification of team members experiencing attendance dips, missing coursework, or at risk of failing to meet certification thresholds.",
            },
            {
              term: "Direct Team Batch Enrollment",
              detail:
                "Self-service enrollment of authorized employees into active training cohorts directly from batch workspaces.",
            },
            {
              term: "One-Click Executive CSV Audit Exports",
              detail:
                "Instant generation of structured compliance spreadsheets for HR leadership, executive reporting, and billing audits.",
            },
            {
              term: "Care-Circle Direct Messaging",
              detail:
                "Secure, integrated communication with course instructors, institutional administrators, and enrolled staff without exposing personal email addresses.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Enterprise Roster Scope & Governance",
            body: "To uphold stringent data privacy standards, your portal displays only the sponsored employees assigned to your supervisory team. If additional staff require training or join your department, your dedicated Corporate Training Coordinator can update your roster immediately.",
          },
        },
      ],
      tips: [
        "Begin each week at the **Dashboard** for a consolidated view of workforce capability and at-risk alerts.",
        "Use **My team** when you want an individual employee's detailed attendance, coursework, and score trajectory.",
      ],
      related: ["sign-in", "dashboard", "sidebar", "account"],
    },

    {
      id: "sign-in",
      title: "How to sign in",
      summary: "Access the LMS console with your corporate manager credentials.",
      feature: "Sign in",
      learn: [
        "How to authenticate into the LMS console",
        "Password troubleshooting and account recovery",
      ],
      before: [
        "The web portal address (`http://localhost:3000` or production URL).",
        "Your authorized corporate email address.",
        "Your secure password.",
      ],
      body: [
        {
          type: "steps",
          items: [
            { text: "Open your web browser (Chrome, Firefox, Edge, or Safari)." },
            { text: "Navigate to the LMS sign-in address." },
            { text: "In the **Username or email** field, enter your corporate email address." },
            { text: "In the **Password** field, enter your password." },
            { text: "Click **Sign in**." },
          ],
        },
      ],
      result: "Your Workforce Command Center opens, displaying real-time metrics and your account initials in the top right corner.",
      tips: [
        "Passwords are case-sensitive. Verify Caps Lock is disabled before typing.",
        "If your organization uses single sign-on or corporate password policies, contact your training coordinator for assistance.",
      ],
      problems: [
        {
          symptom: "Authentication failed error appears.",
          fix: "Retype your credentials carefully. If problems persist, request a password reset through your training coordinator.",
        },
        {
          symptom: "Account temporarily locked notification.",
          fix: "Multiple incorrect attempts trigger a security lock. Wait 10 minutes or contact administrative support.",
        },
      ],
      related: ["dashboard", "account"],
    },

    {
      id: "dashboard",
      title: "Understanding your dashboard",
      summary: "Your executive Workforce Command Center: capability metrics, compliance, and triage.",
      feature: "Dashboard",
      learn: [
        "How to interpret the Workforce Health Index and status badges",
        "What the six Workforce Training KPI cards measure",
        "How to use the Workforce Intervention Desk and Nudge actions",
        "How to download the Workforce Training Audit CSV spreadsheet",
        "How to monitor active training programs and live sessions",
      ],
      body: [
        {
          type: "paragraph",
          text: "Your dashboard is your **Workforce Command Center**. It aggregates live telemetry across all sponsored employees, tracking cohort compliance, attendance velocity, and coursework completion in real time.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/dashboard.webp",
            alt: "Corporate Manager Workforce Command Center showing executive health index, KPI cards, Workforce Intervention Desk with nudge action, active cohorts, and communication metrics.",
            caption:
              "Corporate Manager Workforce Command Center. Real-time telemetry, attendance velocity, and direct triage interventions. Sensitive corporate details are blurred for privacy.",
          },
        },
        { type: "heading", text: "1. Enterprise Hero Command Bar" },
        {
          type: "definitions",
          items: [
            {
              term: "Organization & Portal Identity",
              detail:
                "Displays your company name, enterprise account code, and the Enterprise Workforce Portal designation.",
            },
            {
              term: "Health Index Badge",
              detail:
                "A dynamic composite metric (0–100) reflecting overall training health. Color-coded status includes Healthy (green), Monitor Attention (amber), or Critical Action (red).",
            },
            {
              term: "Export Audit (CSV)",
              detail:
                "One-click export generating a comprehensive spreadsheet with employee names, attendance rates, session totals, overdue deliverables, risk levels, and enrolled courses.",
            },
            {
              term: "Quick Action Toolbar",
              detail:
                "Direct navigational shortcuts to **Team Directory**, **Course Catalog**, and internal **Messages**.",
            },
          ],
        },
        { type: "heading", text: "2. Workforce Training KPIs & Compliance" },
        {
          type: "definitions",
          items: [
            {
              term: "WORKFORCE SIZE",
              detail:
                "Total number of sponsored employees in your supervisory roster, alongside the percentage of active employees.",
            },
            {
              term: "IN-FLIGHT SEATS",
              detail:
                "Total active cohort seats currently occupied by your staff across all running courses.",
            },
            {
              term: "TEAM ATTENDANCE",
              detail:
                "Aggregate session attendance rate across all enrolled staff, evaluated against the 75.0% enterprise attendance benchmark.",
            },
            {
              term: "OVERDUE WORK",
              detail:
                "Total pending coursework deliverables that have passed their submission deadlines without submission.",
            },
            {
              term: "AT-RISK LEARNERS",
              detail:
                "Count of staff members currently flagged for critical absences, low attendance, or overdue assignments.",
            },
            {
              term: "TRAINING HEALTH",
              detail:
                "Overall health score out of 100 with immediate operational recommendation (e.g. Critical Action, Attention, On Track).",
            },
          ],
        },
        { type: "heading", text: "3. Workforce Intervention Desk" },
        {
          type: "paragraph",
          text: "The **Workforce Intervention Desk** is your operational triage console. It highlights employees who require immediate managerial follow-up due to zero attendance, attendance velocity dips, or overdue deliverables.",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Triage Filter Tabs",
              detail:
                "Switch between **All Flagged**, **Critical Absences**, **Low Attendance**, and **Overdue Work** to prioritize interventions.",
            },
            {
              term: "Search Console",
              detail: "Filter learners instantly by name, email, or enrolled course title.",
            },
            {
              term: "Nudge Displayed",
              detail:
                "Triggers an email reminder alert to all currently filtered learners, prompting them to connect with instructors and submit deliverables.",
            },
            {
              term: "Attendance Velocity Bar",
              detail:
                "Visual progress bar illustrating attended sessions versus total scheduled classes to date.",
            },
            {
              term: "Direct Intervention (Nudge)",
              detail:
                "Initiates a pre-formatted, professional managerial check-in directly to the individual employee.",
            },
          ],
        },
        { type: "heading", text: "4. Cohorts, Sessions & Communications" },
        {
          type: "definitions",
          items: [
            {
              term: "Active Workforce Training Programs",
              detail:
                "Shows active course batches, cohort identifiers, lead instructors, and enrolled employee counts.",
            },
            {
              term: "Next Scheduled Live Sessions",
              detail:
                "Displays upcoming live classes, start times, and direct class join links for your team.",
            },
            {
              term: "Manager Workspace & Communications",
              detail:
                "Telemetry cards tracking unread messages, unread alerts, published announcements, and your localized display timezone.",
            },
          ],
        },
      ],
      result: "You have comprehensive operational command over your team's learning progression and risk mitigation.",
      tips: [
        "Use **Export Audit (CSV)** at month-end to generate executive reports for senior leadership.",
        "Act on **Critical Zero Attendance** alerts early in the cohort before employees fall behind permanently.",
      ],
      related: ["sidebar", "my-team", "attendance", "reports"],
    },

    {
      id: "sidebar",
      title: "Understanding the left-hand menu",
      summary: "Navigate every module and workspace accessible to your corporate manager account.",
      feature: "Navigation",
      learn: [
        "How the navigation sidebar is structured",
        "What each workspace section contains",
      ],
      body: [
        {
          type: "paragraph",
          text: "The left-hand sidebar is your primary navigation menu. It provides direct access to every administrative and monitoring workspace authorized for your role.",
        },
        {
          type: "table",
          columns: ["Group", "Included Workspaces", "Operational Purpose"],
          rows: [
            [
              "Overview",
              "Dashboard",
              "Workforce Command Center, 6 KPIs, Intervention Desk, and quick audit exports.",
            ],
            [
              "Learning",
              "Courses, Batches, Timetable, Enrollments, Attendance",
              "Inspect course catalog, view class cohorts, check timetable sessions, verify enrollments, and audit attendance.",
            ],
            [
              "Assessment",
              "Assignments, Quizzes, Examinations, Performance",
              "Track coursework deliverables, review quiz setups, check exam timetables, and evaluate weighted batch performance.",
            ],
            [
              "Content",
              "Shared with me",
              "Curriculum documents, syllabi, and reports shared directly with your account.",
            ],
            [
              "Community",
              "Announcements, Discussions, Messages, Notifications",
              "Institutional broadcasts, academic forums, Care-Circle messaging, and notification feed.",
            ],
            [
              "People",
              "My team, Organizations, Manager assignments",
              "Workforce roster console, corporate entity profile, employee onboarding, and supervisory links.",
            ],
            [
              "Insights",
              "Reports",
              "Six specialized analytical reports with date/cohort filters and CSV data exports.",
            ],
            [
              "Help",
              "Corporate Manager Guide",
              "Comprehensive documentation, workflows, interface walkthroughs, and operational best practices.",
            ],
          ],
        },
      ],
      result: "You can seamlessly navigate between oversight, monitoring, enrollment, and communication workspaces.",
      related: ["dashboard", "my-team", "batches", "reports"],
    },

    {
      id: "account",
      title: "How to update your profile and password",
      summary: "Manage your display timezone, profile details, and account credentials.",
      feature: "Account",
      learn: [
        "How to configure your display timezone",
        "How to update your profile details and password",
      ],
      body: [
        {
          type: "paragraph",
          text: "Your **Account** workspace allows you to configure your local display preferences and maintain credential security.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/account.webp",
            alt: "Corporate manager account settings screen showing profile details, timezone preference, and password update form.",
            caption: "Account settings. Personal details are blurred for privacy.",
          },
        },
        { type: "heading", text: "Updating your timezone" },
        {
          type: "steps",
          items: [
            { text: "Open your profile menu in the top-right corner and select **Account**." },
            { text: "Locate the **Timezone** preference selector." },
            { text: "Select your local operational timezone (e.g. Europe/London, Asia/Dhaka, America/New_York)." },
            { text: "Save your preferences. All timetable and session times automatically format to your local clock." },
          ],
        },
        { type: "heading", text: "Changing your password" },
        {
          type: "steps",
          items: [
            { text: "In the **Security** section, enter your **Current password**." },
            { text: "Enter your **New password** adhering to enterprise complexity standards." },
            { text: "Confirm your new password and click **Update password**." },
          ],
        },
      ],
      result: "Your schedule accurately reflects your local time, and your account credentials remain secure.",
      related: ["dashboard", "sign-in"],
    },
  ],
};
