# Academic assessment & performance system — audit and implementation map

Produced by inspecting the repository, not from description. Every claim below
was read out of the schema, the service layer or the permission catalogue.

---

## 1. What already works, and must be preserved

These are load-bearing and correct. Rebuilding them would be destruction, not
progress.

| Area | State | Why it stays |
|---|---|---|
| `ScopeResolver` (`services/scope.py`) | **Mature** | Already resolves tutor→taught batches, guardian→wards, manager→employees, student→self, as composable `Scope` / `EnrollmentVisibility` / `AttendanceVisibility` / `WorkVisibility` objects applied *inside* queries. This is the enforcement backbone for §20 and it is better than anything a rewrite would produce. |
| Gradebook as a **derived** store | **Correct architecture** | `sync_batch` recomputes entries from assignments, quizzes, exams and attendance; those services stay unaware of it. That is §23's single-source-of-truth rule, already implemented. |
| Idempotent gradebook sync | **Correct** | Two partial unique indexes on `gradebook_entries` (sourced vs unsourced) make a re-sync correct an entry rather than append one. Without them every sync doubles a student's marks. |
| Quiz engine | **Substantial** | Question bank, attempts, auto-grading, negative marking, subjective review queue, question-bank lock once attempts exist. |
| Exam engine | **Substantial** | Offline mark entry (`record_results`), invigilators, separate result publication from exam publication. |
| Attendance | **Correct source of truth** | `attendances` + `attendance_sheets` with a draft/finalize lifecycle. §12 says do not duplicate it; the gradebook already reads from it. |
| Audit trail | **Exists** | `audit_logs` is append-only, enforced by a database trigger. §24 needs richer *content*, not a new mechanism. |
| Notifications + realtime + calendar | **Exists and integrated** | §25/§26 are wiring, not new subsystems. |

---

## 2. What is missing or wrong

Ordered by how much else depends on it.

### 2.1 Assessments cannot be scoped (§3) — **the largest gap**

```
assignments.course_id   NOT NULL,  no batch_id,  no session_id
quizzes.course_id       NOT NULL,  no batch_id,  no session_id
exams.course_id  NULL,  exams.batch_id  NULL,    no session_id
```

Eligibility is `_assert_enrolled_in_course(...)` in both the assignment and quiz
services. **Every assessment is course-wide.** A tutor cannot set work for one
batch, and §3's three-level scoping is unreachable. Exams are half-way there
(course *or* batch) but by a different, hand-rolled shape than the other two —
so there are already two conventions where there should be one.

### 2.2 No weighting configuration (§6, §7) — the second largest

Nothing in the schema stores a weighting policy. `gradebook_entries.weight`
exists and **every synced row is written with `weight = 1`**, so the "weighted
average" is a straight average. The service's own docstring says so. §6's
configurable per-course scheme has nowhere to live.

### 2.3 No result lifecycle (§14)

| Table | What it has | What §14 needs |
|---|---|---|
| `assignment_submissions` | `grade`, `graded_at` — **no status column at all** | Not Started / Pending / Submitted / Late / Under Review / Graded / Published / Absent / Exempted / Resubmission Required / Reassessed |
| `exam_results` | `is_published` boolean | the same lifecycle |
| `transcripts` | `is_final` boolean | Draft never on a transcript |

A boolean cannot express "under review", and there is no way to record *absent*
versus *not yet marked* — which §38 says must be distinguishable.

### 2.4 No tutor class-performance marks (§11)

No table. `GradeComponentType` has a `PRACTICAL` member with no source rows
behind it. §11's per-session grid (participation / interaction / practical /
presentation) does not exist in any layer.

### 2.5 Grading schemes are global and flat (§13)

`grade_bands` is five columns with no scheme grouping and no course override. A
course cannot use a different scale.

### 2.6 Permission catalogue gaps (§21)

Missing entirely: `assignment.publish`, `quiz.publish`, `exam.grade`,
`transcript.view`, `transcript.generate`, `performance.view`,
`grading_scheme.manage`.

