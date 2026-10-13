import type { Section } from "../types";

/** The manager's core job: following their people, and the company record. */
export const yourPeople: Section = {
  id: "your-people",
  title: "Your people",
  blurb: "Who is in your care, how they are getting on, and your company's record.",
  articles: [
    {
      id: "my-team",
      title: "How to see how your people are getting on",
      summary:
        "One screen with attendance, assignments, scores and the next class for everybody in your care.",
      feature: "My team",
      learn: [
        "What each column means",
        "How to find the people who need attention",
        "Why no contact details are shown",
      ],
      body: [
        {
          type: "paragraph",
          text: "**My team** is the screen you will use most. It shows how the people in your care are getting on, in one table.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/my-team.webp",
            alt: "The My team screen showing totals for people, need a look, average attendance and overdue assignments, and a table of people with their learning, attendance, assignments, average score and next session.",
            caption:
              "My team. Names are blurred in this guide for privacy; you will see them in full.",
          },
        },
        { type: "heading", text: "The four totals at the top" },
        {
          type: "definitions",
          items: [
            { term: "People", detail: "How many people are assigned to you." },
            {
              term: "Need a look",
              detail:
                "How many are struggling in some way — poor attendance, overdue work, or low scores.",
            },
            { term: "Average attendance", detail: "Across everybody in your care." },
            { term: "Assignments overdue", detail: "Work due and not handed in, added up." },
          ],
        },
        { type: "heading", text: "The columns" },
        {
          type: "definitions",
          items: [
            { term: "Person", detail: "Their name and the company they are with." },
            { term: "Learning", detail: "Which course or courses they are taking." },
            { term: "Attendance", detail: "What proportion of classes they have attended." },
            {
              term: "Assignments",
              detail: "How many pieces of work they have handed in, and how many are overdue.",
            },
            { term: "Average score", detail: "Their average mark so far." },
            { term: "Next session", detail: "When their next class is." },
          ],
        },
        { type: "heading", text: "Find who needs attention" },
        {
          type: "steps",
          items: [
            { text: "Click **My team** in the left-hand menu." },
            {
              text: "Turn on **Only those who need a look**.",
              note: "The list then shows just the people flagged as struggling.",
            },
            { text: "Use **Columns** to hide anything you do not need." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Names only, never contact details",
            body: "This screen deliberately never shows an email address or a phone number, for anybody. If you need to contact somebody, use **Messages**.",
          },
        },
      ],
      result: "You know who is doing well and who needs a conversation.",
      tips: [
        "Check this weekly. Attendance and overdue work both show a problem long before results do.",
        "A **Needs a look** flag is a prompt to ask, not a judgement. People have good reasons.",
      ],
      problems: [
        {
          symptom: "Somebody from your company is missing.",
          fix: "They have not been assigned to you. Ask the training provider to add them — see the article on manager assignments.",
        },
      ],
      related: ["manager-assignments", "attendance", "performance", "messages"],
    },

    {
      id: "manager-assignments",
      title: "Why you can see some people and not others",
      summary:
        "The list that decides which students you may follow, and how to get it changed.",
      feature: "Manager assignments",
      learn: ["What decides who you can see", "How to ask for a change"],
      body: [
        {
          type: "paragraph",
          text: "**Manager assignments** shows which students each corporate manager may see. It is the list that decides what appears on your other screens.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Employing somebody grants nothing on its own",
            body: "Working at your company does not make somebody visible to you. An administrator has to assign them to you here. This is deliberate: it keeps one manager from seeing colleagues they have no business following.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/manager-assignments.webp",
            alt: "The Manager assignments screen listing manager and student pairs with the date assigned.",
            caption:
              "Your assignments. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Manager assignments** in the left-hand menu." },
            { text: "Check whether the person you expected is listed against your name." },
            {
              text: "If they are not, ask the training provider to assign them to you.",
              note: "You cannot add an assignment yourself — there is no **Assign a student** button on your account.",
            },
          ],
        },
      ],
      result: "You can explain exactly why somebody does or does not appear in My team.",
      tips: [
        "When somebody leaves your company, ask for their assignment to be removed. It does not expire by itself.",
      ],
      related: ["my-team", "organizations", "welcome"],
    },

    {
      id: "organizations",
      title: "How to manage your company record",
      summary: "Your organisation's details, its employees and its managers.",
      feature: "Organizations",
      learn: [
        "What your company record holds",
        "How to add an employee",
        "The difference between an employee and an assigned student",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Organizations** holds your company's record with the training provider. You see your own company only.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/organizations.webp",
            alt: "The Organizations screen showing one organisation with its code and state.",
            caption: "Your company.",
          },
        },
        {
          type: "paragraph",
          text: "Click your company's name to open it. The top shows its name, state, code and contact address, and how many managers and employees it has. There are two tabs.",
        },
        { type: "heading", text: "Employees" },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/organization-employees.webp",
            alt: "The Employees tab of a company showing each employee with their code, department, status and the date they joined.",
            caption:
              "The Employees tab, with the **Add employee** button. Names are blurred here for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Open your company and stay on the **Employees** tab." },
            { text: "Click **Add employee**." },
            { text: "Choose the person and fill in anything you know, such as their department." },
            { text: "Save." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "A removed employee is kept, not deleted",
            body: "Marking somebody as removed keeps the record, because past enrolments still have to show who sponsored them. Nothing is lost.",
          },
        },
        { type: "heading", text: "Managers" },
        {
          type: "paragraph",
          text: "The **Managers** tab lists the people appointed to manage this company.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Appointing a manager gives them no students",
            body: "Being listed here does not let somebody see anybody's results. Students are assigned separately, on **Manager assignments**. The two lists do different jobs.",
          },
        },
        { type: "heading", text: "Editing the company" },
        {
          type: "paragraph",
          text: "**Edit** at the top lets you correct your company's name and contact details.",
        },
      ],
      result: "Your company's record is accurate and its employee list is up to date.",
      tips: [
        "Adding somebody as an employee is not the same as getting to see their results. You need both: an employee record and an assignment.",
      ],
      problems: [
        {
          symptom: "You added an employee but still cannot see their progress.",
          fix: "Employment and visibility are separate. Ask the training provider to assign that student to you.",
        },
      ],
      related: ["manager-assignments", "my-team", "enrollments"],
    },
  ],
};
