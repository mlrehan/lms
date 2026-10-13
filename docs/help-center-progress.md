# Help Center — build progress and feature coverage

The persistent record for the role-by-role user guide project. Update it at
the end of each role so an interrupted run resumes from the last verified
checkpoint instead of repeating work.

**No credentials, tokens or personal data belong in this file.**

---

## Status

| Role | Guide | State | Articles | Screenshots |
|---|---|---|---|---|
| Super Admin | `/help/super-admin` | **Complete** | 41 | 55 |
| Tutor | `/help/tutor` | **Complete** | 25 | 32 |
| Corporate Manager | `/help/corporate-manager` | **Complete** | 22 | 19 |
| Guardian | `/help/guardian` | **Complete** | 19 | 18 |
| Student (managed) | — | Not started | — | — |
| Student (individual) | — | Not started | — | — |

**Last completed checkpoint:** Guardian guide built, integrated and verified in
a browser (12 October 2026). Super Admin, Tutor and Corporate Manager complete
before it.

---

## How the Help Center is built

| Thing | Where |
|---|---|
| Article content | `frontend/src/content/help/<role>/*.ts` |
| Content model | `frontend/src/content/help/types.ts` |
| Guide registry | `frontend/src/content/help/index.ts` |
| Pages | `frontend/src/app/help/` |
| Shared components | `frontend/src/components/help/` |
| Screenshots | `frontend/public/help/<role>/*.webp` |
| Validation tests | `frontend/src/content/help/help-content.test.ts` |

Articles are **typed data, not Markdown**. The template (what you will learn,
before you begin, steps, expected result, tips, problems, related) is enforced
by the type, `related` ids are checked against real articles by a test, and
search is built from the same data the page renders. Adding an article means
adding one object to a section's `articles` array; nothing else changes.

### Adding a new role guide

1. Create `frontend/src/content/help/<role>/` with one file per section.
2. Export a `Guide` from that folder's `index.ts`.
3. Add it to `GUIDES` and to `ROLE_TO_GUIDE` in `content/help/index.ts`.
4. Put screenshots in `frontend/public/help/<role>/`.
5. Run `npx vitest run src/content/help` — it fails on a broken link or a
   missing screenshot file.

A role is left out of `ROLE_TO_GUIDE` until its guide is finished, so the
sidebar never links to an empty guide.

### Capturing screenshots

The capture scripts live in the working session's scratchpad, not in the
repository, because they need credentials. They do three things worth
repeating:

- Log in as the role, walk every route, and record what is really on each
  page (headings, tabs, buttons, columns) to JSON, so articles are written
  from the application rather than from memory.
- **Blur personal data before the shutter opens**: every table cell under a
  column named for a person or a contact detail, and any element whose text
  looks like an email address. These pages are public.
- Capture at 1440×900 at 2× and convert to WebP at 1600px wide.

---

## Super Admin — feature coverage matrix

Every item in the Super Admin sidebar, checked against the running console on
12 October 2026. "Verified" means the page was opened and photographed while
signed in as a Super Admin.

