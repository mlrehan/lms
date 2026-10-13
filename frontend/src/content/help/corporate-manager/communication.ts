import type { Section } from "../types";

/** Messages, alerts, shared files, and the reference data a manager can read. */
export const communication: Section = {
  id: "communication",
  title: "Messages and other screens",
  blurb: "Contacting people, alerts, files shared with you, and reference information.",
  articles: [
    {
      id: "messages",
      title: "How to contact somebody",
      summary: "Write to the people in your care and to the training provider.",
      feature: "Messages",
      learn: [
        "How to send a message",
        "What the folders are",
        "Why there are no email addresses",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Messages** is the internal mailbox. It is how you contact the people in your care and the training provider.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/messages.webp",
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
            body: "Messaging works by name. No email address is shown or shared, in either direction. That is why **My team** shows names only.",
          },
        },
      ],
      result: "The message appears in your **Sent** folder and in the recipient's inbox.",
      tips: [
        "Messaging through the system keeps the conversation with the course record, which is useful months later.",
      ],
      related: ["notifications", "my-team"],
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
            src: "corporate-manager/notifications.webp",
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
      related: ["messages", "dashboard"],
    },

    {
      id: "shared-with-me",
      title: "How to find files shared with you",
      summary: "Material the training provider has shared with you.",
      feature: "Shared with me",
      learn: ["Where to find files shared with you"],
      body: [
        {
          type: "paragraph",
          text: "**Shared with me** lists files that tutors and administrators have shared with you, such as course outlines or progress summaries.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/shared-with-me.webp",
            alt: "The Shared resources screen.",
            caption: "Files shared with you specifically.",
          },
        },
        {
          type: "paragraph",
          text: "Click a file to open it. An empty screen simply means nothing has been shared with you yet.",
        },
      ],
      related: ["messages"],
    },

    {
      id: "academic-setup",
      title: "What Academic setup is for",
      summary: "Reference lists you can look at, such as the current academic year.",
      feature: "Academic setup",
      learn: ["What this screen holds", "Why you cannot change it"],
      body: [
        {
          type: "paragraph",
          text: "**Academic setup** holds the reference data the rest of the system uses: academic years, semesters, departments, course categories and tags.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/academic-setup.webp",
            alt: "The Academic setup screen showing its five tabs with no add buttons.",
            caption: "Read-only on your account. There is no add button.",
          },
        },
        {
          type: "paragraph",
          text: "It is occasionally useful for checking which academic year is current, or which category a course sits in. Everything on it belongs to the training provider to maintain.",
        },
      ],
      related: ["courses"],
    },
  ],
};