Naming note: §21 asks for `gradebook.*`; this codebase already uses `grade.*`
(`grade.read` / `grade.update` / `grade.publish`). **Keep `grade.*`** — §21 says
"where the existing architecture supports it", and renaming a permission in use
is a migration with no benefit.

Role gaps against §1:
* **Tutors cannot create or grade examinations** (`exam.read` only).
* **Corporate Managers hold no `assignment.read`, `quiz.read` or `exam.read`**,
  though §1 says their monitoring may include all three.
* **Guardians hold no `quiz.read`.**

### 2.7 Assignment configuration is thin (§8)

Present: title, description, instructions file, due date, max score,
submission type, rubric, allow-late.
Absent: **start date, passing marks, weight, allowed file types, max upload
size, multiple submissions, resubmission policy, late penalty, draft/publish
state, scheduled publishing.**

### 2.8 No performance calculation engine (§7, §37)

No service computes a weighted overall figure, and nothing can explain one.
§37's drill-down ("82 × 15% = 12.30") has no data behind it.

---

## 3. Implementation map

`existing → required → database → API → UI`

| # | Existing | Required | Database | API | UI |
|---|---|---|---|---|---|
| 1 | `course_id` only on assignments/quizzes; ad-hoc on exams | One reusable scope on all three | `+batch_id`, `+session_id` nullable FKs; CHECK that the scope is coherent; backfill leaves every existing row course-scoped | scope fields on create/update; one shared eligibility resolver | scope picker in the creation flow |
| 2 | `weight = 1` everywhere | Configurable per-course schemes | new `grading_schemes`, `grading_scheme_components`; `courses.grading_scheme_id` | scheme CRUD gated on `grading_scheme.manage` | Super Admin scheme editor |
| 3 | booleans | Real lifecycle | `+status` on submissions and results; keep booleans in step during transition | status transitions as explicit verbs, not PATCHes of a flag | status chips, filters |
| 4 | none | Tutor class marks | new `class_performance_marks` (session, student, criteria) | per-session grid read/write | §11's quick-entry table |
| 5 | flat `grade_bands` | Schemes with course override | `+scheme_id` on `grade_bands` | banded under the scheme | in the scheme editor |
| 6 | 7 permissions missing | Full §21 set | none | `require_permissions(...)` at each new route | permission-aware actions |
| 7 | none | Calculation engine | none (reads existing rows) | `/performance/...` returning the breakdown | drill-down panel |

**Order matters.** 1, 2, 3 and 6 are foundations — 4, 5 and 7 are unbuildable
without them, and every UI phase depends on 7. Nothing above deletes a column or
breaks an API contract; every change is additive with a backfill that preserves
current behaviour (§44).

---

## 4. Decisions taken before writing code

1. **One scope shape for all three assessment types**, not three. §3 says
   explicitly not to duplicate; exams' existing nullable `course_id`/`batch_id`
   becomes the shared shape rather than a fourth variant.
2. **`grade.*` is kept**, `gradebook.*` is not introduced. Two names for one
   capability is worse than a name that differs from a spec written later.
3. **Attendance is never copied into the gradebook** as a stored figure — the
   gradebook already derives it, and §12 forbids duplicating it.
4. **A missing mark is not a zero.** The lifecycle in 2.3 exists precisely so
   that *absent*, *exempted*, *not yet assessed* and *scored zero* are four
   distinct states, as §38 requires.

---

## 5. What has been built since the audit

Sections 1–4 are the record of what was *found* and are left as written. This
section is the running status, and states what is **not** done as plainly as
what is.

| # (from §3) | Status | Where |
|---|---|---|
| 1 — one reusable scope | Done | `services/assessment_scope.py`; `AssessmentScope` on assignments, quizzes, exams |
| 2 — configurable weighting | Done | `models/grading.py`, `services/grading_scheme_service.py`, `/grading-schemes`, console editor |
| 3 — result lifecycle | Done | `ResultState` on submissions, exam results, class-performance marks |
| 4 — tutor class marks | **Done** | `models/class_performance.py`, `services/class_performance_service.py`, `/class-performance/*`, the grid on the session screen |
| 5 — schemes with course override | Done | `grade_bands.scheme_id`, `courses.grading_scheme_id` |
| 6 — permission catalogue | Done | 121 permissions; `class_performance.*` added with item 4 |
| 7 — calculation engine | Done | `core/performance.py` (pure), `services/performance_service.py`, `/performance/*`, the `/performance` screen |

