import type { Section } from "../types";

/** The guardian's main purpose: how the person they look after is doing. */
export const progress: Section = {
  id: "progress",
  title: "How they are getting on",
  blurb: "Progress at a glance, attendance class by class, and overall results.",
  articles: [
    {
      id: "my-team",
      title: "How to see how they are getting on",
      summary:
        "One screen with attendance, work handed in, average score and the next class.",
      feature: "My team",
      learn: [
        "What each column means",
        "What the 'Needs a look' flag means",
        "Why no contact details are shown",
      ],
      body: [
        {
          type: "paragraph",
          text: "**My team** is the screen you will use most. It shows how the person you look after is getting on, all in one place.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/my-team.webp",
            alt: "The My team screen showing totals for people, need a look, average attendance and overdue assignments, and a row for the linked student.",
            caption:
              "My team. Names are blurred in this guide for privacy; you will see them in full.",
          },
        },
        { type: "heading", text: "The four totals at the top" },
        {
          type: "definitions",
          items: [
            { term: "People", detail: "How many people you are linked to." },
            {
              term: "Need a look",
              detail:
                "How many are struggling in some way — poor attendance, overdue work, or low scores.",
            },
            { term: "Average attendance", detail: "How often they have attended." },
            { term: "Assignments overdue", detail: "Work due and not handed in." },
          ],
        },
        { type: "heading", text: "The columns" },
        {
          type: "definitions",
          items: [
            {
              term: "Person",
              detail: "Their name, and how they are related to you — for example PARENT.",
            },
            { term: "Learning", detail: "Which course they are taking." },
            { term: "Attendance", detail: "What proportion of classes they have attended." },
            {
              term: "Assignments",
              detail: "How many pieces of work are done, and how many are overdue.",
            },
            { term: "Average score", detail: "Their average mark so far." },
            { term: "Next session", detail: "When their next class is." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "'Needs a look' is a prompt, not a verdict",
            body: "It means something is worth asking about — a few missed classes, or work not handed in. People have good reasons. It is a conversation starter, not a judgement.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Names only, never contact details",
            body: "This screen never shows an email address or phone number, for anybody. To get in touch, use **Messages**.",
          },
        },
      ],
      result: "You know whether anything needs talking about at home.",
      tips: [
        "Check this once a week. Attendance and overdue work show a problem long before results do.",
      ],
      problems: [
        {
          symptom: "The screen is empty, or somebody is missing.",
          fix: "You are not linked to them. Ask the school to set up the link — see the next article.",
        },
      ],
      related: ["guardians", "attendance", "performance", "messages"],
    },

    {
      id: "guardians",
      title: "Why you can see this person",
      summary:
        "The link that lets you follow somebody, and how to ask for one.",
      feature: "Guardians",
      learn: ["What the link is", "How to check yours", "How to ask for a change"],
      body: [
        {
          type: "paragraph",
          text: "The **Guardians** screen shows who may see a student's attendance, grades and schedule on their behalf. Your own link is listed there.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Being a parent is not enough on its own",
            body: "The school has to create a link between your account and the student's. Without it you would see nothing at all. This is deliberate: it stops anybody seeing a young person's results without permission.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/guardians.webp",
            alt: "The Guardians screen showing one link with guardian, student, relationship, primary contact and the date linked.",
            caption:
              "Your link. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Guardian", detail: "You." },
            { term: "Student", detail: "The person you are allowed to follow." },
            { term: "Relationship", detail: "How you are related, such as PARENT." },
            {
              term: "Primary contact",
              detail: "Whether you are the first person the school contacts.",
            },
            { term: "Linked", detail: "When the link was created." },
          ],
        },
        {
          type: "steps",
          items: [
            { text: "Click **Guardians** in the left-hand menu." },
            { text: "Check the student you expected is listed." },
            {
              text: "If somebody is missing, ask the school to add the link.",
              note: "You cannot create a link yourself. There is no button for it on your account.",
            },
          ],
        },
      ],
      result: "You can explain exactly why you can see one person and not another.",
      tips: [
        "If you look after more than one person, each needs its own link. They all then appear on **My team**.",
      ],
      related: ["my-team", "welcome"],
    },

    {
      id: "attendance",
      title: "How to check attendance",
      summary: "Every class, whether they attended, and who recorded it.",
      feature: "Attendance",
      learn: ["How to check attendance class by class", "What each status means"],
      body: [
        {
          type: "paragraph",
          text: "**Attendance** shows the registers that concern you: one row per class, with what they were marked and who recorded it.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/attendance.webp",
            alt: "The Attendance screen listing session, batch, student, status, remarks and when it was recorded and by whom.",
            caption:
              "Registers for the person you look after. Names are blurred here for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Present", detail: "They attended, on time." },
            { term: "Late", detail: "They attended, after the class started." },
            { term: "Absent", detail: "They did not attend, and it was not agreed in advance." },
            { term: "Excused", detail: "They did not attend, and it was agreed beforehand." },
          ],
        },
        {
          type: "steps",
          items: [
            { text: "Click **Attendance** in the left-hand menu." },
            { text: "Use **Status** to show only absences, for example." },
            { text: "Read the **Recorded** column to see when it was marked, and by which tutor." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "You cannot change a register",
            body: "The register is the tutor's record of the class. If something looks wrong — an absence you believe was agreed, for instance — message the school rather than assuming the record is right or wrong.",
          },
        },
      ],
      result: "You can see exactly which classes were attended and which were missed.",
      tips: [
        "Filter by **Absent** to see every missed class at once. A run of them close together usually means something.",
      ],
      problems: [
        {
          symptom: "Attendance shows 0% but they have been going.",
          fix: "The register may not have been taken yet for recent classes. Check the dates in the list before worrying.",
        },
      ],
      related: ["my-team", "timetable", "messages"],
    },

    {
      id: "performance",
      title: "How to see their overall result",
      summary: "Their current percentage and grade, and the working behind it.",
      feature: "Performance",
      learn: ["How to see the overall figure", "What 'so far incomplete' means"],
      before: ["Choose a **Batch** — the screen is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "**Performance** shows the current standing for the person you look after, and lets you open the row to see exactly how it was worked out.",
        },
        {
          type: "steps",
          items: [
            { text: "Click **Performance** in the left-hand menu." },
            {
              text: "Choose a **Batch** — the class group they are in.",
              image: {
                src: "guardian/performance-batch.webp",
                alt: "The Performance screen for a batch showing one student with a percentage, a status of so far incomplete, and a letter grade.",
                caption:
                  "You see only the person you look after, not the rest of the class. Names are blurred here for privacy.",
              },
            },
            {
              text: "Click their row to see every part of the course, how much it is worth, and what it contributed.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "What 'so far incomplete' means",
            body: "The course is not finished. The percentage is out of the work assessed so far, so it will move — often a lot — as more work is marked. A low figure early on is usually unmarked work, not a bad result.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "You only see your own person",
            body: "Even though the screen is organised by class group, you see only the student linked to you. Other people's results are never shown to you.",
          },
        },
      ],
      result: "You understand where the overall figure comes from.",
      tips: [
        "Open the row before drawing conclusions. One unmarked piece of work can move the figure a long way.",
      ],
      problems: [
        {
          symptom: "The screen stays empty.",
          fix: "No batch is chosen, or no marks have been recorded yet.",
        },
      ],
      related: ["grades", "my-team", "attendance"],
    },
  ],
};
