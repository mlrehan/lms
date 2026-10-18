import type { Section } from "../types";

/** Messages, notices, discussions, alerts, and shared files. */
export const stayingInTouch: Section = {
  id: "staying-in-touch",
  title: "Staying in touch",
  blurb: "Messages, notices, discussions, alerts and files shared with you.",
  articles: [
    {
      id: "messages",
      title: "How to message a tutor or the office",
      summary: "The mailbox inside the system — and why you never need anybody's email address.",
      feature: "Messages",
      learn: ["How to send a message", "What the folders are", "Who you can write to"],
      body: [
        {
          type: "paragraph",
          text: "**Messages** is the mailbox inside the system. It is how you contact your tutor or the office about anything to do with your course.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/messages.webp",
            alt: "The Messages screen with a Compose button and folders for Inbox, Starred, Sent and Drafts, with an empty inbox.",
            caption: "Four folders on the left; the conversation opens on the right.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Messages** in the left-hand menu." },
            { text: "Click **Compose**." },
            { text: "Choose who to write to, by name." },
            { text: "Give it a subject, write your message, and send it." },
          ],
        },
        {
          type: "definitions",
          items: [
            { term: "Inbox", detail: "Messages sent to you." },
            { term: "Starred", detail: "Messages you have marked to come back to." },
            { term: "Sent", detail: "Messages you have sent." },
            { term: "Drafts", detail: "Messages you started but have not sent." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Nobody's email address is shown",
            body: "Messaging works by name. No email address is shown or shared, in either direction — yours included. That is deliberate, and it is why no screen in the system shows contact details.",
          },
        },
      ],
      result: "Your message appears in your **Sent** folder and in their inbox.",
      tips: [
        "Say which course and which class or piece of work you mean. Tutors teach a lot of people.",
        "Use this rather than a personal email. It keeps the conversation attached to your course record.",
      ],
      related: ["notifications", "discussions", "privacy"],
    },

    {
      id: "discussions",
      title: "How to use discussions",
      summary: "Course threads you can read and start — the one place you can post publicly.",
      feature: "Discussions",
      learn: ["What discussions are for", "How to start one", "What a locked thread means"],
      body: [
        {
          type: "paragraph",
          text: "**Discussions** are threads attached to a course. Unlike messages, which go to one person, a discussion is visible to the course.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/discussions.webp",
            alt: "The Discussions screen showing a Start a discussion button and an empty thread list.",
            caption: "Threads for your course. You can start one yourself.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Discussions** in the left-hand menu." },
            { text: "Read any existing threads." },
            { text: "Click **Start a discussion** to ask something yourself." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "A locked thread stays readable",
            body: "If a tutor locks a thread, you can still read it — it just takes no new replies. Nothing is deleted.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Use it for questions others will share",
            body: "A question about the brief or a deadline is usually worth asking here: your classmates probably have it too, and the answer stays where everybody can find it. Use **Messages** for anything personal.",
          },
        },
      ],
      result: "Your question is posted where your tutor and your course can see it.",
      related: ["messages", "announcements"],
    },

    {
      id: "announcements",
      title: "How to read announcements",
      summary: "Notices from the school, and why one you saw last week may be gone.",
      feature: "Announcements",
      learn: ["Where to find notices", "Why one might disappear"],
      body: [
        {
          type: "paragraph",
          text: "**Announcements** are notices the school puts out — a room change, a reminder, an exam date.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/announcements.webp",
            alt: "The Announcements screen showing the feed with notices and updates.",
            caption: "The announcements feed. Displays current institutional notices.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Notices come and go on purpose",
            body: "Each announcement has a window — a date it starts showing and a date it stops. One you saw last week may simply have expired. That is the school tidying up, not something going wrong.",
          },
        },
      ],
      result: "You have seen whatever the school is currently telling people.",
      related: ["notifications", "discussions"],
    },

    {
      id: "notifications",
      title: "How to manage notifications",
      summary:
        "What the system has told you, and how to choose what you keep being told — including the alerts that arrive nowhere else.",
      feature: "Notifications",
      learn: [
        "Where to read your alerts",
        "Which things only ever arrive here",
        "How to change what you receive",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Notifications** has two tabs: **Feed**, what the system has told you, and **Preferences**, what you want to keep being told.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/notifications.webp",
            alt: "The Notifications screen showing the Feed tab with alerts about a scheduled exam, a new quiz, a new assignment and a graded submission, with Mark all read and Unread only controls.",
            caption: "Your feed. Each alert can be marked read individually, or all at once.",
          },
        },
        {
          type: "heading",
          text: "What arrives here",
        },
        {
          type: "bullets",
          items: [
            "**You were enrolled** on a class group.",
            "**New work was set** — an assignment or a quiz.",
            "**Your work was graded**, with the score.",
            "**An examination was scheduled**, or its result published.",
            "**A manager or guardian was linked to your account.** This one arrives nowhere else at all — there is no screen that lists it afterwards.",
          ],
        },
        {
          type: "steps",
          items: [
            { text: "Click **Notifications** in the left-hand menu." },
            { text: "Read the **Feed**. Tick **Unread only** to see just what is new." },
            { text: "Click **Mark read** on one, or **Mark all read** to clear the count." },
            { text: "Open **Preferences** to turn individual kinds of alert on or off." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Read before you clear",
            body: "Marking everything read is quick, and it is how people miss the one alert that mattered. Being linked to a manager or guardian is announced here once and never repeated.",
          },
        },
      ],
      result: "The unread count in the top bar goes down, and you have not missed anything.",
      tips: [
        "If you are getting too many alerts, turn some off in **Preferences** rather than ignoring the lot.",
      ],
      related: ["if-linked", "messages", "dashboard"],
    },

    {
      id: "shared-with-me",
      title: "How to find files shared with you",
      summary: "Course material your tutors have shared.",
      feature: "Shared with me",
      learn: ["Where shared files appear"],
      body: [
        {
          type: "paragraph",
          text: "**Shared with me** lists files that your tutors and administrators have shared with you — course notes, a reading list, a worked example.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/shared-with-me.webp",
            alt: "The Shared resources screen displaying files shared by tutors and administrators.",
            caption: "Files shared with you. Empty simply means nothing has been shared yet.",
          },
        },
        {
          type: "paragraph",
          text: "Click a file to open it. If you are expecting something that is not here, ask your tutor — sharing is a step they take deliberately.",
        },
      ],
      result: "You can open, download, and review shared learning assets whenever needed.",
      related: ["messages", "course"],
    },
  ],
};
