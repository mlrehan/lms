import type { Section } from "../types";

/**
 * Written against the running console signed in as a Tutor. Everything a
 * Tutor cannot reach is left out: there are no articles here for Users,
 * Roles, Permissions, Organizations, Guardians, Manager assignments,
 * Integrations, System settings, Audit log, Security or Operations, because
 * a Tutor account cannot open any of them.
 */
export const gettingStarted: Section = {
  id: "getting-started",
  title: "Getting started",
  blurb: "Sign in, find your way around, and set up your own account.",
  articles: [
    {
      id: "welcome",
      title: "Welcome — what a tutor account can do",
      summary: "What you can do as a tutor, and what you will not be able to do.",
      learn: [
        "What your tutor account is for",
        "Teaching workflows & academic administration",
        "How this guide is organised",
      ],
      body: [
        {
          type: "paragraph",
          text: "This guide is for **tutors**. Your account is built around teaching: the classes you run, the students on them, the work you set, and the marks you give.",
        },
        {
          type: "paragraph",
          text: "You do not need any technical knowledge. Every article tells you where to click and what to type.",
        },
        { type: "heading", text: "What you can do" },
        {
          type: "definitions",
          items: [
            {
              term: "See your classes",
              detail:
                "Your courses, your batches, your timetable and the students enrolled on them.",
            },
            {
              term: "Take the register",
              detail: "Mark who was present at each class.",
            },
            {
              term: "Set and mark work",
              detail:
                "Create assignments, build quizzes, schedule examinations, and record marks in the grade book.",
            },
            {
              term: "See how students are doing",
              detail: "Performance for each batch, and reports across your teaching.",
            },
            {
              term: "Communicate",
              detail: "Share files, post announcements, start discussions and send messages.",
            },
          ],
        },
        { type: "heading", text: "Academic Administration & Faculty Collaboration" },
        {
          type: "definitions",
          items: [
            {
              term: "Curriculum & Batch Provisioning",
              detail:
                "Course outlines, batch schedules, and academic calendars are configured by the Academic Office so faculty can focus entirely on teaching and assessment.",
            },
            {
              term: "Official Student Registration",
              detail:
                "Cohort admissions, transfers, and official withdrawals are administered by Registry to ensure student records meet institutional accreditation standards.",
            },
            {
              term: "Accredited Grading Standards",
              detail:
                "Official grading schemes and degree transcripts are governed institution-wide by Academic Affairs to guarantee grading consistency.",
            },
            {
              term: "Faculty Administrative Requests",
              detail:
                "Need an extra class scheduled, an assignment date extended, or cohort reporting generated? Contact the Academic Office for immediate assistance.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "You only ever see your own teaching",
            body: "Your courses, batches, students and timetable are limited to the ones you teach. Another tutor's classes are not shown to you, and yours are not shown to them.",
          },
        },
      ],
      tips: [
        "Use the search box at the top of this guide if you know the name of the screen you need.",
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
        "The web address of your LMS.",
        "Your username or the email address on your account.",
        "Your password.",
      ],
      body: [
        {
          type: "steps",
          items: [
            { text: "Open your web browser." },
            { text: "Type the address of your LMS and press **Enter**." },
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
          symptom: "Username or password not recognized.",
          fix: "Type your credentials carefully with Caps Lock off. If you require a password reset, use the self-service reset or contact IT support.",
        },
        {
          symptom: "Temporary security lockout.",
          fix: "Repeated invalid attempts initiate a standard security pause. Wait a few moments, or contact IT support for immediate unlocking.",
        },
      ],
      related: ["dashboard", "account"],
    },

    {
      id: "dashboard",
      title: "Understanding your dashboard",
      summary: "The first screen you see, and what each number means.",
      feature: "Dashboard",
      learn: ["What each panel shows", "How to find your next class"],
      body: [
        {
          type: "paragraph",
          text: "Your dashboard is the first screen after you sign in. Click **Dashboard** at the top of the left-hand menu to come back to it.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/dashboard.webp",
            alt: "A tutor's dashboard showing unread messages, notifications, timezone, teaching batches, students and work awaiting grading.",
            caption: "A tutor's dashboard. The panels are about your teaching.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Unread messages", detail: "Messages waiting for you." },
            { term: "Unread notifications", detail: "Alerts you have not read." },
            { term: "Live announcements", detail: "Notices currently being shown." },
            {
              term: "Your timezone",
              detail:
                "All times on screen are shown in this timezone. Check it if times look wrong.",
            },
            { term: "Your teaching batches", detail: "How many groups you currently teach." },
            { term: "Students", detail: "How many students are on those groups in total." },
            {
              term: "Awaiting grading",
              detail: "Work handed in that you have not marked yet. Check this one often.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "A **Join class** button appears on the dashboard when one of your online classes is running.",
          },
        },
      ],
      result: "You can see at a glance what needs your attention today.",
      related: ["timetable", "attendance", "sidebar"],
    },

    {
      id: "sidebar",
      title: "Understanding the left-hand menu",
      summary: "What each group in the menu contains, so you can find any screen.",
      feature: "Navigation",
      learn: ["How the menu is organised", "Where to find each screen"],
      body: [
        {
          type: "paragraph",
          text: "The menu on the left is how you move around. You see only the screens your tutor account can open.",
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
            ["Administration", "Academic setup (you can look, not change)."],
            ["Insights", "Reports."],
            ["Help", "This user guide."],
          ],
        },
        { type: "heading", text: "On a phone or tablet" },
        {
          type: "paragraph",
          text: "On a small screen the menu is hidden. Tap the menu button in the top left corner to open it.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Search is faster than the menu",
            body: "Press Ctrl and K together (Cmd and K on a Mac) to open the search box at the top of the screen.",
          },
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
        {
          type: "screenshot",
          image: {
            src: "tutor/account.webp",
            alt: "The My account screen showing the profile picture, personal details and password sections.",
            caption: "My account. Your details are at the top; the password is further down.",
          },
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
        { type: "heading", text: "Your picture" },
        {
          type: "paragraph",
          text: "Use **Replace picture** to change it, or **Remove** to go back to your initials.",
        },
        { type: "heading", text: "Sign out" },
        {
          type: "paragraph",
          text: "Click your name in the top right corner and choose **Sign out**. **Sign out everywhere** ends your session on every device — use it if you think somebody else knows your password.",
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
      problems: [
        {
          symptom: "The password change is refused.",
          fix: "Check your current password is right, and that the two new password boxes match exactly.",
        },
      ],
      related: ["sign-in", "dashboard"],
    },
  ],
};