### Item 4 was not merely missing — it disabled §5

The seeded default scheme gives class performance 10% of the mark. An unassessed
component is **excluded** from the weighted total rather than scored zero (§38),
and a result is only *final* once every weighted component has been assessed. So
with no write path for `PRACTICAL` marks, **no transcript could ever be
completed** under the default scheme. A gap in §11 silently disabled §5, and
neither screen showed anything wrong.
`tests/integration/test_class_performance.py::test_class_performance_marks_make_a_transcript_completable`
is the test that pins this: it asserts no final result before the marks exist,
and a complete one after.

### Two defects found while building it

1. **Every grade band claimed to be a pass.** `b71f2c8ea940` added
   `grade_bands.is_pass` with `server_default=true`, so every band that already
   existed became a passing band — the live ladder read `F`, `0–49.99`,
   `is_pass = true`, against a scheme passing at 50. `Performance.is_pass` and
   `Transcript.is_pass` are both read straight off the matched band, so every
   student who had failed would have been recorded as passing *on the
   transcript*. Corrected by `e93a5c17b204`, which derives the value only where
   the stored one is a contradiction (the band's whole range below its own
   scheme's passing mark) and leaves bands that straddle the mark alone — those
   are a judgement the institution is entitled to make (§44). No already-issued
   transcript carried the wrong flag, checked before writing the migration.
2. **The grading seeder had no caller.** `bootstrap_grading` was written,
   documented, and invoked from nowhere; `backend/cli/seed.py` called only
   identity and geo. Without it the default scheme has no weightings and no
   grade ladder, so every performance figure reports "not configured" — the
   exact outcome the seeder's own docstring says it exists to prevent. Now wired
   into the seed CLI.

### Transcript presentation (§5)

`/transcripts/{id}` renders the official document: the student, the batch, the
frozen per-component breakdown, the result, the attendance, the grading policy
that produced it, and who certified it. Three things about it are deliberate:

* **Nothing is recomputed.** Every figure, `breakdown` included, is read off the
  stored record — which is the entire reason those columns exist. A document that
  restated itself when a register was corrected would invalidate something
  somebody had already relied on.
* **Access is the backend's, not the page's.** `GET /transcripts/{id}` already
  scopes to visible students and hides a provisional record from anybody without
  the marking grant, so there is no second check in the console to drift out of
  step with it (§46). An unauthorised id is a 404.
* **Print, not a generated PDF.** The browser's own print-to-PDF gives the
  registrar a file they can save, email or put on headed paper, keeps the text
  selectable, and needs no rendering service to keep alive. A `@media print`
  block drops the console chrome. A provisional transcript prints marked
  *Provisional — not certified*, because a draft that prints like an official
  record is worse than one that cannot be printed at all.

### Still not built

* **A class-performance queue.** Attendance has "sessions to take"; class
  performance has to be reached one session at a time from the session screen.
  §11 asks for the marks, not the queue, so this is convenience rather than a
  gap in the requirement — but it is the difference between a tutor using the
  feature and not.
* **Quiz and exam creation forms do not expose the new scope, window and
  online/offline fields.** The backend enforces them; the console does not offer
  them, so they are reachable only through the API.
* **Guardian and corporate-manager dashboards (§18–19), calendar integration of
  assessment deadlines (§26), and the report/analytics surfaces (§34–35).**

### Running these

After pulling this work: **re-run the seeders** (`class_performance.*` is five
new permissions, and nothing checks a permission that was never seeded) and
**apply the migration**:

```bash
python -m alembic upgrade head
python -m backend.cli.seed
```
