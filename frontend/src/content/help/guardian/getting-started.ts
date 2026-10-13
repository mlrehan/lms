import type { Section } from "../types";

/**
 * Written against the running console signed in as a Guardian.
 *
 * There was no guardian account in this environment, so one was created for
 * documentation with the user's approval, linked to an existing student,
 * used for these screenshots, and removed afterwards. Everything described
 * here was seen on screen.
 */
export const gettingStarted: Section = {
  id: "getting-started",
  title: "Getting started",
  blurb: "Sign in, find your way around, and set up your own account.",
  articles: [
    {
      id: "welcome",
      title: "Welcome — what a guardian account is for",
      summary:
        "Follow how the person you look after is getting on with their course.",
      learn: [
        "What your account is for",
        "What you can and cannot do",
        "Why you can see one person and not others",
      ],
      body: [
        {
          type: "paragraph",
          text: "This guide is for **guardians** — a parent, carer or family member who is allowed to follow how somebody's learning is going.",
        },
        {
          type: "paragraph",
          text: "Your account is for watching, not for doing. You can see attendance, work and results. You cannot change any of them, and nothing you do here affects the course.",
        },
        {
          type: "paragraph",
          text: "You do not need any technical knowledge. Every article tells you exactly where to click.",
        },
        { type: "heading", text: "What you can see" },
        {
          type: "definitions",
          items: [
            {
              term: "How they are getting on",
              detail: "Attendance, work handed in, average score and what is coming up next.",
            },
            { term: "Their timetable", detail: "When their classes are." },
            { term: "Their attendance", detail: "Class by class, and who recorded it." },
            { term: "Their work", detail: "Assignments, quizzes and examinations they are set." },
            { term: "Their results", detail: "Marks, overall standing and transcripts." },
            { term: "Notices and messages", detail: "Announcements, and a mailbox for contacting the school." },
          ],
        },
        { type: "heading", text: "What you cannot do" },
        {
          type: "table",
          columns: ["You cannot", "Who can"],
          rows: [
            ["Change attendance, work or marks", "The tutor"],
            ["Hand work in on their behalf", "The student"],
            ["Enrol them on a course", "The school"],
            ["Choose which students you can see", "The school"],
            ["See anybody's email address or phone number", "Nobody, on these screens"],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "You see only the people linked to you",
            body: "Being a parent does not, by itself, let you see somebody here. The school creates a link between your account and theirs, and that link is the only thing that makes them visible to you.",
          },
        },
      ],
      tips: ["Start with **My team**. It answers most questions in one screen."],
      related: ["sign-in", "dashboard", "my-team", "guardians"],
    },

    {
      id: "sign-in",
      title: "How to sign in",
      summary: "Open the system and sign in with your username and password.",
      feature: "Sign in",
      learn: ["How to sign in", "What to do if your password does not work"],
      before: [
        "The web address, which the school will have given you.",
        "Your username or the email address on your account.",
        "Your password.",
      ],
      body: [
        {
          type: "steps",
          items: [
            { text: "Open your web browser." },
            { text: "Type the address the school gave you and press **Enter**." },
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
          fix: "Type it again slowly with Caps Lock off. If it still fails, ask the school to reset your password.",
        },
        {
          symptom: "It says your account is locked.",
          fix: "Too many wrong passwords lock an account for a while. Wait a few minutes, or ask the school to unlock it.",
        },
      ],
      related: ["dashboard", "account"],
    },

    {
      id: "dashboard",
      title: "Understanding your dashboard",
      summary: "The first screen you see, and what each number means.",
      feature: "Dashboard",
      learn: ["What each panel shows", "Where to see the next class"],
      body: [
        {
          type: "paragraph",
          text: "Your dashboard is the first screen after you sign in. Click **Dashboard** at the top of the left-hand menu to come back to it.",
        },
        {
          type: "screenshot",
          image: {
            src: "guardian/dashboard.webp",
            alt: "A guardian's dashboard showing people in your care, attendance, overdue assignments and their next sessions.",
            caption: "A guardian's dashboard. The panels are about the person you look after.",
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
            { term: "People", detail: "How many people you are linked to." },
            { term: "Attendance", detail: "How often they have turned up to class." },
            {
              term: "Overdue assignments",
              detail: "Work they were due to hand in and have not. Worth watching.",
            },
            {
              term: "Their next sessions",
              detail: "The classes coming up, and how soon.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "The Join class button",
            body: "You may see a **Join class** button next to a class. That is for the people taking the class. As a guardian you are not expected to join, and there is no need to.",
          },
        },
      ],
      result: "You can see at a glance whether anything needs a conversation at home.",
      tips: [
        "**Overdue assignments** is usually the first sign of somebody falling behind — earlier than results.",
      ],
      related: ["my-team", "attendance", "sidebar"],
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
          text: "The menu on the left is how you move around. You see only the screens a guardian account can open.",
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
            ["Community", "Announcements, Messages, Notifications."],
            ["People", "My team, Guardians."],
            ["Administration", "Academic setup (you can look, not change)."],
            ["Help", "This user guide."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "There is no Reports screen on a guardian account. Everything you need is on **My team** and **Performance**.",
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
      summary: "Change your details, your password and your timezone.",
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
            src: "guardian/account.webp",
            alt: "The My account screen showing profile details and the password section.",
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
