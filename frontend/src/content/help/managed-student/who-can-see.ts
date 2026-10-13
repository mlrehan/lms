import type { Section } from "../types";

/**
 * The section that makes this guide different from the Individual Student one.
 *
 * Everything here was checked against the running system rather than assumed:
 * a student has no screen listing who is linked to them, but the system does
 * send them a notification at the moment a link is created, and the code that
 * sends it says why in as many words -- "the student finding out is the
 * point -- it is the only moment they could object". The guide says the same
 * thing in plain English, including the part the product does not do.
 */
export const whoCanSee: Section = {
  id: "who-can-see",
  title: "Who can see your progress",
  blurb:
    "Someone at your employer, or a family member, may be able to see how you are getting on. What they see, what they cannot do, and how you find out.",
  articles: [
    {
      id: "who-can-see",
      title: "Why someone else can see your record",
      summary:
        "How a manager or guardian gets access to your progress, what they can see, and how you are told.",
      learn: [
        "Who may be able to see your attendance and marks",
        "Exactly what they can see",
        "How you find out that somebody has been linked to you",
        "What to do if you did not expect it",
      ],
      body: [
        {
          type: "paragraph",
          text: "Your place on this course was arranged by somebody — usually an employer who is paying for it, sometimes a family member. The school can **link** that person to your account so they can follow how you are getting on.",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Manager",
              detail:
                "Somebody at the organisation that arranged your place, such as a training or HR manager. They typically follow several people at once.",
            },
            {
              term: "Guardian",
              detail:
                "A parent, carer or family member linked to you. More common for younger students.",
            },
          ],
        },
        {
          type: "heading",
          text: "What a linked person can see",
        },
        {
          type: "bullets",
          items: [
            "**Your attendance** — every class, whether you were there, and whether it was marked absent or excused.",
            "**The work you have been set**, and whether you have handed it in.",
            "**Your marks**, including individual assignment and quiz scores.",
            "**Your overall standing** on the course, and your grade so far.",
            "**When your next class is.**",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "They see your academic record, not your conversations",
            body: "A link covers your progress. Your private messages are not part of it.",
          },
        },
        {
          type: "heading",
          text: "How you find out",
        },
        {
          type: "paragraph",
          text: "You are told. At the moment a manager or a guardian is linked to you, the system sends you a notification saying so, and naming them:",
        },
        {
          type: "table",
          columns: ["What happened", "What you receive"],
          rows: [
            [
              "A manager is linked to you",
              "“A manager was linked to your account — <name> can now see your academic record.”",
            ],
            [
              "A guardian is linked to you",
              "“A guardian was linked to your account — <name> can now see your academic record.”",
            ],
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "managed-student/notifications.webp",
            alt: "The Notifications screen showing the Feed tab with alerts about a scheduled exam, a new quiz, a new assignment and a graded submission, each with a Mark read button.",
            caption:
              "Your notification feed. A link being created arrives here, like any other alert.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "There is no screen listing who can currently see you",
            body: "This is worth being straight about. The notification is sent once, when the link is created — it is not a running list. If you have scrolled past it, or it arrived before you started using the system, your account has no page that answers “who can see me right now?”. To find out, ask the school using **Messages**.",
          },
        },
        {
          type: "heading",
          text: "If you did not expect it",
        },
        {
          type: "paragraph",
          text: "The notification exists so that you know, and so you have the chance to say something. If somebody has been linked to you and you do not think they should be, message the school and say so. The link was created by an administrator and an administrator can remove it.",
        },
      ],
      result:
        "You understand who may be watching your progress, what they see, and how to ask who that currently is.",
      tips: [
        "Read your notifications rather than clearing them unread. This is one of the things that only ever arrives there.",
      ],
      problems: [
        {
          symptom: "You want to know who can see your record today.",
          fix: "There is no screen for it. Message the school and ask — see **How to message a tutor or the office**.",
        },
      ],
      related: ["what-they-cannot-do", "notifications", "messages"],
    },

    {
      id: "what-they-cannot-do",
      title: "What a manager or guardian cannot do",
      summary:
        "The limits on a linked account: they can watch, but they cannot act for you.",
      learn: [
        "Why nobody else can hand in your work",
        "Who can change a mark or a register",
        "What this means for you",
      ],
      body: [
        {
          type: "paragraph",
          text: "A link lets somebody **see** your record. It does not let them act on your behalf. These are not oversights — each is a deliberate limit.",
        },
        {
          type: "table",
          columns: ["They cannot", "Because"],
          rows: [
            [
              "Hand work in for you",
              "Only your own account can submit an assignment. The work has to be yours.",
            ],
            ["Take a quiz for you", "Same reason. An attempt is recorded against you."],
            ["Change a mark", "Marking belongs to your tutor."],
            ["Change your attendance", "The register is your tutor's record of the class."],
            ["Sign in as you", "Nobody should ever have your password, including them."],
            ["Read your private messages", "A link covers your academic record, not your mailbox."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "What this means in practice",
            body: "If a manager tells you they will “sort out” a missed deadline or a wrong register, they cannot do it directly — they have to ask the school, exactly as you would. You are not saving time by going through them.",
          },
        },
        {
          type: "heading",
          text: "If something on your record is wrong",
        },
        {
          type: "paragraph",
          text: "Go to the person who can change it. An attendance mark belongs to the tutor who took the register; a grade belongs to whoever marked the work. Use **Messages** and say which class or which piece of work you mean.",
        },
      ],
      result: "You know who to ask when something needs changing, and it is not your manager.",
      related: ["who-can-see", "messages", "attendance"],
    },
  ],
};
