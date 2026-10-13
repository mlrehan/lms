import type { Section } from "../types";

/**
 * Assignments, quizzes, examinations, the grade book, performance,
 * transcripts and grading schemes.
 *
 * Every field name and tab name here was read off the running console, and
 * every screenshot is of the real screen being described.
 */
export const assessment: Section = {
  id: "assessment",
  title: "Assessment and marks",
  blurb:
    "Set work, run quizzes and examinations, record marks, and turn them into results and transcripts.",
  articles: [
    {
      id: "assessment-overview",
      title: "How marking fits together",
      summary:
        "Read this first: how assignments, quizzes, exams, the grade book and transcripts connect.",
      learn: [
        "The five things that can earn a student marks",
        "How those marks become a final result",
        "Which screen to use for which job",
      ],
      body: [
        {
          type: "paragraph",
          text: "Marks come from several places and end up in one. It is much easier to use the system once you can see the whole path.",
        },
        { type: "heading", text: "Step 1 — Students earn marks" },
        {
          type: "definitions",
          items: [
            {
              term: "Assignments",
              detail: "Work handed in and marked by a person. Marking happens on the assignment itself.",
            },
            {
              term: "Quizzes",
              detail: "Question banks the system marks automatically as soon as the student finishes.",
            },
            {
              term: "Examinations",
              detail: "Scheduled, invigilated assessments. Marks are typed in for the whole group at once.",
            },
            {
              term: "Attendance",
              detail: "Turning up can itself count towards a result, if your grading scheme says so.",
            },
            { term: "Practical work", detail: "Marks recorded directly in the grade book." },
          ],
        },
        { type: "heading", text: "Step 2 — Everything lands in the grade book" },
        {
          type: "paragraph",
          text: "The **Grade book** holds one row for every contribution a student has made — each assignment, each quiz, attendance, practical work and the final exam.",
        },
        { type: "heading", text: "Step 3 — A grading scheme decides what counts" },
        {
          type: "paragraph",
          text: "A **grading scheme** says how much each part is worth: for example, assignments 30%, attendance 10%, final exam 60%. The **Performance** screen shows the result of that arithmetic for every student.",
        },
        { type: "heading", text: "Step 4 — The result becomes a transcript" },
        {
          type: "paragraph",
          text: "A **transcript** is the final, publishable record of how a student did on a batch. The **grading scale** turns a percentage into a letter grade and GPA points.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Set the grading scheme up first",
            body: "Decide what counts and how much it is worth before you start marking. Changing the weights later changes everybody's result at once.",
          },
        },
      ],
      related: ["grading-schemes", "gradebook", "assignments", "performance"],
    },

    {
      id: "grading-schemes",
      title: "How to set up a grading scheme",
      summary:
        "Decide what counts towards a result and how much each part is worth.",
      feature: "Grading schemes",
      learn: [
        "What a grading scheme does",
        "How to create one",
        "Why a new scheme does nothing until you activate it",
      ],
      before: [
        "Decide which parts count — assignments, quizzes, attendance, practical work, the final exam — and the percentage each is worth.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **grading scheme** is the rule that turns a pile of marks into one result. Without it, the system knows a student scored 8 out of 10 on an assignment but not what that is worth overall.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/grading-schemes.webp",
            alt: "The Grading schemes screen with the New scheme button.",
            caption: "Grading schemes. Each scheme lists the parts that count and their weights.",
          },
        },
        { type: "heading", text: "Create a scheme" },
        {
          type: "steps",
          items: [
            { text: "Click **Grading schemes** in the left-hand menu." },
            { text: "Click **New scheme**." },
            {
              text: "Type a **Name**. This is the only required box.",
              image: {
                src: "super-admin/grading-scheme-new.webp",
                alt: "The New grading scheme form showing Name, Description, Overall pass mark and the option for work with no mark yet.",
                caption:
                  "The create form. Note the message at the top: the scheme is created inactive.",
              },
            },
            { text: "Add a **Description** so colleagues know what it is for." },
            {
              text: "Set the **Overall pass mark (%)** — the percentage a student needs overall.",
            },
            {
              text: "Choose what happens to **Work with no mark yet**.",
              note: "**Leave out of the total** is the usual choice: an exam that has not happened yet is ignored, so a student's standing is out of what has actually been assessed.",
            },
            { text: "Click **Create**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A new scheme is not used yet",
            body: "It is created inactive. Nothing is graded by it until you set the weightings for each part and then activate it. That is deliberate — a half-finished scheme must not start changing results.",
          },
        },
        { type: "heading", text: "After it exists" },
        {
          type: "paragraph",
          text: "Open the scheme and add each part that counts, with its weight. The weights are what the **Performance** screen uses.",
        },
      ],
      result:
        "The scheme appears in the list, marked inactive, ready for you to add weightings.",
      tips: [
        "Make the weights add up to 100. It makes every result easy to explain to a student.",
        "Changing a weighting re-calculates every affected student straight away, so agree the scheme before term starts.",
      ],
      problems: [
        {
          symptom: "Students' results have not changed after you created a scheme.",
          fix: "The scheme is still inactive, or has no weightings. Open it, add the parts and their weights, and activate it.",
        },
      ],
      related: ["gradebook", "performance", "assessment-overview"],
    },

    {
      id: "assignments",
      title: "How to set and mark an assignment",
      summary: "Create coursework, publish it to students, and mark what comes in.",
      feature: "Assignments",
      learn: ["How to create an assignment", "What each setting does", "Where marking happens"],
      before: ["The course must exist and have students enrolled on a batch."],
      body: [
        {
          type: "paragraph",
          text: "An **assignment** is a piece of work students hand in. You set it, they submit, you mark it. The mark then counts towards their result.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/assignments-course.webp",
            alt: "The Assignments screen with a course chosen, showing columns for assignment, due date, type, late work and maximum score.",
            caption:
              "Choose a **Course** first — the list is empty until you do.",
          },
        },
        { type: "heading", text: "Create an assignment" },
        {
          type: "steps",
          items: [
            { text: "Click **Assignments** in the left-hand menu." },
            { text: "Click **New assignment**." },
            {
              text: "Choose the **Course**, then type a **Title**.",
              image: {
                src: "super-admin/dialog-new-assignment.webp",
                alt: "The New assignment form showing Course, Set for, Title, Due, Maximum score, Submission type, Description, Opens, Passing mark and On save.",
                caption: "The fields marked with a star must be filled in.",
              },
            },
            {
              text: "Use **Set for** to choose who gets it. The default is everyone on the course.",
            },
            {
              text: "Set the **Due** date and time.",
              note: "You type the time in your own timezone. The system stores it correctly for everybody.",
            },
            { text: "Set the **Maximum score** — the marks the work is out of." },
            {
              text: "Choose the **Submission type**, such as text or a file.",
            },
            { text: "Add a **Description** telling students what to do." },
            {
              text: "Optionally set **Opens** (when students can first see it) and a **Passing mark**.",
            },
            {
              text: "Choose what happens **On save**. Publishing now means students are notified immediately.",
            },
            { text: "Click **Create assignment**." },
          ],
        },
        { type: "heading", text: "Marking" },
        {
          type: "paragraph",
          text: "Marking happens on the assignment itself, not on a separate screen. Open the assignment from the list to see who has submitted and to enter marks and feedback.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "The dashboard shows how many submissions are waiting to be marked. It is the quickest way to notice marking falling behind.",
          },
        },
      ],
      result:
        "The assignment appears in the list for that course, and students see it once it is published.",
      tips: [
        "Write the description as if the student has no other instructions — many will not have any.",
        "Set the due date at a sensible hour. Midnight deadlines cause avoidable arguments.",
      ],
      problems: [
        {
          symptom: "The assignment list is empty.",
          fix: "You have not chosen a course yet. The list only fills in once a course is selected.",
        },
        {
          symptom: "Students say they cannot see the assignment.",
          fix: "It may still be unpublished, or its **Opens** date may be in the future.",
        },
      ],
      related: ["gradebook", "assessment-overview", "quizzes"],
    },

    {
      id: "quizzes",
      title: "How to build and run a quiz",
      summary:
        "Create a quiz, add questions and an answer key, set how it runs, and see how students did.",
      feature: "Quizzes",
      learn: [
        "How to create a quiz and add questions",
        "What each setting does",
        "How to see and re-mark attempts",
      ],
      before: ["The course must exist."],
      body: [
        {
          type: "paragraph",
          text: "A **quiz** is a set of questions the system marks for you, automatically, as soon as the student finishes. Use it for knowledge checks. For a scheduled, invigilated assessment, use **Examinations** instead.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/quizzes.webp",
            alt: "The Quizzes screen listing quizzes with their state, duration, attempts and pass mark.",
            caption: "The quiz list. Click a quiz title to open it.",
          },
        },
        { type: "heading", text: "Step 1 — Create the quiz" },
        {
          type: "steps",
          items: [
            { text: "Click **Quizzes** in the left-hand menu." },
            { text: "Click **New quiz**." },
            {
              text: "Choose the **Course**, type a **Title**, and set the **Passing score**.",
              image: {
                src: "super-admin/dialog-new-quiz.webp",
                alt: "The New quiz form showing Course, Title, Duration, Attempts allowed, Passing score, Instructions and the shuffle option.",
                caption: "A quiz starts unpublished, so students cannot see it yet.",
              },
            },
            {
              text: "Set **Duration (minutes)** and **Attempts allowed** if you want to limit them.",
            },
            { text: "Add **Instructions** for the student." },
            { text: "Click **Create quiz**." },
          ],
        },
        { type: "heading", text: "Step 2 — Add questions" },
        {
          type: "steps",
          items: [
            { text: "Open the quiz by clicking its title." },
            {
              text: "On the **Questions** tab, click **Add question**.",
              image: {
                src: "super-admin/quiz-questions.webp",
                alt: "The Questions tab of a quiz, showing questions with their type, points and which answers are marked correct.",
                caption:
                  "Questions and the answer key together. Correct answers are labelled.",
              },
            },
            { text: "Type the question, choose its type, and set how many points it is worth." },
            { text: "Enter the answers and mark which are correct." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Students never receive the answer key",
            body: "The answer key is only visible to people who can edit the quiz. What the system sends to a student contains no information about which answer is right.",
          },
        },
        { type: "heading", text: "Step 3 — Decide how it runs" },
        {
          type: "paragraph",
          text: "Open the **Settings** tab to control the quiz.",
        },
        {
          type: "definitions",
          items: [
            { term: "Duration (minutes)", detail: "Leave blank for no time limit." },
            { term: "Attempts allowed", detail: "How many times a student may sit it." },
            { term: "Passing score (%)", detail: "The percentage needed to pass." },
            {
              term: "Total marks",
              detail: "Optional. Set one and the system refuses questions beyond it.",
            },
            {
              term: "Questions per attempt",
              detail:
                "Leave blank to use every question. A number draws that many at random from the bank, so students get different papers.",
            },
            {
              term: "Shuffle",
              detail:
                "Mix up the question order, the answer order, or both, for each attempt.",
            },
          ],
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/quiz-settings.webp",
            alt: "The Settings tab of a quiz showing duration, attempts, passing score, total marks, questions per attempt and shuffle options.",
            caption: "Settings apply to attempts started after you save them.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A quiz locks once somebody has sat it",
            body: "After the first attempt you can no longer change the pass mark or the number of questions. Changing them would rewrite what that student's result means.",
          },
        },
        { type: "heading", text: "Step 4 — Publish it" },
        {
          type: "paragraph",
          text: "A quiz starts unpublished and students cannot see it. Use the **Published** switch at the top of the quiz to release it.",
        },
        { type: "heading", text: "Step 5 — See how students did" },
        {
          type: "steps",
          items: [
            {
              text: "Open the **Attempts** tab.",
              image: {
                src: "super-admin/quiz-attempts.webp",
                alt: "The Attempts tab listing each student's attempt, when they finished and their score, with a Re-mark button.",
                caption:
                  "Each attempt with its score. Student names are blurred in this guide for privacy.",
              },
            },
            {
              text: "If you corrected a question's answer key, click **Re-mark** to score that attempt again.",
            },
          ],
        },
        {
          type: "paragraph",
          text: "**Take it** lets you sit the quiz yourself, which is the best way to check it reads properly before students see it.",
        },
      ],
      result:
        "Students can take the quiz, and their scores appear on the Attempts tab and in the grade book.",
      tips: [
        "Always use **Take it** once before publishing. Typos in questions are very hard to spot while writing them.",
        "Use **Questions per attempt** with a large question bank so no two students get the same paper.",
      ],
      problems: [
        {
          symptom: "Students cannot see the quiz.",
          fix: "It is not published yet. Turn on the **Published** switch at the top of the quiz.",
        },
        {
          symptom: "You cannot change the pass mark.",
          fix: "Somebody has already sat the quiz, so it is locked. This protects results that have already been given.",
        },
        {
          symptom: "An attempt is stuck as **In progress**.",
          fix: "Use **Close expired attempts** on the Settings tab.",
        },
      ],
      related: ["assignments", "exams", "gradebook"],
    },

    {
      id: "exams",
      title: "How to schedule an examination and record results",
      summary:
        "Schedule an exam, publish the schedule, enter marks for the whole group, then publish the results.",
      feature: "Examinations",
      learn: [
        "How to schedule an examination",
        "How to enter marks on the mark sheet",
        "The difference between publishing the schedule and publishing the results",
      ],
      before: ["The course and batch must exist.", "Decide the total marks and the pass mark."],
      body: [
        {
          type: "paragraph",
          text: "An **examination** is a scheduled, invigilated assessment. Unlike a quiz, the system does not mark it — you enter the marks yourself.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/examinations.webp",
            alt: "The Examinations screen listing exams with type, scheduled date, marks and schedule status.",
            caption: "Scheduled examinations.",
          },
        },
        { type: "heading", text: "Step 1 — Schedule it" },
        {
          type: "steps",
          items: [
            { text: "Click **Examinations** in the left-hand menu." },
            { text: "Click **Schedule examination**." },
            {
              text: "Type a **Title** and choose the **Type**, such as Midterm.",
              image: {
                src: "super-admin/dialog-new-exam.webp",
                alt: "The Schedule an examination form showing Title, Type, Scheduled, Duration, Total marks, Passing marks, Venue, Course, Batch and Instructions.",
                caption:
                  "Times are typed in your timezone. The schedule can be published before any results exist.",
              },
            },
            { text: "Set **Scheduled** — the date and time it takes place." },
            { text: "Set **Duration (minutes)**." },
            { text: "Set **Total marks** and **Passing marks**. Both are required." },
            { text: "Enter the **Venue or link**, and choose the **Course** and **Batch**." },
            { text: "Add **Instructions**, for example *Closed book*." },
            { text: "Click **Schedule**." },
          ],
        },
        { type: "heading", text: "Step 2 — Let candidates see when and where" },
        {
          type: "paragraph",
          text: "Open the examination and turn on **Publish the schedule**. Candidates can then see the date, time and venue. They cannot see any marks.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/exam-detail.webp",
            alt: "An examination page showing total marks, passing marks, results recorded, results published, and the visibility switches.",
            caption:
              "The two visibility switches are independent: the schedule and the results are published separately.",
          },
        },
        { type: "heading", text: "Step 3 — Enter the marks" },
        {
          type: "steps",
          items: [
            {
              text: "Open the examination and click the **Mark sheet** tab.",
              image: {
                src: "super-admin/exam-marksheet.webp",
                alt: "The Mark sheet tab of an examination, where marks for the whole cohort are entered together.",
                caption:
                  "The mark sheet is filled in for the whole group in one save, like a register.",
              },
            },
            { text: "Type each candidate's mark." },
            { text: "Save the mark sheet." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A blank mark is not zero",
            body: "Leaving a box empty means 'not marked yet'. It does not mean the candidate scored nothing. Type 0 if that is what you mean.",
          },
        },
        { type: "heading", text: "Step 4 — Release the results" },
        {
          type: "paragraph",
          text: "When every mark is entered and checked, turn on **Publish every recorded result**. This releases all results for that examination at once.",
        },
        { type: "heading", text: "Invigilators" },
        {
          type: "paragraph",
          text: "The **Invigilators** tab is where you record who is supervising the examination.",
        },
      ],
      result:
        "The examination page shows how many results are recorded and how many are published, and candidates can see their marks once you publish them.",
      tips: [
        "Publish the schedule as early as you can. Candidates need to plan.",
        "Check the mark sheet twice before publishing results. Publishing affects every candidate at once.",
      ],
      problems: [
        {
          symptom: "Candidates cannot see the exam date.",
          fix: "**Publish the schedule** is still off.",
        },
        {
          symptom: "Candidates can see the date but not their marks.",
          fix: "That is correct until you turn on **Publish every recorded result**.",
        },
      ],
      related: ["gradebook", "quizzes", "transcripts"],
    },

    {
      id: "gradebook",
      title: "How to use the grade book",
      summary:
        "See every mark a student has earned on a batch, their standing, and the grading scale.",
      feature: "Grade book",
      learn: [
        "What each of the three tabs shows",
        "How to look up one student's marks",
        "How a percentage becomes a letter grade",
      ],
      before: ["Choose a **Batch** at the top — every tab is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "The **Grade book** brings every mark together for one batch. It has three tabs.",
        },
        { type: "heading", text: "Entries" },
        {
          type: "paragraph",
          text: "One row for every contribution a student has made: assignments, quizzes, attendance, practical work and the final exam. The columns show the student, the component, the score, its weight and when it was recorded.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/gradebook-entries.webp",
            alt: "The Entries tab of the grade book, listing each contribution with student, component, score, weight and date recorded.",
            caption:
              "Entries. Use **Component** to show only quizzes, for example, and **Student** for one person.",
          },
        },
        { type: "heading", text: "Student standing" },
        {
          type: "paragraph",
          text: "The result of the arithmetic: each student's position in the batch, worked out from the entries and weighted by the grading scheme.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/gradebook-standing.webp",
            alt: "The Student standing tab of the grade book.",
            caption: "Standing is computed from the entries — it is not typed in.",
          },
        },
        { type: "heading", text: "Grading scale" },
        {
          type: "paragraph",
          text: "The institution-wide bands that turn a percentage into a letter grade and GPA points. Transcripts are calculated against these.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/gradebook-scale.webp",
            alt: "The Grading scale tab showing the bands that convert a percentage into a letter and GPA points.",
            caption: "One scale for the whole institution, so grades mean the same everywhere.",
          },
        },
        { type: "heading", text: "Look up one student" },
        {
          type: "steps",
          items: [
            { text: "Click **Grade book** in the left-hand menu." },
            { text: "Choose the **Batch**." },
            { text: "Choose the **Student**." },
            { text: "Stay on **Entries** to see every mark, or click **Student standing** for the total." },
          ],
        },
      ],
      result: "You can explain exactly how a student's result was arrived at.",
      tips: [
        "If a standing looks wrong, look at **Entries** first. A missing or mistyped entry is the usual cause.",
        "Standing is calculated, never typed. To change it, change the entry behind it.",
      ],
      problems: [
        {
          symptom: "Every tab says to choose a batch.",
          fix: "Choose a **Batch** in the box at the top. Nothing is shown until you do.",
        },
        {
          symptom: "A student's standing is lower than expected.",
          fix: "Unmarked work may be counting as zero. Check the grading scheme's setting for work with no mark yet.",
        },
      ],
      related: ["performance", "grading-schemes", "transcripts", "assessment-overview"],
    },

    {
      id: "performance",
      title: "How to see student performance",
      summary:
        "The weighted standing of every student in a batch, and the arithmetic behind it.",
      feature: "Performance",
      learn: ["How to see a whole batch's results", "How the figure is worked out"],
      before: ["Choose a **Batch** — the screen is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "**Performance** answers one question: how is every student in this batch doing overall? It shows the weighted standing of each one, and lets you see the working behind the number.",
        },
        {
          type: "steps",
          items: [
            { text: "Click **Performance** in the left-hand menu." },
            {
              text: "Choose a **Batch**.",
              image: {
                src: "super-admin/performance-batch.webp",
                alt: "The Performance screen with a batch chosen.",
                caption: "Performance. The whole batch at once, in one list.",
              },
            },
            { text: "Read down the list to see how each student is doing." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "These figures come from the grade book and the active grading scheme. Nothing on this screen is typed in by hand.",
          },
        },
      ],
      result: "You can see at a glance who is doing well and who needs help.",
      tips: [
        "Use this before a progress meeting — it is faster than opening each student in turn.",
      ],
      problems: [
        {
          symptom: "The screen stays empty.",
          fix: "No batch is chosen, or the batch has no marks recorded yet.",
        },
        {
          symptom: "Everyone's figure looks too low.",
          fix: "Work that has not been marked yet may be counting as zero. Check the grading scheme.",
        },
      ],
      related: ["gradebook", "grading-schemes", "transcripts", "reports"],
    },

    {
      id: "transcripts",
      title: "How to generate transcripts",
      summary:
        "Produce the final, publishable record of how students did on a batch.",
      feature: "Transcripts",
      learn: ["What a transcript is", "How to generate them for a batch", "What 'finalised' means"],
      before: [
        "All marks should be recorded first — a transcript is a snapshot of what exists now.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **transcript** is the formal record of a student's standing on a batch: their marks brought together, converted to a grade using the grading scale, ready to be shared or printed.",
        },
        {
          type: "steps",
          items: [
            { text: "Click **Transcripts** in the left-hand menu." },
            {
              text: "Choose a **Batch**.",
              image: {
                src: "super-admin/transcripts-batch.webp",
                alt: "The Transcripts screen with a batch chosen and the Generate for batch button.",
                caption: "Choose the batch, then generate.",
              },
            },
            { text: "Click **Generate for batch**." },
            { text: "Use the **Student** filter to check an individual transcript." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Generating again is safe",
            body: "Regenerating leaves finalised transcripts alone. A transcript you have already finalised is never silently overwritten.",
          },
        },
      ],
      result: "Each student on the batch has a transcript showing their result.",
      tips: [
        "Generate transcripts only when marking is complete, otherwise they record a half-finished picture.",
        "Check two or three transcripts by hand the first time, against the grade book, so you trust the arithmetic.",
      ],
      problems: [
        {
          symptom: "A transcript shows a lower result than the grade book.",
          fix: "It was generated before the last marks were entered. Generate again — unless it has been finalised, in which case it is kept on purpose.",
        },
      ],
      related: ["gradebook", "performance", "exams"],
    },
  ],
};
