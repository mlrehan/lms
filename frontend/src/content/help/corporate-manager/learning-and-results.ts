import type { Section } from "../types";

/**
 * Enterprise-grade Corporate Manager User Guide: Learning and Results
 * Verified against live running application interface.
 */
export const learningAndResults: Section = {
  id: "learning-and-results",
  title: "Courses, classes and results",
  blurb:
    "Explore course offerings, manage cohort enrollments, verify attendance, and evaluate performance analytics.",
  articles: [
    {
      id: "courses",
      title: "How to browse the course catalog",
      summary: "Explore available courses, syllabus structures, and training modalities.",
      feature: "Courses",
      learn: [
        "How to search and filter the course catalog",
        "What course lifecycle statuses indicate",
        "How to request bespoke corporate training tracks",
      ],
      body: [
        {
          type: "paragraph",
          text: "The **Courses** workspace displays the comprehensive academic and vocational curriculum offered by our institute. You can review available courses, instructional levels, and durations to plan upskilling tracks for your team.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/courses.webp",
            alt: "Course catalog interface displaying course cards, status filters, search input, and level badges.",
            caption:
              "Course catalog workspace with multi-attribute filtering (Status, Level, Category).",
          },
        },
        { type: "heading", text: "Course Lifecycle Statuses" },
        {
          type: "table",
          columns: ["Status", "Operational Definition"],
          rows: [
            ["Published", "Course syllabus is complete, certified, and actively accepting cohort enrollments."],
            ["Running", "Instructional classes and cohort sessions are actively underway."],
            ["Completed", "Cohort teaching has concluded and final assessments are marked."],
            ["Draft", "Curriculum is currently undergoing instructional design or quality review."],
            ["Archived", "Historical course retired from active scheduling but preserved for transcript audits."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Bespoke Corporate Programs & Tailored Curriculum",
            body: "If your organization requires customized corporate syllabi, industry-specific modules, or private company cohorts, collaborate with your dedicated Corporate Training Account Manager to design a tailored curriculum.",
          },
        },
      ],
      result: "You can identify suitable courses and plan enrollment pathways for your employees.",
      related: ["batches", "enrollments", "timetable"],
    },

    {
      id: "batches",
      title: "How to inspect class cohorts and enroll team members",
      summary:
        "Open cohort workspaces, inspect schedules, and enroll staff into training batches.",
      feature: "Batches",
      learn: [
        "What constitutes a training batch or cohort",
        "How to navigate cohort workspaces (Overview, Sessions, Enrollments)",
        "How to directly enroll an authorized employee into a live batch",
      ],
      before: [
        "The employee must be registered in your company roster under Organizations.",
        "The cohort must be active and have available seat capacity.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **Batch** represents an active cohort of learners taking a specific course together under a shared calendar and instructional team. As a corporate manager, you have full visibility into the cohorts your staff are attending.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/batches.webp",
            alt: "Batches workspace displaying cohort codes, schedules, tutors, seat counts, and integrated session calendar.",
            caption: "Active training cohorts table and scheduled session calendar.",
          },
        },
        { type: "heading", text: "Cohort Workspace Navigation" },
        {
          type: "steps",
          items: [
            { text: "Select **Batches** from the left-hand navigation menu." },
            {
              text: "Click the **Row actions (...)** menu or click directly on a batch row to open its detailed workspace.",
            },
          ],
        },
        {
          type: "paragraph",
          text: "Each cohort workspace is organized into three operational tabs: **Overview** (course details and capacity), **Sessions** (complete timetable with class dates and classrooms), and **Enrollments** (registered learners and standing).",
        },
        { type: "heading", text: "Enrolling an Employee into a Cohort" },
        {
          type: "paragraph",
          text: "Corporate managers possess direct self-service enrollment authority to assign team members to active cohorts.",
        },
        {
          type: "steps",
          items: [
            { text: "Open the desired batch workspace and select the **Enrollments** tab." },
            { text: "Click the **Enroll** button in the upper-right actions bar." },
            {
              text: "The **Enroll a student** modal appears, confirming the target cohort and course.",
              image: {
                src: "corporate-manager/dialog-enroll.webp",
                alt: "Enroll a student dialog showing cohort name, student selector dropdown, and confirmation toggle.",
                caption:
                  "Enroll a student dialog. Review cohort details and select the team member to enroll.",
              },
            },
            {
              text: "Select the employee from the **Student** picker.",
            },
            {
              text: "Leave **Confirm immediately** toggled on for immediate placement, or toggle off to create a pending reservation.",
            },
            { text: "Click **Enroll student** to complete the registration." },
          ],
        },
      ],
      result: "The employee is immediately enrolled, appearing in the batch roster and populating into your command center.",
      tips: [
        "If a team member does not appear in the Student list, ensure they are registered under your organization's **Employees** tab first.",
      ],
      related: ["enrollments", "timetable", "my-team", "courses"],
    },

    {
      id: "enrollments",
      title: "How to verify team enrollments",
      summary: "Audit employee cohort registrations, seat statuses, and enrollment dates.",
      feature: "Enrollments",
      learn: [
        "How to audit all employee registrations in one register",
        "How to filter by batch, employee, and confirmation status",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Enrollments** serves as your centralized register of all active and historical seats held by your sponsored workforce across every course cohort.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/enrollments.webp",
            alt: "Enrollments register showing student names, batch codes, confirmation status, and enrolled timestamps.",
            caption:
              "Workforce enrollments register. Employee names are blurred for privacy.",
          },
        },
        { type: "heading", text: "Filtering and Verifying Registrations" },
        {
          type: "steps",
          items: [
            { text: "Select **Enrollments** from the left-hand navigation menu." },
            { text: "Use the **Batch** filter to review everyone registered in a particular cohort." },
            { text: "Use the **Student** filter to inspect all past and present courses for an individual employee." },
            { text: "Use the **Status** filter to verify Confirmed vs Pending seats." },
          ],
        },
      ],
      result: "You can verify that all sponsored staff have confirmed places before scheduled classes begin.",
      related: ["batches", "my-team", "timetable"],
    },

    {
      id: "timetable",
      title: "How to check class timetables and live sessions",
      summary: "Review upcoming instructional sessions, class durations, and live virtual classrooms.",
      feature: "Timetable",
      learn: [
        "How to read class schedules in your localized timezone",
        "How to filter sessions by date range, batch, tutor, or employee",
        "How virtual classroom meeting links are accessed",
      ],
      body: [
        {
          type: "paragraph",
          text: "The **Timetable** workspace lists all scheduled classes that concern your team in chronological sequence. All session times automatically reflect your personal display timezone.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/timetable.webp",
            alt: "Timetable screen displaying session start times, finish times, durations, status badges, and Zoom classroom tags.",
            caption: "Session timetable showing live class schedules, durations, and virtual meeting rooms.",
          },
        },
        { type: "heading", text: "Timetable Columns & Controls" },
        {
          type: "definitions",
          items: [
            { term: "STARTS & ENDS", detail: "Exact class start and finish times in your configured timezone." },
            { term: "MINUTES", detail: "Scheduled instructional duration (e.g. 120 minutes)." },
            {
              term: "STATUS",
              detail: "Indicates whether a class is Upcoming, Live Now, or has Completed.",
            },
            {
              term: "WHERE",
              detail: "Instructional classroom delivery method (e.g. Zoom, Microsoft Teams, On-Campus Lecture Hall).",
            },
          ],
        },
        { type: "heading", text: "Filtering Scheduled Sessions" },
        {
          type: "steps",
          items: [
            { text: "Select **Timetable** in the left-hand navigation menu." },
            { text: "Specify **From** and **To** dates to inspect a specific weekly or monthly training block." },
            { text: "Filter by **Batch** or **Student** to examine individual employee commitments." },
          ],
        },
      ],
      result: "You know precisely when your employees are expected in class and can plan corporate shifts accordingly.",
      tips: [
        "Ensure your timezone is configured accurately in **Account** settings so class times match your local calendar.",
      ],
      related: ["batches", "attendance", "account"],
    },

    {
      id: "attendance",
      title: "How to track employee attendance records",
      summary: "Audit official registers recorded by instructors, status codes, and absence patterns.",
      feature: "Attendance",
      learn: [
        "How session attendance registers are officially recorded",
        "What each attendance status code represents",
        "How to isolate unexcused absences and spot attendance dips",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Attendance** provides an immutable audit trail of attendance records recorded by course instructors. Every session generates individual attendance entries for enrolled employees.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/attendance.webp",
            alt: "Attendance register showing session titles, batch codes, student names, status badges, and recorded by instructor details.",
            caption:
              "Attendance registers. Employee and instructor records are blurred for privacy.",
          },
        },
        { type: "heading", text: "Attendance Status Definitions" },
        {
          type: "definitions",
          items: [
            { term: "Present", detail: "The employee logged in on time and completed the instructional session." },
            { term: "Late", detail: "The employee joined the session after instruction commenced." },
            { term: "Absent", detail: "The employee failed to attend without authorized prior notice." },
            { term: "Excused", detail: "The absence was pre-arranged and formally approved by management or administration." },
          ],
        },
        { type: "heading", text: "Auditing Absence Records" },
        {
          type: "steps",
          items: [
            { text: "Select **Attendance** from the left-hand menu." },
            { text: "Set the **Status** filter to **Absent** to isolate missed sessions immediately." },
            { text: "Select a specific **Student** or **Batch** to review attendance patterns over time." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Register Integrity & Academic Auditing",
            body: "Registers are officially signed off by instructors. If an employee was marked absent due to an approved corporate business trip, contact your training coordinator to update the entry to Excused.",
          },
        },
      ],
      result: "You have verified, tamper-proof attendance compliance records for HR and training ROI verification.",
      tips: [
        "Filter by **Absent** every Monday morning to catch emerging absenteeism before it impacts cohort completion.",
      ],
      related: ["my-team", "timetable", "reports"],
    },

    {
      id: "work-and-results",
      title: "How to monitor assignments, quizzes, and examinations",
      summary:
        "Track coursework deadlines, quiz assessments, and scheduled examinations across your team.",
      feature: "Assignments, Quizzes, Examinations",
      learn: [
        "How coursework deliverables, quizzes, and examinations are structured",
        "Where to track submission status and evaluation results",
        "Academic evaluation standards and audit integrity",
      ],
      body: [
        {
          type: "paragraph",
          text: "Our LMS evaluates workforce capability through three structured assessment modalities: **Assignments**, **Quizzes**, and **Examinations**. Corporate managers have read-only audit visibility across all three.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/assignments.webp",
            alt: "Assignments workspace displaying assignment titles, course modules, due dates, and submission status.",
            caption: "Coursework assignments directory with due dates and submission tracking.",
          },
        },
        { type: "heading", text: "Assessment Modalities" },
        {
          type: "definitions",
          items: [
            {
              term: "Assignments",
              detail:
                "Practical coursework deliverables, code repositories, or executive case studies that employees submit for tutor grading.",
            },
            {
              term: "Quizzes",
              detail:
                "Automated knowledge checks evaluating conceptual mastery with fixed time limits, multiple-choice questions, and instant score computation.",
            },
            {
              term: "Examinations",
              detail:
                "Formal scheduled assessments that establish benchmark competence, featuring proctored windows, passing thresholds, and official weightings.",
            },
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/examinations.webp",
            alt: "Examinations workspace displaying assessment titles, courses, scheduled dates, durations, and passing marks.",
            caption: "Examinations schedule workspace showing passing marks and proctored time windows.",
          },
        },
        { type: "heading", text: "Reviewing Employee Assessments" },
        {
          type: "steps",
          items: [
            { text: "Select **Assignments**, **Quizzes**, or **Examinations** from the left-hand menu." },
            { text: "Filter by course or search by assessment title to examine required milestones." },
            { text: "Review upcoming deadlines to ensure your team submits deliverables on schedule." },
          ],
        },
      ],
      result: "You know what deliverables are required and can ensure your employees meet submission deadlines.",
      related: ["performance", "reports", "my-team"],
    },

    {
      id: "performance",
      title: "How to evaluate weighted performance and grade calculations",
      summary:
        "Inspect batch performance, component weightings, standing so far, and letter grades.",
      feature: "Performance",
      learn: [
        "How the LMS calculation engine computes weighted standings",
        "How to select a cohort and expand employee component breakdowns",
        "What 'so far incomplete' means versus final certification grades",
      ],
      body: [
        {
          type: "paragraph",
          text: "The **Performance** workspace reveals the exact arithmetic engine behind each employee's academic standing. Standing is computed from the course's accredited grading scheme, reflecting precise component weightings.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/performance-batch.webp",
            alt: "Performance workspace showing batch selector, student row with standing percentage, letter grade, and expanded component breakdown table.",
            caption:
              "Weighted performance breakdown. Student names and identifying records are blurred for privacy.",
          },
        },
        { type: "heading", text: "Inspecting Cohort Performance" },
        {
          type: "steps",
          items: [
            { text: "Select **Performance** from the left-hand navigation menu." },
            { text: "In the **Batch** selector, choose the cohort you wish to audit (e.g. 11429)." },
            { text: "Review the list of students, their current standing percentage, and provisional letter grade." },
            { text: "Click an employee's row to expand their full component breakdown." },
          ],
        },
        { type: "heading", text: "Component Breakdown Table" },
        {
          type: "definitions",
          items: [
            { term: "Component", detail: "Evaluation category (Assignments, Attendance, Examinations, Practical, Quizzes)." },
            { term: "Weight", detail: "The accredited percentage contribution to the final grade (e.g. 40.00% for Examinations)." },
            { term: "Marks", detail: "Number of completed deliverables scored versus total deliverables set." },
            { term: "Scored", detail: "Raw percentage mark achieved on that specific component." },
            { term: "Contributes", detail: "Calculated point contribution to the overall grade (e.g. 26.40 points)." },
            { term: "Status", detail: "Displays Counted if graded, or Not yet assessed / excluded from total if pending." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Understanding 'So Far Incomplete' Standings",
            body: "During an active cohort, the standing reflects only the components assessed to date. A provisional score of 53.63% indicates the learner's current standing across submitted work, not a final failing grade. Final grades are locked once all weighted components conclude.",
          },
        },
      ],
      result: "You have complete transparency into how marks are calculated, preventing misunderstandings.",
      tips: [
        "Check whether **Attendance** itself carries an academic weighting in the breakdown (often 10%–15%).",
      ],
      related: ["work-and-results", "reports", "my-team"],
    },

    {
      id: "reports",
      title: "How to generate and export executive reports",
      summary: "Six specialized analytical reports and one-click CSV spreadsheet exports.",
      feature: "Reports",
      learn: [
        "What data is analyzed in each of the six analytical reports",
        "How to apply filters and download CSV audit spreadsheets",
        "Best practices for handling exported corporate data",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Reports** provides aggregated analytics across all sponsored staff, enabling data-driven compliance reviews, executive reporting, and billing audits.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/reports.webp",
            alt: "Executive reports dashboard showing six report domain tabs, filters, graphical charts, and Export CSV button.",
            caption: "Executive Reports dashboard. Six dedicated analytical reports with CSV export.",
          },
        },
        { type: "heading", text: "Six Specialized Analytical Domains" },
        {
          type: "definitions",
          items: [
            { term: "Attendance Report", detail: "Session attendance rates, present/absent counts, and velocity trends." },
            { term: "Enrollment Report", detail: "Workforce distribution across courses, departments, and active cohorts." },
            { term: "Performance Report", detail: "Cumulative score distributions, GPA averages, and cohort progression." },
            { term: "Coursework Report", detail: "Deliverables assigned, submission velocities, and overdue work metrics." },
            { term: "Distribution Report", detail: "Statistical grade spread and bell-curve distributions across batches." },
            { term: "Grading Queue Report", detail: "Audit of submitted work currently pending tutor evaluation." },
          ],
        },
        { type: "heading", text: "Exporting Data to Spreadsheets" },
        {
          type: "steps",
          items: [
            { text: "Select **Reports** from the left-hand navigation menu." },
            { text: "Click the tab for the desired report (e.g. Attendance or Performance)." },
            { text: "Configure any desired filters, such as course, batch, or date interval." },
            { text: "Click the **Export CSV** button in the top action bar." },
            { text: "Open the downloaded spreadsheet in Microsoft Excel, Apple Numbers, or Google Sheets." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Data Protection & Export Handling",
            body: "Downloaded CSV spreadsheets contain personal employee training data. Store and distribute exported files in strict accordance with your company's information security and GDPR/data privacy policies.",
          },
        },
      ],
      result: "You have audit-ready workforce spreadsheets formatted for executive presentations and compliance records.",
      tips: [
        "The **Attendance** and **Coursework** CSV exports are ideal for monthly employee review meetings.",
      ],
      related: ["attendance", "performance", "my-team"],
    },
  ],
};