| Menu group | Screen | Route | Article | Screens | Status |
|---|---|---|---|---|---|
| Overview | Dashboard | `/` | `dashboard`, `sync-data` | 1 | Verified |
| Learning | Courses | `/courses` | `courses` | 2 | Verified |
| Learning | Batches | `/batches` | `batches` | 2 | Verified |
| Learning | Timetable | `/sessions` | `timetable` | 1 | Verified |
| Learning | Enrollments | `/enrollments` | `enrollments` | 1 | Verified |
| Learning | Attendance | `/attendance` | `attendance` | 2 | Verified (both tabs) |
| Assessment | Assignments | `/assignments` | `assignments` | 2 | Verified |
| Assessment | Quizzes | `/quizzes` | `quizzes` | 5 | Verified (all 4 tabs + create form) |
| Assessment | Examinations | `/exams` | `exams` | 4 | Verified (detail + mark sheet) |
| Assessment | Grade book | `/gradebook` | `gradebook` | 3 | Verified (all 3 tabs) |
| Assessment | Performance | `/performance` | `performance` | 1 | Verified (with a batch chosen) |
| Assessment | Transcripts | `/transcripts` | `transcripts` | 1 | Verified (with a batch chosen) |
| Assessment | Grading schemes | `/grading-schemes` | `grading-schemes` | 2 | Verified (+ create form) |
| Content | Resources | `/resources` | `resources` | 1 | Verified |
| Content | Shared with me | `/shared-with-me` | `shared-with-me` | 1 | Verified |
| Community | Announcements | `/announcements` | `announcements` | 2 | Verified |
| Community | Discussions | `/discussions` | `discussions` | 2 | Verified |
| Community | Messages | `/messages` | `messages` | 1 | Verified |
| Community | Notifications | `/notifications` | `notifications` | 1 | Verified |
| People | My team | `/team` | `my-team` | 1 | Verified |
| People | Users | `/users` | `users` | 2 | Verified |
| People | Roles | `/roles` | `roles` | 2 | Verified |
| People | Permissions | `/permissions` | `permissions` | 1 | Verified |
| People | Organizations | `/organizations` | `organizations` | 2 | Verified |
| People | Guardians | `/guardians` | `guardians` | 2 | Verified |
| People | Manager assignments | `/manager-links` | `manager-assignments` | 2 | Verified |
| Administration | Academic setup | `/academic` | `academic-setup` | 1 | Verified (5 tabs) |
| Administration | Integrations | `/integrations` | `integrations` | 1 | Verified (3 tabs) |
| Administration | System settings | `/settings` | `system-settings` | 1 | Verified |
| Insights | Reports | `/reports` | `reports` | 1 | Verified (6 tabs) |
| Insights | Audit log | `/audit` | `audit-log` | 1 | Verified |
| Insights | Security | `/security` | `security` | 1 | Verified (3 tabs) |
| Insights | Operations | `/ops` | `operations` | 1 | Verified |
| Account | My account | `/account` | `account`, `sign-out` | 1 | Verified |
| — | Sign in | `/login` | `sign-in` | 0 | Verified |

Plus four articles with no single screen of their own: `welcome`, `sidebar`,
`assessment-overview` and `common-problems`.

### Depth of coverage

Every screen has an article. Beyond that, these workflows were opened and
photographed rather than described from the list page:

- Quiz: Questions, Attempts, Settings and Take it tabs, and the answer key.
- Examination: the detail page, the two visibility switches, and the mark sheet.
- Grade book: Entries, Student standing and Grading scale.
- Attendance: Take attendance and Records.
- Twelve "create" dialogs, opened to read their real field names and closed
  without saving: course, batch, assignment, quiz, examination, account, role,
  organization, guardian link, manager assignment, announcement, discussion.

### Not covered, and why

| Item | Why |
|---|---|
| Completing a create/edit/delete action end to end | The console runs against real institution data. Dialogs were opened and read, never submitted. The steps describe the real fields; the final click was not performed. |
| Google Calendar **Sync to Google now** | Would write to a connected Google account and alter real calendars. Described from the screen, not exercised. |
| Marking a real register, publishing results, generating transcripts | Each changes a real student's record. Described from the screens, not exercised. |
| Webhook creation | Sends institution data to an outside address. Not exercised. |

Articles covering these say what the screen does and what the buttons mean;
they do not claim an outcome that was not observed.

---

## Known application issues found while documenting

| Issue | Detail |
|---|---|
| None blocking | Every Super Admin screen loaded, rendered and responded as described. |

Notes rather than faults:

- `/messages` renders outside the page's `<main>` element. Harmless, but it
  means a naive DOM scrape of that route returns nothing.
- Several screens (Grade book, Performance, Transcripts, Assignments) show
  nothing until a batch or course is chosen. This confuses people often enough
  that it is called out in the troubleshooting article.

---

## Verification performed (Super Admin)

| Check | Result |
|---|---|
| Every article opens signed out, fresh browser profile | 41/41 HTTP 200, no redirect to login |
| Broken internal links | 0 |
| Screenshots load | All, once scrolled into view (they are lazy-loaded) |
| Screenshot files exist for every reference | Enforced by test |
| Search | Returns results for real terms, an honest empty state otherwise |
| Table of contents anchors | Jump to a heading that exists |
| Click-to-enlarge | Opens and closes with Escape |
| Mobile at 375px | No horizontal overflow; Contents drawer opens |
| Sidebar link | Present for Super Admin, absent for Tutor and Student |
| Personal data in screenshots | Blurred; verified by inspecting the Users, Audit log and Quiz attempts captures |
| Credentials in content | Enforced absent by test |
| Console errors on public pages | 0 |


