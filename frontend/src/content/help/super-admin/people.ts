import type { Section } from "../types";

/** Accounts, what each person may do, and who may see whom. */
export const people: Section = {
  id: "people",
  title: "People and permissions",
  blurb:
    "Accounts, roles, what each role may do, employers, guardians and corporate managers.",
  articles: [
    {
      id: "users",
      title: "How to create and manage user accounts",
      summary: "Add an account, give it roles, and find anybody in the institution.",
      feature: "Users",
      learn: [
        "How to create an account",
        "How to find somebody",
        "What the statuses mean",
      ],
      before: [
        "Know the person's email address and which roles they need.",
        "Decide how you will give them their password — this system sends no email.",
      ],
      body: [
        {
          type: "paragraph",
          text: "**Users** lists every account in the institution. A person's **roles** decide what they can do; the system checks that on every request, so what you set here is what is enforced.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/users.webp",
            alt: "The Users screen listing accounts with name, username, email and status, plus filters and the New account button.",
            caption:
              "The account list. Names and email addresses are blurred in this guide for privacy.",
          },
        },
        { type: "heading", text: "Create an account" },
        {
          type: "steps",
          items: [
            { text: "Click **Users** in the left-hand menu." },
            { text: "Click **New account**." },
            {
              text: "Type the **Email** and **Username**. Both are required.",
              image: {
                src: "super-admin/dialog-new-account.webp",
                alt: "The Create an account form showing Email, Username, Title, Gender, First name, Last name, Phone, Roles and Initial password.",
                caption:
                  "Each role is described next to its name, so you can see what you are granting.",
              },
            },
            { text: "Fill in **First name** and **Last name** so colleagues can recognise them." },
            {
              text: "Tick the **Roles** this person needs.",
              note: "Tick only what they need. You can add a role later; it is harder to undo damage done by one granted too early.",
            },
            {
              text: "Set an **Initial password**, or click **Generate** to have one made for you.",
            },
            { text: "Click **Create account**." },
            {
              text: "Give the person their password yourself, in person or by a channel you trust.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "There is no invitation email",
            body: "This system does not send email. Creating the account is you vouching for the person, and passing on the password is your job. Never send a password by ordinary email or a public chat.",
          },
        },
        { type: "heading", text: "Find somebody" },
        {
          type: "bullets",
          items: [
            "Type a name or email into **Search users**.",
            "Use **Any status** to show only active or only suspended accounts.",
            "Use **Any role** to list every tutor, for example.",
          ],
        },
        { type: "heading", text: "Open an account" },
        {
          type: "paragraph",
          text: "Click a person's name to open their account. From there you can edit their details, change their roles, and suspend or restore the account.",
        },
      ],
      result: "The new account appears in the list and the person can sign in.",
      tips: [
        "Use the **Generate** button for passwords. A generated password is far stronger than one you invent.",
        "Suspending an account is usually better than deleting it — the person's history stays intact.",
      ],
      problems: [
        {
          symptom: "The email address is refused.",
          fix: "Another account already uses it. Every email must be unique.",
        },
        {
          symptom: "The new person cannot sign in.",
          fix: "Check the username you gave them matches exactly, and that the account is active.",
        },
      ],
      related: ["roles", "permissions", "guardians", "manager-assignments"],
    },

    {
      id: "roles",
      title: "How roles work",
      summary: "A role is a named set of permissions. Create one and grant it what it needs.",
      feature: "Roles",
      learn: ["What a role is", "How to create a role", "Why a new role can do nothing at first"],
      body: [
        {
          type: "paragraph",
          text: "A **role** is a named set of permissions, such as Tutor or Administrator. Giving somebody a role gives them everything that role holds. A person can have more than one role, and they get everything from all of them added together.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/roles.webp",
            alt: "The Roles screen with the New role button.",
            caption: "Each role lists the permissions it holds.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Roles** in the left-hand menu." },
            { text: "Click **New role**." },
            {
              text: "Type a **Name** and a **Description**.",
              image: {
                src: "super-admin/dialog-new-role.webp",
                alt: "The Create a role form showing Name and Description.",
                caption: "The message explains that a new role starts with no permissions at all.",
              },
            },
            { text: "Click **Create role**." },
            {
              text: "Open the new role and grant it the permissions it needs.",
              note: "This is a separate step on purpose, so nobody is handed authority by a typo in a create form.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            body: "A new role can do nothing until you grant it permissions. If somebody with a new role sees empty screens, that is why.",
          },
        },
      ],
      result: "The role appears in the list, ready for you to grant permissions to.",
      tips: [
        "Grant the smallest set of permissions that lets somebody do their job.",
        "Write a description that says who the role is for. In a year nobody will remember.",
      ],
      related: ["permissions", "users"],
    },

    {
      id: "permissions",
      title: "How to check what a role can do",
      summary:
        "Look up every permission, see which roles hold it, and check what you hold yourself.",
      feature: "Permissions",
      learn: [
        "How to look up a permission",
        "How to compare roles",
        "How to check your own access",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **permission** is one thing somebody is allowed to do, such as creating a course. Roles hold permissions; people hold roles. This screen has three tabs.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/permissions.webp",
            alt: "The Permissions screen showing the Catalog, Role matrix and What I hold tabs with a filter box.",
            caption: "Three views of the same information.",
          },
        },
        {
          type: "definitions",
          items: [
            {
              term: "Catalog",
              detail:
                "Every permission the system recognises, with a description. Use **Filter permissions** to find one.",
            },
            {
              term: "Role matrix",
              detail:
                "A grid of roles against permissions. The quickest way to compare two roles.",
            },
            {
              term: "What I hold",
              detail: "Exactly what your own account can do right now.",
            },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "tip",
            title: "Use this to answer 'why can't they do that?'",
            body: "Find the permission in the **Catalog**, then check the **Role matrix** to see which roles hold it. Then check the person's roles on their account.",
          },
        },
      ],
      result: "You can explain precisely why somebody can or cannot do something.",
      related: ["roles", "users"],
    },

    {
      id: "organizations",
      title: "How to manage organizations",
      summary: "Employers whose staff are enrolled on your courses.",
      feature: "Organizations",
      learn: ["What an organization is", "How to add one"],
      body: [
        {
          type: "paragraph",
          text: "An **organization** is a corporate sponsor: an employer whose staff take your courses. Recording it lets you group those students and report on them together.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/organizations.webp",
            alt: "The Organizations screen listing organizations with their code and state.",
            caption: "Corporate sponsors.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Organizations** in the left-hand menu." },
            { text: "Click **New organization**." },
            {
              text: "Type the **Name**. It is the only required box.",
              image: {
                src: "super-admin/dialog-new-organization.webp",
                alt: "The New organization form showing Name, Code, Contact email and Contact phone.",
                caption: "Managers and members are added after the organization exists.",
              },
            },
            { text: "Add a **Code**, **Contact email** and **Contact phone** if you have them." },
            { text: "Click **Create**." },
          ],
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "Employing somebody grants nothing on its own",
            body: "Adding a company here does not let its manager see any student. That is done separately, on **Manager assignments**.",
          },
        },
      ],
      result: "The organization appears in the list and can have managers and members added.",
      related: ["manager-assignments", "users"],
    },

    {
      id: "guardians",
      title: "How to link a guardian to a student",
      summary:
        "Let a parent or carer see one student's attendance, grades and schedule.",
      feature: "Guardians",
      learn: ["What a guardian can see", "How to create the link"],
      before: [
        "The guardian must already have an account with the **Guardian** role.",
        "The student must already have an account with the **Student** role.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **guardian** is somebody allowed to follow a particular student — usually a parent or carer. A guardian sees only the students linked to them, and nobody else.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/guardians.webp",
            alt: "The Guardians screen listing guardian and student pairs with their relationship.",
            caption: "Each row is one guardian linked to one student.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Guardians** in the left-hand menu." },
            { text: "Click **Link a guardian**." },
            {
              text: "Choose the **Guardian** and the **Student**.",
              image: {
                src: "super-admin/dialog-link-guardian.webp",
                alt: "The Link a guardian to a student form showing Guardian, Student and Relationship.",
                caption: "Both people must already have the right role.",
              },
            },
            { text: "Choose the **Relationship**, such as parent." },
            { text: "Click **Link**." },
          ],
        },
      ],
      result:
        "The guardian can now see that student's progress, attendance and schedule when they sign in.",
      tips: [
        "Create the guardian's account first, with the Guardian role, or they will not appear in the list.",
        "A student can have more than one guardian.",
      ],
      problems: [
        {
          symptom: "The guardian does not appear in the list.",
          fix: "Their account does not hold the **Guardian** role. Add it on their account first.",
        },
        {
          symptom: "A guardian says they can see nothing.",
          fix: "Check that the link exists here, and that the student is enrolled on a batch.",
        },
      ],
      related: ["users", "manager-assignments", "my-team"],
    },

    {
      id: "manager-assignments",
      title: "How to assign students to a corporate manager",
      summary:
        "Decide which students each corporate manager is allowed to follow.",
      feature: "Manager assignments",
      learn: ["Why employment alone grants nothing", "How to assign a student to a manager"],
      before: [
        "The manager must have an account with the **Corporate Manager** role.",
        "The student must have an account with the **Student** role.",
      ],
      body: [
        {
          type: "paragraph",
          text: "A **corporate manager** follows the staff their company has sent on a course. This screen decides which students each one may see.",
        },
        {
          type: "callout",
          callout: {
            kind: "warning",
            title: "This is the only thing that grants access",
            body: "Working for the same company grants nothing by itself. A manager sees the students assigned to them here, and nobody else at that company.",
          },
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/manager-assignments.webp",
            alt: "The Manager assignments screen listing managers and the students assigned to them.",
            caption: "Each row is one manager allowed to see one student.",
          },
        },
        {
          type: "steps",
          items: [
            { text: "Click **Manager assignments** in the left-hand menu." },
            { text: "Click **Assign a student**." },
            {
              text: "Choose the **Manager** and the **Student**.",
              image: {
                src: "super-admin/dialog-assign-student.webp",
                alt: "The Assign a student to a manager form showing Manager, Student and Relationship.",
                caption:
                  "They do not have to work for the same company — or for any company.",
              },
            },
            { text: "Choose the **Relationship**." },
            { text: "Click **Assign**." },
          ],
        },
      ],
      result: "The manager can now follow that student's progress.",
      tips: [
        "Review these assignments when somebody leaves a company. The link does not expire by itself.",
      ],
      problems: [
        {
          symptom: "The manager does not appear in the list.",
          fix: "Their account does not hold the **Corporate Manager** role.",
        },
        {
          symptom: "A manager cannot see an employee.",
          fix: "There is no assignment for that pair. Add one here.",
        },
      ],
      related: ["organizations", "guardians", "users", "sync-data"],
    },

    {
      id: "my-team",
      title: "How to use My team",
      summary:
        "A progress summary for the people in your care — attendance, work and scores.",
      feature: "My team",
      learn: ["What My team shows", "What each column means"],
      body: [
        {
          type: "paragraph",
          text: "**My team** shows how the people in your care are getting on, in one table: their learning, attendance, assignments, average score and next class.",
        },
        {
          type: "screenshot",
          image: {
            src: "super-admin/my-team.webp",
            alt: "The My team screen with columns for person, learning, attendance, assignments, average score and next session.",
            caption:
              "A progress summary. Names are blurred in this guide for privacy.",
          },
        },
        {
          type: "callout",
          callout: {
            kind: "note",
            title: "Names only",
            body: "Contact details are never shown on this screen, whoever is looking at it.",
          },
        },
      ],
      result: "You can see who is falling behind without opening each person in turn.",
      related: ["guardians", "manager-assignments", "performance"],
    },
  ],
};
