import type { Section } from "../types";

/** Files, notices, conversations and alerts. */
export const contentCommunity: Section = {
  id: "content-community",
  title: "Files and communication",
  blurb: "Share files, post notices, run discussions, send messages and manage alerts.",
  articles: [
    {
      id: "resources",
      title: "How to share files and folders",
      summary: "Upload files and share them with a course, a batch, a session or a person.",
      feature: "Resources",
      learn: ["How the library is organised", "How to add a file", "Who can see what you share"],
      body: [
        {
          type: "paragraph",
          text: "**Resources** is the file library. You can organise files in folders and share them with a whole course, one batch, one session, or named people.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/resources.webp",
            alt: "The Resources screen showing the library, a search box, a type filter and the New button.",
            caption: "The file library.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Resources** in the left-hand menu." },
            { text: "Click **New** to add a file or create a folder." },
            { text: "Choose the file from your computer or phone." },
            { text: "Choose who it is shared with." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Share with the batch, not with each student",
            body: "Sharing with a batch means new students get the file automatically when they join. Sharing with named people does not.",
          },
        },
        { type: "heading", text: "Find a file" },
        {
          type: "bullets",
          items: [
            "Type into **Search this library**.",
            "Use **Any type** to show only documents, only images, and so on.",
          ],
        },
      ],
      result: "The file appears in the library and the people you shared it with can open it.",
      tips: [
        "Give files meaningful names. 'Week 3 — SQL joins.pdf' is far more useful than 'notes.pdf'.",
      ],
      related: ["shared-with-me", "batches"],
    },

    {
      id: "shared-with-me",
      title: "How to find files shared with you",
      summary: "Everything your colleagues have shared with you, in one place.",
      feature: "Shared with me",
      learn: ["Where to find files other people shared with you"],
      body: [
        {
          type: "paragraph",
          text: "**Shared with me** lists files that tutors and administrators have shared with you. It is separate from **Resources**, which is the whole library.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/shared-with-me.webp",
            alt: "The Shared resources screen.",
            caption: "Files shared with you specifically.",
          },
        },
        {
          type: "paragraph",
          text: "Click a file to open it. If the screen is empty, nothing has been shared with you yet — that is normal for an administrator, who usually shares rather than receives.",
        },
      ],
      related: ["resources"],
    },

    {
      id: "announcements",
      title: "How to post an announcement",
      summary: "Put a notice in front of students, with a start and end date.",
      feature: "Announcements",
      learn: ["How to post a notice", "How to control who sees it and for how long"],
      body: [
        {
          type: "paragraph",
          text: "An **announcement** is a notice shown to people inside the system. It has a display window: outside that window it is stored but not shown.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/announcements.webp",
            alt: "The Announcements screen with the New announcement button.",
            caption: "Announcements.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Announcements** in the left-hand menu." },
            { text: "Click **New announcement**." },
            {
              text: "Type a **Title** and the **Message**. Both are required.",
              image: {
                src: "super-admin/dialog-new-announcement.webp",
                alt: "The New announcement form showing Title, Message, Course, Batch, Role, Show from, Show until and Pin to the top.",
                caption:
                  "Leave the window blank to publish now and never expire.",
              },
            },
            {
              text: "Narrow who sees it with **Course**, **Batch** or **Role**.",
              note: "Leave all three blank to show it to everybody.",
            },
            {
              text: "Set **Show from** and **Show until** if it should appear and disappear automatically.",
            },
            { text: "Tick **Pin to the top of the feed** for something important." },
            { text: "Click **Post announcement**." },
          ],
        },
      ],
      result: "The announcement appears for the people you chose, within its window.",
      tips: [
        "Use **Show until** for anything time-limited, such as an exam reminder. It tidies itself up.",
        "Pin sparingly. If everything is pinned, nothing stands out.",
      ],
      problems: [
        {
          symptom: "Nobody can see the announcement.",
          fix: "Check **Show from** is not in the future and **Show until** is not in the past.",
        },
      ],
      related: ["notifications", "discussions"],
    },

    {
      id: "discussions",
      title: "How to start a discussion",
      summary: "Course-based conversation threads students and tutors can take part in.",
      feature: "Discussions",
      learn: ["How to start a thread", "What locking a thread does"],
      body: [
        {
          type: "paragraph",
          text: "A **discussion** is a conversation thread attached to a course. Everybody who can see the course can read it.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/discussions.webp",
            alt: "The Discussions screen with a search box, a course filter and the Start a discussion button.",
            caption: "Discussions, grouped by course.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Discussions** in the left-hand menu." },
            { text: "Click **Start a discussion**." },
            {
              text: "Choose the **Course**, type a **Title**, and write the **Opening post**. All three are required.",
              image: {
                src: "super-admin/dialog-new-discussion.webp",
                alt: "The Start a discussion form showing Course, Title and Opening post.",
                caption: "Discussions belong to a course.",
              },
            },
            { text: "Click **Start discussion**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Locking keeps the conversation readable",
            body: "A locked thread can still be read but takes no new replies. Use it when a question has been answered, instead of deleting it.",
          },
        },
      ],
      result: "The thread appears under that course and people can reply.",
      related: ["announcements", "messages"],
    },

    {
      id: "messages",
      title: "How to send a message",
      summary: "Write to people you teach or administer, without seeing their email address.",
      feature: "Messages",
      learn: ["How to send a message", "What the folders are"],
      body: [
        {
          type: "paragraph",
          text: "**Messages** is the internal mailbox. You can write to the people you teach and are taught by, and to administrators.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/messages.webp",
            alt: "The Messages screen with Inbox, Starred, Sent and Drafts folders, a search box and the Compose button.",
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
            body: "Messaging works by name. No email address is shown or shared, in either direction.",
          },
        },
      ],
      result: "The message appears in your **Sent** folder and in the recipient's inbox.",
      related: ["notifications", "discussions"],
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
          text: "**Notifications** has two tabs: **Feed**, which is what the system has told you, and **Preferences**, which is what you want to keep being told.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/notifications.webp",
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
      result: "The unread count on the dashboard and in the top bar goes down.",
      tips: [
        "If you are getting too many alerts, turn some off in **Preferences** rather than ignoring the feed entirely.",
      ],
      related: ["messages", "announcements", "dashboard"],
    },
  ],
};