---

## Tutor — feature coverage matrix

Checked against the running console signed in as a Tutor on 12 October 2026.
A tutor sees **21 sidebar items**; twelve screens a Super Admin can open are
absent from a tutor's menu entirely, so they have no articles.

| Menu group | Screen | Route | Article | Status |
|---|---|---|---|---|
| Overview | Dashboard | `/` | `dashboard` | Verified |
| Learning | Courses | `/courses` | `courses` | Verified (read-only for a tutor) |
| Learning | Batches | `/batches` | `batches` | Verified (workspace, all 4 tabs) |
| Learning | Timetable | `/sessions` | `timetable` | Verified |
| Learning | Enrollments | `/enrollments` | `enrollments` | Verified (read-only) |
| Learning | Attendance | `/attendance` | `attendance` | Verified (register opened, not submitted) |
| Assessment | Assignments | `/assignments` | `assignments` | Verified (+ create form) |
| Assessment | Quizzes | `/quizzes` | `quizzes` | Verified (+ create form) |
| Assessment | Examinations | `/exams` | `exams` | Verified (+ create form) |
| Assessment | Grade book | `/gradebook` | `gradebook` | Verified (all 3 tabs, batch chosen) |
| Assessment | Performance | `/performance` | `performance` | Verified (batch chosen) |
| Assessment | Transcripts | `/transcripts` | `transcripts-and-schemes` | Verified (read-only) |
| Assessment | Grading schemes | `/grading-schemes` | `transcripts-and-schemes` | Verified (read-only) |
| Content | Resources | `/resources` | `resources` | Verified |
| Content | Shared with me | `/shared-with-me` | `resources` | Verified |
| Community | Announcements | `/announcements` | `announcements` | Verified (+ create form) |
| Community | Discussions | `/discussions` | `discussions` | Verified (+ create form) |
| Community | Messages | `/messages` | `messages` | Verified |
| Community | Notifications | `/notifications` | `notifications` | Verified |
| Administration | Academic setup | `/academic` | `academic-setup` | Verified (read-only) |
| Insights | Reports | `/reports` | `reports` | Verified (6 tabs) |
| Account | My account | `/account` | `account` | Verified |
| — | Sign in | `/login` | `sign-in` | Verified |

Plus `welcome`, `sidebar`, `assessment-overview` and `common-problems`.

### What a tutor cannot do, verified rather than assumed

Established by comparing the buttons present on each screen for a Tutor
against the same screen for a Super Admin:

| Not available to a tutor | Screen |
|---|---|
| New course, Sync courses & batches, History | Courses |
| New batch, Sync with Google, the **FEE** column | Batches |
| Any create/edit/remove action | Enrollments |
| New scheme | Grading schemes |
| Generate for batch | Transcripts |
| Add year (and every other add) | Academic setup |
| Export CSV | Reports |
| The whole screen | Users, Roles, Permissions, Organizations, Guardians, Manager assignments, My team, Integrations, System settings, Audit log, Security, Operations |

Data is scoped as well as gated, confirmed against the API as both roles:
courses 28 → 9, batches 26 → 3, sessions 66 → 14, enrolments 41 → 12,
users 82 → 11.

### Not covered, and why

Identical to the Super Admin guide: dialogs were opened and read but never
submitted, and no register was marked, no result published and no mark saved.
The register screen was opened and photographed with **no student marked**,
because marking writes a draft against a real class.

### Verification performed (Tutor)

| Check | Result |
|---|---|
| Every article opens signed out, fresh profile | 25/25 HTTP 200, no redirect |
| Broken internal links | 0 |
| Search, table of contents, click-to-enlarge | Pass |
| Mobile at 375px | No horizontal overflow; drawer opens |
| Sidebar link | `/help/tutor` present for a Tutor, correct label, opens in a new tab |
| Console errors on public pages | 0 |


