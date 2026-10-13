import type { Section } from "../types";

/** Reference data, outside connections, settings and importing. */
export const administration: Section = {
  id: "administration",
  title: "Administration",
  blurb: "Reference data, connections to other systems, settings, and importing data.",
  articles: [
    {
      id: "academic-setup",
      title: "How to set up academic reference data",
      summary:
        "Years, semesters, departments, categories and tags — the lists everything else picks from.",
      feature: "Academic setup",
      learn: ["What each of the five tabs is for", "How to add an academic year"],
      body: [
        {
          type: "paragraph",
          text: "**Academic setup** holds the reference data the rest of the system chooses from. Setting it up once makes everything else tidier.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/academic-setup.webp",
            alt: "The Academic setup screen showing the Academic years, Semesters, Departments, Categories and Tags tabs.",
            caption: "Five tabs, each a list other screens pick from.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Academic years",
              detail:
                "A year such as 2025-2026. Exactly one year is current; promoting a year to current demotes the one that held it.",
            },
            {
              term: "Semesters",
              detail: "Terms inside an academic year. A batch can be placed in one.",
            },
            { term: "Departments", detail: "Faculties or schools. A course can belong to one." },
            {
              term: "Categories",
              detail: "A tree used to group courses. A course belongs to at most one category.",
            },
            {
              term: "Tags",
              detail: "Free-form labels, independent of categories.",
            },
          ],
        },
        { type: "heading", text: "Add an academic year" },
        {
          type: "steps",
          items: [
            { text: "Click **Academic setup** in the left-hand menu." },
            { text: "Stay on the **Academic years** tab." },
            { text: "Type a **Label**, such as 2025-2026." },
            { text: "Choose the **Starts** and **Ends** dates." },
            {
              text: "Tick **Make this the current year** if it is the one running now.",
              note: "Only one year can be current. Ticking this moves it from whichever year held it.",
            },
            { text: "Click **Add year**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "Semesters cannot be added until at least one academic year exists, because every semester belongs to a year.",
          },
        },
      ],
      result: "The year appears in the list and can be chosen elsewhere.",
      tips: [
        "Set up years and departments before creating many courses — it saves editing them all later.",
      ],
      related: ["courses", "batches"],
    },

    {
      id: "sync-data",
      title: "How to import data from LAIT",
      summary:
        "Bring people, courses, batches, sessions and enrolments in from the LAIT system with one button.",
      feature: "Dashboard — Data synchronisation",
      learn: [
        "What the Sync All Data button does",
        "How to read the progress panel",
        "How to turn on automatic importing",
      ],
      before: [
        "Only a Super Admin can start an import.",
        "You do not need to stay on the page — it keeps running on the server.",
      ],
      body: [
        {
          type: "paragraph",
          text: "The **Data synchronisation** panel at the top of your dashboard imports information from the LAIT system. It runs six steps, in an order that matters: a batch is meaningless before its course exists, and an enrolment is meaningless before both.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/dashboard.webp",
            alt: "The data synchronisation panel on the dashboard, showing the Sync All Data button, a progress bar and the six steps.",
            caption: "The panel after a completed import.",
          },
        },
        { type: "heading", text: "Start an import" },
        {
          type: "steps",
          items: [
            { text: "Go to the **Dashboard**." },
            { text: "Click **Sync All Data** in the top right of the panel." },
            {
              text: "Watch the steps turn from waiting, to running, to a tick.",
              note: "You can go to another screen, or close the browser. The import carries on.",
            },
          ],
        },
        { type: "heading", text: "The six steps" },
        {
          type: "table",
          columns: ["Step", "What it brings in"],
          rows: [
            ["Sync users", "Student and tutor accounts."],
            ["Assign managers", "Links corporate managers to the students they look after."],
            ["Sync courses", "The course catalogue."],
            ["Sync batches", "Groups of students, keeping their course."],
            ["Sync sessions", "Class times, keeping their batch."],
            ["Sync enrollments", "Who is on which batch."],
          ],
        },
        { type: "heading", text: "Reading the numbers" },
        {
          type: "definitions",
          items: [
            { term: "Processed", detail: "How many records were looked at." },
            { term: "Succeeded", detail: "How many were brought in or already matched." },
            {
              term: "Failed",
              detail:
                "How many could not be handled and are worth looking at. Zero is what you want.",
            },
            {
              term: "Last successful",
              detail: "When an import last finished with every step completed.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Skipped is not failed",
            body: "The managers step often says something like '95 skipped (no LMS account)'. That is normal: LAIT lists many company contacts who have no account here, so there is nobody to link them to. It is not an error and needs no action.",
          },
        },
        { type: "heading", text: "If a step fails" },
        {
          type: "steps",
          items: [
            { text: "Read the message shown under the failed step." },
            {
              text: "Click **Retry failed steps**.",
              note: "Steps that already succeeded are not run again, so a retry is quick.",
            },
          ],
        },
        { type: "heading", text: "Import automatically" },
        {
          type: "steps",
          items: [
            { text: "Click **Automatic synchronisation** at the bottom of the panel." },
            { text: "Turn on **Run automatically**." },
            { text: "Set how many hours between imports." },
            { text: "Click **Save**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Automatic importing needs a worker running",
            body: "The schedule is obeyed by a separate background program. If nothing imports automatically, ask whoever looks after your servers whether that program is running.",
          },
        },
      ],
      result:
        "The panel shows **Completed**, every step has a tick, and **Failed** shows 0.",
      tips: [
        "Importing never deletes anything. Running it twice does not create duplicates.",
        "If you are not sure whether an import is needed, check **Last successful**.",
      ],
      problems: [
        {
          symptom: "The button is greyed out and says **Synchronising…**",
          fix: "An import is already running. Wait for it to finish — only one can run at a time.",
        },
        {
          symptom: "A step says a synchronisation is already running.",
          fix: "Somebody has pressed a sync button elsewhere. It will wait and then continue by itself.",
        },
        {
          symptom: "Nothing happens automatically even though it is switched on.",
          fix: "The background worker is probably not running. This is for your technical team.",
        },
      ],
      related: ["dashboard", "users", "manager-assignments", "system-settings"],
    },

    {
      id: "integrations",
      title: "How to use integrations",
      summary: "Google Calendar, outgoing webhooks and subscribable calendar feeds.",
      feature: "Integrations",
      learn: ["What each of the three tabs does", "How the Google Calendar connection works"],
      body: [
        {
          type: "paragraph",
          text: "**Integrations** connects this system to things outside it. There are three tabs.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/integrations.webp",
            alt: "The Integrations screen showing the Google Calendar, Webhooks and Calendar feeds tabs, with Google Calendar connected.",
            caption: "Google Calendar, shown connected.",
          },
        },
        { type: "heading", text: "Google Calendar" },
        {
          type: "paragraph",
          text: "One calendar per batch, one event per session. People see their classes because they are guests on the events. Guest email addresses are not sent — the event simply appears on their calendar.",
        },
        {
          type: "bullets",
          items: [
            "**Sync to Google now** pushes the current timetable to Google.",
            "**Preview changes** reports what would change and writes nothing.",
            "**History** shows every past run.",
            "**Reconnect** and **Disconnect** manage the account connection.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Changes made in Google need approval",
            body: "Adding or removing a guest in Google Calendar is treated as a proposal. It appears under **Changes from Google** and nothing happens until somebody approves it here.",
          },
        },
        { type: "heading", text: "Webhooks" },
        {
          type: "paragraph",
          text: "Addresses the system sends information to. Only public web addresses are accepted. This is a technical feature — if you do not know you need it, you do not need it.",
        },
        { type: "heading", text: "Calendar feeds" },
        {
          type: "paragraph",
          text: "A subscribable link to your own timetable, which you can add to a calendar app.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A calendar feed link is a password",
            body: "Anybody holding the link can read your schedule without signing in. Do not post it anywhere public.",
          },
        },
      ],
      result: "Classes appear in Google Calendar for the people who should see them.",
      related: ["timetable", "system-settings"],
    },

    {
      id: "system-settings",
      title: "How to change system settings",
      summary: "A list of named settings and their values.",
      feature: "System settings",
      learn: ["What this screen is", "How to change a value", "Why to be careful"],
      body: [
        {
          type: "paragraph",
          text: "**System settings** is a simple list of named settings and their values. Only a Super Admin can change them — not even an Administrator can.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/system-settings.webp",
            alt: "The System settings screen showing stored settings with their values and a New setting button.",
            caption: "Settings are stored as a name and a value.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **System settings** in the left-hand menu." },
            { text: "Find the setting, using **Filter by key prefix** if the list is long." },
            { text: "Edit the value." },
            { text: "Click **Save** on that row." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Nothing checks what you type here",
            body: "The screen cannot tell you which names the system actually reads, or whether a value is valid. A misspelled name is a setting that silently does nothing. Only change a setting you were asked to change, exactly as written.",
          },
        },
        { type: "heading", text: "Deleting a setting" },
        {
          type: "paragraph",
          text: "Click the bin icon and type the setting's name to confirm. Anything reading it then falls back to its built-in default.",
        },
      ],
      result: "The new value is saved and used from then on.",
      tips: [
        "Write down the old value before changing one, so you can put it back.",
        "The automatic import schedule is stored here, but it is far safer to change it from the dashboard panel.",
      ],
      related: ["sync-data", "integrations"],
    },
  ],
};
