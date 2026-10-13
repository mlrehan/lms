import type { Section } from "../types";

/** The tutor's day job: classes, the batch workspace, and the register. */
export const teaching: Section = {
  id: "teaching",
  title: "Your classes",
  blurb: "Your courses and groups, the timetable, who is enrolled, and taking the register.",
  articles: [
    {
      id: "courses",
      title: "How to see your courses",
      summary: "The subjects you teach, and what the statuses mean.",
      feature: "Courses",
      learn: ["Where to find your courses", "What each status means"],
      body: [
        {
          type: "paragraph",
          text: "**Courses** shows the subjects you teach. You see only your own — not the whole catalogue.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/courses.webp",
            alt: "A tutor's Courses screen listing their own courses with status, level and hours.",
            caption: "Your courses only. Use the filters to narrow a long list.",
          },
        },
        {
          type: "table",
          columns: ["Status", "What it means"],
          rows: [
            ["Draft", "Still being prepared. Students cannot see it."],
            ["Published", "Finished and visible."],
            ["Running", "Teaching is under way."],
            ["Completed", "Teaching has finished."],
            ["Archived", "Kept for the record."],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Only an administrator creates a course",
            body: "There is no **New course** button on your account. If a course is missing or wrong, ask an administrator.",
          },
        },
      ],
      result: "You can see every subject you teach and what state it is in.",
      related: ["batches", "timetable"],
    },

    {
      id: "batches",
      title: "How to use your batch workspace",
      summary:
        "Open a group to see its students, sessions, register and details in one place.",
      feature: "Batches",
      learn: [
        "What a batch is",
        "How to open a batch workspace",
        "What each of its four tabs shows",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **batch** is one group of students taking one course together. It is where almost all of your teaching happens, so it has a workspace of its own.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/batches.webp",
            alt: "A tutor's Batches screen listing the groups they teach with schedule, dates, method, sessions, enrolled and state.",
            caption: "The groups you teach. Student names are blurred in this guide for privacy.",
          },
        },
        { type: "heading", text: "Open a batch" },
        {
          type: "steps",
          items: [
            { text: "Click **Batches** in the left-hand menu." },
            {
              text: "Click anywhere on the batch's row.",
              note: "The **Actions** button at the end of the row does the same thing, and also offers **Take attendance** when there is a class to mark.",
            },
          ],
        },
        {
          type: "paragraph",
          text: "The top of the workspace always shows the course, the batch code, whether it is active, the dates, the days and time it meets, how long each class is, how it is taught, and who teaches it. There is also a **Grade book** link.",
        },
        { type: "heading", text: "The four tabs" },
        {
          type: "definitions",
          items: [
            {
              term: "Overview",
              detail:
                "How many are enrolled, seats available, planned sessions and class length, plus the batch's own details.",
            },
            {
              term: "Sessions",
              detail:
                "Every class with its start, end, place and length. Each one has a **Register** action that takes you straight to marking it.",
            },
            {
              term: "Attendance",
              detail: "Every class with whether its register is **Done** or still **Pending**.",
            },
            {
              term: "Enrollments",
              detail:
                "Who is on the batch, their status, when they enrolled, and how they are performing.",
            },
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/batch-overview.webp",
            alt: "The Overview tab of a batch workspace showing enrolled count, seats available, planned sessions and the batch details.",
            caption:
              "The Overview tab, where you land. The header above it stays on every tab.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/batch-sessions.webp",
            alt: "The Sessions tab of a batch workspace, listing each class with a Register action.",
            caption:
              "The Sessions tab. **Register** is the quickest way into marking a particular class.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/batch-enrollments.webp",
            alt: "The Enrollments tab of a batch workspace showing students, status, enrolled date and performance.",
            caption:
              "The Enrollments tab, showing how many seats are taken. Names are blurred here for privacy.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Some details are not yours to change",
            body: "You can read the batch details, but creating batches, enrolling students and setting the fee belong to an administrator. The fee shows as a dash on your account.",
          },
        },
      ],
      result: "You can run a whole class from one screen.",
      tips: [
        "Bookmark the workspace of the batch you teach most. It is the fastest route to the register.",
      ],
      problems: [
        {
          symptom: "A student is not on the Enrollments tab.",
          fix: "They are not enrolled yet. Only an administrator can add them.",
        },
      ],
      related: ["attendance", "timetable", "gradebook", "performance"],
    },

    {
      id: "timetable",
      title: "How to use the timetable",
      summary: "See your classes in order, and join an online class.",
      feature: "Timetable",
      learn: ["How to read your timetable", "How to join an online class"],
      body: [
        {
          type: "paragraph",
          text: "The **Timetable** lists the classes you can see, earliest first. Times are shown in your own timezone, which is written at the top.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/timetable.webp",
            alt: "A tutor's timetable listing sessions with start, end and length, and date and batch filters.",
            caption: "Your classes in order.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Timetable** in the left-hand menu." },
            { text: "Use **From** and **To** to choose a range of dates." },
            { text: "Use **Batch** to see one group only." },
            {
              text: "Click **Join class** on a class that is running now.",
              note: "Classes that have finished say **Class has ended** instead.",
            },
          ],
        },
      ],
      result: "You know exactly what you are teaching and when.",
      tips: ["Leave the date boxes empty to see everything."],
      problems: [
        {
          symptom: "The timetable looks empty.",
          fix: "A date filter is probably still set. Clear **From** and **To**.",
        },
        {
          symptom: "The times look wrong.",
          fix: "Check your timezone on the **My account** screen.",
        },
      ],
      related: ["batches", "attendance", "account"],
    },

    {
      id: "enrollments",
      title: "How to see who is on your classes",
      summary: "Every student enrolled on the groups you teach.",
      feature: "Enrollments",
      learn: ["Where to see your students", "What the statuses mean"],
      body: [
        {
          type: "paragraph",
          text: "**Enrollments** lists the students on the batches you teach, with the batch they are on and whether their place is confirmed.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/enrollments.webp",
            alt: "A tutor's Enrollments screen listing students, their batch, status and enrolled date.",
            caption:
              "Your students only. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Enrollments** in the left-hand menu." },
            { text: "Use **Batch** to see one group." },
            { text: "Use **Student** to find one person." },
            { text: "Use **Status** to show only confirmed places." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "You can see enrolments but not change them. Adding, removing or transferring a student is an administrator's job.",
          },
        },
      ],
      result: "You know who should be in each class.",
      related: ["batches", "attendance"],
    },

    {
      id: "attendance",
      title: "How to take the register",
      summary:
        "Mark who was present at a class. This is the task tutors do most often.",
      feature: "Attendance",
      learn: [
        "How to mark a register",
        "What the four marks mean",
        "The difference between a draft and a submitted register",
      ],
      before: ["The class must have happened, or be happening.", "Students must be enrolled."],
      body: [
        {
          type: "paragraph",
          text: "The **Attendance** screen has two tabs. **Take attendance** is where you mark a register. **Records** is where you look back at ones already taken.",
        },
        { type: "heading", text: "Mark a register" },
        {
          type: "steps",
          items: [
            { text: "Click **Attendance** in the left-hand menu." },
            {
              text: "Stay on the **Take attendance** tab. Your classes are listed on the left.",
              image: {
                src: "tutor/attendance-take.webp",
                alt: "The Take attendance tab listing a tutor's class sessions with Pending labels.",
                caption:
                  "Classes needing a register. The buttons above filter by To do, Drafts, Done or All.",
              },
            },
            {
              text: "Click the class you want to mark. It opens on the right.",
              image: {
                src: "tutor/attendance-session.webp",
                alt: "The register for one class, showing counters for present, late, absent, excused and unmarked, a Mark all present button, and each student with four buttons.",
                caption:
                  "The register. Every student has four buttons; the counters at the top update as you go. Names are blurred here for privacy.",
              },
            },
            {
              text: "For each student, click **Present**, **Late**, **Absent** or **Excused**.",
              note: "If almost everybody came, click **Mark all present** first and then change the few who did not.",
            },
            { text: "Check the **Unmarked** counter at the top has reached 0." },
            { text: "Submit the register." },
          ],
        },
        { type: "heading", text: "What the four marks mean" },
        {
          type: "definitions",
          items: [
            { term: "Present", detail: "They came, on time." },
            { term: "Late", detail: "They came, but after the class started." },
            { term: "Absent", detail: "They did not come, and it was not agreed in advance." },
            { term: "Excused", detail: "They did not come, and it was agreed beforehand." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Your marking is saved as you go",
            body: "A register you have started but not submitted is kept as a **draft**, so you will not lose it if you are interrupted. Submitting is what turns it into the official record.",
          },
        },
        { type: "heading", text: "Find classes that still need a register" },
        {
          type: "bullets",
          items: [
            "**To do** — classes that have happened with no register yet.",
            "**Drafts** — registers you started but have not submitted.",
            "**Done** — registers already submitted.",
            "**All** — everything.",
            "**Last 7 days** changes how far back the list goes.",
          ],
        },
        { type: "heading", text: "Look back at a register" },
        {
          type: "paragraph",
          text: "Click the **Records** tab and filter by batch, student or status.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Attendance can count towards results",
            body: "On many courses attendance is part of a student's final mark. An absence recorded by mistake can lower somebody's result, so take a moment to check before submitting.",
          },
        },
      ],
      result:
        "The register is saved, the class shows as **Done**, and attendance appears in reports and in each student's standing.",
      tips: [
        "Take the register during the class, or straight after. It is much harder to remember later.",
        "The **Register** action on a batch's **Sessions** tab takes you straight to the right class.",
      ],
      problems: [
        {
          symptom: "A student is missing from the register.",
          fix: "They are not enrolled on that batch. Ask an administrator to enrol them.",
        },
        {
          symptom: "The class you want is not in the list.",
          fix: "Change the date filter from **Last 7 days**, or click **All**.",
        },
        {
          symptom: "You marked somebody wrongly and have already submitted.",
          fix: "Open the same class again from the **Records** tab and correct it.",
        },
      ],
      related: ["batches", "timetable", "gradebook", "reports"],
    },
  ],
};