---

## Corporate Manager — feature coverage matrix

Checked against the running console on 12 October 2026.

**One care point worth repeating.** The test account holds **both**
`CORPORATE_MANAGER` and `STUDENT`, so it can open four screens the
corporate-manager role does not grant: Announcements, Discussions, Resources
and Grading schemes. The pure-role view was computed from the permission
catalogue against `navigation.ts` rather than read off that account's screen,
and the guide documents the role, not the account. The sidebar article tells a
reader who sees extra items why.

A pure corporate manager sees **19 sidebar items**.

| Menu group | Screen | Route | Article | Status |
|---|---|---|---|---|
| Overview | Dashboard | `/` | `dashboard` | Verified |
| Learning | Courses | `/courses` | `courses` | Verified (whole catalogue) |
| Learning | Batches | `/batches` | `batches` | Verified (3 tabs; **Enroll** exercised as far as the dialog) |
| Learning | Timetable | `/sessions` | `timetable` | Verified |
| Learning | Enrollments | `/enrollments` | `enrollments` | Verified (read-only) |
| Learning | Attendance | `/attendance` | `attendance` | Verified (read-only, no tabs) |
| Assessment | Assignments | `/assignments` | `work-and-results` | Verified (read-only) |
| Assessment | Quizzes | `/quizzes` | `work-and-results` | Verified (read-only) |
| Assessment | Examinations | `/exams` | `work-and-results` | Verified (read-only) |
| Assessment | Grade book | `/gradebook` | `work-and-results` | Verified (batch chosen) |
| Assessment | Performance | `/performance` | `performance` | Verified (batch chosen) |
| Assessment | Transcripts | `/transcripts` | `transcripts` | Verified (read-only) |
| Content | Shared with me | `/shared-with-me` | `shared-with-me` | Verified |
| Community | Messages | `/messages` | `messages` | Verified |
| Community | Notifications | `/notifications` | `notifications` | Verified |
| People | My team | `/team` | `my-team` | Verified |
| People | Organizations | `/organizations` | `organizations` | Verified (both tabs) |
| People | Manager assignments | `/manager-links` | `manager-assignments` | Verified (read-only) |
| Administration | Academic setup | `/academic` | `academic-setup` | Verified (read-only) |
| Insights | Reports | `/reports` | `reports` | Verified (6 tabs, **Export CSV** present) |
| Account | My account | `/account` | `account` | Verified |
| — | Sign in | `/login` | `sign-in` | Verified |

Plus `welcome`, `sidebar` and `common-problems`.

### The manager's one write action

`enrollment.create` surfaces in exactly **one** place in the whole console:
the batch workspace, Enrollments tab, **Enroll** button. That was found by
searching the frontend for the permission, then confirmed by opening a batch
as the manager and seeing the button appear. The dialog was opened and
cancelled; nobody was enrolled.

Everything else a manager can do is reading. **Add employee** on their own
company is the only other control, and it was not exercised.

### Scoping, verified against the API as both roles

| | Super Admin | Corporate Manager |
|---|---|---|
| courses | 28 | 28 (they hold `course.view_all`) |
| batches | 26 | 1 |
| sessions | 66 | 6 |
| enrolments | 41 | 7 |
| users | 82 | 8 |
| manager assignments | 15 | 7 |
| organizations | 14 | 1 |

### Verification performed (Corporate Manager)

| Check | Result |
|---|---|
| Every article opens signed out, fresh profile | 22/22 HTTP 200, no redirect |
| Broken internal links | 0 |
| Search, table of contents, click-to-enlarge | Pass |
| Mobile at 375px | No horizontal overflow; drawer opens |
| Sidebar link | `/help/corporate-manager`, correct label, new tab |
| Console errors on public pages | 0 |


---

## Guardian — feature coverage matrix

**There was no guardian in this environment.** The two accounts the brief
named (`gina@lmsdemo.com`, `cal@lmsdemo.com`) do not exist here, **no account
held the GUARDIAN role**, and `student_guardians` was empty. The guide could
not be written by inspection until that was fixed.

