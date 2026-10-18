import type { Section } from "../types";

/** Communication, announcements, discussions, and shared resources for corporate managers. */
export const communication: Section = {
  id: "communication",
  title: "Communication and Community",
  blurb: "Direct messaging, announcements, course discussions, notifications, and shared files.",
  articles: [
    {
      id: "announcements",
      title: "How to read institute announcements",
      summary: "Stay informed with institutional updates, academic notices, and scheduling changes.",
      feature: "Announcements",
      learn: [
        "How to browse announcements",
        "How to distinguish pinned priority updates",
        "When to check the announcement feed",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Announcements** serves as the official broadcast channel for the training institute. Administrators and lead instructors post key scheduling changes, holiday schedules, examination notices, and system-wide updates here.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/announcements.webp",
            alt: "The Announcements screen displaying broadcasts and notifications from instructors and administrators.",
            caption: "Official broadcast feed displaying institute-wide and cohort announcements.",
          },
        },
        { type: "heading", text: "Browsing and reviewing announcements" },
        {
          type: "steps",
          items: [
            { text: "Click **Announcements** under the **Community** group in the left-hand menu." },
            { text: "Review the chronological list of published announcements." },
            {
              text: "Notice pinned announcements anchored at the top of the feed for critical, time-sensitive operational notices.",
            },
            {
              text: "Click an announcement title to view full details, including publishing instructor, timestamp, and target cohort details.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Proactive cohort monitoring",
            body: "Review Announcements weekly before Monday morning sessions to stay ahead of upcoming examination deadlines or scheduled timetable shifts.",
          },
        },
      ],
      result: "You stay completely aligned with institutional dates and instructor announcements.",
      tips: [
        "Major timetable shifts or campus closures are announced here first before session updates appear on the timetable.",
      ],
      related: ["notifications", "messages", "timetable"],
    },

    {
      id: "discussions",
      title: "How to participate in course discussions",
      summary: "Engage in academic discussions, monitor course Q&A, and support team collaboration.",
      feature: "Discussions",
      learn: [
        "How to find course discussion topics",
        "How to post replies and managerial insights",
        "How discussion participation enriches learning",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Discussions** provides collaborative forum spaces attached to training courses. Learners, instructors, and managers can ask clarifying questions, share contextual industry case studies, and discuss practical exercises.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/discussions.webp",
            alt: "The Discussions forum screen showing topics, replies, and course dialogs.",
            caption: "Collaborative forum workspace where course questions and insights are discussed.",
          },
        },
        { type: "heading", text: "Navigating forum topics" },
        {
          type: "steps",
          items: [
            { text: "Click **Discussions** in the left-hand menu." },
            { text: "Select a topic thread to review questions and answers from instructors and peers." },
            {
              text: "Add comments or managerial guidance when relevant to reinforce corporate learning objectives.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Peer learning visibility",
            body: "Discussion threads are visible to all learners enrolled in the course. Keep communications focused on course concepts and collaborative problem solving.",
          },
        },
      ],
      result: "You can track employee engagement in peer discussions and reinforce academic concepts.",
      related: ["courses", "batches", "messages"],
    },

    {
      id: "messages",
      title: "How to use internal messages",
      summary: "Communicate securely with tutors, training coordinators, and employees in your care.",
      feature: "Messages",
      learn: [
        "How to compose and send messages",
        "How conversation folders are organized",
        "How identity and corporate data privacy are protected",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Messages** is the internal Care-Circle communication console. It allows you to communicate directly with instructors, program coordinators, and individual team members without exposing personal phone numbers or off-platform contact details.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/messages.webp",
            alt: "The Messages screen with Inbox, Starred, Sent, and Drafts folders alongside the Compose action.",
            caption: "Four communication folders on the left; the selected conversation thread opens on the right.",
          },
        },
        { type: "heading", text: "Composing and sending a message" },
        {
          type: "steps",
          items: [
            { text: "Click **Messages** under the **Community** group in the left-hand menu." },
            { text: "Click the **Compose** button at the top of the mailbox navigation." },
            {
              text: "Choose the recipient from the directory picker (tutor, training coordinator, or managed employee).",
            },
            { text: "Enter a clear, descriptive subject line and your message content." },
            { text: "Click **Send** to transmit the message immediately." },
          ],
        },
        {
          type: "definitions",
          items: [
            { term: "Inbox", detail: "Incoming messages from tutors, coordinators, and employees." },
            {
              term: "Starred",
              detail: "Priority messages you have flagged for rapid follow-up or administrative auditing.",
            },
            { term: "Sent", detail: "Archived record of all dispatched managerial messages." },
            { term: "Drafts", detail: "In-progress communications saved prior to transmission." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Enterprise privacy safeguards",
            body: "The internal messaging console operates purely on system names and corporate roles. Personal email addresses and private phone numbers are strictly protected, safeguarding institutional data privacy.",
          },
        },
      ],
      result: "Your message is delivered immediately to the recipient's internal inbox with complete audit traceability.",
      tips: [
        "Conducting training-related conversations inside LMS Messages creates an immutable audit trail tied to cohort enrollment records.",
      ],
      related: ["notifications", "my-team", "announcements"],
    },

    {
      id: "notifications",
      title: "How to manage notifications and alert preferences",
      summary: "Review real-time system alerts and configure your event delivery preferences.",
      feature: "Notifications",
      learn: [
        "Where to read incoming operational alerts",
        "How to mark all notifications as read",
        "How to toggle alert categories in Preferences",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Notifications** centralizes all automated system alerts, including assignment submission updates, grading notifications, attendance risk alerts, and timetable updates.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/notifications.webp",
            alt: "The Notifications screen showing Feed and Preferences tabs with a Mark all read button.",
            caption: "Activity feed with customizable delivery preferences on the secondary tab.",
          },
        },
        { type: "heading", text: "Managing your notification feed" },
        {
          type: "steps",
          items: [
            { text: "Click **Notifications** in the left-hand menu." },
            {
              text: "Inspect the **Feed** tab to review real-time alerts arranged chronologically.",
            },
            {
              text: "Click **Mark all read** in the top action bar to reset your unread indicator count.",
            },
            {
              text: "Switch to the **Preferences** tab to configure which categories trigger instant alerts (e.g., assignment submissions, attendance flags, system announcements).",
            },
          ],
        },
      ],
      result: "Your notification feed reflects current alerts, and your unread badge clears immediately.",
      tips: [
        "Keep attendance risk and examination alert notifications enabled to maintain proactive workforce oversight.",
      ],
      related: ["messages", "dashboard"],
    },

    {
      id: "shared-with-me",
      title: "How to access files shared with you",
      summary: "Review curriculum resources, corporate syllabi, and reports shared by training coordinators.",
      feature: "Shared with me",
      learn: [
        "Where to locate shared documents and syllabi",
        "How to download or preview shared learning materials",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Shared with me** acts as an institutional document repository. Training coordinators and instructors use it to provide corporate managers with cohort syllabi, accreditation frameworks, custom enterprise training agreements, and executive summary slide decks.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/shared-with-me.webp",
            alt: "The Shared with me resource library showing files and documents shared by tutors and administrators.",
            caption: "Resource library displaying institutional documents and training materials shared with your account.",
          },
        },
        { type: "heading", text: "Accessing shared resources" },
        {
          type: "steps",
          items: [
            { text: "Click **Shared with me** under the **Content** group in the left-hand menu." },
            { text: "Browse the repository of documents, PDFs, and spreadsheets." },
            {
              text: "Click any document row to preview or download the file directly to your local computer.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Empty repository status",
            body: "If the screen displays no files, no documents have been specifically shared with your corporate account yet. Contact your training account coordinator via Messages if you require specific syllabus copies or program documentation.",
          },
        },
      ],
      result: "You can open, download, and review shared training assets whenever needed.",
      related: ["courses", "reports", "messages"],
    },
  ],
};
