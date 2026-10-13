import type { Section } from "../types";

/**
 * Written against the running console signed in as a Corporate Manager.
 *
 * One care point worth recording: the test account also holds the Student
 * role, so it sees a few screens a *pure* corporate manager does not
 * (Announcements, Discussions, Resources, Grading schemes). This guide
 * documents the corporate-manager role only, and the sidebar article says
 * plainly that an account which is also enrolled as a learner sees more.
 */
export const gettingStarted: Section = {
  id: "getting-started",
  title: "Getting started",
  blurb: "Sign in, find your way around, and set up your own account.",
  articles: [
    {
      id: "welcome",
      title: "Welcome — what a corporate manager account can do",
      summary:
        "Follow the staff your company has sent on a course: attendance, work and results.",
      learn: [
        "What your account is for",
        "What you can and cannot do",
        "Why you see some people and not others",
      ],
      body: [
        {
          type: "paragraph",
          text: "This guide is for **corporate managers**. Your company sponsors staff to take courses here, and your account lets you follow how they are getting on.",
        },
        {
          type: "paragraph",
          text: "You do not need any technical knowledge. Every article tells you exactly where to click.",
        },
        { type: "heading", text: "What you can do" },
        {
          type: "definitions",
          items: [
            {
              term: "Follow your people",
              detail:
                "See attendance, assignments, scores and what is coming up for each person in your care.",
            },
            {
              term: "See their courses and classes",
              detail: "The courses they are on, their timetable and their results.",
            },
            {
              term: "Enrol somebody onto a class",
              detail: "From the batch they are joining. This is your one change-making action.",
            },
            {
              term: "Manage your company record",
              detail: "Your organisation's details and its list of employees.",
            },
            { term: "Export reports", detail: "Download figures as a spreadsheet." },
          ],
        },
        { type: "heading", text: "What you cannot do" },
        {
          type: "table",
          columns: ["You cannot", "Who can"],
          rows: [
            ["Create courses, batches or classes", "An administrator"],
            ["Take or change a register", "The tutor"],
            ["Set or mark work", "The tutor"],
            ["Change anybody's marks", "The tutor"],
            ["Decide which students you may see", "An administrator"],
            ["Create user accounts", "An administrator"],
            ["See anybody's email address or phone number", "Nobody, on these screens"],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "You see only the people assigned to you",
            body: "Employing somebody does not, by itself, let you see them. An administrator assigns particular students to you, and those are the only ones you see — not everybody at your company.",
          },
        },
      ],
      tips: [
        "Start with **My team**. It answers most questions in one screen.",
      ],
      related: ["sign-in", "dashboard", "my-team", "manager-assignments"],
    },

    {
      id: "sign-in",
      title: "How to sign in",
      summary: "Open the system and sign in with your username and password.",
      feature: "Sign in",
      learn: ["How to sign in", "What to do if your password does not work"],
      before: [
        "The web address of the LMS.",
        "Your username or the email address on your account.",
        "Your password.",
      ],
      body: [
        {
          type: "steps",
          items: [
            { text: "Open your web browser." },
            { text: "Type the address of the LMS and press **Enter**." },
            { text: "In the **Username or email** box, type your username or email address." },
            { text: "In the **Password** box, type your password." },
            { text: "Click **Sign in**." },
          ],
        },
      ],
      result: "Your dashboard opens and your name appears in the top right corner.",
      tips: ["Passwords are case sensitive. Check Caps Lock before trying again."],
      problems: [
        {
          symptom: "It says your username or password is wrong.",
          fix: "Type it again slowly with Caps Lock off. If it still fails, ask the training provider to reset your password.",
        },
        {
          symptom: "It says your account is locked.",
          fix: "Too many wrong passwords lock an account for a while. Wait a few minutes, or ask the training provider to unlock it.",
        },
      ],
      related: ["dashboard", "account"],
    },

    {
      id: "dashboard",
      title: "Understanding your dashboard",
      summary: "The first screen you see, and what each number means.",
      feature: "Dashboard",
      learn: ["What each panel shows", "How to see your people's next classes"],
      body: [
        {
          type: "paragraph",
          text: "Your dashboard is the first screen after you sign in. Click **Dashboard** at the top of the left-hand menu to come back to it.",
        },
        {
          type: "screenshot",
          image: {
            src: "corporate-manager/dashboard.webp",
            alt: "A corporate manager's dashboard showing people in your care, attendance, overdue assignments and their next sessions.",
            caption:
              "A corporate manager's dashboard. The panels are about the people in your care.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Unread messages and notifications", detail: "Anything waiting for you." },
            {
              term: "Your timezone",
              detail: "All times are shown in this timezone. Check it if times look wrong.",
            },
            { term: "People", detail: "How many people are in your care." },
            {
              term: "Attendance",
              detail: "How often, on average, your people have turned up.",
            },
            {
              term: "Overdue assignments",
              detail: "Work your people were due to hand in and have not. Worth watching.",
            },
            {
              term: "Their next sessions",
              detail:
                "The classes coming up, with how soon. A **Join class** button appears when one is running.",
            },
          ],
        },
      ],
      result: "You can see at a glance whether anybody needs chasing.",
      tips: [
        "**Overdue assignments** is usually the first sign that somebody is falling behind.",
      ],
      related: ["my-team", "attendance", "sidebar"],
    },

    {
      id: "sidebar",
      title: "Understanding the left-hand menu",
      summary: "What each group contains, and why you may see more than this guide covers.",
      feature: "Navigation",
      learn: ["How the menu is organised", "Why your menu may have extra items"],
      body: [
        {
          type: "paragraph",
          text: "The menu on the left is how you move around. You see only the screens your account can open.",
        },
        {
          type: "table",
          columns: ["Group", "What is in it"],
          rows: [
            ["Overview", "Dashboard."],
            ["Learning", "Courses, Batches, Timetable, Enrollments, Attendance."],
            [
              "Assessment",
              "Assignments, Quizzes, Examinations, Grade book, Performance, Transcripts.",
            ],
            ["Content", "Shared with me."],
            ["Community", "Messages, Notifications."],
            ["People", "My team, Organizations, Manager assignments."],
            ["Administration", "Academic setup (you can look, not change)."],
            ["Insights", "Reports."],
            ["Help", "This user guide."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "You may see more than this list",
            body: "Some people hold a second role — for example, a manager who is also taking a course is a learner too. If you are enrolled as a student as well, you will also see Announcements, Discussions and Resources. Those belong to your learner account, and the Student guide covers them.",
          },
        },
        { type: "heading", text: "On a phone or tablet" },
        {
          type: "paragraph",
          text: "On a small screen the menu is hidden. Tap the menu button in the top left corner to open it.",
        },
      ],
      related: ["dashboard", "welcome"],
    },

    {
      id: "account",
      title: "How to update your profile and password",
      summary: "Change your picture, your details, your password and your timezone.",
      feature: "My account",
      learn: ["How to change your own details", "How to change your password", "How to sign out"],
      body: [
        {
          type: "paragraph",
          text: "Click your name in the top right corner and choose **My account**.",
        },
        { type: "heading", text: "Change your details" },
        {
          type: "steps",
          items: [
            { text: "Edit any box, such as your phone number." },
            { text: "Click **Save changes**." },
            { text: "Click **Discard** to undo changes you have not saved." },
          ],
        },
        { type: "heading", text: "Change your password" },
        {
          type: "steps",
          items: [
            { text: "Scroll down to the password section." },
            { text: "Type your current password." },
            { text: "Type your new password twice." },
            { text: "Click **Change password**." },
          ],
        },
        { type: "heading", text: "Sign out" },
        {
          type: "paragraph",
          text: "Click your name in the top right corner and choose **Sign out**. **Sign out everywhere** ends your session on every device.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Always sign out on a shared computer",
            body: "Closing the browser window is not the same as signing out.",
          },
        },
      ],
      result: "Your new details appear straight away.",
      tips: ["If times look wrong to you, check your timezone on this screen first."],
      related: ["sign-in", "dashboard"],
    },
  ],
};
