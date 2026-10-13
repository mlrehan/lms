import type { Section } from "../types";

/**
 * The problems that do not belong to one screen.
 *
 * Problems specific to a feature live on that feature's own article, under
 * "If something goes wrong". This section is for the ones that send somebody
 * hunting through the whole guide.
 */
export const troubleshooting: Section = {
  id: "troubleshooting",
  title: "Solving problems",
  blurb: "Answers to the questions that come up most often.",
  articles: [
    {
      id: "common-problems",
      title: "Common problems and how to solve them",
      summary: "The usual causes of the most frequent complaints, and what to check first.",
      learn: [
        "What to check when somebody cannot see something",
        "What to do when a screen looks empty or wrong",
        "When a problem is one for your technical team",
      ],
      body: [
        { type: "heading", text: "Somebody cannot see a course or class" },
        {
          type: "paragraph",
          text: "Work down this list in order. The cause is almost always one of these, and they are listed with the most common first.",
        },
        {
          type: "steps",
          items: [
            {
              text: "Check the person is **enrolled** on the batch. Open **Enrollments** and filter by their name.",
            },
            {
              text: "Check the course is **published**. A draft course is invisible to students.",
            },
            { text: "Check the batch has **sessions** in the timetable." },
            {
              text: "Check their account is **active** on the **Users** screen.",
            },
            {
              text: "Check they hold the right **role**. A person with no Student role is not a student.",
            },
          ],
        },

        { type: "heading", text: "A screen looks empty" },
        {
          type: "bullets",
          items: [
            "**A filter is still set from last time.** This is by far the most common cause. Clear the search box and set every filter back to 'Any'.",
            "**Some screens need a batch or course chosen first.** Grade book, Performance, Transcripts and Assignments all show nothing until you choose one.",
            "**A date range is excluding everything.** Clear **From** and **To** on the Timetable.",
          ],
        },

        { type: "heading", text: "Somebody cannot sign in" },
        {
          type: "steps",
          items: [
            { text: "Ask them to check Caps Lock and type the password again slowly." },
            {
              text: "Open **Security** and look at **Locked accounts**. Too many wrong attempts locks an account.",
            },
            { text: "Check the account is active on **Users**." },
            {
              text: "Confirm they are using the right username. It is often an email address, but not always.",
            },
          ],
        },

        { type: "heading", text: "The times are all wrong" },
        {
          type: "paragraph",
          text: "Times are stored the same way for everybody and shown in each person's own timezone. If they look wrong to you, open **My account** and check your timezone. It is written at the top of the dashboard too.",
        },

        { type: "heading", text: "A student's result looks wrong" },
        {
          type: "steps",
          items: [
            {
              text: "Open the **Grade book**, choose the batch and the student, and look at **Entries**. A missing or mistyped entry is the usual cause.",
            },
            {
              text: "Check the **grading scheme** is active and its weights are what you expect.",
            },
            {
              text: "Check how the scheme treats **work with no mark yet**. Unmarked work counting as zero drags results down.",
            },
            {
              text: "If the transcript disagrees with the grade book, it was generated earlier. Generate it again.",
            },
          ],
        },

        { type: "heading", text: "A guardian or manager cannot see their student" },
        {
          type: "paragraph",
          text: "Being a parent, or working at the same company, grants nothing on its own. There must be an explicit link: **Guardians** for a guardian, **Manager assignments** for a corporate manager. Check the link exists, and that both people hold the right role.",
        },

        { type: "heading", text: "You changed something and nothing happened" },
        {
          type: "bullets",
          items: [
            "**A new role has no permissions until you grant them.**",
            "**A new grading scheme is inactive until you activate it.**",
            "**A new course is a draft until you publish it.**",
            "**A new quiz is unpublished until you publish it.**",
            "**An announcement outside its date window is stored but not shown.**",
          ],
        },

        { type: "heading", text: "When to ask your technical team" },
        {
          type: "paragraph",
          text: "Some things are not fixable from the console. Take a screenshot of **Operations** and describe what you did, if:",
        },
        {
          type: "bullets",
          items: [
            "Pages fail to load or show an error message you cannot act on.",
            "Automatic importing is switched on but never runs.",
            "The system is very slow for everybody at once.",
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "The audit log usually answers 'who changed this?'",
            body: "Before assuming something is broken, check the **Audit log**. A surprising number of mysteries turn out to be a colleague making a change.",
          },
        },
      ],
      related: ["security", "audit-log", "gradebook", "operations"],
    },
  ],
};
