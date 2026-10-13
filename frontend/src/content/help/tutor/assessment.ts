import type { Section } from "../types";

/** Setting work, marking it, and seeing how students are doing. */
export const assessment: Section = {
  id: "assessment",
  title: "Setting and marking work",
  blurb:
    "Assignments, quizzes, examinations, the grade book, and how students are doing.",
  articles: [
    {
      id: "assessment-overview",
      title: "How marking fits together",
      summary: "Read this first: where marks come from and what happens to them.",
      learn: [
        "The different kinds of work you can set",
        "How marks become a result",
        "Which parts are yours and which are not",
      ],
      body: [
        {
          type: "paragraph",
          text: "Marks come from several places and end up in one. Knowing the path makes every other article here easier.",
        },
        { type: "heading", text: "Step 1 — Students earn marks" },
        {
          type: "definitions",
          items: [
            {
              term: "Assignments",
              detail: "Work handed in, which you mark yourself.",
            },
            {
              term: "Quizzes",
              detail: "Questions the system marks automatically as soon as the student finishes.",
            },
            {
              term: "Examinations",
              detail: "Scheduled assessments where you type the marks in for the whole class.",
            },
            {
              term: "Attendance",
              detail: "Turning up can itself count, if the grading scheme says so.",
            },
            { term: "Practical work", detail: "Marks you add straight into the grade book." },
          ],
        },
        { type: "heading", text: "Step 2 — Everything lands in the grade book" },
        {
          type: "paragraph",
          text: "The **Grade book** holds one row for every contribution a student has made on a batch.",
        },
        { type: "heading", text: "Step 3 — A grading scheme decides what counts" },
        {
          type: "paragraph",
          text: "A **grading scheme** says how much each part is worth — for example assignments 30%, attendance 10%, final exam 60%. **Performance** shows the result of that arithmetic.",
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "The scheme is not yours to change",
            body: "You can read the grading scheme, but only a Super Admin can create or change one. If the weights look wrong for your course, raise it with them before marking starts.",
          },
        },
        { type: "heading", text: "Step 4 — Results become transcripts" },
        {
          type: "paragraph",
          text: "A **transcript** is the final record for a batch. You can read transcripts; generating them is an administrator's job.",
        },
      ],
      related: ["assignments", "quizzes", "exams", "gradebook", "performance"],
    },

    {
      id: "assignments",
      title: "How to set and mark an assignment",
      summary: "Create coursework for your class, publish it, and mark what comes in.",
      feature: "Assignments",
      learn: ["How to create an assignment", "What each setting does", "Where marking happens"],
      before: ["You must teach the course you are setting work for."],
      body: [
        {
          type: "paragraph",
          text: "An **assignment** is a piece of work students hand in. You set it, they submit, you mark it.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/assignments.webp",
            alt: "A tutor's Assignments screen with a course picker and the New assignment button.",
            caption: "Choose a **Course** first — the list is empty until you do.",
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
                src: "tutor/dialog-new-assignment.webp",
                alt: "The New assignment form showing Course, Set for, Title, Due, Maximum score, Submission type, Description, Opens, Passing mark and On save.",
                caption: "Boxes marked with a star must be filled in.",
              },
            },
            {
              text: "Use **Set for** to choose who gets it. The default is everyone on the course.",
            },
            {
              text: "Set the **Due** date and time.",
              note: "You type the time in your own timezone; the system stores it correctly for everybody.",
            },
            { text: "Set the **Maximum score** — the marks the work is out of." },
            { text: "Choose the **Submission type**, such as text or a file." },
            { text: "Write the **Description** telling students exactly what to do." },
            {
              text: "Optionally set **Opens** (when students first see it) and a **Passing mark**.",
            },
            {
              text: "Choose what happens **On save**. Publishing now notifies students immediately.",
            },
            { text: "Click **Create assignment**." },
          ],
        },
        { type: "heading", text: "Marking" },
        {
          type: "paragraph",
          text: "Marking happens on the assignment itself. Open it from the list to see who has submitted, enter marks and write feedback.",
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            body: "**Awaiting grading** on your dashboard counts work students have handed in that nobody has marked. It is the quickest way to see whether you are behind.",
          },
        },
      ],
      result:
        "The assignment appears under that course, and students see it once it is published.",
      tips: [
        "Write the description as if the student has no other instructions — many will not have any.",
        "Avoid midnight deadlines. They cause avoidable arguments.",
      ],
      problems: [
        {
          symptom: "The assignment list is empty.",
          fix: "You have not chosen a course yet. The list fills in once you do.",
        },
        {
          symptom: "Students say they cannot see it.",
          fix: "It may still be unpublished, or its **Opens** date may be in the future.",
        },
      ],
      related: ["gradebook", "quizzes", "assessment-overview"],
    },

    {
      id: "quizzes",
      title: "How to build and run a quiz",
      summary:
        "Create a quiz, add questions and answers, set how it runs, and see how students did.",
      feature: "Quizzes",
      learn: [
        "How to create a quiz and add questions",
        "What each setting does",
        "How to see and re-mark attempts",
      ],
      before: ["You must teach the course."],
      body: [
        {
          type: "paragraph",
          text: "A **quiz** is a set of questions the system marks for you automatically. Use it for knowledge checks. For a scheduled, invigilated assessment use **Examinations** instead.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/quizzes.webp",
            alt: "A tutor's Quizzes screen with the New quiz button.",
            caption: "Your quizzes.",
          },
        },
        { type: "heading", text: "Step 1 — Create the quiz" },
        {
          type: "steps",
          items: [
            { text: "Click **Quizzes** in the left-hand menu." },
            { text: "Click **New quiz**." },
            {
              text: "Choose the **Course**, type a **Title** and set the **Passing score**.",
              image: {
                src: "tutor/dialog-new-quiz.webp",
                alt: "The New quiz form showing Course, Title, Duration, Attempts allowed, Passing score, Instructions and a shuffle option.",
                caption: "A quiz starts unpublished, so students cannot see it yet.",
              },
            },
            { text: "Set **Duration (minutes)** and **Attempts allowed** if you want limits." },
            { text: "Add **Instructions** for the student." },
            { text: "Click **Create quiz**." },
          ],
        },
        { type: "heading", text: "Step 2 — Add questions" },
        {
          type: "steps",
          items: [
            { text: "Open the quiz by clicking its title." },
            { text: "On the **Questions** tab, click **Add question**." },
            { text: "Type the question, choose its type, and set how many points it is worth." },
            { text: "Enter the answers and mark which are correct." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Students never receive the answer key",
            body: "The answers you mark correct are only visible to people who can edit the quiz. What the system sends a student contains nothing about which answer is right.",
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
              detail: "Optional. Set one and questions beyond it are refused.",
            },
            {
              term: "Questions per attempt",
              detail:
                "Leave blank to use every question. A number draws that many at random, so students get different papers.",
            },
            { term: "Shuffle", detail: "Mix up the question order, the answer order, or both." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "A quiz locks once somebody has sat it",
            body: "After the first attempt you cannot change the pass mark or the number of questions, because that would rewrite what an existing result means. Check the settings before you publish.",
          },
        },
        { type: "heading", text: "Step 4 — Publish it" },
        {
          type: "paragraph",
          text: "Use the **Published** switch at the top of the quiz. Until then, students cannot see or attempt it.",
        },
        { type: "heading", text: "Step 5 — See how students did" },
        {
          type: "steps",
          items: [
            { text: "Open the **Attempts** tab to see each student's attempt and score." },
            {
              text: "If you corrected an answer key afterwards, click **Re-mark** to score that attempt again.",
            },
          ],
        },
        {
          type: "paragraph",
          text: "**Take it** lets you sit the quiz yourself. This is the best way to check it reads properly before students see it.",
        },
      ],
      result: "Students can take the quiz, and their scores reach the grade book.",
      tips: [
        "Always use **Take it** once before publishing. Typos are very hard to spot while writing.",
        "An attempt stuck as **In progress** can be cleared with **Close expired attempts** on the Settings tab.",
      ],
      problems: [
        {
          symptom: "Students cannot see the quiz.",
          fix: "It is not published. Turn on the **Published** switch at the top.",
        },
        {
          symptom: "You cannot change the pass mark.",
          fix: "Somebody has already sat it, so it is locked. This protects results already given.",
        },
      ],
      related: ["assignments", "exams", "gradebook"],
    },

    {
      id: "exams",
      title: "How to schedule an examination and record results",
      summary:
        "Schedule an exam, publish the schedule, enter marks for the whole class, then publish results.",
      feature: "Examinations",
      learn: [
        "How to schedule an examination",
        "How to enter marks on the mark sheet",
        "The difference between publishing the schedule and publishing the results",
      ],
      before: ["You must teach the course.", "Decide the total marks and the pass mark."],
      body: [
        {
          type: "paragraph",
          text: "An **examination** is a scheduled, invigilated assessment. The system does not mark it — you enter the marks yourself.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/examinations.webp",
            alt: "A tutor's Examinations screen with the Schedule examination button.",
            caption: "Your examinations.",
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
                src: "tutor/dialog-new-exam.webp",
                alt: "The Schedule an examination form showing Title, Type, Scheduled, Duration, Total marks, Passing marks, Venue, Course, Batch and Instructions.",
                caption: "The schedule can be published before any results exist.",
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
          text: "Open the examination and turn on **Publish the schedule**. Candidates can then see the date, time and venue, but no marks.",
        },
        { type: "heading", text: "Step 3 — Enter the marks" },
        {
          type: "steps",
          items: [
            { text: "Open the examination and click the **Mark sheet** tab." },
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
      ],
      result:
        "The examination page shows how many results are recorded and published, and candidates see their marks once published.",
      tips: [
        "Publish the schedule early — candidates need to plan.",
        "Check the mark sheet twice before publishing. Publishing affects every candidate at once.",
      ],
      problems: [
        {
          symptom: "Candidates cannot see the exam date.",
          fix: "**Publish the schedule** is still off.",
        },
        {
          symptom: "Candidates see the date but not their marks.",
          fix: "That is correct until you turn on **Publish every recorded result**.",
        },
      ],
      related: ["gradebook", "quizzes", "assessment-overview"],
    },

    {
      id: "gradebook",
      title: "How to use the grade book",
      summary: "Every mark a student has earned on a batch, and how to add one.",
      feature: "Grade book",
      learn: [
        "What each of the three tabs shows",
        "How to add a mark yourself",
        "What Sync from marks does",
      ],
      before: ["Choose a **Batch** at the top — every tab is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "The **Grade book** brings every mark together for one batch. It has three tabs.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/gradebook-batch.webp",
            alt: "The grade book Entries tab with a batch chosen, showing the Sync from marks and Add entry buttons.",
            caption:
              "Entries, with a batch chosen. Note **Sync from marks** and **Add entry**.",
          },
        },
        { type: "heading", text: "Entries" },
        {
          type: "paragraph",
          text: "One row for every contribution a student has made: assignments, quizzes, attendance, practical work and the final exam.",
        },
        {
          type: "definitions",
          items: [
            {
              term: "Sync from marks",
              detail:
                "Brings in the marks already recorded elsewhere — assignments, quizzes and examinations — so you do not type them twice.",
            },
            {
              term: "Add entry",
              detail:
                "Record a mark by hand. Use this for practical work, or anything assessed outside the system.",
            },
          ],
        },
        { type: "heading", text: "Student standing" },
        {
          type: "paragraph",
          text: "Each student's position in the batch, worked out from the entries and weighted by the grading scheme. It is calculated, never typed.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/gradebook-standing.webp",
            alt: "The Student standing tab of the grade book.",
            caption: "Standing is computed from the entries.",
          },
        },
        { type: "heading", text: "Grading scale" },
        {
          type: "paragraph",
          text: "The bands that turn a percentage into a letter grade and GPA points. These are set for the whole institution, so grades mean the same on every course.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/gradebook-scale.webp",
            alt: "The Grading scale tab showing the bands that convert a percentage into a letter grade.",
            caption: "One scale for the whole institution. You can read it, not change it.",
          },
        },
      ],
      result: "You can explain exactly how a student's mark was arrived at.",
      tips: [
        "If a standing looks wrong, check **Entries** first. A missing or mistyped entry is the usual cause.",
        "Use **Sync from marks** before adding anything by hand — the mark may already be there.",
      ],
      problems: [
        {
          symptom: "Every tab tells you to choose a batch.",
          fix: "Choose a **Batch** in the box at the top. Nothing shows until you do.",
        },
        {
          symptom: "A student's standing is lower than expected.",
          fix: "Work that has not been marked may be counting as zero. Check with whoever set the grading scheme.",
        },
      ],
      related: ["performance", "assignments", "exams", "assessment-overview"],
    },

    {
      id: "performance",
      title: "How to see how your students are doing",
      summary:
        "Every student in a batch with their current percentage and grade, and the working behind it.",
      feature: "Performance",
      learn: ["How to see a whole class at once", "What 'so far incomplete' means"],
      before: ["Choose a **Batch** — the screen is empty until you do."],
      body: [
        {
          type: "paragraph",
          text: "**Performance** answers one question: how is everybody in this class doing? It is computed per batch, because the weighting comes from the course's grading scheme.",
        },
        {
          type: "steps",
          items: [
            { text: "Click **Performance** in the left-hand menu." },
            {
              text: "Choose a **Batch**.",
              image: {
                src: "tutor/performance-batch.webp",
                alt: "The Performance screen for a batch, listing each student with a percentage, a status of so far incomplete, and a letter grade.",
                caption:
                  "Each student with their percentage and grade. Names are blurred in this guide for privacy.",
              },
            },
            {
              text: "Click a student's row to see every component, its weight and what it contributed.",
            },
            { text: "Click **Profile** to open that student." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "What 'so far incomplete' means",
            body: "It means not everything has been assessed yet. The percentage is out of the work done so far, so it will move as the course goes on. It is not a final result.",
          },
        },
      ],
      result: "You can see at a glance who is doing well and who needs help.",
      tips: [
        "Look at this before a progress meeting — it is far faster than opening each student in turn.",
        "A low figure early in a course is often just unmarked work, not a struggling student.",
      ],
      problems: [
        {
          symptom: "The screen stays empty.",
          fix: "No batch is chosen, or no marks have been recorded yet.",
        },
      ],
      related: ["gradebook", "transcripts-and-schemes", "reports"],
    },

    {
      id: "transcripts-and-schemes",
      title: "What transcripts and grading schemes are for",
      summary:
        "Two screens you can look at but not change, and what they are for.",
      feature: "Transcripts, Grading schemes",
      learn: ["What a transcript is", "What a grading scheme is", "Who to ask to change them"],
      body: [
        {
          type: "paragraph",
          text: "These two screens appear in your menu, but your account can only read them. They matter because they decide what your marking adds up to.",
        },
        { type: "heading", text: "Grading schemes" },
        {
          type: "paragraph",
          text: "A **grading scheme** lists what counts towards a result and how much each part is worth. Your institution has a default scheme with several components totalling 100%.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/grading-schemes.webp",
            alt: "The Grading schemes screen showing the institution default scheme with its number of components.",
            caption: "Read-only for a tutor. There is no New scheme button on your account.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Check the scheme before term starts",
            body: "It tells you how much your assignments and the final exam are each worth. If that looks wrong for your course, raise it with a Super Admin before you start marking — changing it later changes everybody's result at once.",
          },
        },
        { type: "heading", text: "Transcripts" },
        {
          type: "paragraph",
          text: "A **transcript** is the final, formal record of a student's standing on a batch. You can look one up by batch or student. Generating them is an administrator's job.",
        },
        {
          type: "screenshot",
          image: {
            src: "tutor/transcripts.webp",
            alt: "The Transcripts screen with batch and student filters and no generate button.",
            caption: "You can read transcripts. There is no **Generate for batch** button for a tutor.",
          },
        },
      ],
      result: "You know what your marks add up to, and who to ask if it is wrong.",
      related: ["gradebook", "performance", "assessment-overview"],
    },
  ],
};
