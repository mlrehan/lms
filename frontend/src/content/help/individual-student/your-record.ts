import type { Section } from "../types";

/**
 * The counterpart to the Managed Student guide's "who can see your progress".
 *
 * An individual student has nobody linked to their account -- verified in the
 * database for the account this guide was written from: zero managers, zero
 * guardians, no employer membership. But "nobody" would be wrong: tutors and
 * administrators can see their work, and a link can be created later. Both
 * are said plainly here rather than implying a privacy that does not exist.
 */
export const yourRecord: Section = {
  id: "your-record",
  title: "Your record and who sees it",
  blurb:
    "Who can see your work today, what stays private, and what would happen if somebody were ever linked to your account.",
  articles: [
    {
      id: "privacy",
      title: "Who can see your work",
      summary:
        "Your tutors and the school's staff can see your record. No outside person is following it.",
      learn: [
        "Who can see your marks and attendance",
        "What other students can and cannot see",
        "What stays private",
      ],
      body: [
        {
          type: "paragraph",
          text: "Studying on your own account, nobody outside the school is following your progress. That does not mean nobody can see it, and the difference is worth being clear about.",
        },
        {
          type: "table",
          columns: ["Who", "What they can see"],
          rows: [
            [
              "Your tutor",
              "Your attendance, the work you hand in, and your marks. They teach the class and do the marking.",
            ],
            [
              "School administrators",
              "The same, as part of running the school and producing your records.",
            ],
            ["Other students on your course", "Nothing of yours. Not your marks, not your work."],
            ["Anybody outside the school", "Nothing, unless the school links them — see below."],
          ],
        },
        {
          type: "heading",
          text: "What other students see",
        },
        {
          type: "paragraph",
          text: "Screens like **Performance** and the **Grade book** are organised by class group, which can make it look as though you are seeing a whole cohort. You are not — your account shows only your own row, and other people's accounts show only theirs.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/performance-batch.webp",
            alt: "The Performance screen for a batch showing a single student row with a percentage, a status of so far incomplete and a letter grade.",
            caption:
              "One row: yours. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "heading",
          text: "What stays private either way",
        },
        {
          type: "bullets",
          items: [
            "**Your messages.** Private between you and the person you wrote to.",
            "**Your email address.** The system never shows anybody's contact details — yours included. Messaging works by name.",
            "**Your password.** Nobody at the school can see it.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Discussions are the exception, and deliberately so",
            body: "Anything you post in **Discussions** is visible to your course. That is the point of it. Use **Messages** for anything you would not want the class to read.",
          },
        },
      ],
      result: "You know exactly who can see your record and what other students cannot.",
      related: ["if-linked", "messages", "discussions"],
    },

    {
      id: "if-linked",
      title: "What would happen if somebody were linked to you",
      summary:
        "An employer or family member can be given access later — and you would be told the moment it happened.",
      learn: [
        "How somebody could gain access to your record",
        "How you would find out",
        "What they could and could not do",
      ],
      body: [
        {
          type: "paragraph",
          text: "Nobody outside the school is linked to your account today. The school can create such a link later — if an employer starts sponsoring your place, for example — so it is worth knowing how that works before it happens.",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Manager",
              detail:
                "Somebody at an organisation sponsoring your place, such as a training or HR manager.",
            },
            {
              term: "Guardian",
              detail: "A parent, carer or family member. More common for younger students.",
            },
          ],
        },
        {
          type: "heading",
          text: "You would be told, once, at the moment it happened",
        },
        {
          type: "paragraph",
          text: "The system sends you a notification naming the person — *“A manager was linked to your account”* or *“A guardian was linked to your account”*. It arrives in your **Notifications** feed like any other alert.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/notifications.webp",
            alt: "The Notifications screen showing the Feed tab with alerts about a scheduled exam, a new quiz and a new assignment, each with a Mark read button.",
            caption: "Your notification feed. A link being created would arrive here.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "It is announced once and never repeated",
            body: "There is no screen anywhere in the system that lists who currently has access to your record. The notification is the only time you are told, which is a good reason to read your notifications rather than clearing them unread. If you think you have missed one, ask the office.",
          },
        },
        {
          type: "heading",
          text: "What a linked person could do",
        },
        {
          type: "paragraph",
          text: "They could **see** your attendance, the work you have been set, your marks and your overall standing. They could not act for you:",
        },
        {
          type: "table",
          columns: ["They could not", "Because"],
          rows: [
            ["Hand work in for you", "Only your own account can submit. The work has to be yours."],
            ["Take a quiz for you", "An attempt is recorded against you."],
            ["Change a mark", "Marking belongs to your tutor."],
            ["Change your attendance", "The register is your tutor's record of the class."],
            ["Read your messages", "A link covers your academic record, not your mailbox."],
          ],
        },
        {
          type: "paragraph",
          text: "If a link is ever created that you did not expect, message the school. An administrator created it and an administrator can remove it — the notification exists so that you have the chance to say so.",
        },
      ],
      result: "You would recognise the notification and know what it means.",
      tips: [
        "Leave notifications unread until you have actually read them. This one arrives nowhere else.",
      ],
      related: ["privacy", "notifications", "messages"],
    },
  ],
};