With the user's approval, one guardian account was created through the API
exactly as an administrator would, linked to an existing student with real
attendance and marks, used for these screenshots, and then removed. Afterwards:
**0 guardian links, 0 live GUARDIAN accounts.** The account is soft-deleted
(users cannot be hard-deleted — `audit_logs` references them), so that row and
its audit entries remain by design.

A guardian sees **19 sidebar items** and can change nothing.

| Menu group | Screen | Route | Article | Status |
|---|---|---|---|---|
| Overview | Dashboard | `/` | `dashboard` | Verified |
| Learning | Courses | `/courses` | `course` | Verified (whole catalogue) |
| Learning | Batches | `/batches` | `course` | Verified |
| Learning | Timetable | `/sessions` | `timetable` | Verified |
| Learning | Enrollments | `/enrollments` | `course` | Verified (read-only) |
| Learning | Attendance | `/attendance` | `attendance` | Verified (read-only) |
| Assessment | Assignments | `/assignments` | `work` | Verified (read-only) |
| Assessment | Quizzes | `/quizzes` | `work` | Verified (read-only) |
| Assessment | Examinations | `/exams` | `work` | Verified (read-only) |
| Assessment | Grade book | `/gradebook` | `grades` | Verified (batch chosen) |
| Assessment | Performance | `/performance` | `performance` | Verified (batch chosen) |
| Assessment | Transcripts | `/transcripts` | `grades` | Verified |
| Content | Shared with me | `/shared-with-me` | `shared-with-me` | Verified |
| Community | Announcements | `/announcements` | `announcements` | Verified |
| Community | Messages | `/messages` | `messages` | Verified |
| Community | Notifications | `/notifications` | `notifications` | Verified |
| People | My team | `/team` | `my-team` | Verified |
| People | Guardians | `/guardians` | `guardians` | Verified (read-only) |
| Administration | Academic setup | `/academic` | `academic-setup` | Verified (read-only) |
| Account | My account | `/account` | `account` | Verified |
| — | Sign in | `/login` | `sign-in` | Verified |

Plus `welcome`, `sidebar` and `common-problems`.

### What makes a guardian different

* **No write action at all.** The corporate manager has one (enrolling from a
  batch); a guardian has none. The guide says so plainly rather than leaving a
  reader hunting for buttons.
* **No Reports screen.** A guardian lacks `report.read`, so unlike a corporate
  manager there is no Reports item at all.
* **Performance shows only their own student**, even though the screen is
  organised by class group. Confirmed on screen: one row, not the cohort.
* **Announcements, which a corporate manager does not have.** `announcement.read`
  is a guardian permission and not a manager one.

### Verification performed (Guardian)

| Check | Result |
|---|---|
| Every article opens signed out, fresh profile | 19/19 HTTP 200, no redirect |
| Broken internal links | 0 |
| Search, table of contents, click-to-enlarge | Pass |
| Mobile at 375px | No horizontal overflow; drawer opens |
| Sidebar link | `/help/guardian`, correct label, new tab |
| Console errors on public pages | 0 |
| Temporary account removed | 0 links, 0 live guardian accounts |

---

## 5. Managed Student — complete (13 Oct 2026)

`frontend/src/content/help/managed-student/`, 23 articles in 7 sections,
20 screenshots in `frontend/public/help/managed-student/`.

Driven as a real managed student: a student with one enrolment whose account
is watched by two corporate managers.

### Feature coverage

Every item in the student's sidebar is covered. The menu has 17 items — there
is deliberately no Enrollments item (that nav entry also needs `user.read`,
which a student does not hold), no My team, and no Guardians screen.

