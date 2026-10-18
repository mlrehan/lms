import type { Section } from "../types";

/**
 * Enterprise-grade Corporate Manager User Guide: Your People
 * Verified against live running application interface.
 */
export const yourPeople: Section = {
  id: "your-people",
  title: "Your people",
  blurb: "Supervise sponsored staff, audit supervisory links, and manage your corporate roster.",
  articles: [
    {
      id: "my-team",
      title: "How to monitor employee training in My team",
      summary:
        "Comprehensive workforce training console: attendance, assignments, scores, and risk triage.",
      feature: "My team",
      learn: [
        "How to interpret the four executive summary cards",
        "How to use the 'Only those who need a look' triage filter",
        "How to customize table columns for tailored reporting",
        "How data privacy governance safeguards employee contact details",
      ],
      body: [
        {
          type: "paragraph",
          text: "**My team** is your primary workforce monitoring console. It provides a centralized, real-time register of all sponsored employees under your supervisory care, consolidating attendance, coursework, examination results, and next scheduled sessions.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/my-team.webp",
            alt: "My team console displaying workforce metric cards, search bar, triage filter, and employee performance table.",
            caption:
              "My team workforce console. Employee and manager names are blurred in this guide for privacy.",
          },
        },
        { type: "heading", text: "Executive Summary Cards" },
        {
          type: "definitions",
          items: [
            {
              term: "PEOPLE",
              detail: "Total number of sponsored employees actively assigned to your supervisory team.",
            },
            {
              term: "NEED A LOOK",
              detail:
                "Count of staff members currently flagged for attendance dips, overdue assignments, or lagging assessment scores.",
            },
            {
              term: "AVERAGE ATTENDANCE",
              detail: "Mean session attendance percentage calculated across all assigned learners.",
            },
            {
              term: "ASSIGNMENTS OVERDUE",
              detail: "Aggregate count of coursework deliverables whose deadlines have elapsed without submission.",
            },
          ],
        },
        { type: "heading", text: "Workforce Roster Columns" },
        {
          type: "definitions",
          items: [
            {
              term: "PERSON",
              detail: "Employee name and their assigned corporate supervisory relationship (e.g. Line Manager).",
            },
            {
              term: "LEARNING",
              detail: "Active course title and current training status (e.g. 1 active enrollment).",
            },
            {
              term: "ATTENDANCE",
              detail: "Overall percentage of attended classes, highlighted with color-coded status chips.",
            },
            {
              term: "ASSIGNMENTS",
              detail: "Ratio of submitted deliverables versus total set coursework (e.g. 1/1).",
            },
            {
              term: "AVERAGE SCORE",
              detail: "Cumulative weighted academic score achieved across completed evaluations.",
            },
            {
              term: "NEXT SESSION",
              detail: "Date and time of the employee's next scheduled live instructional session.",
            },
            {
              term: "RISK STATUS",
              detail: "Visual indicator badge (e.g. Needs a look) identifying learners requiring managerial check-in.",
            },
          ],
        },
        { type: "heading", text: "Triage & Filtering" },
        {
          type: "steps",
          items: [
            { text: "Select **My team** from the left-hand navigation menu." },
            {
              text: "Enable the **Only those who need a look** checkbox to isolate employees needing academic or attendance intervention.",
            },
            {
              text: "Use the **Search by name** input to locate individual team members instantly.",
            },
            {
              text: "Click **Columns** in the toolbar to show or hide specific metrics based on your reporting requirements.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Enterprise Data Privacy & Secure Communication",
            body: "To comply with institutional privacy policies and corporate data standards, employee personal contact numbers and personal emails are protected. Direct managerial communication is conducted seamlessly through the integrated **Messages** portal.",
          },
        },
      ],
      result: "You maintain a clear, continuous audit of your employees' training progress and can resolve performance dips proactively.",
      tips: [
        "Review **My team** weekly to ensure any **Needs a look** flag is addressed before cohort milestones.",
      ],
      problems: [
        {
          symptom: "An enrolled employee is missing from the list.",
          fix: "The employee has not yet been linked to your supervisory account. Contact your Corporate Training Coordinator to establish the link.",
        },
      ],
      related: ["manager-assignments", "attendance", "performance", "messages"],
    },

    {
      id: "manager-assignments",
      title: "How authorized supervisory rosters are managed",
      summary:
        "Understand supervisory relationships, audit employee reporting lines, and request roster updates.",
      feature: "Manager assignments",
      learn: [
        "How supervisory reporting lines govern access to employee data",
        "How to audit active manager-student links",
        "How to request roster adjustments for new hires or department transfers",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Manager assignments** provides a transparent audit of which staff members are linked to your managerial account. These supervisory records establish the data boundary for your dashboard telemetry, team rosters, and downloadable compliance reports.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/manager-assignments.webp",
            alt: "Manager assignments table showing manager, student, relationship, first contact badge, and assigned timestamp.",
            caption:
              "Authorized manager assignments table. Names and identifying records are blurred for privacy.",
          },
        },
        { type: "heading", text: "Roster Audit Fields" },
        {
          type: "definitions",
          items: [
            {
              term: "MANAGER",
              detail: "The appointed corporate manager authorized to oversee training.",
            },
            {
              term: "STUDENT",
              detail: "The sponsored employee undertaking courses with the institute.",
            },
            {
              term: "RELATIONSHIP",
              detail: "Organizational supervisory designation (e.g. Line Manager, Department Head, Mentor).",
            },
            {
              term: "FIRST CONTACT",
              detail: "Status badge indicating whether the manager is designated as the primary emergency and administrative contact.",
            },
            {
              term: "ASSIGNED",
              detail: "Exact timestamp when the supervisory authorization was established.",
            },
          ],
        },
        { type: "heading", text: "Updating your team roster" },
        {
          type: "steps",
          items: [
            { text: "Open **Manager assignments** in the left-hand navigation menu." },
            { text: "Review the list of employees currently linked to your managerial account." },
            {
              text: "When new employees join your organization or transfer into your team, send their details to your dedicated Training Coordinator.",
            },
            {
              text: "The administration promptly provisions their account and maps the supervisory link to your portal.",
            },
          ],
        },
      ],
      result: "Your supervisory scope is fully verified, ensuring seamless compliance monitoring across your department.",
      tips: [
        "Keep your training coordinator informed when staff changes occur to maintain unbroken audit logs.",
      ],
      related: ["my-team", "organizations", "welcome"],
    },

    {
      id: "organizations",
      title: "How to manage your corporate organization and employees",
      summary: "Inspect your corporate profile, manage employee lists, and add new staff.",
      feature: "Organizations",
      learn: [
        "How to access your corporate organization profile",
        "How to review active employees and appointed managers",
        "How to register a new employee into your corporate roster",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Organizations** holds your company's institutional profile with our training institute. It defines your organization code, primary business address, appointed managers, and employee roster.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/organizations.webp",
            alt: "Organizations listing showing company profile, organization code, and employee count.",
            caption: "Corporate organization directory. Company details are blurred for privacy.",
          },
        },
        { type: "heading", text: "Accessing your company workspace" },
        {
          type: "steps",
          items: [
            { text: "Select **Organizations** in the left-hand menu." },
            { text: "Click your company's name in the table to open its detailed profile." },
          ],
        },
        {
          type: "paragraph",
          text: "The organization workspace displays your enterprise code, contact address, active status, and contains dedicated tabs for **Employees** and **Managers**.",
        },
        { type: "heading", text: "Employees Management & Onboarding" },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/organization-employees.webp",
            alt: "Organization detail workspace with Employees tab active, showing employee records and Add employee button.",
            caption:
              "Organization Employees tab. Employee names and emails are blurred for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "In your organization profile, select the **Employees** tab." },
            { text: "Click the **Add employee** button in the top action bar." },
            {
              text: "In the modal, select the employee account and assign their corporate department and employee code.",
            },
            { text: "Click **Save** to confirm their corporate registration." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Archival Governance & Audit Retention",
            body: "If an employee leaves your organization, their past training and certification records are permanently archived rather than purged. This preserves historical compliance documentation for past billing and accreditation audits.",
          },
        },
      ],
      result: "Your corporate record is current, and your authorized employee roster is fully maintained.",
      tips: [
        "Registering staff under the **Employees** tab allows them to be enrolled into sponsored training batches.",
      ],
      related: ["manager-assignments", "my-team", "batches"],
    },
  ],
};
