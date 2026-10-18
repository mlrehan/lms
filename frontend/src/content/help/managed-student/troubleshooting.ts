import type { Section } from "../types";

/** The questions students actually arrive with. */
export const troubleshooting: Section = {
  id: "troubleshooting",
  title: "Solving problems",
  blurb: "What to check first, what is not a fault, and when to ask somebody.",
  articles: [
    {
      id: "common-problems",
      title: "Common problems and how to solve them",
      summary: "The things that go wrong most often, and who to ask when they do.",
      learn: [
        "What to check when a screen looks empty",
        "Which worries usually turn out to be nothing",
        "Who to contact for what",
      ],
      body: [
        { type: "heading", text: "A screen looks empty" },
        {
          type: "bullets",
          items: [
            "**Give it a moment.** Some screens show 'Loading' briefly, especially the first time.",
            "**Some screens need a class group first.** Performance shows nothing until you choose a **Batch**.",
            "**A date range may be excluding everything.** Clear **From** and **To** on the Timetable.",
            "**A filter may still be set from last time.** Put filters back to 'Any'.",
          ],
        },

        { type: "heading", text: "I cannot hand my work in" },
        {
          type: "table",
          columns: ["What you see", "What to do"],
          rows: [
            ["No way to submit", "Open the **My submission** tab. The first tab is the record, not the form."],
            [
              "The deadline has passed",
              "Check the **Late work** column. 'Accepted' means you can still hand in.",
            ],
            [
              "Late work is not accepted",
              "Message your tutor now, before you do anything else. Only they can give an extension.",
            ],
            [
              "You submitted but see no time",
              "It did not go through. Do it again rather than assuming it worked.",
            ],
          ],
        },

        { type: "heading", text: "My times are all wrong" },
        {
          type: "paragraph",
          text: "Every time in the system is converted into **your** timezone, which is set on **My account**. If that is wrong, every class time and deadline you see is wrong by the same amount. Check it there first — it explains almost every case of this.",
        },

        { type: "heading", text: "My attendance looks wrong" },
        {
          type: "bullets",
          items: [
            "**Recent classes may not be marked yet.** The register is taken after the class, sometimes a day or two later.",
            "**Early in a course, one absence moves the percentage a long way.** Count the actual rows.",
            "**If a specific class is genuinely wrong**, message your tutor with the date and the batch number. You cannot change a register yourself, and should not expect to.",
          ],
        },

        { type: "heading", text: "My mark looks low, or is missing" },
        {
          type: "bullets",
          items: [
            "**'So far incomplete' means the course is not finished.** The figure is out of the work marked so far, and it moves.",
            "**Unmarked work is not a zero you earned.** It simply has not been marked.",
            "**Not everything counts equally.** Check the **weight** column before worrying about one mark.",
            "**A mark can be given but not published.** You see it when the tutor releases it.",
          ],
        },

        { type: "heading", text: "Managing sponsor visibility and access" },
        {
          type: "paragraph",
          text: "Sponsor relationships (such as employer or guardian links) are established through institutional administration to safeguard student privacy. Whenever an authorized link is provisioned, you receive an automated notification. To review, verify, or adjust your authorized sponsor contacts, contact Student Services via **Messages**.",
        },

        { type: "heading", text: "Student Academic Roles & Institutional Support" },
        {
          type: "paragraph",
          text: "The Student Portal is focused on your learning, coursework submissions, timetable, and study resources. Institutional actions are managed by your school support team:",
        },
        {
          type: "table",
          columns: ["Topic", "Support Contact"],
          rows: [
            ["Coursework, assignment extensions, or quiz questions", "Contact your course tutor via Messages."],
            ["Course enrollment, batch schedules, or room locations", "Contact Student Services."],
            ["Official transcripts or enrollment letters", "Contact the Academic Registry."],
            ["Account sign-in or password issues", "Use the reset link or contact the Helpdesk."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Say which class and which piece of work",
            body: "Whoever you are writing to deals with a lot of people. Naming the batch number and the assignment gets you a useful answer first time.",
          },
        },
      ],
      related: ["messages", "attendance", "submit", "who-can-see"],
    },
  ],
};
