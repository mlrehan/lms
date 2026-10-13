import type { Section } from "../types";

/** Courses, batches, the timetable, enrolments and the register. */
export const learning: Section = {
  id: "learning",
  title: "Teaching and the timetable",
  blurb: "Courses, groups of students, the timetable, who is enrolled, and the register.",
  articles: [
    {
      id: "courses",
      title: "How to create and manage courses",
      summary:
        "Add a course to the catalogue, fill in its details, and move it from draft to published.",
      feature: "Courses",
      learn: [
        "What a course is and what the statuses mean",
        "How to add a new course",
        "How to find a course quickly",
      ],
      before: [
        "Decide the course title and how long it runs for.",
        "If you want it in a category or department, create those first under **Academic setup**.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **course** is a subject you teach, such as *Data Analysis with Python*. It is the template. The actual group of students who take it together is a **batch**, which you create afterwards.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/courses.webp",
            alt: "The Courses screen with the search box, filters and the New course button.",
            caption: "The course catalogue. Use the search box and the three filters to narrow the list.",
          },
        },
        { type: "heading", text: "What the statuses mean" },
        {
          type: "paragraph",
          text: "A course moves through these stages in order. The system will not let you skip a stage or go backwards.",
        },
        {
          type: "table",
          columns: ["Status", "What it means"],
          rows: [
            ["Draft", "You are still working on it. Students cannot see it."],
            ["Published", "Finished and visible. Students can be enrolled."],
            ["Running", "Teaching is under way."],
            ["Completed", "Teaching has finished."],
            ["Archived", "Kept for the record, no longer offered."],
          ],
        },
        { type: "heading", text: "Add a new course" },
        {
          type: "steps",
          items: [
            { text: "Click **Courses** in the left-hand menu." },
            { text: "Click **New course** in the top right." },
            {
              text: "Fill in **Title**. This is the only box you must fill in — it has a star next to it.",
              image: {
                src: "super-admin/dialog-new-course.webp",
                alt: "The Create a course form showing Title, Code, Level, Duration, Price, Course link, Category, Department, Description and Prerequisites.",
                caption: "Boxes marked with a star are required. Everything else can be added later.",
              },
            },
            {
              text: "Fill in anything else you already know: **Code**, **Level**, **Duration (hours)**, **Price (GBP)**, **Category**, **Department**, **Description** and **Prerequisites**.",
              note: "You can come back and edit all of these at any time.",
            },
            { text: "Click **Create course**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "A new course starts as a draft",
            body: "Students cannot see it until you publish it. That is deliberate, so you can prepare a course without anybody seeing a half-finished one.",
          },
        },
        { type: "heading", text: "Find a course" },
        {
          type: "bullets",
          items: [
            "Type into **Search courses** to match the title.",
            "Use **Any status**, **Any level** and **Any category** to narrow the list.",
            "The filters work together: you can see every published beginner course in one category at once.",
          ],
        },
      ],
      result: "The new course appears in the list with the status **Draft**.",
      tips: [
        "Give every course a short code such as DAP-01. It makes batches much easier to recognise later.",
        "A price is only ever shown to a Super Admin. Other roles never see it.",
      ],
      problems: [
        {
          symptom: "The **Create course** button does nothing.",
          fix: "The **Title** box is empty. Fill it in — it is the one required box.",
        },
        {
          symptom: "A course does not appear in the list.",
          fix: "Clear the search box and set all three filters back to 'Any'. A filter left on from earlier is the usual cause.",
        },
      ],
      related: ["batches", "enrollments", "academic-setup"],
    },

    {
      id: "batches",
      title: "How to create and manage batches",
      summary:
        "A batch is one group of students taking a course together, with its own schedule and register.",
      feature: "Batches",
      learn: [
        "What a batch is and how it differs from a course",
        "How to create a batch",
        "What the columns on the batch list tell you",
      ],
      before: [
        "The course must already exist.",
        "Decide which days of the week the class meets and when it starts.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **batch** is one group of students taking one course together, starting and finishing on particular dates. One course can have many batches — a January group and a March group, for example. The batch is where the students, the sessions, the timetable and the register all live.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/batches.webp",
            alt: "The Batches screen listing batches with columns for batch, tutor, schedule, dates, method, sessions, enrolled, fee and state.",
            caption:
              "Each row is one group of students. Click a batch code to open it.",
          },
        },
        { type: "heading", text: "What the columns mean" },
        {
          type: "definitions",
          items: [
            { term: "Batch", detail: "The batch code and the course it belongs to." },
            { term: "Tutor", detail: "Who teaches it." },
            { term: "Schedule", detail: "Which days of the week the class meets." },
            { term: "Dates", detail: "The first and last day." },
            { term: "Method", detail: "How it is taught, for example online using Zoom." },
            { term: "Sessions", detail: "How many classes are planned." },
            { term: "Enrolled", detail: "How many students are on it." },
            { term: "State", detail: "Whether the batch is active." },
          ],
        },
        { type: "heading", text: "Create a batch" },
        {
          type: "steps",
          items: [
            { text: "Click **Batches** in the left-hand menu." },
            { text: "Click **New batch**." },
            {
              text: "Choose the **Course** and type a **Batch code**. Both are required.",
              image: {
                src: "super-admin/dialog-new-batch.webp",
                alt: "The New batch form showing Course, Batch code, Capacity, Duration, Planned sessions, Start date, End date and Notes.",
                caption: "A batch code is how people recognise the group, so make it meaningful.",
              },
            },
            {
              text: "Set **Capacity** — the largest number of students allowed on it.",
            },
            { text: "Set **Start date** and **End date**." },
            { text: "Fill in **Planned sessions** if you know how many classes there will be." },
            { text: "Click **Create batch**." },
          ],
        },
        { type: "heading", text: "Open a batch" },
        {
          type: "paragraph",
          text: "Click anywhere on the batch's row to open its workspace. Inside you can see its students, its sessions, its timetable and its register in one place.",
        },
        {
          type: "paragraph",
          text: "The **Actions** button at the end of each row is a quicker route to the same places: it offers **Open batch workspace** and, where there is a class to mark, **Take attendance**.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Show more or fewer columns",
            body: "Click **Columns** above the table to hide columns you do not need. This is very helpful on a small screen.",
          },
        },
      ],
      result: "The new batch appears in the list and can take enrolments.",
      tips: [
        "Include the course code and the month in the batch code, such as DAP-01-JAN, so it is obvious later.",
        "Set the capacity honestly. It stops a class being over-filled by mistake.",
      ],
      problems: [
        {
          symptom: "You cannot find the course in the Course list.",
          fix: "Only courses that exist can be chosen. Create the course first.",
        },
        {
          symptom: "The batch code is refused.",
          fix: "Batch codes must be unique. Another batch already uses that code.",
        },
      ],
      related: ["courses", "timetable", "enrollments", "attendance"],
    },

    {
      id: "timetable",
      title: "How to use the timetable",
      summary: "See every class that is scheduled, and filter it down to the one you want.",
      feature: "Timetable",
      learn: ["How to read the timetable", "How to filter it", "How to join an online class"],
      body: [
        {
          type: "paragraph",
          text: "The **Timetable** lists every class session you are allowed to see, earliest first. All times are shown in your own timezone, which is written at the top of the screen.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/timetable.webp",
            alt: "The Timetable screen showing date filters, batch, tutor and student filters, and a list of sessions with start and end times.",
            caption:
              "Sessions in order. The Join class button appears on classes that are happening now.",
          },
        },
        { type: "heading", text: "Narrow the list" },
        {
          type: "steps",
          items: [
            { text: "Use **From** and **To** to choose a range of dates." },
            { text: "Use **Batch** to see one group's classes only." },
            { text: "Use **Tutor** to see one teacher's classes." },
            { text: "Use **Student** to see the classes one student is expected at." },
          ],
        },
        { type: "heading", text: "Join an online class" },
        {
          type: "paragraph",
          text: "When a class is taught online and is happening now, a **Join class** button appears on its row. Click it to open the meeting. Sessions that have finished say **Class has ended** instead.",
        },
      ],
      result: "You can see exactly which classes are running, and when.",
      tips: [
        "If the times look wrong, check your timezone on the **My account** screen. Times are stored the same way for everybody and only displayed in yours.",
        "Leave the date boxes empty to see everything.",
      ],
      problems: [
        {
          symptom: "The timetable looks empty.",
          fix: "A date filter is probably still set from earlier. Clear **From** and **To**.",
        },
      ],
      related: ["batches", "attendance", "account"],
    },

    {
      id: "enrollments",
      title: "How to manage enrolments",
      summary: "See which students are on which batch, and in what state.",
      feature: "Enrollments",
      learn: [
        "What an enrolment is",
        "What the statuses mean",
        "How to find a particular student's enrolment",
      ],
      body: [
        {
          type: "paragraph",
          text: "An **enrolment** is the record that puts one student on one batch. Until a student is enrolled, they cannot see the course or appear on the register.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/enrollments.webp",
            alt: "The Enrollments screen listing students, their batch, status and the date they enrolled.",
            caption: "One row for each student on each batch.",
          },
        },
        { type: "heading", text: "Finding an enrolment" },
        {
          type: "steps",
          items: [
            { text: "Click **Enrollments** in the left-hand menu." },
            { text: "Use **Batch** to see everybody on one group." },
            { text: "Use **Student** to see every batch one person is on." },
            { text: "Use the status filter to show only confirmed enrolments, for example." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Transfers keep their history",
            body: "When a student moves to a different batch, the old enrolment is linked to the new one rather than being replaced. You can always see where somebody came from.",
          },
        },
      ],
      result: "You can see at a glance who is on a batch and whether their place is confirmed.",
      tips: [
        "The **Enrolled** column on the Batches screen is the quickest way to see whether a group is filling up.",
      ],
      problems: [
        {
          symptom: "A student says they cannot see their course.",
          fix: "Check here that they have an enrolment on that batch, and that its status is confirmed.",
        },
      ],
      related: ["batches", "attendance", "users"],
    },

    {
      id: "attendance",
      title: "How to take and check attendance",
      summary:
        "Mark who was in a class, and look back at the register for any batch or student.",
      feature: "Attendance",
      learn: [
        "How to mark a register for a class",
        "The difference between a draft and a submitted register",
        "How to look up past attendance",
      ],
      before: ["The class session must exist, and students must be enrolled on the batch."],
      body: [
        {
          type: "paragraph",
          text: "The **Attendance** screen has two tabs. **Take attendance** is where you mark a register. **Records** is where you look back at registers already taken.",
        },
        { type: "heading", text: "Take a register" },
        {
          type: "steps",
          items: [
            { text: "Click **Attendance** in the left-hand menu." },
            {
              text: "Stay on the **Take attendance** tab. You will see a list of sessions.",
              image: {
                src: "super-admin/attendance-take.webp",
                alt: "The Take attendance tab listing class sessions with their time, batch, tutor, number of students and a Pending label.",
                caption:
                  "Sessions needing a register. The buttons above filter by To do, Drafts, Done or All.",
              },
            },
            { text: "Click the session you want to mark." },
            { text: "Mark each student as present, late, absent or excused." },
            { text: "When you are sure, submit the register." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Your work is saved as you go",
            body: "A register you have started but not submitted is kept as a draft, so you will not lose it if you are interrupted. Submitting is what turns it into the official record.",
          },
        },
        { type: "heading", text: "Find sessions that still need a register" },
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
        { type: "heading", text: "Look up past attendance" },
        {
          type: "steps",
          items: [
            { text: "Click the **Records** tab." },
            {
              text: "Choose a **Batch**, a **Student**, or a **Status** to narrow the list.",
              image: {
                src: "super-admin/attendance-records.webp",
                alt: "The Records tab with filters for status, batch and student.",
                caption: "Records. Use the filters to answer a question about one person or one group.",
              },
            },
          ],
        },
      ],
      result:
        "The register is saved, and attendance appears in reports and in each student's standing.",
      tips: [
        "Take the register during or straight after the class. It is much harder to remember later.",
        "**Excused** is not the same as **Absent** — use it when the absence was agreed in advance.",
      ],
      problems: [
        {
          symptom: "A student is missing from the register.",
          fix: "They are not enrolled on that batch. Check the Enrollments screen.",
        },
        {
          symptom: "The session you want is not in the list.",
          fix: "Change the date filter from **Last 7 days**, or click **All**.",
        },
      ],
      related: ["timetable", "enrollments", "reports", "gradebook"],
    },
  ],
};
