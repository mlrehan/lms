import type { Section } from "../types";

/**
 * The first six articles. Everything here was checked against the running
 * console signed in as a Super Admin; no feature, button or label is written
 * down that was not seen on screen.
 */
export const gettingStarted: Section = {
  id: "getting-started",
  title: "Getting started",
  blurb: "Sign in, find your way around, and set up your own account.",
  articles: [
    {
      id: "welcome",
      title: "Welcome to the LMS",
      summary:
        "What a Super Admin account can do, and how this guide is organised.",
      learn: [
        "What the Super Admin role is for",
        "What you are able to do that other people cannot",
        "How to find the right article quickly",
      ],
      body: [
        {
          type: "paragraph",
          text: "This is the guide for people with a **Super Admin** account. A Super Admin can see and change everything in the system. You look after the whole institution: the people, the courses, the timetable, the marks and the settings.",
        },
        {
          type: "paragraph",
          text: "You do not need any technical knowledge to use this guide. Every article tells you exactly where to click and what to type. If you have never used a system like this before, start with **How to sign in** and then read **Understanding your dashboard**.",
        },
        { type: "heading", text: "What you can do" },
        {
          type: "definitions",
          items: [
            {
              term: "Teach and schedule",
              detail:
                "Create courses, open batches (a group of students taking a course together), build the timetable and record attendance.",
            },
            {
              term: "Assess and grade",
              detail:
                "Set assignments, build quizzes, schedule examinations, record marks in the grade book, and produce transcripts.",
            },
            {
              term: "Manage people",
              detail:
                "Create accounts, decide what each person is allowed to do, and link guardians and corporate managers to the students they look after.",
            },
            {
              term: "Run the system",
              detail:
                "Change settings, connect outside services, import data, and check the history of everything that has happened.",
            },
          ],
        },
        { type: "heading", text: "Who else uses the system" },
        {
          type: "paragraph",
          text: "Other people see much less than you do. The system decides what each person can see from their **role**:",
        },
        {
          type: "table",
          columns: ["Role", "What they mainly do"],
          rows: [
            ["Super Admin", "Everything. That is you."],
            ["Administrator", "Day-to-day running of the academic office."],
            ["Tutor", "Teaches batches, marks work, takes attendance."],
            ["Corporate Manager", "Follows the staff their company has sent on a course."],
            ["Guardian", "Follows the progress of a child or family member."],
            ["Student", "Takes courses, hands in work, sees their own results."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "This guide is for Super Admins only",
            body: "Other roles have their own guides. A Tutor or a Student will not see many of the screens shown here, so sending them this guide will confuse them.",
          },
        },
      ],
      tips: [
        "Use the search box at the top of the guide if you know the name of the screen you need.",
        "Every article ends with links to related articles, so you can follow a whole task from start to finish.",
      ],
      related: ["sign-in", "dashboard", "sidebar"],
    },

    {
      id: "sign-in",
      title: "How to sign in",
      summary: "Open the system and sign in with your username and password.",
      feature: "Sign in",
      learn: ["How to sign in", "What to do if your password does not work"],
      before: [
        "The web address of your LMS (your administrator will have given you this).",
        "Your username or the email address on your account.",
        "Your password.",
      ],
      body: [
        {
          type: "steps",
          items: [
            { text: "Open your web browser." },
            { text: "Type the address of your LMS and press **Enter**." },
            {
              text: "In the **Username or email** box, type your username or your email address.",
            },
            { text: "In the **Password** box, type your password." },
            {
              text: "Click **Sign in**.",
              note: "If you are on your own computer, you can tick the box to stay signed in for longer.",
            },
          ],
        },
      ],
      result:
        "The dashboard opens and your name appears in the top right corner of the screen.",
      tips: [
        "Passwords are case sensitive. 'Summer2026' and 'summer2026' are different.",
        "Never share your password. A Super Admin account can change anything, so it is the most important account to keep safe.",
      ],
      problems: [
        {
          symptom: "It says your username or password is wrong.",
          fix: "Check that Caps Lock is off and type the password again slowly. If it still fails, ask another Super Admin to reset it for you.",
        },
        {
          symptom: "It says your account is locked.",
          fix: "Too many wrong passwords lock an account for a while. Wait, or ask another Super Admin to unlock it on the **Security** screen.",
        },
        {
          symptom: "You are signed out again as soon as you click something.",
          fix: "Your session has expired. Sign in again. If it keeps happening, your computer's clock may be wrong.",
        },
      ],
      related: ["dashboard", "account", "security"],
    },

    {
      id: "dashboard",
      title: "Understanding your dashboard",
      summary:
        "The first screen you see, what each number means, and the data synchronisation panel.",
      feature: "Dashboard",
      learn: [
        "What each panel on the dashboard shows",
        "What the data synchronisation panel is for",
      ],
      body: [
        {
          type: "paragraph",
          text: "The dashboard is the first screen after you sign in. You can return to it at any time by clicking **Dashboard** at the top of the left-hand menu.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/dashboard.webp",
            alt: "The Super Admin dashboard, showing the data synchronisation panel at the top and number panels underneath.",
            caption:
              "The dashboard. The panels you see depend on what your role lets you see — as a Super Admin you see all of them.",
          },
        },
        { type: "heading", text: "The panels" },
        {
          type: "definitions",
          items: [
            {
              term: "Data synchronisation",
              detail:
                "Brings people, courses, batches, sessions and enrolments in from the LAIT system. See the article on importing data.",
            },
            {
              term: "Unread messages and notifications",
              detail: "Anything waiting for you personally.",
            },
            {
              term: "Live announcements",
              detail: "Notices currently being shown to people.",
            },
            {
              term: "Your timezone",
              detail:
                "All times on screen are shown in this timezone. Times are stored the same way for everybody and only displayed in yours.",
            },
            {
              term: "Institution",
              detail:
                "Totals for the whole institution: active users, published courses, active batches, attendance over the last 30 days, confirmed enrolments and work waiting to be marked.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "The number of submissions awaiting grading is the quickest way to see whether marking is falling behind.",
          },
        },
      ],
      result: "You can tell at a glance how the institution is doing today.",
      related: ["sidebar", "sync-data", "notifications"],
    },

    {
      id: "sidebar",
      title: "Understanding the left-hand menu",
      summary: "What each group in the menu contains, so you can find any screen.",
      feature: "Navigation",
      learn: ["How the menu is organised", "Which group holds the screen you want"],
      body: [
        {
          type: "paragraph",
          text: "The menu on the left is how you move around. It is split into groups. You only ever see the groups your role allows — as a Super Admin you see all of them.",
        },
        {
          type: "table",
          columns: ["Group", "What is in it"],
          rows: [
            ["Overview", "Dashboard."],
            ["Learning", "Courses, Batches, Timetable, Enrollments, Attendance."],
            [
              "Assessment",
              "Assignments, Quizzes, Examinations, Grade book, Performance, Transcripts, Grading schemes.",
            ],
            ["Content", "Resources, Shared with me."],
            ["Community", "Announcements, Discussions, Messages, Notifications."],
            [
              "People",
              "My team, Users, Roles, Permissions, Organizations, Guardians, Manager assignments.",
            ],
            ["Administration", "Academic setup, Integrations, System settings."],
            ["Insights", "Reports, Audit log, Security, Operations."],
            ["Help", "This user guide."],
          ],
        },
        { type: "heading", text: "On a phone or tablet" },
        {
          type: "paragraph",
          text: "On a small screen the menu is hidden to leave room for the page. Tap the menu button in the top left corner to open it, and tap any item to go there.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Search is faster than the menu",
            body: "Press Ctrl and K together (Cmd and K on a Mac) to open the search box at the top of the screen, then type what you are looking for.",
          },
        },
      ],
      related: ["dashboard", "welcome"],
    },

    {
      id: "account",
      title: "How to update your profile and password",
      summary:
        "Change your picture, your details, your password and how the system looks.",
      feature: "My account",
      learn: [
        "How to change your own details",
        "How to change your password",
        "How to change the timezone and appearance",
      ],
      before: ["You must be signed in. You can always edit your own account."],
      body: [
        {
          type: "paragraph",
          text: "Open your account screen by clicking your name in the top right corner and choosing **My account**.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/account.webp",
            alt: "The My account screen with the profile picture, personal details and password sections.",
            caption:
              "My account. Personal details are at the top; the password and appearance settings are further down.",
          },
        },
        { type: "heading", text: "Change your details" },
        {
          type: "steps",
          items: [
            { text: "Edit any of the boxes, such as your first name or phone number." },
            { text: "Click **Save changes**." },
            {
              text: "If you change your mind before saving, click **Discard**.",
              note: "Discard puts every box back to how it was when you opened the screen.",
            },
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
        { type: "heading", text: "Change your picture" },
        {
          type: "steps",
          items: [
            { text: "Click **Upload picture**." },
            { text: "Choose an image from your computer or phone." },
          ],
        },
        { type: "heading", text: "Sign out of every device" },
        {
          type: "paragraph",
          text: "**Sign out everywhere** ends your session on every computer and phone you have used. Use it if you think somebody else has your password, or if you signed in on a shared computer and forgot to sign out.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            body: "Sign out everywhere signs you out here too. You will have to sign in again.",
          },
        },
      ],
      result:
        "Your new details appear straight away, and your name updates in the top right corner.",
      tips: [
        "Choose a long password you can remember rather than a short complicated one.",
        "If times look wrong to you, check the timezone on this screen before changing anything else.",
      ],
      problems: [
        {
          symptom: "The password change is refused.",
          fix: "Check that your current password is right, and that the two new password boxes match exactly.",
        },
        {
          symptom: "Your picture does not appear.",
          fix: "Very large images can fail to upload. Try a smaller picture.",
        },
      ],
      related: ["sign-in", "sign-out", "security"],
    },

    {
      id: "sign-out",
      title: "How to sign out",
      summary: "Leave the system safely when you have finished.",
      feature: "Sign out",
      learn: ["How to sign out", "When to use Sign out everywhere"],
      body: [
        {
          type: "steps",
          items: [
            { text: "Click your name in the top right corner of the screen." },
            { text: "Click **Sign out**." },
          ],
        },
        {
          type: "paragraph",
          text: "You are returned to the sign-in screen. Nobody can use your account again without your password.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Always sign out on a shared computer",
            body: "Closing the browser window is not the same as signing out. If you were on a library or office computer, sign out properly.",
          },
        },
      ],
      result: "You see the sign-in screen again.",
      related: ["account", "sign-in"],
    },
  ],
};
