import type { Section } from "../types";

/** Contacting the school, notices, alerts and the remaining screens. */
export const stayingInTouch: Section = {
  id: "staying-in-touch",
  title: "Staying in touch",
  blurb: "Messages, notices, alerts and files shared with you.",
  articles: [
    {
      id: "messages",
      title: "How to contact the school",
      summary: "Write to tutors and administrators without needing an email address.",
      feature: "Messages",
      learn: ["How to send a message", "What the folders are"],
      body: [
        {
          type: "paragraph",
          text: "**Messages** is the mailbox inside the system. It is how you contact the school about the person you look after.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/messages.webp",
            alt: "The Messages screen with Inbox, Starred, Sent and Drafts folders and the Compose button.",
            caption: "Four folders on the left; the conversation opens on the right.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Messages** in the left-hand menu." },
            { text: "Click **Compose**." },
            { text: "Choose who to write to, type a subject and your message." },
            { text: "Send it." },
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
            body: "Messaging works by name. No email address is shown or shared, in either direction. That is why no screen here shows contact details.",
          },
        },
      ],
      result: "The message appears in your **Sent** folder and in the recipient's inbox.",
      tips: [
        "Say which student you mean and which class. Tutors teach a lot of people.",
        "Messaging through the system keeps the conversation with the course record.",
      ],
      related: ["notifications", "my-team"],
    },

    {
      id: "announcements",
      title: "How to read announcements",
      summary: "Notices from the school.",
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
            src: "guardian/announcements.webp",
            alt: "The Announcements screen showing the feed.",
            caption: "The feed. 'Nothing announced' simply means there are no current notices.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Notices come and go on purpose",
            body: "Each announcement has a window — a date it starts showing and a date it stops. One you saw last week may have expired. That is the school tidying up after itself, not something going wrong.",
          },
        },
      ],
      result: "You have seen whatever the school is currently telling people.",
      related: ["notifications", "messages"],
    },

    {
      id: "notifications",
      title: "How to manage notifications",
      summary: "See what the system has told you, and choose what you keep receiving.",
      feature: "Notifications",
      learn: ["Where to read your alerts", "How to change what you are told about"],
      body: [
        {
          type: "paragraph",
          text: "**Notifications** has two tabs: **Feed**, what the system has told you, and **Preferences**, what you want to keep being told.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/notifications.webp",
            alt: "The Notifications screen showing the Feed and Preferences tabs and the Mark all read button.",
            caption: "The feed, with Preferences on the second tab.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Notifications** in the left-hand menu." },
            { text: "Read the **Feed**." },
            { text: "Click **Mark all read** to clear the count." },
            { text: "Click **Preferences** to turn individual kinds of alert on or off." },
          ],
        },
      ],
      result: "The unread count in the top bar goes down.",
      tips: [
        "If you are getting too many alerts, turn some off in **Preferences** rather than ignoring them all.",
      ],
      related: ["messages", "announcements", "dashboard"],
    },

    {
      id: "shared-with-me",
      title: "How to find files shared with you",
      summary: "Material the school has shared with you.",
      feature: "Shared with me",
      learn: ["Where to find files shared with you"],
      body: [
        {
          type: "paragraph",
          text: "**Shared with me** lists files that tutors and administrators have shared with you — a course outline or a progress summary, for example.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/shared-with-me.webp",
            alt: "The Shared resources screen.",
            caption: "Files shared with you specifically.",
          },
        },
        {
          type: "paragraph",
          text: "Click a file to open it. An empty screen just means nothing has been shared with you yet.",
        },
      ],
      related: ["messages"],
    },

    {
      id: "academic-setup",
      title: "What Academic setup is for",
      summary: "Reference lists you can look at, such as the current academic year.",
      feature: "Academic setup",
      learn: ["What reference lists are displayed", "How the school structures academic years"],
      body: [
        {
          type: "paragraph",
          text: "**Academic setup** holds the school's reference lists: academic years, terms, departments, course categories and tags.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/academic-setup.webp",
            alt: "The Academic setup screen showing reference academic years, semesters, and departments.",
            caption: "Reference lists maintained by the institution.",
          },
        },
        {
          type: "paragraph",
          text: "You will rarely need it. It is occasionally useful for checking which academic year is current. Everything on it belongs to the school to maintain.",
        },
      ],
      related: ["course"],
    },
  ],
};
