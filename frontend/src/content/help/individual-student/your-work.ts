import type { Section } from "../types";

/** Finding the work, handing it in, quizzes and examinations. */
export const yourWork: Section = {
  id: "your-work",
  title: "Your work",
  blurb: "Finding what you have been set, handing it in, quizzes and examinations.",
  articles: [
    {
      id: "assignments",
      title: "How to find the work you have been set",
      summary: "Every assignment, when it is due, and what counts as overdue.",
      feature: "Assignments",
      learn: [
        "Where your coursework is listed",
        "What each column means",
        "How to tell what is late",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Assignments** lists the coursework you have been set, across every course you are taking. Nobody will remind you about these, so it is worth a look each week.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/assignments.webp",
            alt: "The Assignments screen listing two assignments with columns for assignment name, due date, type, whether late work is accepted and the maximum score.",
            caption: "Everything you have been set. A due date in the past is shown as time ago.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Assignment", detail: "The title, and which batch it was set for." },
            {
              term: "Due",
              detail:
                "When it has to be in. Past dates are shown as how long ago, such as 'yesterday'.",
            },
            {
              term: "Type",
              detail:
                "How you hand it in — **Text** means you type your answer, **File Upload** means you attach a file.",
            },
            {
              term: "Late work",
              detail:
                "Whether the tutor accepts work after the due date. 'Accepted' does not mean it will not be marked late.",
            },
            { term: "Max score", detail: "What the work is marked out of." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Overdue means due and not handed in",
            body: "Your dashboard counts this for you. If **Overdue assignments** is zero, there is nothing outstanding, whatever the list looks like.",
          },
        },
      ],
      result: "You know what you owe and when.",
      tips: [
        "Use the **Course** filter if you are taking more than one subject and the list is long.",
      ],
      related: ["submit", "quizzes", "dashboard"],
    },

    {
      id: "submit",
      title: "How to hand in an assignment",
      summary:
        "Opening a piece of work, reading the brief, submitting it, and checking it arrived.",
      feature: "Assignments",
      learn: [
        "How to read the brief",
        "How to hand work in",
        "How to check your submission arrived",
        "Where your mark appears",
      ],
      before: ["Have your work ready — typed, or saved as a file if the type is File Upload."],
      body: [
        {
          type: "paragraph",
          text: "Open an assignment by clicking its title. The top of the screen tells you everything about it before you start.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/assignment-detail.webp",
            alt: "An open assignment showing its course, type, that late work is accepted, the due date, what it is marked out of, the brief, and tabs for Submissions and My submission.",
            caption:
              "An open assignment. The brief is the tutor's instructions — read it before you start. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Brief", detail: "What the tutor is asking you to do. Read this first." },
            { term: "Type", detail: "Text to type, or File Upload to attach a file." },
            { term: "Due", detail: "The deadline, and how long away it is." },
            { term: "Out of", detail: "The maximum mark." },
          ],
        },
        { type: "heading", text: "Handing it in" },
        {
          type: "steps",
          items: [
            { text: "Click **Assignments** in the left-hand menu." },
            { text: "Click the assignment's title to open it." },
            { text: "Read the **Brief**." },
            {
              text: "Open the **My submission** tab.",
              note: "This is your own work. It is where you hand in and where your mark appears.",
            },
            { text: "Type your answer, or attach your file, and submit it." },
            {
              text: "Check it is listed with a time against it.",
              note: "If you cannot see a submitted time, it did not go through. Do it again rather than assuming.",
            },
          ],
        },
        { type: "heading", text: "What the columns mean afterwards" },
        {
          type: "definitions",
          items: [
            { term: "Submitted", detail: "When your work arrived." },
            {
              term: "Status",
              detail:
                "Where it has got to — handed in, being marked, or published. 'Published' means the mark has been released to you.",
            },
            { term: "Grade", detail: "Your mark, once it has been published." },
            { term: "Graded by", detail: "Which tutor marked it, and when." },
            { term: "Files", detail: "What you attached." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "'All submissions' still only shows yours",
            body: "There is a control labelled **All submissions**. On your account it means every submission you are allowed to see, which is your own. You cannot see other people's work, and they cannot see yours.",
          },
        },
      ],
      result: "Your work is in, with a time recorded against it.",
      tips: [
        "Hand in something rather than nothing if you are running out of time. Late and accepted beats missing.",
        "If late work is not accepted and you are going to miss the deadline, message your tutor **before** it passes.",
      ],
      problems: [
        {
          symptom: "You cannot see how to submit.",
          fix: "Open the **My submission** tab. The first tab shows the record, not the form.",
        },
        {
          symptom: "The deadline has passed.",
          fix: "Check the **Late work** column. If it says Accepted you can still hand in. If not, message your tutor.",
        },
        {
          symptom: "There is no mark yet.",
          fix: "It has not been marked, or the mark has not been published. Marks appear as the tutor works through them.",
        },
      ],
      related: ["assignments", "performance", "messages"],
    },

    {
      id: "quizzes",
      title: "How to take a quiz",
      summary:
        "Checking the time limit and how many attempts you get, then taking it — and why you cannot see the answers.",
      feature: "Quizzes",
      learn: [
        "How to check the rules before you start",
        "How to take a quiz",
        "Why the correct answers are not shown",
      ],
      before: [
        "Check how long you get and how many attempts are allowed. With one attempt, there is no second go.",
      ],
      body: [
        { type: "heading", text: "Check the rules first" },
        {
          type: "paragraph",
          text: "**Quizzes** are question sets marked by the system. The list tells you the rules before you commit to anything.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/quizzes.webp",
            alt: "The Quizzes screen listing quizzes with columns for the quiz name, its state, duration, number of attempts allowed and the pass mark.",
            caption:
              "Read this row before you open anything. Duration and attempts are the two that matter.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "State", detail: "Published means you can take it." },
            { term: "Duration", detail: "How long you get once you start." },
            {
              term: "Attempts",
              detail:
                "How many goes you are allowed. Often one — in which case there is no practice run.",
            },
            { term: "Pass mark", detail: "The score you need." },
          ],
        },
        { type: "heading", text: "Taking it" },
        {
          type: "screenshot",
          image: {
            src: "individual-student/quiz-detail.webp",
            alt: "An open quiz showing it is published, with the number of questions, total points, pass mark, attempts and duration, and tabs for Questions, Attempts and Take it.",
            caption: "An open quiz. Three tabs: the questions, your past attempts, and Take it.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Quizzes**, then the quiz title." },
            { text: "Read the summary line: questions, points, pass mark, attempts and time." },
            { text: "Look at the **Questions** tab to see what kind of questions they are." },
            {
              text: "When you are ready, open **Take it**.",
              note: "The clock starts when you begin. Do not open it to 'have a look' if you only get one attempt.",
            },
            { text: "Check **Attempts** afterwards for your score." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "The correct answers are not shown to you",
            body: "You can read the questions, but the system deliberately does not send the answer key to your account — before, during or after. That is not a fault, and it is the same for every student.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "One attempt means one",
            body: "If the Attempts column says 1, starting the quiz uses it up. Make sure you have the time and quiet to finish before you open Take it.",
          },
        },
      ],
      result: "Your attempt is recorded, with a score.",
      tips: [
        "Check the duration against the number of questions. Forty minutes for fifteen questions is comfortable; ten minutes is not.",
      ],
      problems: [
        {
          symptom: "There is no Take it tab.",
          fix: "The quiz may not be published yet, or you may have used all your attempts. Check the **Attempts** tab.",
        },
        {
          symptom: "You ran out of time.",
          fix: "Message your tutor. Whether you get another attempt is their decision, not something the system can give you.",
        },
      ],
      related: ["examinations", "performance", "assignments"],
    },

    {
      id: "examinations",
      title: "What examinations are, and when you will know your mark",
      summary:
        "Scheduled, supervised assessments — and why the date and the result are released separately.",
      feature: "Examinations",
      learn: [
        "How an examination differs from a quiz",
        "How to find out when yours is",
        "Why the result comes separately",
      ],
      body: [
        {
          type: "paragraph",
          text: "An **examination** is a scheduled, supervised assessment. Unlike a quiz, you do not take it in the system at a time of your choosing.",
        },
        {
          type: "screenshot",
          image: {
            src: "individual-student/examinations.webp",
            alt: "The Examinations screen showing one examination with its type, scheduled date, the passing and total marks, and whether its schedule is published.",
            caption: "Your examinations. The Schedule column says whether the date is confirmed.",
          },
        },
        {
          type: "definitions",
          items: [
            { term: "Type", detail: "Such as Midterm or Final." },
            { term: "Scheduled", detail: "When it is, once the school has released the date." },
            { term: "Marks", detail: "The pass mark and the total, shown as pass out of total." },
            {
              term: "Schedule",
              detail:
                "Whether the date has been published. Not published means it has not been announced yet.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "The date and the result are two separate releases",
            body: "The school publishes the schedule when the date is settled, and publishes the results later, when marking is done. One happening does not mean the other has.",
          },
        },
        {
          type: "paragraph",
          text: "When your result is released you will get a notification saying so, and the mark appears in your **Performance** standing and coursework breakdown.",
        },
      ],
      result: "You know when your examination is and where the result will appear.",
      tips: [
        "An examination with no date yet is normal part-way through a course. Keep an eye on your notifications.",
      ],
      related: ["performance", "notifications", "quizzes"],
    },
  ],
};
