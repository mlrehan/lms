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
    {
      id: "class-performance",
      title: "How to mark class performance",
      summary:
        "Record how each student took part in a class. These marks count towards their final result.",
      feature: "Class performance",
      learn: [
        "Where to record class performance",
        "Why an unmarked class holds up a result",
        "What publishing does, and how to correct a published mark",
      ],
      before: ["Open the class from the **Timetable**. The sheet is on the session's own page."],
      body: [
        {
          type: "paragraph",
          text: "**Class performance** is your assessment of how each student took part - participation, preparation, practical work and so on. It sits on the session page, under the register.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "This is a graded component, not a note to yourself",
            body: "Class performance is one of the weighted parts of the final result. A class you leave unassessed does not score zero - it leaves every student on it **incomplete**, and an incomplete result cannot be turned into a transcript. If an administrator tells you a transcript will not finalise, an unmarked class is the usual reason.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/class-performance.webp",
            alt: "The class performance sheet on a session page, showing one row per student with columns for participation, interaction, preparation, practical, presentation, teamwork, communication and professionalism, an overall score and a comment.",
            caption:
              "One row per student. Names are blurred in this guide for privacy; you will see them in full.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Open the class from the **Timetable**." },
            { text: "Scroll to **Class performance**." },
            {
              text: "Set **Out of** if you do not want the default of 100.",
              note: "It applies to the whole sheet, so set it before you start typing.",
            },
            {
              text: "Fill in a score for each student. You can use just **Overall** if the detailed columns are not useful to you.",
            },
            { text: "Click **Save marks**." },
            {
              text: "When you are happy, publish the sheet.",
              note: "Publishing is what releases the marks. The header tells you how many of the class are assessed.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Published marks are locked on purpose",
            body: "Once released, somebody has seen the figure. To change one you have to **Withdraw** the sheet first, which is a deliberate act rather than an accidental edit.",
          },
        },
      ],
      result: "Every student on the class has a mark, and the result can be completed.",
      tips: [
        "Mark it straight after the class while you still remember it. It takes a minute and it is the part most often forgotten.",
      ],
      problems: [
        {
          symptom: "The sheet will not save.",
          fix: "Only the session's assigned tutor can record it, or an administrator on their behalf. Check you are the tutor on this class.",
        },
        {
          symptom: "A student's result says 'so far incomplete' after everything else is marked.",
          fix: "Check this sheet. An unassessed class is the component most often missing.",
        },
      ],
      related: ["attendance", "timetable", "gradebook", "performance"],
    },

    {
      id: "share-recording",
      title: "How to share a class recording or video",
      summary:
        "Put a YouTube, Vimeo, Zoom or other video link on a class so your students can watch it.",
      feature: "Timetable",
      learn: [
        "Where to paste a video link",
        "Which links work",
        "Who can watch it, and what they are given",
      ],
      before: [
        "Have the video's web address copied - the one from your browser's address bar is fine.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A class can carry a recording. Paste the link once and everyone entitled to that class can watch it inside the LMS - you do not have to send it round.",
        },
        {
          type: "steps",
          items: [
            { text: "Open the class from the **Timetable**." },
            { text: "Click **Edit session**." },
            { text: "Paste the address into **Recording link**." },
            { text: "Save." },
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/share-recording.webp",
            alt: "A session page showing the Recording section with a video player embedded below the session details.",
            caption: "Once saved, the video plays on the class page itself.",
          },
        },
        { type: "heading", text: "Which links work" },
        {
          type: "table",
          columns: ["Where the video is", "What happens"],
          rows: [
            [
              "YouTube",
              "Plays on the class page. Any YouTube address works - the watch page, a share link or a youtu.be link.",
            ],
            ["Vimeo", "Plays on the class page."],
            [
              "Zoom cloud recording",
              "Plays on the class page, under Zoom's own rules - if the recording has a passcode, your students still need it.",
            ],
            [
              "Google Drive",
              "Plays on the class page, if the file is shared so your students can open it.",
            ],
            ["A video file (.mp4 and similar)", "Plays on the class page."],
            [
              "Anywhere else",
              "Offered as a link that opens in a new tab, rather than a player that would not work.",
            ],
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "You do not need the 'embed' address",
            body: "Paste the ordinary address you see in your browser. The system works out the right player address itself.",
          },
        },
        { type: "heading", text: "Who can watch it" },
        {
          type: "paragraph",
          text: "Everyone who is entitled to the class: the students enrolled on it, their guardians and corporate managers, you, and administrators. Permission is checked every time somebody presses play, so a student removed from the batch loses access immediately.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "The link itself stays with staff",
            body: "Students are never handed the provider's address - only a way to watch through the LMS. That is deliberate: a bare YouTube or Zoom link works for anybody who has it, signed out, for ever.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "A video that must not be downloadable belongs in the library",
            body: "Once the video is playing on YouTube's or Zoom's player, whatever download controls that provider offers are theirs, not ours. Upload the file to **Resources** instead if that matters.",
          },
        },
      ],
      result: "The class page shows the video, and your students can watch it.",
      tips: [
        "Check it yourself after saving. The player appears on the class page straight away.",
      ],
      problems: [
        {
          symptom: "The link is refused when you save.",
          fix: "The message says why - usually the address is incomplete. Copy it again from your browser's address bar.",
        },
        {
          symptom: "The player says the video is private or unavailable.",
          fix: "That is the provider, not the LMS. Check the video's own sharing settings allow people outside your account to watch it.",
        },
        {
          symptom: "A student says they cannot see any recording.",
          fix: "Check they are confirmed on the batch - the recording follows the class, so somebody not enrolled sees nothing.",
        },
      ],
      related: ["timetable", "batches", "resources"],
    },
  ],
};
