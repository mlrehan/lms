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
