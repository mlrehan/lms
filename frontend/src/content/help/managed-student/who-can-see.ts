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
            kind: "note",
            title: "Privacy transparency and authorized sponsors",
            body: "Authorized sponsors (such as your designated employer manager or guardian) receive formal read-only access approved by your organization. Notification alerts confirm whenever an authorized link is provisioned. To review or clarify your active authorized contacts, message the school administration via **Messages**.",
          },
        },
        {
          type: "heading",
          text: "Reviewing authorized sponsor relationships",
        },
        {
          type: "paragraph",
          text: "The notification feed ensures complete transparency. If you have any questions regarding who has access to your training milestones, connect with the administrative office via **Messages** for instant assistance.",
        },
      ],
      result:
        "You understand how sponsor visibility is governed and how your academic privacy is maintained.",
      tips: [
        "Review your notifications feed regularly to stay updated on training alerts and newly provisioned sponsor access.",
      ],
      problems: [
        {
          symptom: "Confirming your authorized sponsor list.",
          fix: "Send a quick inquiry to school administration via **Messages** — see **How to message a tutor or the office**.",
        },
      ],
      related: ["what-they-cannot-do", "notifications", "messages"],
    },

    {
      id: "what-they-cannot-do",
      title: "How your academic work and privacy are protected",
      summary:
        "How your personal coursework, independent submissions, and account privacy are safeguarded.",
      learn: [
        "How your independent coursework is protected",
        "How grading integrity and attendance records are maintained",
        "How your private messages and credentials stay secure",
      ],
      body: [
        {
          type: "paragraph",
          text: "When an employer, sponsor, or guardian supports your education, they receive visibility into your attendance milestones and overall results. Strict institutional safeguards ensure your academic work remains independent and your privacy is protected.",
        },
        {
          type: "table",
          columns: ["Academic Safeguard", "How It Protects You"],
          rows: [
            [
              "Independent Coursework Submissions",
              "Only your authenticated account can submit assignments and complete quizzes, ensuring all accredited achievements reflect your genuine learning.",
            ],
            [
              "Objective Faculty Evaluation",
              "Tutors and instructors independently evaluate and grade coursework according to accredited institutional rubrics.",
            ],
            [
              "Verified Attendance Registers",
              "Session attendance is recorded live by the assigned instructor as the official institutional record.",
            ],
            [
              "Private Communication Channels",
              "Your direct messages with tutors, academic advisors, and support staff remain private between you and the recipient.",
            ],
            [
              "Sign-In Credential Security",
              "Your login password belongs to you alone and must remain confidential at all times.",
            ],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Collaborative Learning Support",
            body: "Your sponsor or guardian is there to encourage and support your growth. Having visibility into your course timetable and progress allows them to celebrate your achievements and support your learning goals.",
          },
        },
        {
          type: "heading",
          text: "If you have a question about a mark or session",
        },
        {
          type: "paragraph",
          text: "Reach out directly to your course instructor. Attendance records belong to the tutor who ran the class, and coursework feedback belongs to the instructor who evaluated it. Use **Messages** to discuss any questions directly with your teacher.",
        },
      ],
      result: "You understand how your academic independence, privacy, and accomplishments are fully protected.",
      related: ["who-can-see", "messages", "attendance"],
    },
  ],
};
