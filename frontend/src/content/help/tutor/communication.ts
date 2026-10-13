import type { Section } from "../types";

/** Sharing material, talking to students, and the reports a tutor can see. */
export const communication: Section = {
  id: "communication",
  title: "Files, messages and reports",
  blurb: "Share material, post notices, talk to your students, and see how your classes are doing.",
  articles: [
    {
      id: "resources",
      title: "How to share files with your class",
      summary: "Upload material and share it with a course, a batch, a class or a person.",
      feature: "Resources",
      learn: ["How to add a file", "Who to share it with"],
      body: [
        {
          type: "paragraph",
          text: "**Resources** is the file library. Share slides, worksheets and reading with the people you teach.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/resources.webp",
            alt: "A tutor's Resources screen with a search box, a type filter and the New button.",
            caption: "The file library.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Resources** in the left-hand menu." },
            {
              text: "Click **New** and choose what to add.",
              note: "**New** opens a short menu rather than going straight to a form.",
            },
            { text: "Choose the file from your computer or phone." },
            { text: "Choose who it is shared with." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Share with the batch, not with each student",
            body: "Sharing with a batch means anybody who joins later gets the file automatically. Sharing with named people does not.",
          },
        },
        { type: "heading", text: "Files shared with you" },
        {
          type: "paragraph",
          text: "**Shared with me** holds material other people have shared with you — course handbooks, marking guidance and so on.",
        },
      ],
      result: "Your students can open the file from their own account.",
      tips: ["Name files so they make sense later: 'Week 3 — SQL joins.pdf', not 'notes.pdf'."],
      related: ["announcements", "discussions"],
    },

    {
      id: "announcements",
      title: "How to post an announcement",
      summary: "Put a notice in front of your class, with a start and end date.",
      feature: "Announcements",
      learn: ["How to post a notice", "How to control who sees it and for how long"],
      body: [
        {
          type: "paragraph",
          text: "An **announcement** is a notice shown inside the system. It has a display window: outside that window it is stored but not shown.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/announcements.webp",
            alt: "A tutor's Announcements screen with the New announcement button.",
            caption: "Announcements you have posted.",
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
                src: "tutor/dialog-new-announcement.webp",
                alt: "The New announcement form showing Title, Message, Course, Batch, Role, Show from, Show until and Pin to the top.",
                caption: "Leave the window blank to publish now and never expire.",
              },
            },
            {
              text: "Choose the **Course** or **Batch** so only your class sees it.",
              note: "Leaving them blank shows it far more widely than you probably intend.",
            },
            { text: "Set **Show from** and **Show until** if it should appear and disappear by itself." },
            { text: "Tick **Pin to the top of the feed** for something important." },
            { text: "Click **Post announcement**." },
          ],
        },
      ],
      result: "The notice appears for the people you chose, within its window.",
      tips: [
        "Always set a **Batch** or **Course**. An announcement with neither goes much wider than your class.",
        "Use **Show until** for anything time-limited, such as a room change. It tidies itself up.",
      ],
      problems: [
        {
          symptom: "Nobody can see it.",
          fix: "Check **Show from** is not in the future and **Show until** is not in the past.",
        },
      ],
      related: ["discussions", "messages", "resources"],
    },

    {
      id: "discussions",
      title: "How to start a discussion",
      summary: "A conversation thread attached to one of your courses.",
      feature: "Discussions",
      learn: ["How to start a thread", "What locking a thread does"],
      body: [
        {
          type: "paragraph",
          text: "A **discussion** is a thread attached to a course. Everybody who can see the course can read and reply.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/discussions.webp",
            alt: "A tutor's Discussions screen with a search box, a course filter and the Start a discussion button.",
            caption: "Discussions, grouped by course.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Discussions** in the left-hand menu." },
            { text: "Click **Start a discussion**." },
            {
              text: "Choose the **Course**, type a **Title** and write the **Opening post**.",
              image: {
                src: "tutor/dialog-new-discussion.webp",
                alt: "The Start a discussion form showing Course, Title and Opening post.",
                caption: "All three boxes are required.",
              },
            },
            { text: "Click **Start discussion**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Locking keeps the answer visible",
            body: "A locked thread can still be read but takes no new replies. Use it when a question has been answered, instead of deleting it.",
          },
        },
      ],
      result: "The thread appears under that course and students can reply.",
      tips: [
        "Start one thread per topic. One long thread about everything is very hard for students to search.",
      ],
      related: ["announcements", "messages"],
    },

    {
      id: "messages",
      title: "How to send a message",
      summary: "Write to your students and to administrators, without email addresses.",
      feature: "Messages",
      learn: ["How to send a message", "What the folders are"],
      body: [
        {
          type: "paragraph",
          text: "**Messages** is the internal mailbox. You can write to the people you teach, and to administrators.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/messages.webp",
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
          type: "callout",
          callout: {
            kind: "note",
            title: "Nobody's email address is shown",
            body: "Messaging works by name. No email address is shown or shared, in either direction.",
          },
        },
      ],
      result: "The message appears in your **Sent** folder and in the recipient's inbox.",
      related: ["notifications", "announcements"],
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
            src: "tutor/notifications.webp",
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
        "If you get too many alerts, turn some off in **Preferences** rather than ignoring the feed.",
      ],
      related: ["messages", "dashboard"],
    },

    {
      id: "reports",
      title: "How to use reports",
      summary: "Six ready-made reports covering the classes you teach.",
      feature: "Reports",
      learn: ["What each report shows", "Which one to check regularly"],
      body: [
        {
          type: "paragraph",
          text: "**Reports** are figures worked out by the system, covering only what you are allowed to see — your own teaching.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/reports.webp",
            alt: "A tutor's Reports screen showing the Attendance, Enrollment, Performance, Coursework, Distribution and Grading queue tabs.",
            caption: "Six reports, each on its own tab.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Attendance",
              detail: "Present, late, absent and excused counts, and the resulting rate.",
            },
            { term: "Enrollment", detail: "How many students are enrolled, and where." },
            { term: "Performance", detail: "How your students are doing overall." },
            { term: "Coursework", detail: "Assignments set and handed in." },
            { term: "Distribution", detail: "How marks are spread across grades." },
            {
              term: "Grading queue",
              detail: "Work waiting to be marked. The one worth checking every week.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "No export on a tutor account",
            body: "There is no **Export CSV** button for a tutor. If you need a report as a spreadsheet, ask an administrator.",
          },
        },
      ],
      result: "You can see how your classes are doing without opening each student.",
      tips: ["Check **Grading queue** weekly — it is the earliest sign that marking is slipping."],
      related: ["performance", "attendance", "gradebook"],
    },

    {
      id: "academic-setup",
      title: "What Academic setup is for",
      summary: "The reference lists other screens pick from. You can look, not change.",
      feature: "Academic setup",
      learn: ["What this screen is for", "Why you cannot change it"],
      body: [
        {
          type: "paragraph",
          text: "**Academic setup** holds the reference data the rest of the system chooses from: academic years, semesters, departments, course categories and tags.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/academic-setup.webp",
            alt: "The Academic setup screen showing its five tabs, with no add button on a tutor account.",
            caption: "Read-only for a tutor — there is no **Add year** button.",
          },
        },
        {
          type: "paragraph",
          text: "It is useful for checking which academic year is current, or which category a course sits in. Changing any of it belongs to an administrator.",
        },
      ],
      result: "You can check the institution's reference data when you need to.",
      related: ["courses"],
    },
  ],
};