| Area | Screen | Route | Article | Status |
|---|---|---|---|---|
| Home | Dashboard | `/` | `dashboard` | Verified |
| Learning | Courses | `/courses` | `course` | Verified (read-only) |
| Learning | Batches | `/batches` | `course` | Verified (read-only) |
| Learning | Timetable | `/sessions` | `timetable`, `join-class` | Verified |
| Learning | Attendance | `/attendance` | `attendance` | Verified (read-only) |
| Assessment | Assignments | `/assignments` | `assignments` | Verified |
| Assessment | Assignment detail | `/assignments/{id}` | `submit` | Verified (opened, nothing submitted) |
| Assessment | Quizzes | `/quizzes` | `quizzes` | Verified |
| Assessment | Quiz detail | `/quizzes/{id}` | `quizzes` | Verified (no attempt started) |
| Assessment | Examinations | `/exams` | `examinations` | Verified (read-only) |
| Assessment | Grade book | `/gradebook` | `grades` | Verified (batch chosen) |
| Assessment | Performance | `/performance` | `performance` | Verified (batch chosen) |
| Assessment | Transcripts | `/transcripts` | `transcripts` | Verified |
| Content | Shared with me | `/shared-with-me` | `shared-with-me` | Verified |
| Community | Announcements | `/announcements` | `announcements` | Verified |
| Community | Discussions | `/discussions` | `discussions` | Verified |
| Community | Messages | `/messages` | `messages` | Verified |
| Community | Notifications | `/notifications` | `notifications` | Verified |
| Administration | Academic setup | `/academic` | `academic-setup` | Verified (read-only) |
| Account | My account | `/account` | `account` | Verified |

Plus `welcome`, `who-can-see`, `what-they-cannot-do` and `common-problems`.

### What makes a managed student different

A managed student holds the **same STUDENT role and the same 27 permissions**
as any other student, and sees the same screens. The difference is entirely
contextual: a manager or guardian is linked to their account. Established from
the running system, not assumed:

* **They can see, but cannot act.** `assignment.submit` is held by the student
  role and by neither `CORPORATE_MANAGER` nor `GUARDIAN`. Nobody can hand work
  in, take a quiz, change a mark or change a register on the student's behalf.
* **The student has no screen listing who is linked to them.** There is no My
  team and no Guardians item on their menu. The guide says so outright rather
  than letting a reader search for one.
* **They are notified when a link is created**, once, naming the person —
  `guardian_linked` and `manager_linked` in `backend/core/notification_types.py`,
  sent to both sides. The comment in `managed_student_service.py` gives the
  reason: *"The student finding out is the point -- it is the only moment they
  could object."* The guide tells them to read that notification, and to ask
  the office if they have missed it.
* **"All submissions" shows only their own.** The control on the assignment
  page is scoped by `work_visibility`; measured over the API, the student sees
  1 of 6 submissions. Not a leak — a confusingly-labelled control, so the guide
  explains it.
* **The quiz answer key is never sent to a student account**, before, during or
  after an attempt.

### Verification performed (Managed Student)

| Check | Result |
|---|---|
| Every article opens signed out, fresh profile | 23/23 HTTP 200, no redirect |
| Broken images | 0 across 23 articles |
| Broken internal links | 0 |
| Search, table of contents, click-to-enlarge | Pass |
| Mobile at 375px | No horizontal overflow (375 vs 375); drawer opens |
| Sidebar link | `/help/managed-student`, correct label, new tab, copy button |
| Console errors on public pages | 0 |
| `vitest src/content/help` | 20 passed |
| `tsc --noEmit`, `eslint src` | Clean (14 pre-existing warnings elsewhere) |

### Two things to carry into the Individual Student guide

1. **One role, two guides.** `ROLE_TO_GUIDE` maps a role to one guide, and both
   student guides are the same `STUDENT` role — nothing in a student's own token
   says whether anyone is linked to them. STUDENT currently maps to
   `managed-student`, so an individual student is offered it too. A chooser may
   serve both better once the second guide exists.
2. **Privacy policy was widened.** `privacy.js` gained two rules: names supplied
   by the caller (read from the signed-in person's own account page at capture
   time, never written into a script) and "… by Firstname Lastname" credits. The
   six screens showing a real person were re-photographed under the new rules.

---

## 6. Individual Student — complete (13 Oct 2026)

`frontend/src/content/help/individual-student/`, 23 articles in 7 sections,
20 screenshots in `frontend/public/help/individual-student/`.

Driven as a real student with **no manager, no guardian and no employer
membership** — confirmed in the database against the managed student used for
guide 5, who differs only in having two managers and one employer membership.
Same role, same 27 permissions, same 17 menu items, comparable volume of work
(1 enrolment, 1 submission, 3 attendance records each).

### Feature coverage

Identical screen coverage to the Managed Student guide; the articles differ in
framing rather than in which screens they describe.

| Area | Screen | Route | Article | Status |
|---|---|---|---|---|
| Home | Dashboard | `/` | `dashboard` | Verified |
| Learning | Courses | `/courses` | `course` | Verified (read-only) |
| Learning | Batches | `/batches` | `course` | Verified (read-only) |
| Learning | Timetable | `/sessions` | `timetable`, `join-class` | Verified |
| Learning | Attendance | `/attendance` | `attendance` | Verified (read-only) |
| Assessment | Assignments | `/assignments` | `assignments` | Verified |
| Assessment | Assignment detail | `/assignments/{id}` | `submit` | Verified (opened, nothing submitted) |
| Assessment | Quizzes | `/quizzes` | `quizzes` | Verified |
| Assessment | Quiz detail | `/quizzes/{id}` | `quizzes` | Verified (no attempt started) |
| Assessment | Examinations | `/exams` | `examinations` | Verified (read-only) |
| Assessment | Grade book | `/gradebook` | `grades` | Verified (batch chosen) |
| Assessment | Performance | `/performance` | `performance`, `privacy` | Verified (batch chosen) |
| Assessment | Transcripts | `/transcripts` | `transcripts` | Verified |
| Content | Shared with me | `/shared-with-me` | `shared-with-me` | Verified |
| Community | Announcements | `/announcements` | `announcements` | Verified |
| Community | Discussions | `/discussions` | `discussions` | Verified |
| Community | Messages | `/messages` | `messages` | Verified |
| Community | Notifications | `/notifications` | `notifications` | Verified |
| Administration | Academic setup | `/academic` | `academic-setup` | Verified (read-only) |
| Account | My account | `/account` | `account` | Verified |

Plus `welcome`, `privacy`, `if-linked` and `common-problems`.

### What makes an individual student different

Nothing in the software — the difference is situation, and the guide is written
around it rather than pretending to a distinction that is not there:

* **Nobody chases them.** No manager or guardian is watching, so the guide
  points repeatedly at the dashboard as the thing that does the chasing.
* **"Private" would have been the wrong word.** Tutors and administrators can
  read their record, and a link can be created later, so `privacy` states who
  can see what in a table instead of implying nobody can.
* **`if-linked` explains the notification before it arrives**, so a reader who
  is later sponsored recognises it rather than being surprised by it.
* **Discussions are flagged as the one public surface**, since everything else
  about their record is between them and the school.

### Companion guides — how the shared role was resolved

`Guide.sibling` (new, optional) points a guide at its companion, rendered as one
line on the landing page: *"If nobody at an employer or at home follows your
progress, read the Individual Student guide instead."* and the reverse. Driven
in a browser in both directions.

This is what makes the shared `STUDENT` → `managed-student` sidebar mapping
acceptable: a reader offered the wrong guide switches in one click rather than
going back out to the Help Center to work out which of two similarly-named
guides is theirs. Three tests cover it — both links resolve, neither points at
itself, and the student pair is linked both ways.

### Verification performed (Individual Student)

| Check | Result |
|---|---|
| Every article opens signed out, fresh profile | 23/23 HTTP 200, no redirect |
| Broken images / internal links | 0 / 0 |
| Search, table of contents, click-to-enlarge | Pass |
| Mobile at 375px | No horizontal overflow (375 vs 375); drawer opens |
| Sidebar link | `/help/managed-student` (shared role), correct label, new tab |
| Companion link, both directions | Followed in a browser; both resolve |
| Console errors on public pages | 0 |
| `vitest` (full suite) | 237 passed |
| `tsc --noEmit`, `eslint src` | Clean |
| `npm run build` | 199 static pages, all 23 generated |

---

## All six guides are complete

| # | Guide | Articles | Screenshots |
|---|---|---|---|
| 1 | Super Admin | 41 | 55 |
| 2 | Tutor | 25 | 32 |
| 3 | Corporate Manager | 22 | 19 |
| 4 | Guardian | 19 | 18 |
| 5 | Managed Student | 23 | 20 |
| 6 | Individual Student | 23 | 20 |
| | **Total** | **153** | **164** |

Every guide is publicly readable at `/help/<slug>` without signing in, and
linked from the sidebar of the role it serves.
