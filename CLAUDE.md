# Learning Management System (lms-new)

## What this project is

A standalone, single-institution Learning Management System: courses, batches and sessions, enrollment, attendance, learning resources/files, assignments, quizzes, formal examinations, a grade book, communication (messages/discussions/announcements/notifications), corporate-organization and guardian relationships, academic administration, and RBAC.

**This project is fully independent.** It shares a machine and a local Postgres server with several other unrelated projects (an Enterprise IAM/AI-assistant platform, nursery-management apps, an AI chatbot, others), but shares no code, no auth, and no database with any of them. Do not assume integration with anything outside this repository without asking first.

## Tech stack

Python 3.13+, FastAPI, Pydantic 2, SQLAlchemy 2.0 async, Alembic, PostgreSQL, `psycopg` (v3) as the driver for **both** the sync Alembic engine and the async app engine (not `asyncpg` — declared once, never referenced, removed). Argon2id password hashing, AES-256-GCM envelope encryption for secrets (built, not yet wired to anything this product stores).

**Windows-specific requirement**: psycopg's async mode cannot run under Windows' default `ProactorEventLoop`. `backend/main.py` sets `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` before anything else runs — required on this dev machine, a harmless no-op elsewhere. Don't remove it.

## History

The repository was originally generated across disconnected sessions and never actually run: broken imports, three mutually incompatible database session implementations, an Alembic config pointing at a module that didn't exist, and — the more serious finding — large parts of `core/`, `security/`, and the original `AuditLog` model were boilerplate copy-pasted wholesale from an unrelated product called **"db-admin-platform"** (a database-administration/query tool). Confirmed concretely: `.env` had `SECURITY_JWT_ISSUER=db-admin-platform`, and a real Postgres database named `db_admin_platform` exists on this same server.

That was fixed in three passes:

1. **Full repository audit** — every model, config, and db/security file read and catalogued against the business spec. Findings preserved in a published Artifact, *"LMS Current-State Audit."*
2. **Models rewritten from scratch** to be internally consistent and match the spec: one import convention throughout, `PublicIdMixin` (internal integer PK + a UUID `public_id` for anything API-facing, since sequential integer PKs are trivially enumerable), `SoftDeleteMixin`, `native_enum=False` on every enum column, the frozen-timestamp `server_default` bug fixed everywhere it appeared, the `course_batch.py` grab-bag file split into one file per aggregate. Verified by `configure_mappers()` plus compiling every table's DDL against the Postgres dialect — not just read for correctness.
3. **Roles expanded to six, plus a corporate/guardian schema, plus the session layer fixed** — see "Confirmed architectural decisions" and "Session/DB layer" below. Findings and the schema proposal preserved in a second published Artifact, *"Roles, Organizations & Architecture Review."*

**`alembic upgrade head` has been run.** `lms_platform_db` currently has the full 57-table schema live (`alembic_version = ec8f0a2fc9dd`), verified directly against the database, not assumed from the migration file alone.

## Confirmed architectural decisions (do not re-litigate without new user input)

- **Six roles**: `SUPER_ADMIN, ADMIN, CORPORATE_MANAGER, GUARDIAN, TUTOR, STUDENT` (`backend/utils/enums.py::Roles`).
- **Corporate organizations are real tables** (`backend/models/organization.py`: `Organization`, `OrganizationManager`, `OrganizationMembership`) — never a `corporate_manager_id` or `organization_id` column bolted directly onto `User`/Student. A bare column can express exactly one relationship and forgets history the moment someone is reassigned; both failure modes are named requirements this design has to survive.
- **Confirmed cardinality**: one manager belongs to exactly one organization at a time (an organization may have many managers); one student belongs to exactly one organization at a time. Both enforced with a partial unique index on `user_id` scoped to the "currently active" row (`WHERE is_active` / `WHERE status IN (...)`) — the same technique `enrollments` uses for re-enrollment — so a reassignment inserts a new row rather than destroying history.
- **Guardians are a many-to-many table** (`backend/models/guardian.py::StudentGuardian`, `guardian_id` × `student_id`) — never a `guardian_id` column on student. A student can have more than one guardian; a guardian can have more than one ward.
- **`enrollments.organization_id`** (nullable) records which organization sponsored a *specific* enrollment, independent of the student's *current* org membership — stays historically correct if they later change employer.
- **Every table**: internal integer PK + indexed unique `public_id` UUID (`PublicIdMixin`, `backend/models/base.py`) for anything exposed in a URL or API response.
- **Database name is `lms_platform_db`** — a deliberate rename from the original `lms_db` scaffold default. `lms_db` still exists on the Postgres server but is orphaned/unused; don't confuse the two.
- **Examination is deliberately separate from Quiz** (`backend/models/exam.py` vs `backend/models/quiz.py`) — the spec frames exams as scheduling + invigilation + result-publication, not an auto-graded question bank. Don't merge them.

## What's built

`backend/models/` — 57 tables across identity, course/batch/enrollment/attendance, resources (folder hierarchy + versioning + a Course→Batch→Session→Individual permission-cascade table), assignments, quizzes, examinations, grade book, certificates/badges, notifications/announcements/discussions, a rewritten audit log (real LMS actions, not raw SQL statements), academic administration (academic years/semesters/departments/categories/tags/settings), and the organization/guardian tables above.

`backend/core/`, `backend/db/` — consolidated onto one working session layer. `DatabaseManager` (`db/manager.py`) is the single engine/session factory, with Postgres-level `statement_timeout`/`lock_timeout`/`idle_in_transaction_session_timeout` hardening and `hide_parameters=True` so bound SQL values never leak into exception logs. `db/dependencies.py` uses `session_factory.begin()` for a real commit/rollback boundary (the earlier version only ever rolled back, never committed). `backend/main.py` builds and wires the actual `FastAPI()` app for the first time — lifespan, CORS/TrustedHost middleware from config that already existed but was never connected, `AppError`/generic exception handlers, `/livez` + `/readyz` (readyz genuinely pings Postgres).

## API layer

Built and driven live against real Postgres. **30 paths** under `/api/v1`:

* **Phase 1 — identity**: `auth` (login, refresh, logout, logout-all, me,
  password change, session list/revoke), `users` (CRUD, status, roles, admin
  password set), `roles` (CRUD + permission grants), `permissions` (catalog).
* **Phase 2 — academics**: `courses` (CRUD, lifecycle, tutor assignment,
  nested batch create/list), `batches` (read/update/delete, seat counts),
  `enrollments` (enroll, status lifecycle, transfer).
* **Phase 3 — corporate & guardianship**: `organizations` (CRUD, manager
  appoint/revoke, employee add/status), `guardian-links` (CRUD).
* **Phase 4 — sessions & attendance**: `sessions` (schedule, update, delete,
  timetable listing), `attendance` (bulk register marking, listing, summary
  reporting).
* **Phase 5 — RBAC completeness audit + geo reference data**: `geo`
  (countries, cities, timezones — read-only lookups for profile forms).
* **Phase 6 — assessment**: `assignments` + `submissions` (create, submit,
  replace, grade), `quizzes` + `questions` + `attempts` (authoring,
  publishing, sitting, auto-grading, manual grading), `exams` +
  `exam-results` (scheduling, invigilators, bulk mark entry, publication).

* **Phase 7 — grade book**: `grade-bands` (grading scale), `gradebook`
  (entries, sync, summary), `transcripts` (generate, finalise).

* **Phase 8 — resources & file management**: `folders` (tree), `resources`
  (upload, versioning, download, copy, soft delete/restore/purge),
  `resource-permissions` (the §11 cascade), sharing and public share links.

* **Phase 9 — communication**: `messages` (send, inbox/sent/all, correspondent
  summary, unread count, mark read, per-side delete), `notifications` (tray,
  unread count, acknowledge), `announcements` (audience-filtered feed, post,
  edit, withdraw), `discussions` + `discussion-replies` (threads, replies,
  moderation).

* **Phase 10 — academic administration**: `academic-years`, `semesters`,
  `departments`, `categories`, `tags` (full CRUD with usage counts and
  delete guards), `settings` (key/value, Super-Admin-write), plus
  `PUT /courses/{id}/tags` — and the reference data wired into courses
  (category/department/tag, with catalogue filters) and batches
  (academic year/semester).

* **Phase 11 — reporting & dashboards**: `dashboard` (role-shaped, one
  endpoint), `reports/attendance`, `reports/enrollment`,
  `reports/performance` — each grouped several ways and exportable as CSV.

* **Phase 12 — audit trail & security**: `audit-logs` (search, per-entity
  trail, catalog, CSV export), `security` (incident feed, posture summary,
  locked accounts, unlock, live sessions, revoke one / revoke all).

* **Phase 13 — notifications & search**: `notifications/preferences` (list,
  per-type toggle, reset) and `search` (one query across seven kinds).
  Notifications are now emitted by five real events rather than one.

* **Phase 14 — integrations & performance**: `integrations/webhooks` (registry,
  rotate, test-fire, delivery log), `integrations/calendar-feeds` plus a
  public `.ics` subscription, and `ops` (health, request metrics, database
  statistics). A `dispatch_webhooks` CLI drains the delivery queue.

**160 paths total.** Every scoped relationship is now creatable through the
API — tutor assignment, enrollment, organization membership and guardianship
no longer need direct database access.

## Integrations and performance (spec §24–§25)

Twelve endpoints, one migration, one new CLI process, and four permissions
(`integration.*`). Operational endpoints ride on `setting.read` rather than a
module of their own — "may this person see how the system is configured" and
"may they see how it is behaving" have the same audience.

### The security core: institution input decides what the server connects to

Everywhere else in this platform a bad value reads or writes the wrong row.
A webhook URL makes the **application process open a socket** — from inside
the deployment's network, holding database credentials, with a route to the
cloud metadata service. Unguarded, "send my webhooks here" is a
request-forgery primitive: point it at `169.254.169.254`, read the instance
credentials out of your own HTTP log, and never touch the API again.

`integrations/url_safety.py` has four properties, each the one most SSRF
filters get wrong:

1. **Scheme allowlist, not a blocklist** — a blocklist has to enumerate
   `file:`, `gopher:`, `dict:` and whatever the client supports next release.
2. **Resolve, then check the resolved addresses**, never the hostname. A name
   whose A record is `127.0.0.1` is indistinguishable from any other name to
   a string filter.
3. **Check every address a name resolves to.** One public record and one on
   `10.0.0.5` passes any check that looks at `getaddrinfo()[0]`.
4. **Re-check at the moment of use.** Validation at registration proves
   something about the moment somebody clicked save; the delivery client
   validates again, because DNS changes.

The refusal message names the address it resolved to — "invalid URL" sends an
administrator to look at their typing rather than their DNS. Link-local is
reported *before* private, because `ipaddress` calls `169.254.0.0/16` both and
"the cloud metadata service" is the half that tells an operator what they
actually pointed at.

**The residual risk is recorded rather than glossed:** this does not close DNS
rebinding. Closing it means pinning the checked address into the connection,
which the delivery client does not do; the exposure is bounded by refusing
redirects and by never returning the response body to the caller.

### Signing, because the URL authenticates nothing

A webhook URL sits in a database row, in logs, and in whatever the receiver's
framework prints on an error — so a receiver that trusts "it arrived at my
secret path" is trusting a value that leaks by design.

**The timestamp is inside the signed material**, not merely sent alongside it:
signing only the body lets an attacker replay yesterday's delivery for ever
with its signature intact. The separator in `f"{timestamp}."` + body is
load-bearing too — without it, timestamp `12` with body `3abc` and timestamp
`123` with body `abc` hash identically.

**The secret is returned by exactly one response model.** `WebhookCreated
Response` carries it; every other route returns a model with **no field
capable of holding it** — a shared model that merely declines to populate one
is a single careless edit from leaking. Rotation has no overlap window: two
valid secrets means a leaked one keeps working while somebody decides, and
the reason to rotate is that it may have leaked.

### Delivery is queued, and the queue has a name

A `POST /enrollments` that waits on a receiver's ten-second timeout has made
the enrolment screen as slow as the slowest integration anybody registered.
The delivery row is written **in the same transaction as the event**, so an
event that rolled back leaves nothing claiming it happened, and
`python -m backend.cli.dispatch_webhooks` drains it. Each delivery gets its
own transaction: one batch in one transaction would hold every row's lock for
the length of the slowest receiver and discard the record of the successes
that preceded a failure.

Retries are exponential and **capped** — the cap matters more than the curve,
because without it the thirtieth retry is scheduled for some time next year,
which is the same as never but harder to notice. A 4xx other than 408/429 is
not retried at all: the receiver understood and refused.

**The event catalogue lists only events the platform actually emits** — three.
Publishing an impressive list and wiring three of them would let somebody
subscribe to `course.archived`, receive nothing, and have no way to tell a
broken integration from a quiet one. One webhook fires per *event*, not per
recipient: an assignment published to a roster of forty produces forty
notifications and one webhook.

### The calendar feed is a capability URL, and says so

Calendar clients cannot send an `Authorization` header, so a subscribable feed
has to carry its credential in the URL — the link *is* the credential.
Mitigated rather than pretended away: 32 random bytes, stored **hashed** so
the table is not a list of working URLs, revocable in one call, and carrying
only session times, titles and locations. A wrong or revoked token is a
**404**, identical to one that never existed; a 401 would confirm that some
link was once valid, which is the only thing an attacker guessing tokens could
learn. The creation response says outright that the link is the credential.

`icalendar.py` is hand-written because the two things that actually break
calendar clients are line folding and escaping — and a rejected `.ics` gives
the user no error at all, just an empty subscription. Folding is on **75
octets, not characters**: an accented title is two octets in UTF-8, and a
split landing mid-sequence emits invalid UTF-8.

### Performance: what this deployment can actually observe

`/ops/metrics` is keyed by **route template**, never path — keying on the path
makes a thousand courses a thousand metrics describing one route, and the one
number an operator wants is nowhere. Latency is bucketed rather than sampled,
because keeping every sample would make the metrics endpoint the largest
allocation in the system. The response states that the numbers are per
process and reset by a restart.

`/ops/database` reports size, connection state, the SQLAlchemy pool, per-table
scan counts and unused indexes. `mostly_sequential` is flagged only above a
row floor: a sequential scan of forty rows is the correct plan, and reporting
it sends people to add indexes that make writes slower and reads no faster.

**Statement-level timing is reported unavailable, with the reason.**
`pg_stat_statements` is available on this deployment but not in
`shared_preload_libraries`, so `CREATE EXTENSION` would succeed and every
query against the view would then fail — an endpoint that exists and cannot
work. It names the setting instead.

These are deliberately **not** the Kubernetes probes. `/livez` and `/readyz`
stay unauthenticated, unversioned and outside the router, because a load
balancer is the wrong audience for table sizes and route latencies.

### Findings

**The dispatcher was silent on an empty pass**, which is indistinguishable
from a dispatcher nobody is running — the same failure the exit code was
already written to avoid. It now reports every pass, including zeros.

**Two of my own test defects, both the vacuous-pass shape.** The fixture
pre-enrolled the student, so the test's own `POST /enrollments` returned 409
and the "a delivery was queued" assertion had nothing to find; and the
companion check ("no delivery for an unsubscribed event") passed on an *empty*
list, which would have held with the subscription filter deleted. Both now
assert the positive and the negative in the same breath.

**Three more, every one of them found by the mutation round rather than by
the suite, and all the same shape — an assertion that could not fail:**

1. **The scheme test refused for the wrong reason.** `file:///etc/passwd` has
   no host, so the *host* check rejected it and the scheme allowlist was
   never reached — deleting the allowlist entirely left the test green. It now
   uses `gopher://example.com/x`, which has a host, so only the allowlist can
   refuse it.
2. **The replay assertion was satisfied by `verify()`'s own freshness
   window**, not by the timestamp being inside the HMAC. Removing the
   timestamp from the signed material changed nothing: signing and
   verification simply agreed on the shorter material, and the replay case
   still failed on *age* before an HMAC was computed. The new check verifies
   a signature against a **different but equally fresh** timestamp, which can
   only fail if the timestamp is genuinely signed.
3. **The metrics tests asserted shape, not measurement.** With recording
   disabled every route still appeared — the registry creates the entry
   before observing it — so "keyed by template" and "latency is bucketed"
   both held with zero counts. The suite now asserts the numbers are
   non-zero.

**And one real bug, surfaced by a mutation run whose failures were entirely
unrelated to the mutation.** Disabling metric recording produced six calendar
*feed* failures, which is impossible — the actual cause was that
`create_calendar_feed` never called `commit_before_responding`, so the link it
hands back 404s until the transaction lands. "Create a feed, click the link"
was intermittently broken, and the clean runs had been passing on timing.
Fourth occurrence of the response-before-commit ordering, and the first one
that was a user-visible product bug rather than a test flake.

**A real receiver could not be delivered to, and that is the guard working.**
Every address a local test server can bind is loopback or private, so the
SSRF check refuses it — which is the correct behaviour and makes the wire
format untestable end to end. The signature, headers and exact body are
therefore verified against a real `http.server` receiver with
`assert_safe_url` bypassed **for that one check**, clearly confined, while the
guard itself is proven separately through the API.

### Verified

**63 live checks** against real Postgres, all passing: five SSRF refusals
through the API (loopback, metadata, private, non-HTTP scheme, database port)
plus name resolution (`localhost` → refused, naming `127.0.0.1`); the secret
returned once and absent from every other route; duplicate-name and
unknown-event refusals; an enrolment that queues a delivery **without waiting
on the receiver**; the subscription filter proven in both directions; the
dispatcher draining and recording an attempt; a real receiver confirming the
headers, the exact signed bytes, and that the signature fails for a wrong
secret, a tampered body and a replay; the calendar feed served
unauthenticated with CRLF endings and an escaped location, revoked and dead
immediately; and metrics keyed by template with no UUID appearing as a key.

## Notifications and search (spec §21–§22)

Two surfaces that mostly existed on paper. `/notifications` had been readable
since the messaging pass, and **exactly one event in the whole platform ever
produced a row** — a private message arriving. Everything a student would
actually want telling about happened silently. Search did not exist at all.

**A notification type is a catalogue entry, not a string.**
`core/notification_types.py` is the single source of truth, in the same shape
as `permissions.py`: a `type` is written by an emitter, stored on the row,
listed by the preferences screen and matched by an opt-out — four places that
must agree, and the failure when they drift is silent in the worst direction.
An emitter inventing `grade_posted` while the settings screen offers
`grade_recorded` produces a notification nobody can turn off, with no error
anywhere. `assert_known()` refuses an unregistered type at emit time, and the
catalogue checks its own consistency at import.

**Four security types are mandatory and cannot be switched off.** You do not
get to opt out of being told your account was unlocked or that somebody ended
your sessions: a warning an attacker can silence by flipping a preference is
worse than no warning, because it is believed to be working. The API refuses
the change with 422 rather than accepting it and ignoring it — a setting that
reports success and does nothing is the decorative-field pattern applied to a
security control.

**Preferences store only the exceptions.** "On" is the absence of a row, so
switching a type back on *deletes* rather than writing `enabled=true`: one
representation of one state, and the table stays a list of opt-outs. A full
matrix would be twelve rows per account at registration and a backfill
migration every time a type is added — with the accounts that backfill missed
silently defaulting to whatever the join produced. The listing is likewise
built from the **catalogue**, not the stored rows, so a type added since
somebody last opened the screen appears switched on instead of being
invisible.

**Preferences fail open.** If the preference lookup itself misbehaves the
notification is sent: not telling somebody about their grade because a
settings query timed out is a worse outcome than one unwanted row.

**Only `SYSTEM` is ever written, and the API says so out loud.**
`NotificationChannel` models EMAIL, SMS and PUSH and there is no transport for
any of them, so there are deliberately **no per-channel toggles** — a switch
that changes nothing would have people believing they had turned email on.
The response carries a `channels_note` stating it rather than leaving it to be
discovered.

**Notifications now come from five events**: enrolment, a new assignment
(the one fan-out, bounded by a course roster and capped at `MAX_FANOUT`;
anything wider is an announcement, which has its own feed), a graded
submission, an administrative unlock, and an administrative session
revocation. Each is emitted inside the same transaction as the thing it
announces, so a tray can never hold "your grade was recorded" for a mark whose
insert rolled back.

### Search is a fan-out over the existing listings, not a new query surface

Every group delegates to the domain's own repository `search()` — the same
method that domain's own endpoint calls, with the same scope object. That is
the entire design. Search touches every table at once, which makes it the most
likely place in the API for a row-scoping rule to be re-derived slightly
differently and got wrong; here there is nothing to re-derive. If `/courses`
will not show you a draft course, neither will search, because it is the same
query. Three repositories simply had no `query` parameter yet and gained one.

**A type the caller cannot read is skipped, not emptied.** Returning an empty
`user` group to a student implies nobody matched; `skipped` says the question
was never asked, which is a different and more useful claim on a screen whose
job is to say what exists.

**Groups are capped independently** so one crowded type cannot squeeze the
other six out, and each reports the `total` *that caller may see* — computed
by the same scoped query, never a global count. Like `/dashboard`, search is
gated on authentication alone: it returns nothing the caller could not already
list, so a permission of its own would gate an aggregation rather than any
data.

**Trigram indexes, because the query shape demanded them.** Search matches
`lower(col) LIKE '%q%'`, and a leading wildcard makes a btree index unusable —
every one of these lookups was a sequential scan. Migration `e402de36ad18`
installs `pg_trgm` and adds GIN indexes on the eleven **label** columns
(titles, names, codes), expressed as `lower(col)` to match the predicate
verbatim: an index on `col` would simply not be used by a predicate on
`lower(col)`, and the plan would silently fall back to a scan while the index
sat there looking like it was working. The long description/body columns are
deliberately not indexed — a GIN trigram index costs real write throughput on
every update, and the label is what people search for.

A one-character query is refused rather than served slowly: it matches most of
every table, so the index cannot help and the answer is useless.

### Verified

**41 live checks** against real Postgres, all passing: the preference matrix
including both refusals, a per-type opt-out proven by two students receiving
different notifications from the *same* event, a mandatory notice arriving for
somebody with a stored opt-out for that very type, and search across courses,
batches, assignments and people.

**The scoping proof is a draft course.** `c2` is a DRAFT assigned to one
tutor: that tutor's search finds it, the other tutor's does not, a student's
does not, and all three find the published courses — through the same
`CourseRepository.search` the catalogue endpoint uses.

**Seven mutations**: ignoring the opt-out, allowing a mandatory type to be
switched off, making mandatory types honour opt-outs, dropping search's
per-group permission check, running the course search unrestricted, ignoring
the per-group cap, and accepting a one-character query.

### Two of my own tests could not fail, and the mutations said so

The first mutation round caught four guards and left three untouched. Two of
those were tests passing for the wrong reason, and both are more instructive
than the code:

1. **The opt-out test never exercised `notify`.** The assignment fan-out uses
   `notify_many`, which has its own preference lookup, so removing the check
   inside `notify` changed nothing — and `notify`'s only caller, enrolment,
   was never opted out of in the test. Now it is: a student switches off
   `enrolled_in_batch`, is enrolled again, and receives nothing.
2. **The mandatory-notice test passed because `emit` is indifferent, not
   because mandatory types are protected.** The security notices called
   `emit`, which consults no preference at all, so the mandatory bypass in
   `wants()` was never reached and deleting it broke nothing. The comment
   justifying that call ("the preference lookup would be a query asking a
   question with one possible answer") was wrong twice over: `wants()`
   short-circuits on a mandatory type *without* querying, so it cost nothing,
   and routing around the rule meant the guarantee was never exercised.
   Security notices now go through `notify` like everything else, and the
   test plants an opt-out row for a mandatory type **directly** — the API
   refuses to create one, so without that the assertion had nothing to
   ignore.

The third uncaught mutation was not a defect: `MIN_QUERY` is enforced twice,
once by the route's `Query(min_length=...)` and once in the service. FastAPI
rejects the request before the service is reached, so removing the service
check cannot change the HTTP behaviour. The service-level check remains as
the guard for a non-HTTP caller, and the test correctly asserts the 422.

**A second surface hit by the response-before-commit ordering.** A test
reading a notification immediately after the write that produced it raced,
intermittently — the same defect measured in the audit/security pass, which
is fixed only on the three endpoints whose contract is "effective now". The
test retries for up to three seconds through a helper that names the reason,
rather than quietly widening a sleep. It is further evidence for the
outstanding architectural fix, not a new finding.

**Not exercised, and said rather than implied:** `MAX_FANOUT` — testing it
needs 500 accounts, and the cap is asserted only by reading the code.

## Audit trail and security (spec §19–§20)

Eleven endpoints over a table that already existed and had never been
readable, plus the three operations an administrator needs *while* something
is happening. Three permissions were added: `audit.export`, and a new
`security` module with `read` and `manage`.

**The audit log is append-only, enforced by a database trigger.** Withholding
an UPDATE permission does not help here, because the log exists to constrain
the administrator — it cannot be the administrator who is trusted not to edit
it. A trigger rather than `REVOKE UPDATE, DELETE` because in this deployment
`DATABASE_RUNTIME_USERNAME` and `DATABASE_MIGRATION_USERNAME` both resolve to
`postgres`, and a superuser bypasses table privileges entirely — the REVOKE
would have been a comforting no-op. It is issued as well, guarded, for a
deployment that does split the roles as the configuration already
anticipates. Purging becomes a deliberate act (disable trigger, delete,
re-enable), and that friction is the feature.

**`audit.read` is not row-scoped, and that is the decision.** Everywhere else
in this codebase a read is narrowed to what the caller is connected to. A
*partial* audit log is worse than none: an administrator investigating an
incident who is silently shown two thirds of the evidence draws a confident,
wrong conclusion. The control is who holds the permission — Administrators
and Super Admins — not what the query hides from them.

**No internal integer identifier appears in any response, which took work
rather than being free.** `audit_logs.entity_id` stores the *internal*
primary key, and it has to: the audit row outlives the row it describes, so a
public id copied at write time would be the only copy of a value that no
longer resolves. So `repositories/audit.py` carries a registry of the 29
audited entity types and resolves each page back to `{public_id, label}` with
**one query per distinct type**, not one per row. "UPDATE course
*Applied Mathematics*" instead of "UPDATE course 47" — and a deleted entity
comes back with a null id and whatever label survives, which is a true
statement about an audit trail rather than an error. `role` is registered but
deliberately **not** filterable by id: roles are addressed by name everywhere
in this API, and exposing their integer to keep one query parameter uniform
would be the wrong trade.

**`AuditLog.actor` was `lazy="selectin"`, on a model carrying twenty eager
relationships of its own.** Loading the actor for a page of fifty audit rows
would have fanned out into hundreds of queries, on the one endpoint whose job
is paging a large table. It is `lazy="raise"` now; the row already
denormalizes `actor_email` precisely so the join is unnecessary, and actor
public ids are resolved in a single batch.

**Reading and exporting are separate permissions**, and the split is proven
rather than asserted: the test creates the read-only `AUDITOR` role that
`permissions.py`'s own comment anticipated — `audit.read` + `security.read`,
nothing else — and shows it reading the trail, reading the security summary,
and being refused both the CSV export and any action on an account.

**`/security/events` narrows, never widens.** A caller-supplied `action` is
intersected with the eight incident actions, so passing `CREATE` returns
nothing rather than turning the security feed into a second, less-privileged
audit-log endpoint. Successful sign-ins are excluded on volume grounds and
stay one filter away on `/audit-logs?action=LOGIN`.

**Unlocking is its own operation and does not touch `status`.** Previously the
only way to clear a lockout was to push the account through `SetUserStatus` to
ACTIVE, which clears the counters as a *side effect* — so an already-active
locked account could only be freed by setting a status it already had, which
no administrator would guess. Unlock is idempotent (unlocking an unlocked
account reports `was_locked: false` rather than 409: somebody answering "I
can't sign in" should not have to diagnose why before they may act), and it
leaves a suspended account suspended.

### Three defects, each found by running it

1. **The append-only trigger had a hole exactly where it mattered, and my own
   probe demonstrated it by emptying the table.** `BEFORE UPDATE OR DELETE`
   does not fire for `TRUNCATE` — in PostgreSQL that is a *separate* trigger
   event. The first version refused UPDATE, refused DELETE, refused even a
   DELETE matching no rows, and then allowed `TRUNCATE audit_logs`, which
   removed all 291 rows in one statement. An append-only guarantee that stops
   the careful destructive statements and permits the total one is worse than
   none, because it is believed. `OR TRUNCATE` added; all four now refused,
   INSERT still allowed, and the deliberate disable-purge-enable path still
   works — verified in both directions rather than read off the definition.
2. **"Is this account locked out?" was answered two ways, and this phase added
   a third.** `auth_service` honoured `locked_until`, so a lapsed lock let
   somebody sign in; `api/deps.get_current_user` read the raw `is_locked`
   column, so the token that sign-in had just issued was rejected on every
   subsequent request with an opaque "Authentication required". Same account,
   same instant, opposite answers — and my new `/security/locked-accounts`
   query introduced a third reading, treating a NULL expiry as locked where
   `auth_service` treated it as over. The drift was the defect, not any one
   reading, so the fix is a single `User.is_locked_out` predicate that all
   three now ask (with a documented SQL mirror, because a property cannot run
   in a WHERE clause). A NULL expiry means *locked indefinitely*: the
   failed-login path always sets one, so a NULL can only come from a
   deliberate administrative lock, and calling that "already over" made an
   indefinite lock inexpressible. Exactly the shape of the IAM platform's
   `can_authenticate` finding, one project over.
3. **The API sends its response before the transaction commits.** Unlocking an
   account and immediately signing in failed **3 times in 40**, with the login
   reporting the account still locked. Measured rather than reasoned about: a
   two-second sleep in the `yield` dependency's teardown returned its `200` to
   the client in **0.92s**, with the commit still pending. This is not
   specific to unlock — every write endpoint in the application can return
   `2xx` before its data is visible; it simply never mattered before, because
   nothing else reads its own write back within milliseconds.
   `commit_before_responding()` now makes the three security writes commit
   before producing their response, with **80 out of 80** clean runs afterwards, against 3-in-40 and 4-in-40 before. The general remedy — a unit-of-work boundary that closes before the response, for all ~145 routes — is recorded as outstanding rather than quietly done as a side effect of this phase.

**A hypothesis that turned out wrong, kept because it is worth recording:**
the first suspect was `RequestContextMiddleware`, a `BaseHTTPMiddleware` —
Starlette runs the inner app in a separate task under that base class, which
is a documented way to break dependency-teardown ordering. Removing it gave a
clean 40/40 and I took that as confirmation. It was not: converting the
middleware to pure ASGI left the failure rate unchanged at 36/40, so the
original 40/40 was a ~5%-likely clean run at a ~7% failure rate. **One clean
sample is not a confirmed mechanism.** The pure-ASGI conversion is kept on its
own merits — one fewer task hop, and none of `BaseHTTPMiddleware`'s known
interactions — and is verified not to have broken the request-id header,
client-IP capture, or the `request_id`/`ip_address` columns on audit rows,
but it is not the fix and is not claimed as one.

### Verified

**64 live checks** against real Postgres, all passing: the trail recording
real create/update/delete actions and outliving the entity it describes,
entity and actor resolution to public ids and labels, every filter including
the two that must be refused, lockout through to unlock, the expired-lock and
indefinite-lock cases, session listing and both revocation shapes, CSV export
with out-of-band truncation headers, and the permission matrix across five
roles including the purpose-built read-only auditor.

The append-only property is proven at the database level as the superuser —
bypassing every line of application code — for UPDATE, DELETE, a DELETE
matching nothing, and TRUNCATE.

## Reporting and dashboards (spec §17–§18)

Four endpoints, no migration, and almost all of the design is in two
decisions about *who* rather than *what*.

**A dashboard needs no permission of its own; a report does.** A dashboard
assembles things the caller can already reach, so `/dashboard` is gated on
authentication alone and each *panel* is gated on the permission for its own
data. Requiring `report.read` was the obvious move and is exactly backwards:
neither Student nor Guardian holds it, so the two roles whose dashboard
matters most would have been locked out of their own. A missing permission
**removes a panel, it never fails the request** — a dashboard that 403s
because one tile is unavailable is useless, and the 403 tells the caller
nothing they can act on. The response's `panels` list names what came back,
so a client renders what it was given rather than inferring from the role.

Panels are `personal` (always), then `student`, `teaching`, `care` and
`institution` for the callers they apply to. Roles are additive here as
everywhere else: somebody who teaches *and* has a child enrolled gets both.
Each panel is computed only if the caller qualifies, so the cost of the
endpoint tracks how many hats they actually wear.

**Every aggregate carries the same scope object the listing carries.** A
count computed over rows the caller cannot see leaks precisely what the row
filter exists to withhold, one number at a time — "how many students failed"
is a smaller answer than the list, not a safer one. `AttendanceVisibility`,
`EnrollmentVisibility` and `WorkVisibility` are **required** arguments in
`repositories/reporting.py`, never optional narrowings, so there is no way to
call one of these and accidentally aggregate the institution.

**A report returns groups, never rows.** There is deliberately no "export
every attendance record" query: the row-level views already exist with paging
and scoping, and an endpoint that dumps them into one response is a
data-exfiltration tool wearing a report's name. Grouping also bounds the
result naturally — there are only so many courses, tutors or months — with a
`MAX_GROUPS` cap and an honest `truncated` flag rather than a prefix that
looks complete.

**Reading and exporting are different permissions, and the split is
meaningful.** A tutor holds `report.read` and not `report.export`: the figures
for their own batches are theirs to consult on screen, and a CSV is theirs to
keep after their account is closed. `?format=csv` is checked inside the
handler rather than by a second dependency, because it is one report with two
renderings and splitting the route would duplicate every filter twice over.

**Five smaller decisions worth not re-litigating:**
1. **Attendance is ranged on the session's scheduled time, not on when the
   register was filled in.** A mark recorded late still belongs to the class
   it describes; keying on data entry would move rows between months
   depending on when a tutor got round to it.
2. **The window is half-open `[from, to)` and defaults to a year.** A closed
   range silently drops or double-counts the boundary day, so month-on-month
   reports disagree with themselves at the seams. An unbounded default is the
   slowest query in the system and the largest answer, run by accident.
3. **Performance averages `SUM(score) / SUM(max_score)`, not the mean of each
   row's percentage.** A 1-mark quiz and a 100-mark exam are not equal halves
   of a student's performance, and averaging percentages makes them so.
4. **`None` is never rendered as `0`** — in JSON or in a CSV cell. "Nothing
   assessable yet" and "scored nothing" are different facts, and only one of
   them belongs at the bottom of a distribution.
5. **Every enrollment status gets a column even when it is zero**, so a CSV
   keeps the same shape month to month; a spreadsheet whose columns appear
   and disappear cannot be appended to.

**`attendance_rate` moved to `services/metrics.py`.** It was inline in
`attendance_service.summarise`; the §18 reports quote it grouped by course,
tutor, student and month, and a dashboard tile quotes it again. Three
implementations of "what counts as attendance" is three numbers the
institution can disagree with itself about — the same shape as the
`can_authenticate` drift the auth layer already learned from. Excused
absences leave the denominator, `late` counts as attended, and a student with
only excused records gets `null` rather than 0% or 100%.

`ScopeResolver.held_permissions` was made public so the dashboard can decide
per panel without a service importing the API layer's `resolve_permissions`.

### Two test defects, and the harness one is the instructive half

1. **The first mutation run was vacuous, and it passed.** Removing the
   attendance report's scope filter left all 53 checks green — because the
   run script started the server *once, outside* the loop, so every mutation
   was tested against the unmutated process still in memory. Restarting per
   run, the same mutation immediately fails with a tutor seeing
   `['MATH-101-A', 'rept_b1', 'rept_b2']`. **A mutation that appears not to
   be caught is first evidence about the harness, not about the test** — and
   a mutation harness that cannot fail is the same defect as a test that
   cannot fail, one level up.
2. **An assertion pinned an absolute total in a shared database.** "Three
   confirmed enrollments" was correct for the fixture and wrong for an
   *institution-wide* report, which legitimately includes every enrollment
   that already existed. Rewritten as `>= 3` plus exact per-course totals,
   where the fixture owns the rows.

A third finding came out of the mutations rather than a failure: making
excused absences count against the student was caught by only **one** check,
which meant the assertion labelled "excused leaves the denominator" was not
really testing that. The fixture gained a student whose only record is
excused — whose rate must be `null` — and the same mutation now fails three
checks.

### Verified, not just written

**54 live checks** against real Postgres over an exactly-countable fixture
(4 students, 2 tutors, 2 courses, 2 batches, 3 sessions, 6 attendance marks,
1 assignment, 2 gradebook entries), run twice with 0 failures. Exact numbers
throughout rather than "returns 200": a batch at 66.67%, a student at 100%,
another at 0%, one at `null`, a weighted course average of exactly 70.0, one
submission awaiting grading, one overdue assignment named in the student's
deadline list.

**The scoping proof is the point.** A tutor's report over the same batch
returns *the same numbers* as the administrator's, and one fewer row: same
arithmetic, narrower window. The other tutor sees only their own batch, and
neither sees the other's.

**Seven mutations, seven caught** (all with the fixed harness): attendance
scoping, enrollment scoping, performance scoping, the export permission
check, the excused-absence rule, both reporting-window guards, and gating the
whole dashboard on `report.read`. Each failed exactly the checks written for
it and passed again on restore.

## Academic administration (spec §23)

Academic years, semesters, departments, categories, tags and system settings —
the reference data everything else is described in terms of. Six small tables,
and almost all of the work is in what happens at their edges rather than in the
CRUD.

**Reference data is deleted differently from records.** Every foreign key into
these tables is `ON DELETE SET NULL` or CASCADE, so Postgres will happily
accept a delete and silently blank a hundred courses' department, promote a
subtree of categories to top level, or unschedule a term's worth of batches.
That is data loss with no error raised and no audit signature. So the rule
throughout: **a delete is refused with 409 while anything still references the
row, and the message names the count** — "12 course(s) still belong to this
department", not a 204 followed by a support ticket. Every response carries the
`usage_count` that decides it, so an administrator does not have to try the
delete to find out.

**The one exception is a tag**, and the distinction is the point: a department
or a category is something a course *belongs to* and blanking it loses a fact,
whereas a tag is a label and untagging is exactly what deleting one means. The
number of courses affected goes into the audit record rather than into the way.

**Dates are validated against the parent, not just against each other.** A
"Fall" semester running from 2025 into 2027 passes any start-before-end check
and is still wrong. Only the service can see both sides — the request knows the
semester's dates, the row knows the year's — so `_assert_inside_year` lives
there, and narrowing a year so its own semesters fall outside it is refused
too.

**A batch's calendar placement is one fact stored in two columns, so the two
have to agree.** `academic_year_id` and `semester_id` are independent nullable
foreign keys: "2025-2026" plus "Spring 2019" is perfectly describable and
nonsense, and nothing else can catch it — the database sees two valid
references and the request alone does not know which year a semester belongs
to. `_resolve_calendar` refuses the mismatch, and naming *only* a semester
adopts its year, so the contradiction cannot be created by omission either.
Clearing the year clears the semester with it: a batch in "Fall" of no
particular year is not a state worth having.

**The delete guard counts through both routes into a year** — direct
`academic_year_id` and via `semester_id` — because a year's semesters cascade
away with it. Counting only the direct column would report a year as unused
while batches sat in its autumn term. The two are UNIONed and counted
`DISTINCT`, so a batch naming both is one batch.

**`public_id` was added to all five reference tables** (migration
`b87e1b34858e`). They were the last models still exposing a sequential integer
primary key at the API boundary. Autogenerate wrote the column as
`nullable=False` with no default, which fails on a populated table — rewritten
as add-nullable → `gen_random_uuid()` backfill → NOT NULL → unique index, and
verified by running it forwards, backwards and forwards again.

**`system_settings` is the deliberate exception and keeps its natural key.**
`grading.pass_mark` is the name of the thing and what a caller already knows;
minting a UUID for it would mean looking up an identifier in order to ask for a
value by name. Writing settings stays Super Admin only — spec §2 is explicit
that an Administrator runs the institution's operations and does not change the
rules those operations run under, and the existing grants already said so.

**`academic.read` was granted to Tutor, Student, Corporate Manager and
Guardian.** These are the vocabulary the catalogue is described in; withholding
the read protects nothing (the names are already embedded in every course
response) and only makes the catalogue unfilterable. Writing stays with the
administration. **Re-run `python -m backend.cli.seed --skip-geo` after pulling.**

### The decorative-field note in `schemas/course.py` was finally cashed in

That file carried a docstring explaining that `category_id`/`department_id`
were held out of the request bodies because nothing could populate them — "it
lands with the administration endpoints or not at all". It lands now: both are
settable on create and update, tags are replaced as a set through
`PUT /courses/{id}/tags`, and the catalogue filters by all three. Batches gained
`academic_year_id`/`semester_id` the same way.

Detaching uses an explicit `clear_category` / `clear_department` /
`clear_academic_year` / `clear_head_tutor` flag rather than sending null: with
optional fields omitted from a PATCH body, "set this to nothing" and "do not
touch this" are the same JSON, and only one of them is what the caller meant.

### Three defects found by running it

1. **`_course_response` could not survive its own new fields.** It was
   `CourseResponse.model_validate(course)`, which works only while every
   response field maps 1:1 onto an ORM attribute of the same type. `Course
   .category_id` is the internal **integer** foreign key and the API's
   `category_id` is the category's **public UUID** — same name, different
   value. The mapper is now written field by field. (The batch mapper had
   already hit this and carried a comment about it; the course one had not.)
2. **The batch response was built in two places and they drifted.** Batch
   *create* lives in `courses.py` (`POST /courses/{id}/batches`) while every
   other batch route lives in `batches.py`, and each had its own copy of the
   response mapper. Adding the calendar fields to one left create returning
   them empty — while the delete guards proved the database had stored them
   correctly, so the write was right and only the echo was wrong. There is now
   one `batch_response`, imported.
3. **A newly-constructed instance's scalar relationships are marked *loaded as
   None*, not unloaded.** So `BatchService.create`'s re-read handed back the
   same identity-map object with `academic_year` still None, and the response
   reported an unscheduled batch. `session.expire(batch, [...])` before the
   re-read is what makes it repopulate — the same trap `set_tutors` was fixed
   for, one relationship kind over. `CourseService.create` needed the plain
   re-read for the matching reason: touching `course.category` on the
   just-built instance was a lazy load inside the event loop
   (`MissingGreenlet`).

**A fourth was my test, not the code.** "Detach a category to top level" asserted
200 while a *different* top-level category already held that name — a real
collision, correctly refused with 409. The test was rewritten to assert the
409, free the name, and then assert the 200.

### Verified, not just written

**65 live checks** against real Postgres, run three times consecutively with
0 failures: the exclusivity of `is_current`, semester containment in both
directions, department head must hold TUTOR, category sibling-name rules at
each level, self-parent and own-subtree refusals, delete guards for
departments/categories/years/semesters, tag replacement (including that an
unknown id fails the whole request and applies nothing), catalogue filtering by
category/department/tag, the batch calendar including the mismatch refusal and
semester-implies-year, and the settings permission split in both directions.

**Then mutation-tested.** Seven guards removed and restored: the department
delete guard, the category subtree guard, semester containment, the
batch year/semester mismatch check, the `session.expire` behind tag
replacement, the via-semester half of the year usage count, and `is_current`
exclusivity. Each failed exactly the test written for it and passed again on
restore.

**The via-semester count needed a row the API cannot create** (naming a
semester always adopts its year), so the test writes one directly — which is
also the shape any row predating these endpoints would have. Without that step
the UNION in `batch_counts` would have been untested defensive code claimed as
proven.

**One anomaly, recorded rather than smoothed over.** A single run immediately
after the mutation series returned a 500 on "duplicate category name under one
parent". It has not reproduced: three clean suite runs, seven consecutive
targeted HTTP repeats, and a direct service-level call all give the correct
409. The likeliest cause is leftover state from the mutated run — mutation 2
deliberately creates a parent/child cycle — rather than the restored code, and
the teardown now detaches category parents before deleting instead of relying
on the self-referential foreign key to unwind mid-statement.

## Communication — messaging, notifications, announcements, discussions (spec §16)

Four surfaces, one shared idea: **a permission says what you may do, and it
can never say to whom.** `message.create`, `announcement.create` and
`discussion.create` are held by nearly every role, because everybody has
somebody they legitimately need to reach. Left at that, each one is a broadcast
weapon — so the interesting work in this phase is the second question, answered
in the service layer against relationships the schema already had.

**Who may message whom.** `message.create` alone would turn the user directory
into an address book: one student messaging all 10,000 others, or a guardian
contacting another family's child. `MessageService._assert_can_correspond`
requires a real connection, and it is **symmetric on purpose**: the recipient
is in the sender's scope, *or* the sender is in the recipient's. Checking only
the first direction would make every relationship in the product one-way — a
tutor could open a conversation and the student could not start one back.
Unrestricted callers may write to anyone, and anyone may write **to** them,
because a student who cannot contact the office has no route to report a
problem.

**Reading is stricter than seeing, and this is the one place
`institution.view_all` deliberately does not widen.** That grant is over
institutional records — enrollments, attendance, grades. A private message
between two people is not one of those, so an administrator gets a 404 on a
message they are not party to, exactly like a stranger. Proven live rather than
asserted.

**Deletion is per side.** The model shipped a single `is_deleted`, which lets
either participant erase the other's copy of a correspondence they are equally
party to. `sender_deleted` / `recipient_deleted` now hide it from one mailbox
each; `is_deleted` is reserved for the administrative tombstone and is set only
once both sides have let go. Migration `885d3a5240d0` adds them, plus `read_at`
(*when* it was read — "she says she never saw it" is a support question a
boolean cannot answer) and the composite `(recipient_id, created_at)` /
`(sender_id, created_at)` indexes an inbox actually sorts on.

**Announcement targeting is three nullable columns, and the predicate is
written per dimension as "not narrowed by it, or narrowed to something I am".**
Written the natural way round — `course_id IN my_courses` — an
institution-wide notice (`course_id IS NULL`) would reach nobody: the
announcement everybody needed is the one nobody saw. The empty-scope case is
`IS NULL`, never "skip the filter", so a reader enrolled in nothing sees
untargeted notices only. And **nobody broadcasts wider than they teach**: a
tutor must target a course or batch they teach, so all-three-NULL is
administration-only.

**Moderation is a relationship, not a permission.** `discussion.update` cannot
say *whose* thread. Authorship governs title/body; being a tutor **of that
course** governs pinning, locking and removing somebody else's post. A second
permission name would have made "moderator" global — and a tutor of Mathematics
is not a moderator of the History forum. Two consequences fall out: a reply may
be *removed* by a moderator but never *edited* by one (rewriting somebody's
words under their name is not moderation), and an author may withdraw their own
thread only while nobody else has replied — after that, deleting it deletes
other people's words to retract yours, which is a moderator's call.

**Notifications have no create endpoint, deliberately.** A notification is
something the system emits as a consequence of an event; an API that lets a
client place arbitrary text in somebody else's tray is a phishing surface
carrying the institution's branding. `NotificationService.emit` is called by
other services inside the same transaction as the thing being announced, so a
tray can never hold "you have a new message" for a message whose insert rolled
back. The message notification carries the **subject only, never the body** — a
tray is rendered in places a message is not.

**Role grants extended** (re-run `python -m backend.cli.seed` to pick them up):
TUTOR gained `announcement.update`/`delete` and `discussion.delete`, STUDENT
gained `discussion.update`/`delete`, and every mailbox-holding role gained
`message.delete`. A tutor who can post an announcement but can never correct or
withdraw it is worse off than one who cannot post at all — the mistake is
permanent and only an administrator can clear it. All are scoped to *your own*
content in the service.

### Two defects found by driving it, not by reading it

1. **Every announcement was stored already expired, and every reader's feed was
   empty.** `end_at` was declared `utc_datetime_column(nullable=True)` — and
   that helper defaults to `default=True`, which attaches
   `server_default=CURRENT_TIMESTAMP`. SQLAlchemy treats an attribute set to
   `None` as *unset* when a column has a default, so passing `end_at=None` for
   "never expires" fired the default instead. Rows sat plainly visible in the
   table with an `end_at` *earlier* than their own `start_at`, and the feed
   query correctly excluded all of them. It also made editing an announcement
   return 422 (`end_at must be after start_at`) for a payload that touched
   neither field. Fixed with `default=False` and migration `4a84ceeb59b0`,
   which drops the server default and NULLs the rows carrying the defect's
   exact signature (`end_at <= start_at`, never a window anybody asked for).
   **Three of the four announcement audience tests had been passing
   vacuously** — an empty feed satisfies every "does not see" assertion.
   `shared_links.visible_from` has the same shape and was left alone: there,
   defaulting to "visible from now" is a defensible reading.
2. **`User` loaded every message and review the caller had ever sent or
   received, on every authenticated request.** `sent_messages`,
   `received_messages`, `reviews_written` and `reviews_received` were all
   `lazy="selectin"`, and `deps.get_current_user` loads a `User` by query on
   every request to resolve permissions — so the whole mailbox was attached to
   the hot path of the entire API. All five collections (including
   `notifications`) are now `lazy="raise"`: nothing needs them as collections,
   the endpoints query with paging and a scope filter, and raising names the
   real cause where a lazy load under asyncio would surface as
   `MissingGreenlet`. `CourseDiscussion.replies` got the same treatment, so a
   300-reply thread is no longer loaded in full to render a reply *count*.

A third, smaller one, and the same trap the earlier phases kept hitting:
`MessageService.send` returned the instance it had just constructed, whose
relationships are unloaded — `message.sender` in the response mapper was then a
lazy load inside the event loop. It re-reads through the repository, as every
other create path here does.

### Verified, not just written

**72 live checks** against real Postgres, all passing: correspondence policy in
both directions and both refusals, admin-cannot-read-private-mail, per-side
deletion (recipient deletes then gets 404, **sender still gets 200**),
conversation grouping with unread counts, notification isolation, the audience
feed from four vantage points including a student enrolled in nothing, tutor
targeting limits, the scheduled/expired window, thread scoping, lock
enforcement with a moderator exemption, and the
author-cannot-delete-a-thread-others-replied-to rule.

**Then mutation-tested, because a negative test that cannot fail proves
nothing** — and this phase had just produced three of those. Seven guards were
each removed and restored: the reverse-direction correspondence check (1 test
fails), per-side deletion (1), the announcement targeting guard (2), the role
audience filter (1), the empty-course-scope deny-all (1), the discussion
course-visibility gate (3), and the moderation/authoring split (1). Every one
failed exactly the test written for it, and passed again on restore.

**Not built, and deliberately:** `TutorReview` (the table exists from the model
rebuild, but no `review` module is in the permission catalog, and tutor ratings
are a different feature from communication) and any real delivery channel —
`NotificationChannel` models EMAIL/SMS/PUSH, and only SYSTEM is written today.

## Resources and file management (spec §10–§11)

**Storage is behind one `Protocol` with two implementations**
(`backend/storage/`): the local filesystem (default) and Cloudflare R2.
Everything above that line deals in opaque *keys*, never paths or bucket
names, so `STORAGE_MODE=local|r2` moves where bytes live without touching a
caller. `boto3` is an optional extra (`pip install -e ".[r2]"`), imported
lazily, so a local deployment never carries the AWS SDK; selecting `r2`
without it fails at startup naming the install command rather than at the
first upload.

**`presigned_url()` returning `None` is the honest difference between the
two backends**, not a gap. R2 hands the client a short-lived URL so file
traffic bypasses this server; a local file has no such thing and is streamed
back through the authenticated endpoint. Either way the permission check
happens *first* — a presigned link is only minted for someone already
entitled to the file.

**The client's filename never reaches the filesystem.** `build_key()` uses it
only to recover an extension, sanitised to `[a-z0-9]{1,10}`, and the stored
name is a fresh UUID under `resources/{resource_public_id}/`. `assert_safe_key`
runs on every read *and* write, so a key that reached the database malformed
cannot become an arbitrary-file-read later; `LocalStorage` then re-checks the
*resolved* path is inside the root, because a symlinked directory only
reveals itself after resolution. Verified live: uploading
`../../../../etc/passwd.pdf` stored a UUID under the storage root and wrote
nothing outside `var/storage`.

**MIME validation is an allowlist** (`STORAGE_ALLOWED_MIME_TYPES`, 19 types
by default) with a size cap (`STORAGE_MAX_UPLOAD_BYTES`, 100 MB). A blocklist
of "dangerous" extensions is unbounded and always one format behind; an
allowlist fails closed on anything unanticipated. The stored key is
deliberately absent from every response schema — publishing it invites
callers to build their own bucket URLs instead of going through the check.

**A resource is reachable three independent ways**, which is the whole shape
of §11's cascade: its course, its batch, or an explicit
`resource_permissions` grant / direct `shared_resources` share. The third
route is what lets one file be handed to someone outside the course without
opening the course to them — verified live: a student enrolled elsewhere saw
`total=0` and got 404 on the file, then after a share saw exactly `total=1`,
could download it, and still got 404 on a different file in the same folder.

**Deletion is two-step and recoverable.** Soft delete keeps the bytes and
hides the row from its audience (a student gets 404 while an admin who could
restore it still sees it); `purge` is irreversible, refuses on a
not-yet-deleted resource, and best-effort-deletes every stored version — an
orphaned object is reclaimable dead weight, whereas failing there would leave
a row nobody can remove. Folder delete is refused while non-empty, because
the FK cascades and would silently take the whole subtree.

**Versioning keeps every upload** (spec §10): a new version becomes current
while earlier ones stay downloadable via `?version=N`. `Resource.path/
mime_type/size` are a denormalised pointer to the current version, kept in
step in `_store_new_version` — that is why those columns exist rather than
joining to the newest version on every read.

**A public share link is 256 bits of randomness and revocable.** The token
*is* the authorisation, compared in constant time; the endpoint is
deliberately unauthenticated, and both revoking the link and soft-deleting
the resource cut access immediately (both verified live → 404).

### Two defects found by running it

1. **`ResourceFolder` had no `course`/`batch`/`creator` relationships** — the
   anchor columns existed but nothing could read through them, so the API
   returned `course_id: null` on a folder that plainly had one.
2. **Fresh uploads reported `current_version: 0`.** Version rows are inserted
   directly rather than appended to `resource.versions`, so that collection
   still held the empty list it was initialised with. Fixed with
   `session.expire(resource, ["versions"])` — and the *copy* path needed the
   same fix separately, because it builds its version row inline instead of
   through `_store_new_version`.

**`MissingGreenlet` on a new object's collections struck for the fourth time
here** (role seeder, `set_tutors`, `_apply_location`, now folders/resources).
`lazy="selectin"` only loads relationships for objects fetched *by a query*;
a newly-constructed instance has them unloaded, and the flush cascade touches
them. The rule, now stated plainly: **initialise every collection on a new
instance before `session.add`, and re-read for the response.**

**Also fixed in passing:** `AuditAction` had no `UPLOAD`/`DOWNLOAD`
constants, despite spec §19 listing both as tracked events and the
`AuditLog` model naming them in a comment — the first caller to use one
crashed. Uploads and downloads are now audited (verified: 11 and 12 rows).

## Grade book (spec §15)

**The grade book is derived, not written to by the marking services.**
`POST /batches/{id}/gradebook/sync` pulls graded assignment submissions,
completed quiz attempts, recorded exam results and attendance into
`gradebook_entries`. Wiring a `GradeBookEntry` write into each of those four
services instead would scatter one aggregation rule across four places and
guarantee they drift.

**Sync is idempotent by construction**, resting on two partial unique indexes
on `gradebook_entries` — which were declared on the model but **had never
reached the database** until migration `a992973be095`. Without them a re-sync
appends a second entry per source row instead of correcting the first, so
every run doubles a student's marks and the GPA drifts further from reality.
Two partial indexes rather than one four-column constraint because
`reference_id` is nullable and Postgres treats NULLs as distinct: a plain
UNIQUE would allow unlimited duplicate ATTENDANCE rows, which are exactly the
ones with no source row to point at. Verified live — first sync `created: 6`,
immediate re-run `created: 0, unchanged: 6`.

**Unmarked work is absent from the grade book, never a zero.** An ungraded
submission, an attempt still awaiting essay marking, or a student with only
excused absences is counted in `skipped_ungraded` and contributes nothing. A
zero would penalise a student for work the tutor simply has not reached.

**Derived entries cannot be hand-edited or deleted** — the next sync would
silently revert the change, which is worse than refusing. The API says so and
points at the underlying mark instead. Only reference-less components
(PRACTICAL) are manually creatable, one per student per batch.

**Component percentages are averaged, not raw points pooled.** Pooling would
let a 100-mark exam drown out a 10-point quiz purely because of the scale its
marks happen to use. Verified live: bob's 87.50% assignment, 50% attendance,
72% exam and 56.25% quiz average to **66.44% → D → 1.00 GPA**.

**Quiz entries use a denominator of 100** because `QuizAttempt.score` is
already a percentage (see the assessment section). **Attendance excludes
excused absences from its denominator**, matching `/attendance/summary`
exactly — two different numbers for the same thing would be worse than
either.

**Transcripts are provisional until finalised.** A non-final transcript is
visible only to staff who can mark; it is recomputed on every generate, and a
student acting on one would be acting on a figure that is still moving.
Finalising both reveals it and freezes it — regeneration reports
`skipped_final` rather than silently changing a number someone has acted on.
A transcript with no GPA cannot be finalised. Verified live: bob and his
guardian saw `total=0` until finalisation, then `total=1`; gina (guardian of
a different student) still sees `0`.

**Grade bands cannot overlap**, and letters are unique — two bands matching
one percentage would make the resulting letter depend on row order. Band CRUD
is gated on `academic.*` (institution configuration), not `grade.*`.

## Assessment — assignments, quizzes, exams (spec §12–§14)

**The answer key is a security boundary, and it is structural.** A student
fetching quiz questions must never receive `is_correct`. That is enforced by
two *entirely separate* schemas — `OptionForStudent` has no `is_correct`
field at all, so there is no serialisation path for it — served by two
different routes under two different permissions:
`GET /quizzes/{id}/questions` (`quiz.read`) and
`GET /quizzes/{id}/answer-key` (`quiz.update`). Deliberately **not** one
route with an `include_answers` flag: a flag makes leaking the entire answer
key a one-character mistake in a query string, and a permission check living
inside a handler is easier to bypass by accident than one bound to the route.
Verified live — the student response contains only
`['id', 'option_text', 'order', 'public_id']`, and `/answer-key` is 403.

**Auto-grading, and what it deliberately refuses to do.** MCQ (single and
multiple) and true/false are marked immediately; short-answer and essay are
left at `score_awarded = null` for a human. `null` is meaningfully distinct
from `Decimal(0)` here — conflating them would make an unmarked essay look
like a zero. While *any* answer is unmarked the attempt's `score` and
`is_passed` both stay `null` rather than reporting a total that ignores the
ungraded work. Multi-select is all-or-nothing: partial credit needs a rule
nobody has specified, and inventing one would silently decide how every
multi-select question in the institution is marked. Negative marking
(`grading_policy.negative_marking`) applies to wrong answers but never to
blanks — penalising someone for *not guessing* is the opposite of what
negative marking is for. A malformed `grading_policy` degrades to zero
rather than breaking grading for everyone.

**`QuizAttempt.score` is a percentage, not raw points** — it is the only
thing ever compared against `Quiz.passing_score` ("e.g. 70.00"), and it stays
meaningful if the question set changes. Raw per-question points remain on
each `QuizAnswer.score_awarded`. Verified live: 10 (correct MCQ) − 2.50
(wrong multi-select, 0.25 × 10) + 15 (essay) = 22.50 of 40 points = **56.25%**,
correctly failed against a 60 pass mark.

**Once a quiz has attempts, neither it nor its questions can be changed.**
Editing the pass mark, grading policy or answer key afterwards retroactively
rewrites what existing results mean. Same reasoning refuses deleting an
assignment that has submissions, or an exam that has results (the cascade
would take every mark with it).

**Attempt integrity:** an in-progress attempt blocks starting a second one —
without that, the attempt limit is bypassed by opening several and submitting
only the best. A submission arriving past `duration_minutes` (plus a 30s
network grace) is still graded rather than discarded — a blip must not
destroy someone's work — but is stamped `submitted_late` so the tutor can
see it. Without that column `duration_minutes` would be a decorative field.

**Publication is two independent switches on an exam.** `Exam.is_published`
releases the *schedule*; `ExamResult.is_published` releases the *marks*. A
timetable is normally public long before any results are, so one flag could
not express both. Recording a mark does not release it. Verified live: with
results unpublished, bob and his guardian see `total=0` while admin and the
tutor see both marks; publishing reveals them to exactly the right people;
retracting hides them again.

**Marks are entered in bulk**, like attendance — an examiner does a whole
cohort in one pass, and a per-student endpoint would leave a half-entered
mark sheet if one call failed. A student not enrolled in the exam's course
or batch refuses the *entire* sheet rather than being skipped silently.

### Three defects found by running it

1. **`Assignment` had no `course` relationship.** `Quiz` and `Exam` both
   carried one; `Assignment` had only the raw `course_id` FK, so any query
   needing the course title had nothing to eager-load and every create
   returned a 500. ORM-only fix, no migration.
2. **A Tutor could record marks but not read them back.** Unpublished results
   were gated on `exam.update` (admin-only), while entering marks needs
   `grade.update` (which Tutors hold) — so a tutor could submit a cohort's
   marks and then find them invisible. The gate is now `grade.update`:
   publication exists to withhold results from *candidates*, not from the
   staff doing the marking.
3. **An invigilator couldn't see their own unpublished exam.** Being assigned
   to supervise a not-yet-announced exam is precisely when it should appear
   on someone's duty roster; the schedule-visibility check excluded them.

**Two schema gaps closed** (migration `546fe0c102ba`):
`ck_exams_anchored_to_course_or_batch` — both anchors are individually
nullable, but an exam attached to *neither* is unreachable by every scoping
query and therefore invisible to everyone but an unrestricted admin; and
`quiz_attempts.submitted_late`, above.

## RBAC completeness audit + geo reference data

A user-requested audit against a real checklist (roles, permissions,
role_permissions, super admin, super admin's full grants, cities, timezones)
confirmed the first five were already solid — 90 permissions, 6 roles
correctly scoped, `SUPER_ADMIN` holding the full catalog, all self-escalation
guards intact — and found the last two completely unbuilt: `Country`/`City`/
`TimeZone` had models and nothing else. Zero repository, service, API route,
or seeder referenced them anywhere. `User.country_id`/`city_id` were the
exact "decorative field" pattern already flagged twice before in this
project — present on the model, absent from every schema.

**Real data, not generated.** Rather than hand-write an approximate country
list or a small hardcoded timezone table (both real risks when generated
from a model's training data instead of sourced), this pulled the actual
datasets live: 250 countries from
[mledoze/countries](https://github.com/mledoze/countries) (ODbL) and 34,134
cities (population ≥ 15,000) from [GeoNames](https://www.geonames.org/)'
`cities15000` dump (CC BY 4.0) — both fetched once, verified, and committed
as static JSON in `backend/bootstrap/data/` rather than called live at seed
time. See `backend/bootstrap/data/ATTRIBUTION.md` for exact provenance and
the license obligations (both require attribution wherever the data is
served, which `/geo/*` now does).

**Timezones are seeded from the stdlib, not a file.**
`zoneinfo.available_timezones()` — Python's own binding to the IANA
database that ships with the OS/`tzdata` package. No network call, no file
to go stale, and it's the same call `schemas/user.py` uses to validate a
submitted timezone string — the check and the seeded table can never
disagree because they share one source.

**Bundling instead of a live third-party call at deploy time was a
deliberate, confirmed choice** (the old reference project this was audited
against fetched cities from a public API during seeding): a seed step that
can fail because an unrelated API is down, rate-limited, or has changed
shape is a production liability, and a bundled snapshot is exactly
reproducible on every run.

**Three model corrections, all because the tables were finally getting real
data:** `Country`/`City` gained `PublicIdMixin` (the "never expose the
integer PK" rule, already applied everywhere else, had simply never reached
these two tables); `Country.code` and `City.country_id` went from nullable
to NOT NULL (a country with no ISO code, or a city with no country, was
never a valid row — just never enforced); `City.geoname_id` gained a unique
index, which is what makes the seeder's idempotency check real rather than
assumed. `City.country_code` (a redundant denormalized duplicate of
`country_id`) was dropped — reachable via `city.country.code`, and keeping
both is exactly the "two sources of truth" pattern this codebase has
removed everywhere else it turned up. Migration `a1a30b5d8e9d`.

**Country/city/timezone are now real fields on the user profile, not
decorative ones**, with actual consistency logic in
`UserService._apply_location`: setting a city with no country derives the
country from the city; setting a city that contradicts an explicitly-given
country is refused (409, names both); changing country away from an
incompatible city clears the city rather than leaving it dangling; clearing
country while a city is still specified is refused outright (a city cannot
outlive its country); clearing country alone cascades to clear an existing
incompatible city. `timezone` is validated against the same
`zoneinfo.available_timezones()` set at the schema layer, synchronously, with
no DB round trip.

### The bug this found, and why it's a repeat of one already in this file

Setting `user.country_id = 5` directly does **not** tell SQLAlchemy that
`user.country` — eagerly loaded by `self.get()` moments earlier in the same
request — is now stale. The relationship attribute keeps whatever it
resolved to when first loaded. Verified live before the fix: setting a
user's city returned `city: null, country: null` in the very same response
that had just accepted the write; changing country away from an
incompatible city echoed the *previous* country back. The write was correct
in the database throughout — only the response lied.

This is the third occurrence of "an in-memory ORM object doesn't know a
just-made change invalidates something it already loaded" in this codebase
(the role seeder's `MissingGreenlet` on a fresh collection; `set_tutors`'
stale `tutors` list after reassignment; now a stale scalar relationship after
reassignment). Fixed with `await session.refresh(user, attribute_names=[...])`
— `refresh`, not a bare `expire`, because this is async and touching an
expired attribute outside an explicit awaited reload raises `MissingGreenlet`,
which is the other two bugs' failure mode. **The pattern to watch for:**
any write that changes a relationship's target and then immediately builds a
response from the same in-memory object needs an explicit refresh — reading
the object back never proves this on its own, since the identity map hands
back the same stale instance.

**Verified live, end to end**, including the seeding performance: 250
countries + 34,134 cities + 598 timezones seeded in 10.5s, a re-run
confirming true idempotency (0 inserted, totals unchanged), and the full
consistency matrix above — all reflected correctly in the very response that
made each change, not just on a subsequent read.

**Layering**: `api/v1/<domain>.py` (HTTP) -> `services/<domain>_service.py`
(business rules, guards, audit) -> `repositories/<domain>.py` (queries) ->
models. Schemas in `schemas/`. Deliberately *not* generic auto-CRUD: the
useful queries here ("batches this tutor teaches") are exactly where the
authorization rules live, and no generic `list(model)` can express them.

**Conventions worth not re-litigating:**

- **`backend/core/permissions.py` is the single source of truth** for what
  permissions exist. The seeder and `require_permissions(...)` both read it,
  so a permission cannot be enforced that was never seeded. Names are
  `<module>.<action>`, matching the `Permission` model's own columns.
  `require_permissions()` validates its arguments against the catalog **at
  import time** — a typo becomes a startup error, not a route that silently
  denies everyone.
- **`*.manage` does not imply CRUD.** No implicit expansion: a role that
  should read and update is granted both, explicitly, so "what can this role
  do" is answerable by looking rather than by simulating inheritance.
- **The access token carries identity only** — no roles, no permissions.
  Those are resolved from the database per request (one indexed query, with
  roles+permissions eager-loaded in a single round trip). Cost: one lookup.
  Benefit: revoking a role or suspending an account takes effect on the very
  next request rather than whenever a token happens to expire.
- **Refresh tokens are opaque random values, not JWTs**, stored SHA-256
  hashed and rotated on every use. SHA-256 rather than Argon2 is correct
  *here specifically*: the value is 256 bits of entropy so guessing is not
  the threat, and Argon2's per-hash salt would make indexed lookup
  impossible. Replaying a spent token revokes **every** session for that
  user — two parties hold it and there is no way to tell which is asking.
- **Resources are addressed by `public_id` (UUID); roles and permissions by
  name.** Roles/permissions are a fixed code-defined catalog, so
  `/roles/TUTOR` is stable across environments and readable in a log, where
  a UUID would differ per environment and say nothing.
- **Single resources return bare JSON; collections return `Page`**
  (`items`/`total`/`limit`/`offset`, hard-capped at 200). No `{"data": ...}`
  envelope — errors are already distinguishable by status plus the
  `{code, message}` body from `core/errors.py`.
- **409 vs 422 is a real distinction here.** A malformed body is 422; a
  policy refusal on a well-formed request ("cannot change your own roles",
  "SUPER_ADMIN's permissions are immutable", "built-in roles cannot be
  deleted") is 409, so a client can tell "you sent something wrong" from
  "that target forbids this".

## Row-level scoping — which *rows*, not just which actions

`backend/services/scope.py`. Permissions answer "may this role do X at all";
they cannot answer "to whom" -- `user.read` is one grant whether it means
"every student in the institution" or "the two children I am guardian to".
Three scoped relationships, each over a join that already exists:

| Role | Sees | Via |
|---|---|---|
| Tutor | students in batches they teach | `tutor_courses` (course-level) **or** `batch_sessions.tutor_id` (single session — how a stand-in gets access) |
| Guardian | their linked students | `student_guardians` |
| Corporate Manager | their organization's employees | `organization_managers` → `organization_memberships` |

**`institution.view_all` is the bypass**, held by SUPER_ADMIN and ADMIN only.
It is a permission rather than a check on role name because an institution
will eventually want a REGISTRAR or AUDITOR role with full visibility and few
write rights, and `if role in (ADMIN, SUPER_ADMIN)` scattered through the
service layer cannot express that without a code change.

**Roles are additive.** A user holding several roles sees the union — scoping
is never a switch on "the" role. Verified: a student who is both a tutor's
pupil and a manager's employee appears in both their lists.

**The bug this module exists to prevent:** an empty scope silently meaning
"no filter". Written naively as `if self.ids: stmt = stmt.where(...)`, a
guardian linked to nobody falls through the `if` and is handed the entire
table. `Scope.apply` makes empty mean *deny all* — proven by compiling both
forms: the real one emits `WHERE false`, the naive one emits **no WHERE
clause at all**.

**Refusals are 404, never 403.** A 403 on an out-of-scope id confirms the
account exists, which is precisely what someone probing ids is after.

**`UserService.list_users`/`get` take `actor` as a required keyword
argument**, so an endpoint that forgets to scope cannot silently compile into
one that returns the whole directory. Future domain services must follow
this: take the actor, resolve a `Scope`, and apply it in the repository
before any other filter — never fetch-then-hide.

**Verified live** against real Postgres with a purpose-built fixture: Admin 9
users, Tutor 3 (her two students + self), Guardian 2 (his ward + self),
Manager 3 (two employees + self), a guardian with zero wards exactly 1
(himself). Removing an employee (`status='REMOVED'`) and deactivating a
manager (`is_active=false`) each correctly withdrew visibility, and restoring
them returned it.

### A real leak, found only by having two courses

`visible_batch_ids` was first written to widen from `visible_student_ids`:
"the batches my visible students are enrolled in". That is wrong for a tutor,
and it leaked. She may read the *profiles* of students she teaches, so the
naive union pulled in every batch any of them happened to attend — handing
her a batch of a course she has nothing to do with, because one of her
students also studied history.

It was invisible with one course in the database: "sees her own" and "sees
everything" produce identical output until a second course exists that she
does not teach. **A scoping test with only one of the thing being scoped
proves nothing.**

The correct union — now shared with `EnrollmentVisibility` — is *batches I
teach*, plus *batches the people in my care are enrolled in*, where "in my
care" is self + wards + employees and deliberately **excludes** a tutor's
students. Confirmed after the fix: tina lost `HIST-101-A` from her list and
gets 404 probing it directly, while gary (whose ward is enrolled there) still
gets 200.

## Academics — courses, batches, enrollments (spec §5–§7)

**Both lifecycles are explicit transition maps**, in `course_service.py` and
`enrollment_service.py`. The interesting property is what is *absent*: a
DRAFT course cannot jump to COMPLETED, nothing leaves ARCHIVED, and
un-publishing to DRAFT is allowed while un-completing is not (grades and
certificates hang off a completed course). For enrollments, CANCELLED is
reachable only from PENDING — a confirmed student who leaves has DROPPED,
and collapsing the two would lose the difference between someone who never
started and someone who withdrew part-way. Refusals are 409 and name the
transitions that *are* available.

**Transfer preserves history.** The original enrollment is closed as DROPPED
and a new row created pointing back through `previous_enrollment_id`, rather
than rewriting `batch_id` in place — which would erase the fact the student
was ever in the first batch, along with the context for the attendance and
grades recorded there. Re-enrolling after DROPPED creates a fresh row; the
partial unique index `uq_enrollments_active_batch_student` allows exactly
that while refusing two *live* enrollments for the same pair.

**Capacity is checked under a row lock** (`BatchRepository.lock_for_enrollment`,
`SELECT ... FOR UPDATE`). Capacity is a read-modify-write, so without
serialising on the batch row two simultaneous enrollments both see the last
free seat and both take it. The lock is per-batch, so unrelated enrollments
are unaffected.

**The sponsoring organization is derived, never accepted.** When a Corporate
Manager enrols someone, `enrollments.organization_id` comes from *their own*
active `organization_managers` row — a caller-supplied id would let anyone
attribute an enrollment to a company they have nothing to do with. Enrolling
a student who is not in their organization is refused rather than silently
recorded as unsponsored.

**The course catalogue is deliberately unscoped, but status-filtered.**
Anyone with `course.read` can browse, or a Corporate Manager could never find
a course to enrol employees into. What is hidden from ordinary callers is
DRAFT and ARCHIVED — with an exception so an assigned tutor still sees their
own course while it is a draft. A hidden course answers 404, not 403: a draft
is not something the institution admits to having yet.

**Tutor assignment (`PUT /courses/{id}/tutors`) is an authorization write.**
`tutor_courses` is what grants a tutor sight of the course's batches and the
students in them, so assigning someone there hands them access to student
records. Assigning a user who does not hold the TUTOR role is refused.

## Sessions and attendance (spec §8–§9)

**`attendances` shipped without a unique constraint** on
`(session_id, student_id)` — so re-marking a register inserted a second row
instead of correcting the first, leaving a student simultaneously PRESENT and
ABSENT for one class and every attendance percentage computed from those rows
silently wrong. Fixed by migration `34a1817c1962`, which deliberately carries
no de-duplication step: this database had zero attendance rows, and against a
populated one it should fail loudly rather than have a migration decide
unsupervised which of two contradictory registers is real.

**Marking is bulk and idempotent.** `PUT /sessions/{id}/attendance` takes the
whole register — thirty separate requests to take one register would leave it
half-marked if the fifteenth failed. Re-sending corrects existing entries
(upsert against the constraint above). Marking a student who is not enrolled
in the session's batch refuses the **entire** request rather than skipping
them: a register that silently drops names is worse than one that fails
visibly, because nobody notices the gap.

**Assigning a session tutor is an authorization write.**
`batch_sessions.tutor_id` is one of the two routes by which a tutor reaches a
batch's students, so covering a single session grants access to that roster —
hence the TUTOR-role check, matching course tutor assignment.

**Scheduling belongs to administrators, not tutors** (spec §2 lists
scheduling under Admin). Tutors hold `session.update` but not
`session.create`, so they can add notes and a recording link to their own
sessions without being able to schedule new ones. Verified: a tutor gets 403
scheduling, 200 marking attendance; a guardian gets 403 marking.

**Double-booking a tutor is refused**, using a standard interval overlap
(`existing.start < new.end AND existing.end > new.start`) so touching
endpoints do not collide — back-to-back 10:00–11:00 and 11:00–12:00 classes
are both allowed. Only checked when an end time is known: inventing a
duration for an open-ended session would refuse bookings on a guess.

**A session with attendance recorded cannot be deleted** — the FK cascades,
so deleting would silently rewrite every affected student's record. A session
that actually happened is history, not a scheduling mistake.

**`attendance_rate` = (present + late) / (total − excused)**, as a
percentage. An excused absence leaves the denominator rather than counting
against the student — that is what "excused" means. Null, not 0% or 100%,
when the denominator is empty (no records at all, or only excused ones);
both paths verified.

**The scope filter applies to the aggregate, not just the listing.** A
summary computed over rows the caller cannot see would leak the same
information one number at a time. Verified: a guardian requesting another
guardian's ward's summary gets `total=0, rate=null`, while the real guardian
gets the true figures.

## Corporate organizations and guardianship

**Two invariants, enforced twice.** A user manages at most one organization
at a time, and belongs to at most one at a time. The service checks so the
caller gets a readable 409 naming the *other* organization; the partial
unique indexes (`uq_organization_managers_active_user`,
`uq_organization_memberships_active_user`) are what make the rule true under
concurrency. Reassignment inserts a new row rather than overwriting, so a
previous spell of employment survives — verified: a re-hired employee has
both an ACTIVE and a REMOVED membership row.

**`organization.appoint` is withheld from Corporate Managers, deliberately.**
Appointing a manager grants sight of every employee's records, so a manager
who could appoint co-managers could hand a colleague their whole roster with
no institutional involvement. Administrators appoint; managers invite
employees (`organization.invite`) and nothing more. Verified live: a manager
attempting to appoint gets 403 naming the missing permission.

**Manager revocation deactivates, membership removal is terminal, guardian
unlinking hard-deletes.** Three different answers because the questions
differ: who had access to employees' data and when is exactly what an audit
asks about (keep it); a past employment is context for sponsored enrollments
(keep it); but who *used to* be able to read a child's records, retained
indefinitely, is data nobody asked us to hold (delete it).

**Guardianship is administrative only.** The GUARDIAN role holds
`guardian.read` and not `guardian.create` — "I am this child's guardian" is a
claim, not a fact, and the institution has to be the one asserting it.
Refused links: duplicate, self-guardianship, a non-GUARDIAN as guardian, a
non-STUDENT as student. A student has at most one primary contact; promoting
one guardian demotes the incumbent.

**Organizations are scoped with no browsing case**, unlike the course
catalogue: one company has no business enumerating the others. A manager
listing organizations sees exactly theirs, and another company's id answers
404.

**Verified live, end to end.** Appointing mary gave her exactly Acme (1 org,
3 employees + herself); removing an employee dropped her view to 2; revoking
her appointment dropped it to herself alone; re-appointing restored all of
it. Guardian links behaved the same way — linking granted sight of the ward,
unlinking removed it, and one guardian filtering by another's ward returned
`total=0` rather than leaking.

**Security-critical subtlety, load-bearing:** a failed login must be recorded
in an **independent transaction** (`services/audit_service.py`'s
`record_independently`, and `AuthService._register_failed_attempt`). The
request is about to raise a 401, and that rollback would otherwise discard
the `failed_login_attempts` increment — leaving the counter permanently at
zero and the lockout permanently unreachable, while every "wrong password
returns 401" test still passed. Verified live: five bad attempts, then the
*correct* password is refused, and `attempts=5, is_locked=true` is in the
database.

**Seeding** (idempotent, safe on every deploy):

```bash
LMS_ADMIN_PASSWORD='...' .venv\Scripts\python.exe -m backend.cli.seed --non-interactive
```

Seeds 88 permissions, the 6 roles and their 253 grants, and the first Super
Admin. Re-running reports 0 changes and **never resets an existing admin's
password**. The password comes from the environment or an interactive
prompt, never a CLI argument (which would land in shell history and the
process list).

**Running the API on Windows needs an explicitly-constructed event loop.**
`backend/main.py`'s `_serve()` builds one via
`asyncio.Runner(loop_factory=...)` rather than trusting
`WindowsSelectorEventLoopPolicy`: `uvicorn.run()` creates its own loop and
does not reliably honour the policy, so the server came up on a
ProactorEventLoop and every database call failed at startup — while the same
code worked fine under the test client, which does honour it. Run with
`python -m backend.main`.

**Two bugs this phase found by running it, both invisible to inspection:**

1. **`Permission.roles` was annotated `Mapped["Role"]` — singular.**
   SQLAlchemy infers cardinality from that annotation, so it was a *scalar*
   many-to-one, and `back_populates` meant granting a permission to a second
   role silently revoked it from the first. The symptom was arithmetic:
   role grant counts summed to exactly 88, the total permission count, no
   matter how many roles were meant to share them. The `role_permissions`
   table was always a correct many-to-many; only the annotation disagreed.
   This survived the earlier model review, which called the file "already
   correct".
2. **Autogenerate emitted an unsafe migration.** `add_column(..., nullable=False)`
   with no default succeeds only while the table is empty — `tokens` was, so
   it passed locally and would have failed the production deploy the moment
   anyone had ever signed in. Rewritten as add-nullable → backfill → set
   NOT NULL (migration `ccb255c9e895`).

**Two more in phase 2, both async-ORM traps worth recognising on sight:**

3. **`MissingGreenlet` on a freshly-created object's collection.** Reading
   `course.tutors` right after `flush()` triggers a lazy SELECT — under
   asyncio that raises rather than quietly querying. `lazy="selectin"` does
   not help: it applies to objects loaded *by a query*, and a brand-new
   instance was never queried. Fix: initialise the collection (`course.tutors
   = []`) before it becomes persistent. Third occurrence of this pattern in
   this codebase (role seeder, `role.users`, now this).
4. **A stale collection survived a re-read.** After changing
   `tutor_courses` rows, `set_tutors` re-queried the course with
   `selectinload` — and got back the *same* instance from the identity map,
   still holding the collection loaded before the change. The API reported no
   tutors while the assignment had in fact succeeded. Fix:
   `session.expire(course, ["tutors"])` before the re-read. Re-querying alone
   is not a refresh.

## The console (frontend)

`frontend/` holds the **LMS Console**: Next.js 16 (App Router) + TypeScript
(strict) + Tailwind v4 + Base UI + TanStack Query + react-hook-form/zod +
Recharts + Vitest. 43 routes covering every domain the API serves — users,
roles, permissions, organizations, guardians, courses, batches, timetable,
enrollments, attendance, assignments, quizzes, examinations, grade book,
transcripts, resources, announcements, discussions, messages, notifications,
academic setup, settings, integrations, reports, audit, security and ops.

Setup, architecture and the checks: [frontend/README.md](frontend/README.md).
**Where the last session stopped, what is left running on the machine, and the
four outstanding items:
[frontend/docs/SESSION-STATE.md](frontend/docs/SESSION-STATE.md) — read that
first when resuming.**
What the console deliberately does **not** offer, and why:
[frontend/docs/BACKEND-GAPS.md](frontend/docs/BACKEND-GAPS.md).

**`frontend/` was empty before this pass.** The brief said not to introduce a
framework if the project already had an appropriate one; it had none, so the
stack is a decision made here rather than one inherited, and is recorded as
such.

### Two rules the rest follows from

1. **The browser never holds a token.** Both tokens live in `httpOnly`
   cookies; every call goes through the same-origin BFF proxy at
   `/api/backend/[...path]`, which attaches the bearer server-side. Verified
   live: `document.cookie` is empty and both storages hold nothing. There are
   deliberately no `NEXT_PUBLIC_*` variables — the browser is never told where
   the API is.
2. **The backend is the authorization layer.** `can("user.create")` decides
   what to *show*. Proven live: signed in as a Tutor, the sidebar renders 20
   of 32 screens, `/audit` refuses by name, and calling `audit-logs`, `roles`,
   `settings` and `security/summary` straight through the proxy returns
   **403** from the API while `courses` returns 200.

Nothing branches on a role name. Permissions come from `GET /auth/me`, which
returns the caller's effective set after role resolution.

### Generated, not transcribed

| File | Source | Regenerate |
|---|---|---|
| `src/lib/api/types.ts` | the API's own OpenAPI document (251 schemas) | `python frontend/scripts/generate_api_types.py` |
| `src/lib/auth/permission-names.ts` | `backend/core/permissions.py` (97 permissions) | `python frontend/scripts/generate_permissions.py` |
| `src/test/role-grants.ts` | the same, role grants — **test fixture only** | as above |

Hand-writing 251 response shapes is how a frontend ends up describing an API
that no longer exists. The permission union is the same idea one level up:
`can("user.creat")` is a compile error rather than a control that silently
never appears for anybody. `role-grants.ts` sits under `src/test/` and not
`src/lib/` on purpose — a role-to-permission map beside the permission helpers
is an invitation to branch on a role name.

### Five defects found by driving it, not by reading it

Every one was invisible to a green suite and to `curl`.

1. **The sign-in form put the password in the URL.** A click landing during a
   slow dev rebuild — before hydration — produced
   `GET /login?identifier=superadmin&password=...`, and from there browser
   history, the access log and the next request's `Referer`. The trigger was
   timing; the defect was that a form with no `method` defaults to GET, so any
   submit escaping React serialises its fields. Every form in the console now
   declares `method="post"`, and `src/app/forms.test.ts` fails if one does not.
2. **Sign-out revoked nothing.** `POST /auth/logout` needs a bearer token *and*
   the raw refresh token; the route sent only the body, got a 401, and cleared
   the cookies anyway. Cookies gone, console back at sign-in, session still
   live in `tokens` until natural expiry — indistinguishable from success.
   Found by checking the table, not the browser. It was visible at all because
   the route reports `revoked` honestly rather than always claiming `ok`. Now:
   token created 17:51:54 then **revoked at 17:51:56**, and `?scope=all`
   revokes every session.
3. **The proxy had no upstream timeout.** With the API stopped mid-request the
   console sat on "Loading your account" for **118 seconds** with no error,
   because nothing ever rejected. Bounded now by *time-to-first-byte* rather
   than total duration, so a large CSV export still streams for as long as it
   needs; a stalled API answers 504 and the error state takes over.
4. **`GET /audit-logs` returned a 500 depending on which rows the page hit.**
   `resolve_entities` selected `kind.model.id`, but `Enrollments` is keyed by
   `enrollment_id`. Any audit page containing an enrollment row crashed while
   its neighbours were fine. The primary key is now read from the mapper, and
   `_check_registry()` runs at import so a future model with a differently
   named key fails at startup naming the entry, instead of intermittently at
   read time. One of 29 registered types was affected.
5. **The spec section 53 IP lookup silently returned nothing.** `ipapi.co`
   answers **429 RateLimited** to Node's default user agent and 200 to a real
   one, so the route reported the IP it found and null for everything else —
   which reads as "this address has no known location". With a descriptive
   User-Agent it resolves `103.170.173.46` to `Asia/Dhaka, BD, bn-BD`, and the
   response says whether the address was the client's or the server's egress.

### Testing

`npm test` — 71 tests over the pieces where being wrong is silent: the
permission set, the route-to-permission map, the redirect allowlist, query
building, date/time conversion, proxy header stripping, refresh
serialisation, the upstream timeout, the sign-out contract, and the **RBAC
navigation matrix** driven from the backend's real grants.

`python frontend/scripts/mutation_test.py` breaks each guard in turn and
expects the test written for it to go red. A negative assertion is worth
nothing until a mutation proves it can fail -- and on the first full sweep one
of the fourteen survived: the repo-wide check that every form declares
`method="post"` searched for that text as a *substring*, and the explanatory
comment inside the sign-in form tag contains it, so deleting the real
attribute left the check green. The test now strips comments and matches the
attribute as an attribute. **The sweep caught a test that could not fail on
the same day it was written.**

**Writing the RBAC matrix from the specification's prose produced four
failures, and the implementation was right in all four.** An Administrator
holds `setting.read` and `permission.read` (they may look, not change); a
Student holds `enrollment.read` (their own); Tutors and Guardians both hold
`user.read` (to look up the people they are responsible for). Read access and
write access are separate grants and the sidebar gates on read. The test now
says so rather than asserting what the prose implied.

### Timezones (spec section 53)

The database stores UTC and the API returns UTC; the console only decides how
an instant is *shown*. Precedence: an explicit choice in this browser, then
the account's `timezone`, then the browser's own. `GET /api/locale` implements
the `icanhazip` to `ipapi.co` chain and is deliberately **last** and lazy: it
tells two third parties an IP address, and behind a proxy that address is the
server's — which the response states.

Two conversions carry the weight. Instants with no offset are marked UTC
before parsing; read as local time the whole display is wrong by the viewer's
offset, which looks like a data problem. And `datetime-local` values are
anchored at the *candidate instant*, not at "now", so 09:00 in Europe/London
is 09:00 in both January and June. Verified live: the same stored sessions
render 15:00 in Asia/Dhaka and 09:00 in Europe/London.

### Environment notes

- `next dev` needs `frontend/.env.local` with `LMS_API_URL`; there is no
  fallback, and the error names the variable.
- **ESLint 10 cannot load `next/core-web-vitals`** — the bundled
  `eslint-plugin-react` calls `context.getFilename()`, removed in ESLint 10,
  and crashes on the first file. `eslint.config.mjs` assembles the TypeScript,
  React Hooks and Next core-web-vitals rules directly instead. Nothing is
  suppressed; what is lost is `eslint-plugin-jsx-a11y`, which cannot be
  imported on its own because it is nested inside `eslint-config-next`. Stated
  in the config rather than left as a silent gap.
- Vitest's default `forks` pool times out spawning workers on this host; the
  config uses `threads`, caps concurrency at 2 and raises the per-test timeout
  to 30s. With seven files in flight the CPU contention alone pushed component
  renders past the default 5s, which looks exactly like a slow component and
  is not one.
- **Do not run the test suite beside `next dev` and the API**: they compete
  for the same cores and vitest starts failing to spawn workers at all.

## Known gaps — flagged, not forgotten, not yet addressed

> **Pruned 2026-10-05.** Four entries here had become false — "no automated
> tests", "no file upload anywhere", "quiz `shuffle_questions` is stored and
> never applied", and the grade book being stale until somebody pressed Sync.
> A gaps list that still names solved problems is the same failure as a
> comment asserting a safety property that no longer holds: it stops the next
> person checking. Anything left below was re-read, not assumed.


- **Messaging and academic administration are unbuilt** (spec §16, §23) —
  models and permissions exist for both, but no endpoints.
- **No virus scanning** (spec §20). Uploads are checked for size and content
  type only. A real scan means handing bytes to an external scanner before
  they become downloadable, which is a background-job shape this codebase
  has no runtime for yet.
- **Uploads are buffered fully in memory** before being written. Fine at the
  100 MB default; a video-sized limit would want streaming straight to the
  backend rather than `await upload.read()`.
- **`ResourcePermissionLevel` is stored but not enforced.** A grant records
  VIEW / DOWNLOAD / EDIT / MANAGE, and the *existence* of a grant makes the
  resource reachable, but nothing yet distinguishes them — a VIEW grant
  currently permits download. Enforcing the distinction is the natural next
  step on this domain.
- **Assignment submissions still take caller-supplied file metadata** rather
  than going through this upload pipeline. `AssignmentSubmission.files` is a
  JSON blob; wiring it to real `Resource` rows would give submissions the
  same validation, versioning and storage abstraction.
- **Per-component weighting is not configurable.** Every synced grade book
  entry carries `weight = 1`, so the weighted average is currently a straight
  average across components; only manual entries can set another weight. A
  real policy ("coursework is 40% of the final mark") needs a table to store
  it in, which no model provides — the natural home is a per-course or
  per-batch weighting row keyed by `GradeComponentType`.
- **Sync is no longer the only writer, but it is still the only reconciler.**
  Marking a quiz, an assignment or an exam now enters the grade book
  immediately (§47), so it is no longer stale between a mark and a sweep.
  `sync_batch` remains what repairs a write the fail-open hook lost, and
  nothing runs it on a schedule.
- **Transcript PDF/export does not exist** (spec §18's PDF/Excel/CSV export
  covers reports generally, and none of it is built).
- **No way to add a city the bundled GeoNames snapshot doesn't have**
  (population < 15,000, or a place that's grown since the dump was taken).
  `/geo/*` is read-only by design (seeded reference data, not
  admin-managed) — if this becomes a real need, it's an argument for letting
  a user submit a free-text city name that creates a `City` row with no
  `geoname_id` on first use, not for building a full city CRUD surface.
- **No recurring-session scheduling.** Sessions are created one at a time;
  a ten-week course needs ten calls. A "repeat weekly until" helper is the
  obvious next convenience, and would need its own overlap checking.
- **Attendance reporting is per-student and per-batch only.** Spec §9 also
  asks for per-tutor, per-course, monthly and yearly views; the repository's
  `summarise` takes the filters it needs for the first two and would need
  date bucketing for the rest.
- **Corporate enrollment has no dedicated route.** A Corporate Manager
  enrols an employee through the ordinary `POST /enrollments`, and the
  sponsoring organization is derived from their own appointment. That works,
  but there is no bulk "enrol these ten employees" path.
- Every future endpoint returning student-linked data (attendance, grades,
  submissions) **must** resolve a scope and apply it in the repository
  before any other filter. That is the single most likely place for a data
  leak to be introduced — see the leak that phase 2 actually hit, above.
- No email module, so password reset and email verification are unbuilt
  (`MAIL_*` settings and `backend/email/` exist; no SMTP library installed).
- No rate limiting on `/auth/login` beyond per-account lockout — an attacker
  spreading attempts across many accounts is unthrottled. `redis` is a
  declared dependency and unused.
- Soft-delete isn't uniformly applied: `Resource`/`UserMessage` use
  hand-rolled `is_deleted` fields instead of the shared `SoftDeleteMixin`.
- No single written `ondelete` (CASCADE/SET NULL/RESTRICT) policy — chosen
  per-column reasonably, but ad hoc rather than documented.
- `core/config.py`'s `ConnectionSettings`/`QuerySettings` are still-inert
  "db-admin-platform" leftovers — unused, not yet removed.
- **`.env` still sets `SECURITY_JWT_ISSUER=db-admin-platform`**, so every
  token this LMS issues carries that unrelated product's name as its `iss`
  claim. Cosmetic today (issuer and verifier agree), wrong regardless.

## Re-running verification

```bash
cd D:\LAIT\LMS_NEW
uv sync                                     # installs psycopg, drops the unused asyncpg
.venv\Scripts\python.exe -c "from backend.models import *; from sqlalchemy.orm import configure_mappers; configure_mappers(); print('OK')"
.venv\Scripts\python.exe -m alembic current # should report 6612ea1b2250
.venv\Scripts\python.exe -m backend.main    # NOT `uvicorn ...` -- see the event-loop note above
# then: curl http://localhost:8000/readyz
#       http://localhost:8000/docs for the interactive API browser
```

The console, in a second terminal (it needs the API already running):

```bash
cd D:\LAIT\LMS_NEW\frontend
npm install
# frontend/.env.local must contain: LMS_API_URL=http://127.0.0.1:8000/api/v1
npm run dev                                 # http://localhost:3000
npm run typecheck && npm run lint && npm test && npm run build
python scripts/mutation_test.py             # breaks each guard, expects red
```

Regenerate the derived frontend files after any backend schema or permission
change -- they are read from the running application, not maintained by hand:

```bash
.venv\Scripts\python.exe frontend\scripts\generate_api_types.py
.venv\Scripts\python.exe frontend\scripts\generate_permissions.py
```

## LAIT user synchronisation

Users are provisioned from the LAIT API (`/api/Students/latest`, `/api/Tutors`, by-guid detail) by a worker (`python -m backend.cli.sync_lait_users --once|--interval N [--dry-run]`) and by the admin **Sync from LAIT** button (`POST /v1/users/sync`, permission `user.sync`; history under `/users/sync/runs`). Settings: `LAIT_*` (`LaitSettings`); migration `a15c0de5f1d7`. Re-seed after upgrading (`LMS_ADMIN_PASSWORD=... python -m backend.cli.seed --skip-geo --non-interactive`) to pick up `user.sync` and `user.allow_login`.

- **Access is separate from provisioning.** Synced accounts get the shared default password but `can_login=false`; only `user.allow_login` (Super Admin) flips it. One predicate, `User.is_login_permitted`, is used by login, refresh and `get_current_user`; refusal is the same generic message as a wrong password.
- **Additive only.** `/latest` is a recent-registrations feed, so absence means nothing: the sync never suspends, deletes or demotes. It never writes status, can_login, password, slug or username on update; it can grant only STUDENT/TUTOR/CORPORATE_MANAGER/GUARDIAN, never admin roles. A username/email collision (crosswise) skips the row, never merges.
- Country: fuzzy match only, never created. City: fuzzy within country (transposition-aware), created only when clearly new; ambiguous or junk -> left empty. `RegistrationDate` is UK time, stored UTC.
- One transaction per record; dry-run does the work and rolls back; the `RUNNING` row (partial unique index) is the lock.
- Tests: `tests/unit` (mapping/client/geo) and `tests/integration/test_lait_sync_service.py` (real Postgres, fake LAIT); guards mutation-tested. **Unpaired DB constraints can mask a missing app check** — assert the failure *reason*, not just that the row was skipped.
- Windows: run uvicorn on a Selector loop (`asyncio.Runner(loop_factory=...)`); the seed CLI prompts for a password unless `LMS_ADMIN_PASSWORD` is set.
- Not verified: a real (non-dry) sync against the live LAIT API — real people's data; run it deliberately.

## Profile pictures, self-service profile, account creation UX

- **Pictures** are re-encoded server-side (`backend/services/avatar.py`): Pillow decides the type (JPEG/PNG/WebP only; SVG/GIF/HTML fail to decode), pixel budget checked before decoding, EXIF/GPS stripped, output a 512x512 WebP. Stored under `avatars/{public_id}/`; the old object is deleted on replace/remove. `profile_picture` in API responses is a *path* (`/users/{id}/picture?v=...`, `v` = key stem for cache busting), never the storage key. `GET` needs only a signed-in session; UUIDs are unguessable and "no user" and "no picture" are the same 404.
- **Two routes to the same data:** admins `PUT/DELETE /users/{id}/picture` + `PATCH /users/{id}` (need `user.update`, scoped); everyone `PATCH /auth/me`, `PUT/DELETE /auth/me/picture` (own row only; email is refused with 422 — it is the sign-in identifier and cannot be verified here; roles/status are not in the schema). Verified live: a student gets 403 on another user's profile/picture.
- **Frontend:** shared `ProfileForm` (mode `admin`|`self`, sticky dirty/save bar, `beforeunload` guard), `AvatarUploader`, `UserAvatar` (initials fallback), and a rebuilt `CreateUserDialog` (username suggested from email, role cards, generated/strength-metered password, one-time credentials screen).
- **Bugs fixed on the way:** (1) BFF proxy 500'd when a refresh failed (response body cancelled then reused) and concurrent requests each rotated the same refresh token, which the backend reads as theft and revokes the session — refresh is now single-flight per token. (2) Create form and Change-password form allowed 8-char passwords while the server requires 12.

## LAIT academic synchronisation (courses, batches, sessions, enrolments)

`POST /v1/courses/sync` (`course.sync`; `--dry-run` via `?dry_run=true`), history under `/courses/sync/runs`, worker `python -m backend.cli.sync_lait_academic --once|--interval N|--dry-run|--status-only`. Migration `b27e4c90a1d3`; re-seed for `course.sync`. Built on the user sync: same `user_sync_runs` table (`kind` = USERS|ACADEMIC; **one RUNNING row across both kinds is the lock** — an academic run can create users) and it reuses `LaitSyncService.upsert_record` to create missing tutors/students on demand (without login access).

- **Time:** LAIT sends naive UK time; everything is converted with `zoneinfo` (BST-aware), stored UTC. Verified on real data: a 6 PM UK batch is 17:00 UTC before 25 Oct and 18:00 UTC after.
- **Sessions are derived** from `training_days` (free text: `Mon, Wed & Fri (2 wks)`, `5 Thursdays`, `Thursday to Friday`, ...) between start and end, capped at LAIT's `training_sessions`; all 13 real batches yield exactly the reported count (36). A disagreement is reported, never silently resolved. Re-sync matches on `(batch_id, session_start_time)` (unique index); a session that leaves the schedule is deleted only if pristine (no attendance/links/notes), otherwise kept and counted.
- **Course fields from the public page** (`lait_academic.parse_course_page`, keyed on stable element ids): level (a range like "Intermediate to Advanced" resolves to its *lower* bound), duration, prerequisites (stops at "Software Requirements"). **Category comes from the site's own menu**, matched by course URL; a course listed under several headings takes the narrowest. Nothing is invented: unlisted -> no category.
- **Page fetching never carries the API key**, only fetches https on `course_page_hosts` (and subdomains), does not follow redirects, and caps the body (`lait_pages.py`).
- **Course status is derived, not taken from LAIT:** RUNNING while an *active* batch is in progress (UTC dates), else PUBLISHED; DRAFT/COMPLETED/ARCHIVED/deleted are never touched; recomputed on every run *including failed ones*, and via `--status-only`.
- **LAIT owns what it sends; admins own the rest.** Never overwritten: enrolment `status` (a local DROPPED survives), batch `capacity`/edited `notes` (generated notes carry an `Auto: ` prefix), session links, a category once set. A locally deleted course stays deleted; a title collision with a different course is reported, not merged. Enrolments are never removed because a feed stopped listing them.
- **`batches.total_enrollments`** starts from LAIT's `total_admission` and is then recounted from `enrollments`. `enrollments.previous_enrollment_id` = the student's latest enrolment in another batch. A student's `company` becomes an `organizations` row (placeholder values like "N/A"/"Self employed" are refused), shared per normalised name; **no membership is created** (memberships grant row-scope visibility).
- `courses.course_picture` was renamed `course_image` and `small_course_image` added.
- **Test hygiene lesson:** the first cut of the sync tests ran `DELETE FROM user_sync_runs`, wiping the dev database's real run history. Tests now delete only the run ids they created. A test that cleans a shared dev DB must scope its deletes.
- Not verified: a real (non-dry) academic sync against live LAIT. Real dry run: 25 courses, 13 batches, 36 sessions, 18 enrolments, 0 errors.

## Course management pass (list, create, edit, images, price)

- **List:** thumbnail (`CourseThumb`, default icon when none or when the URL fails to load), tutor/student filters replace department/tag (`GET /courses?tutor_id=&student_id=`; **institution-wide callers only** — filtering by person reveals who teaches/studies what; anyone else gets 403), and a **View details** modal (`CourseDetailsDialog`; `CourseResponse` now carries `batches`). A tutor's courses = `tutor_courses` **or** a session they teach (synced batches never fill `tutor_courses`); a student's = active enrolments.
- **One form for create and edit** (`components/domain/course-form.tsx`): staged image pickers with preview (uploaded *after* the course is saved; a failed image never undoes the course), code suggested from the title until typed over (`GET /courses/suggest-code`, `PPB-001`; unique constraint stays the arbiter), inline add of category/department (needs `academic.create`), price/link/prerequisites, **Fetch** from the link (`POST /courses/link-preview`: LAIT hosts only, fills *empty* fields only, saves nothing). An edit page for a course with a link but no price offers the price on open.
- **Course images** are processed server-side (`services/images.py`: type from the bytes, pixel budget, re-encode to WebP, EXIF dropped, *fit* not crop: 320x320 / 1600x1200). Uploaded = a storage key in `course_image`/`small_course_image`; external = an http(s) URL. The API exposes an uploaded image only as a path (`/courses/{id}/image/{kind}?v=`), never the key. **A request body can only set an http(s) URL** (schema validator) — if it could set a key, the image endpoint would serve any stored object. The sync never overwrites an uploaded image, only URLs LAIT supplied.
- **Price** comes from the page's "Regular Price" (`MainContent_lblPrice`), not the lower batch/group prices; the sync now sets it (**re-run Sync courses & batches** to fill existing courses).
- **Lessons:** (1) a pydantic field with `validation_alias` is silently ignored when the model is built by its plain field name — `_course_response` dropped both images on the detail page while the list (`model_validate`) worked; caught in the browser, now covered by a response-shape test. (2) The project's `forms.test.ts` regex matches a literal form-tag string even inside a comment.

## Google Calendar integration

Calendar API only (scopes: `calendar.app.created`, `calendar.acls`, `openid`, `email`; no Classroom/Meet/YouTube). One organisation Google account (`GOOGLE_EMAIL`), connected once by a Super Admin at Integrations -> Google Calendar (`google.update`); ADMIN has `google.read`/`google.sync`. Settings live in the **root `.env`** (`backend/.env` is not read): `GOOGLE_EMAIL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (must be registered on the OAuth client), plus `GOOGLE_INVITE_ATTENDEES`, `GOOGLE_SEND_UPDATES` (default `none`: guests get the event with no email), `GOOGLE_SHARE_WITH_ADMINS`, `GOOGLE_PULL_SESSION_TIMES`, `GOOGLE_SYNC_INTERVAL_SECONDS`. Worker: `python -m backend.cli.sync_google_calendar --once|--interval N|--dry-run`. Migration `c48d7a2e9b15`.

- **Shape:** one calendar per batch, one event per session; guests = the session's tutor + enrolled students + their guardians + their employers' managers; admins get writer access. Guests cannot see each other, edit, or invite; reminders are popups only; `tutor_notes` cannot reach Google (not an input to the builder).
- **Flow:** LMS -> Google is the rule (per-batch/session digests mean an unchanged run makes no writes). Google -> LMS: **session time edits only** (sanity-checked: end after start, <=24h, <=366 days shift; audited). Guest-list edits are *not* applied to enrolments (an enrolment carries fees/certificates/grades); drift is reported and put back. An event deleted in Google is recreated; cancel a class by deleting the session in the LMS. Pull happens before push, and a difference older than our last push is not a Google edit.
- **Credential:** the refresh token is AES-GCM encrypted with the master key, purpose-bound (`security/token_cipher.py`), never in any schema. The OAuth `state` is HMAC-signed and bound to the user; the connecting account must equal `GOOGLE_EMAIL`. `GoogleSettings.configuration_problem` turns a mis-pasted client ID (a real one was pasted as `http://<id>/`) into an instruction instead of Google's "invalid_client" page; a link-shaped paste is tidied.
- **Verified live against real Google** on a throwaway batch with no guests: preview writes nothing; create; times UTC-exact; privacy flags; idempotent re-run; LMS reschedule flows out; a time edit made in Google flows back and settles; a Google-deleted event is recreated; a session deleted in the LMS deletes its event; cleanup. **Not exercised live:** guest invitations and admin sharing (both would touch real people/accounts) -- covered only against the fake Google in `tests/integration/test_google_calendar_sync.py`.
- **Gotcha:** Google's calendar delete is eventually consistent (readable ~2s after a successful delete, then 404); do not assert "gone" immediately.

## Managing the schedule FROM Google Calendar (Google -> our database)

Migrations `d5a1c93f7e20`, `e6b2d84a1c39`. Every change below is written to **our database**, not just Google.

- **Who may edit:** Google cannot say who made an edit, so write access to the calendar IS the authorisation. SUPER_ADMIN is shared as `writer`; ADMIN as `reader` (`GOOGLE_ADMINS_CAN_EDIT=true` makes them writers). Tutors/students/guardians/managers are only *guests* on their own events (never given the calendar), so they see just their own sessions; guests can't see each other and the description never names anyone.
- **Add:** an event added to a batch calendar becomes a `batch_sessions` row (`origin='GOOGLE'`) after validation (end after start, 5 min-24 h, within 60 days of the batch, tutor not double-booked). Tutor = a guest holding the TUTOR role, else the batch's usual tutor. Location -> platform ("Zoom Video Conferencing", "Microsoft Teams"...) or, for any other text, `Classroom` + the text as `classroom`. The event is then rewritten to `Course (batch-code)` with "Session n of N" in the description. A refused event is left in place with `NOT ADDED TO THE LMS: <reason>` and a red colour, and is reconsidered only when it changes.
- **Move:** dragging/resizing updates the session time (sanity-checked, tutor-clash-checked, audited).
- **Delete:** deleting the event **deletes the session row**, unless it has attendance/recording/tutor notes, in which case it is kept as cancelled (`cancelled_at`, reason says why) so history is never destroyed. **A title starting `CANCEL`** always keeps the record as cancelled and removes the event from every calendar. Cancelled sessions are excluded from the schedule/timetable/feeds, don't block the tutor, refuse attendance, and no longer occupy their `(batch, start)` slot (partial unique index).
- **Enrolments are proposals, not edits.** A guest added/removed in Google creates a `google_change_requests` row (ENROL_ADD/ENROL_REMOVE) shown under Integrations -> Google Calendar -> "Changes from Google". Approve applies it through the ordinary `EnrollmentService` (capacity, batch open, notifications, webhooks, audit; a removal is `DROPPED`, never a delete); if those rules refuse, the request stays PENDING with the reason. Reject leaves the LMS as it is. Until decided the calendar is put back to what the LMS says; proposals that the LMS already satisfies close themselves (`SUPERSEDED`).
- **`batch_sessions.origin`:** `LAIT` (or NULL) sessions are derived data the LAIT sync may remove when a schedule shrinks; `MANUAL`/`GOOGLE` ones are decisions and are never deleted by it.
- **Bugs the tests/live run found:** (1) our own previous push looks like a "Google edit" once an enrolment changes in the LMS (it proposed removing the student just approved) -> a guest/time difference only counts if `event.updated` is newer than our last write; (2) my revoked-connection test marked the developer's REAL `google_connections` row `ERROR`, silently disconnecting the console -> a test-only token override never touches the stored connection (regression test added); (3) a unique index on `(batch, start)` blocked replacing a cancelled session.
- **Verified live against real Google** (throwaway batch, `example.com` guests, no emails): add, invalid-event refusal, move, CANCEL, delete, guest-add -> proposal -> approve -> enrolled in the DB and the calendar agrees; 16/16. Not exercised live: administrator sharing (reader/writer ACL), only against the fake.

## Class schedule calendar (Batches page)

`components/domain/batch-calendar.tsx` sits under the batch table, built on **FullCalendar 6** (core, daygrid, timegrid, list, multimonth, interaction, and the **luxon3** plugin -- named time zones need it, otherwise the display zone preference would be ignored). Pin `@fullcalendar/react` to 6.x: npm resolves 7.x, which does not match the 6.x core. It is drawn from **our own sessions**, not an embedded Google iframe: an iframe cannot add, move or delete anything in our database, and shows nothing to a guest not signed in to the right Google account. Google stays in step through the existing sync (a batch is pushed after every change; "Sync with Google" pulls Google-side edits).

- **Views:** Day, Week, Month, Year, Schedule; phones default to Schedule. Loaded via `GET /sessions/calendar?from&to&batch_id` (row-scoped like the session list; window <= 400 days, cap 3000 rows, `truncated` flag). Loaded with `next/dynamic` `ssr:false`.
- **Editing (admins only:** `session.create` + `.update` + `.delete`; tutors hold `session.update` for their own notes, deliberately not enough here): drag to move (15-minute snap), drag the bottom edge to resize, drag over empty time or click a day to add, click a class to edit/delete. A refused move (tutor clash) reverts and toasts the reason. Everyone else gets the same views read-only.
- **Details modal:** `GET /sessions/{id}/overview` (`SessionOverviewService`). The roster is the caller's `EnrollmentVisibility` (admin all, tutor their batch, student themselves, guardian their wards, corporate manager their employees); contacts, guardians, managers, tutor notes and the live head-count are limited to administrators and the batch's tutors. `batches.total_enrollments` is a cached counter that lags -- never display it where a count matters.
- Creating a session with only `duration_minutes` used to store no end time and crash the Google push. `SessionService.create` now derives the end and the sync coalesces a missing end for older rows.
- Date maths for the old hand-built grid lives in `lib/calendar.ts` (tested); only `batchHue` is still used.
- `package.json` asked for `eslint@^9.42.0`, which the registry does not have (eslint 10.10 was what was actually installed and working); it now says `^10.10.0` so `npm install` can resolve.
- **Only batches that have been synced exist in Google.** The calendar in the project always shows every session; Google only has the batches that were pushed. A full push creates one calendar per batch and adds tutors, students, guardians and managers as guests (no emails, `send_updates=none`, but the event appears on their Google calendar) -- do it deliberately.

## Display time zone (top bar)

`components/shell/timezone-menu.tsx` is a visible, searchable popover in the top bar (name + `GMT+6`; offset only on phones), preselected to the zone in force. Choosing a zone re-renders every time in the console at once, because everything reads `useDisplayTimeZone()`. Precedence is unchanged: a choice made in this browser (`lms.timezone`), then the account's `timezone`, then the browser's. Picking the profile's own zone clears the local override; "Save as my default" PATCHes `/auth/me` so it follows the account across devices. Search matches name, region and offset (`dhaka`, `asia`, `+6`), the full IANA list comes from `Intl.supportedValuesOf` merged with `/geo/timezones`, and the popup offers "Your browser is in X -- use that" when the browser and profile disagree.

**A time that "looks 4 hours wrong" is almost always the wrong zone being applied, not wrong data.** Batch 11285 is stored as 09:00 UTC = 15:00 in Dhaka; it displayed 11:00 because the *profile* said Europe/Paris and the profile outranks the browser. Check the top-bar zone before suspecting the data. (Browser automation note: the tool's key presses arrive with an empty `key`, so `Enter` handlers cannot be exercised that way; dispatch a `KeyboardEvent` instead.)

## Contact privacy, teams, sign-in location and internal mail

Four related changes made together. The thread running through them: **a person's email address, phone number and
login name are the Super Admin's to see and nobody else's, and every new surface was built to that rule from the start.**

### Contact details (`core/privacy.py`, permission `user.view_contact`)
Only a holder of `user.view_contact` (SUPER_ADMIN, by construction; ADMIN was explicitly removed) sees another person's
email, phone, mobile, emergency contact or **login name**; everyone sees their own. Being related changes nothing -- a
tutor does not get a student's email because the student is in their batch. **Login names are covered because 54 of 77 are
literally the email address**; hiding `email` while returning `username` would leak exactly what is protected. Wherever a
mapper used `x.username` it now uses `visible_username(x)` (the person's full name when the viewer may not see the login
name); `UserSummary`/`UserResponse` use per-field serializers (a model-level serializer collapses the OpenAPI schema).
`get_current_user` records the viewer in a ContextVar; **no viewer means deny**. Also covered: user search (names only unless
the viewer may see contact -- matching on email lets anyone confirm an address by typing it), audit actors and entity
labels, search hits, security lists, Google change requests, and the session details modal. `tutors_visible_to()` limits
the tutors shown on a course (a student sees their own tutors, a tutor only themselves).
**Known residue:** audit `details` JSON still records usernames as written at the time; an Administrator can read them.
To let Administrators see contact details again, grant `user.view_contact` to the ADMIN role.
`tests/integration/test_contact_privacy.py` drives the app over HTTP as six different roles and asserts no other person's
email or phone appears in any of nine endpoints; mutation-tested.

### My team (`/team`, permission `team.read`)
A corporate manager's employees, or a guardian's wards, with attendance, assignments (overdue flagged), scores/GPA, next
session, and a "needs a look" rule (attendance < 75% over >= 3 sessions, or anything overdue). Who appears is
`EnrollmentVisibility.cared_for_student_ids` minus the viewer -- nothing in the request names an organisation. An id outside
the set is a 404. **Making someone a manager** = (1) they hold `CORPORATE_MANAGER`, (2) `POST /organizations/{id}/managers`,
(3) each person `POST /organizations/{id}/members` (`activate_immediately`). Console: Organizations -> the organisation ->
Managers / Members. Done for the University of the West of Scotland | London Campus group.

### Sign-in location and time zone (`services/locale_service.py`, `integrations/ip_locale.py`, `LOCALE_*`)
At sign-in, and every 10 minutes / on tab focus while the console is open, the person's public IP is compared with the
one stored on the account (`users.locale_ip`); only a **different** address costs a lookup (icanhazip for the server's own
address when the caller's is private -- local development; ipapi.co for what an address implies). Results are cached in
process, failures back off, nothing ever raises into a sign-in. **A time zone the person chose is never overwritten**
(`timezone_is_auto`); one that was itself filled in from an address follows it. **This sends people's IP addresses to
ipapi.co**; `LOCALE_ENABLED=false` turns it off.

### Internal mail (`/messages`, `models/mail.py`, `services/mail_*.py`, `integrations/smtp.py`)
Replaces one-to-one `user_messages` (table dropped; it was empty). To/Cc/Bcc, drafts that autosave, threads, rich text,
attachments, star/read, per-person removal. **Who may write to whom** (`MailAudience`, from live enrolment data on every
send): administrators to anybody; a tutor to their students; a student to their tutors; a guardian/manager to the tutors of
their people; everyone to administrators. The directory returns **names and a role label only**. **Bcc is disclosed to the
sender alone.** Bodies are re-parsed by `nh3` and only formatting tags survive (`mail_html.py`) -- the stored HTML is what
every reader gets. Attachments: 10 files, 10 MB each, 25 MB total, programs/scripts refused, names made safe, served only as
downloads to the sender and the recipients. Email copies (`mail_delivery.py`) are sent **after** commit, one email per
recipient addressed to them alone, **no email address in any body or header, no Reply-To**; a Bcc'd person's email is
indistinguishable from the others'; the sender can ask for a copy. Off by default: set `MAIL_ENABLED=true` (plus
`MAIL_APP_URL` for the reply link) -- until then every recipient is recorded as SKIPPED and nothing is sent.
`MailSettings.from_email` is populated through its env alias `MAIL_FROM`, **not** its field name; a test that passes
`from_email=` is silently ignored and gets the real sender. Tests use a local SMTP sink and cannot reach a real server.
The compose/reader UI has typecheck, lint and API-level tests but **has not been driven in a browser signed in**.

## Batch workspace, session planner and attendance sheets

**Batch schedule.** `batches` carries the LAIT schedule (`training_days`, `training_start_day/end_day`, `training_start_time/end_time`, `class_duration_minutes`, `training_method`, `batch_fee`, `schedule_timezone`; migration `b3e8d17a5c46`). Batches synced before that need a LAIT re-sync, or the planner infers from existing sessions.

**Re-create sessions.** `services/session_planner.py` is pure (plans in the chosen zone, converts to UTC at the end; DST gaps warn). `SessionPlanService` backs `POST /sessions/plan` (preview) and `/sessions/replace`. A session with attendance, a started sheet, a recording or notes is **never** deleted by a re-create; other sessions are replaced only on confirmation; a tutor clash refuses the whole operation atomically. UI: `recreate-sessions-dialog.tsx`, opened from the Batches row menu and the workspace header.

**Attendance sheets** (migration `c4f9a26e8b57`). NOT_STARTED -> DRAFT -> FINALIZED; later edits are append-only events (`attendance_sheet_events`, UPDATE blocked by a trigger — a REVOKE means nothing against the owner role). Only the assigned tutor or a holder of `attendance.override` (Super Admin) may take/edit a register, and on-behalf submission is recorded. **ADMIN no longer takes a register without `attendance.override`.** Routes: `/attendance/queue`, `/attendance/sessions/{id}/sheet` (+ `/history`). Legacy `PUT /sessions/{id}/attendance` now goes through the sheet service.

**Frontend.** DataTable v2 (server sort/paging, toolbar, row actions, sticky header) is used by Batches; other tables can adopt it opt-in. The batch page is the operational workspace (schedule card, Overview / Sessions / Attendance / Enrollments, `?tab=`). Timetable and Enrollments remain as cross-batch views of the same data.

**Not driven in a browser** (sign-in is the user's to do) — verified by tsc, eslint, vitest, `next build` and backend tests only.

## Role testing pass — five accounts driven in a browser

Super Admin, two Tutors, a Student, a Guardian and a Corporate Manager were each signed in (by the user) and driven through their real surfaces. Isolation held everywhere it was probed; five defects were found and fixed.

**Fixed in this pass:**
1. `batch_response` never set `tutor_name`, so the batch workspace always showed Tutor "—" while the list showed it. Now derived from the batch's sessions.
2. `UserPicker` displayed a raw UUID for a value set from outside (a default tutor, an existing session). It now looks the name up.
3. `_resource_response` never mapped `batch_id`, so a batch-scoped resource always reported null and no client could filter by batch. **The identical omission had already been fixed for `ResourceFolder` and recurred on `Resource`** — the column existed, the schema field existed, only the mapper was missing.
4. **`message_received` notifications were never raised.** The type was in the catalogue and shown as a preference toggle defaulting to on, while `mail_service.py` dispatched nothing — no such row existed anywhere in the database. Now sent to every recipient including Bcc. `tests/integration/test_mail.py`'s teardown needed a `notifications` delete as a result.
5. **An enrollment oracle.** `EnrollmentService.enroll` ran the duplicate check *before* resolving the sponsoring organization, so a Corporate Manager probing an outside student got "already enrolled in this batch" — disclosing a student and a batch that `GET /users/{id}` and `GET /batches/{id}` both answer 404 to. Two distinguishable 409s made it enumerable. Ownership is now resolved immediately after loading the student, before the batch is read.

**Coursework scoping, fixed after the pass:** `AssignmentService.create` and `QuizService.create` loaded the
course through the deliberately-unscoped catalogue and never consulted `ScopeResolver.visible_course_ids`,
while `get`/`update`/`delete` all do. A tutor could set coursework on a colleague's course, notify that
course's students, and then get 404 for the row they had just made. Both now apply the same predicate as the
reads — *a write must not reach further than the read that would show its result*. It is a **403, not the
reads' 404**, because the catalogue is public by design so the course's existence is not a secret; what the
caller lacks is standing to teach it. `tests/integration/test_coursework_scoping.py` drives two real tutors
against live Postgres (a fake scope would assert nothing about the actor's relationship to the course) and
includes an unrestricted-admin case, since a check that ignored `is_unrestricted` would lock administrators
out everywhere. Mutation-tested: deleting either check fails exactly its own negative test.
`ExamService.create` has the same unscoped shape but is gated on `exam.create`, which only unrestricted
administrators hold, so it is latent rather than reachable — left alone rather than changed untested.

**Guardian notifications, added after the pass:** guardians received nothing, ever — not one notification row
existed for any guardian in the database, because every emitter addressed only the student. Three new types in
a new `guardian` category (`ward_submission_graded`, `ward_assignment_published`, `ward_enrolled_in_batch`)
are emitted alongside the student's own by `NotificationService.notify_guardians_of`.

Four decisions worth not re-litigating:
1. **Distinct `ward_*` codes, not the student's type sent to a guardian.** Every description in the catalogue
   is second person about its subject ("Your submission was graded"), so reusing them would tell a parent
   their own work was marked, and would leave both audiences sharing one opt-out switch.
2. **The copy names the child.** A parent of two told only that "a student in your care" was graded has to go
   and find out which, and a guardian of two children on one course would otherwise get two identical rows.
3. **Its own fan-out, not guardians appended to the roster.** A large course would otherwise push the combined
   audience past `MAX_FANOUT` and fail the assignment creation that triggered it.
4. **Separately opt-out per type**, because the volumes differ by an order of magnitude: a parent may want
   every grade and not every piece of homework.

Only the three types with **live emitters** were wired. `GRADE_RECORDED`, `EXAM_RESULT_PUBLISHED`,
`ENROLLMENT_STATUS_CHANGED`, `GUARDIAN_LINKED`, `ACCOUNT_LOCKED` and `PASSWORD_CHANGED` are declared in the
catalogue and emitted by nothing — the decorative-field pattern again, and a guardian type mirroring one would
inherit its silence. **There is still no attendance notification of any kind**, for students or guardians, so
"your child was absent" remains unbuilt rather than broken.

`tests/integration/test_guardian_notifications.py` covers the copy, the naming, the guardian's own opt-out and
the no-guardian case; mutation-tested by removing the fan-out and by dropping the `{student}` substitution.

**Care-circle messaging, added after the pass:** `MailAudience` routed a guardian or corporate manager only to
the *tutors* teaching the people in their care, never to those people themselves — so a manager whose employees
are not yet enrolled anywhere had an audience of administrators and nobody else, while being able to read those
employees' grades. `_care_circle` now adds, in **both** directions, a manager's employees and an employee's
managers, a guardian's wards and a ward's guardians.

Two decisions worth not re-litigating:
1. **Both directions, or Reply is refused on a message the platform just delivered.** The return leg is not a
   nicety; without it the button is dead.
2. **Computed in `mail_audience`, not taken from `ScopeResolver`.** That resolver answers whose *data* you may
   read, and an employee being allowed to reply to their manager must not turn into the employee reading that
   manager's enrolments. Writing to somebody is a smaller permission than reading about them, so it gets its
   own, smaller query. A `REMOVED` membership is out of reach in both directions, matching where data
   visibility already draws the line.

`tests/integration/test_care_circle_messaging.py` (6 tests) covers both directions, the former employee, the
guardian pair, the stranger still being refused, and the sender never being in their own audience.
Mutation-tested: removing the care circle fails 4, ignoring membership status fails the former-employee test.
Verified against live data — Lakshmi now reaches all 7 of her employees by name, they reach her, and neither
reaches an unrelated student.

**Found, not fixed — needs a product decision:**
- **A Corporate Manager sees zero batches** despite holding `enrollment.create` and `organization.enroll`, so
  the enrolment capability is unusable through the UI.
- Tutors hold only `exam.read`, so Examinations is read-only for them.

**Two behaviours that look like bugs and are not:** attendance "To do" means *takeable now* (not finalized and starting within the hour), so future classes correctly appear only under "All"; and Transcripts is gated on `grade.read`, not a transcript permission.

## Design system overhaul — enterprise visual layer

A three-phase rewrite of the visual foundation. The architecture was already
right (semantic tokens everywhere, no hard-coded hexes in components), so the
work was re-pointing the tokens and re-skinning the primitives; the DNA then
changed across every screen at once.

**Tokens (`globals.css`).** Slate neutral ramp — canvas `#f8fafc` / `#020617`,
surfaces stepping up to white / slate-900. Depth is a *surface step plus a
hairline*, never blur; shadows are tinted with the neutral's own hue, because a
pure-black shadow over a blue-grey surface is most of what reads as muddy. Dark
mode drops them almost entirely — on a near-black canvas a shadow does nothing.
Radii are deliberately tighter than stock (3/5/6/8/10/14px): a 12px radius on a
32px control is the friendly-consumer look. Type is **Inter** (UI) / **Inter
Tight** (headings, hero numerals) / **JetBrains Mono** (identifiers). Negative
tracking is baked into the scale so no call site has to remember it, and weight
is disciplined: 400 body, 500 interactive, 600 section titles, **750 only for
hero numerals** (`.numeral`).

**Primitives.** Hover shifts colour, never geometry — a button that grows
shoves its neighbours in a toolbar. Solid buttons carry a 1px inner top
highlight, which is the difference between a coloured rectangle and something
lit from above. Badges are tinted fill + inset ring; without the ring a pale
tone floats edgeless on white and reads as a rendering artefact. One focus
treatment everywhere: accent border + 3px halo, a ring rather than an offset
outline, because an outline on a 36px input collides with its neighbour in a
dense form. Skeletons sweep rather than pulse — half a screen pulsing reads as
an outage.

**Structure.** The rail sits on the canvas and the *selected* item is the only
thing on it rendered as a raised surface — a chip pulled out of the nav rather
than a coloured pill painted on it. Previously the sidebar was white against a
grey content area, which inverted the depth order. Top bar is real glass (72% +
blur, not 95% which is opaque with a decorative blur). Tables got glass sticky
headers, eyebrow column labels, and **row actions that reveal on hover or
keyboard focus** and stay put on touch. `SectionHeader` gives long pages a
hairline to scan along.

### Three defects found by building on top of it

1. **The console had never rendered in its intended typeface.** `@theme inline`
   substitutes a token's value into the utilities that use it and deliberately
   does *not* emit the custom property, so `body { font-family: var(--font-sans) }`
   was invalid at computed-value time and fell back to Preflight's system stack.
   Geist was downloaded on every page load and never applied. No error anywhere
   — found by reading computed styles, not by looking at the page. Fixed by
   moving the font variables to `<html>` and referencing the real stacks.
2. **`Stat` rendered strings in the hero-numeral slot.** "Asia/Dhaka" at 28px /
   750 with tracking tuned for digits. `isFigure` now steps text values down.
3. **A column of identical row buttons.** Courses rendered a "View details"
   button on every row; the row itself was not clickable and there was no
   keyboard path. The row now opens the course and the contextual menu carries
   the same action for keyboard and touch.

**Swept globally:** 133 bare `border-border` / `divide-border` across 53 files
converted to the 60% hairline.

**Verified:** `tsc` clean, `eslint` 0 errors, `next build` 36 pages, **93/93**
frontend tests, and light + dark driven in a browser with computed styles
checked rather than eyeballed.

**Known gap:** clickable table rows are a mouse convenience only — no
`tabIndex` is added, deliberately, to avoid 25 tab stops per page. Every such
row carries its actions in the keyboard-reachable menu instead.

### Visual sweep — every screen walked

Five defects the page-by-page pass found, all fixed:

1. **A vertical scrollbar on every tab strip in the console.** `overflow-x-auto`
   sets only one axis, and CSS computes the other to `auto`; the selected tab's
   `-mb-px` then made the content one pixel taller than the box. The result was
   arrow glyphs at the right of every tab row and 15px of stolen width. Fixed
   with an explicit `overflow-y-hidden`.
2. **Twenty tables fell back to a line of grey text when empty.** The designed
   `EmptyState` is now `DataTable`'s default rather than an opt-in, so no screen
   can look unfinished by omission. `EmptyState`'s `title` widened to `ReactNode`
   to carry a table's existing message.
3. **The access-denied screen looked like a page that failed to load** — an
   unframed message floating at the top of a blank canvas. On a console with
   narrow roles that is a large share of the navigation, so it is now a centred
   card with a way back to the dashboard.
4. **Two internal engineering notes were rendered to end users**, one naming an
   endpoint and citing `docs/BACKEND-GAPS.md` on the timetable, one describing a
   missing API on the resource share panel. Rewritten from the reader's side.
5. **The method string was shortened in the table and not on the batch page**, so
   one batch read `Online · Zoom` in the list and `Online Training using ...`
   truncated on its own screen. `lib/format/batch.ts` now holds `shortMethod` and
   `durationLabel` for both, and the schedule card demotes the timezone to a
   second line instead of truncating the name mid-word.

**Scope of the sweep, stated honestly:** driven as a Tutor, so the admin screens
(academic, audit, ops, organizations, permissions, reports, roles, security,
guardians, integrations) showed the denied state rather than their own content —
that state was verified, their layouts were not. The login screen was not checked,
as reaching it means ending the signed-in session.

### Admin-screen sweep (Super Admin)

The eleven screens a Tutor could not reach. Four more defects, two of them
console-wide:

1. **No tab in the console had a selected state.** `TabsTab` styled on
   `data-[selected]`, but Base UI marks the active tab with `data-active` — there
   is no `data-selected` attribute, so the selector matched nothing and every tab
   strip rendered a transparent underline at weight 500. Verified from computed
   style, not by eye. Now keyed on **`aria-selected`**, the accessibility contract
   rather than an implementation detail, so a library rename cannot silently
   break it again. *(Pre-existing — the committed version had the same selector.)*
2. **`Switch` collapsed to a 16px mark wherever it was not already a flex child.**
   Base UI's switch root computes to `display: inline`, and width/height do not
   apply to a non-replaced inline box, so `h-5 w-9` were ignored. It looked
   correct on the notification preferences (a flex row blockifies its children)
   and rendered as a stray vertical bar in the Guardians table. Fixed with an
   explicit `inline-flex`. *(Pre-existing.)*
3. **Four warning banners were invisible in light mode** — white text on a pale
   amber tint. This one **was mine**: the token rewrite redefined
   `--warning-foreground` as white, which is right for ink on a *solid* warning
   fill and wrong on `bg-warning/10`. All four now use `text-warning`, legible on
   the tint in both themes.
4. **The reports bar chart rendered three slabs the width of the panel**, on
   dashed gridlines. Constrained with `maxBarSize` and `barCategoryGap`, grid
   changed to a solid hairline, axes moved to the metadata tone. A magnitude
   chart is read along the tops of the bars; their width carries no information.

**One self-inflicted regression, caught and fixed in the same pass:** a `//`
comment placed in JSX child position rendered as literal text on the reports
page. `tsc` passes on it — it is valid JSX text — so only looking at the page
caught it.

**Two things that looked like defects and were not**, both confirmed rather than
assumed: the Timetable's Starts/Ends columns (I misread a downscaled screenshot;
the DOM shows `16:00 → 18:00` matching the API), and tab clicks appearing not to
register (a programmatic click switches correctly — the synthetic mouse click was
a tooling artifact of the emulated viewport).

## Files, part 1 — the permission ladder that was never read

Items 2 and 3 of the files/media brief. The audit that preceded it is the useful
part: **most of the data model already existed and was well designed** —
`resource_folders` (self-referential tree), `resources` + `resource_versions`,
`resource_permissions` with scope `COURSE→BATCH→SESSION→USER`, `shared_resources`,
and a storage abstraction with local + R2 including presigned URLs. Folder CRUD,
move, rename, copy, soft-delete/restore/purge, grant/revoke and share were all
already built.

**What was missing was enforcement.** `ResourcePermissionLevel` —
`VIEW / DOWNLOAD / EDIT / MANAGE` — was written by `grant_permission` and read by
*nothing*. Access was a single reachability boolean, so:

* a student granted **VIEW could call `/download` and receive the bytes**;
* a tutor holding `resource.delete` globally could delete a file that had been
  shared with them read-only, because the global permission and reachability were
  the only things consulted.

Same decorative-field shape as `token_budget_per_month`, `provider_credentials`,
`message_received` and `resources.batch_id` before it.

**`backend/core/resource_access.py`** is the missing half: the levels are a
*ladder*, not a set (MANAGE ⊃ EDIT ⊃ DOWNLOAD ⊃ VIEW), kept pure so the ordering
is unit-testable without a database and every call site asks in the same words.

**`ResourceService.effective_level()`** resolves three routes, most capable wins:
1. unrestricted → MANAGE;
2. **owning the space** — a file in a course/batch the caller administers takes
   its level from their *global* resource permissions (`resource.delete` → MANAGE,
   `resource.update` → EDIT, else VIEW), so a tutor manages their own materials
   without a grant per file;
3. **an explicit grant or share** on that one file — and this is the fix: foreign
   content is governed *only* by what was granted, so global `resource.delete` no
   longer overrides a read-only share.

Enforced at **8 doors**: download (DOWNLOAD), update/upload-version (EDIT),
soft-delete/restore/purge/share/share-link (MANAGE).

**`shared_resources` gained a `level`** (migration `d8b1f4e07a23`). It had no way
to say *how* a file was shared, so a recipient's rights came entirely from their
role. Existing rows backfill to **DOWNLOAD, not VIEW** — that is what they
effectively had, and silently tightening access on files people already hold
would break working links. Tightening is the owner's decision, per share.

**Preview (`GET /resources/{id}/preview`)** needs only VIEW, which is the whole
point of the level existing — a file can be read without being kept. Two
deliberate decisions:
* **Never redirected to a presigned URL, even on R2.** A presigned URL *is* a
  download link; issuing one here would hand the viewer exactly what the level
  was withholding. The bytes always stream through the server.
* **A type allowlist, and `image/svg+xml` and `text/html` are not on it.** An SVG
  is a document that can carry script; served inline it executes in this origin
  and steals the session. They remain downloadable, just not rendered. Backed by
  `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff` and
  `Content-Disposition: inline` — the allowlist is the first line, the headers the
  second, because one list edited carelessly should not become stored XSS.

`my_level` and `can_preview` ride on `ResourceResponse` so the console can hide
actions it would be refused. The list endpoint deliberately does **not** carry
them: resolving a level per row is a query per row.

**Mutation-tested:** removing the download guard fails the viewer test; letting
the role baseline apply to foreign files fails the no-access test. 12 unit + 7
integration tests.

**Not done in this pass, and stated rather than implied:** the Drive-like folder
navigation UI (breadcrumbs, move, grid view) and the preview *viewer* component —
the backend is ready for both. Live HTTP verification was not possible: restarting
the backend ended the browser session and signing in is the user's to do.

### Files, part 2 — the viewer and the Drive verbs

`components/domain/resources/file-preview.tsx` renders a file in place from
`/preview` (VIEW) rather than `/download` (DOWNLOAD) — the two endpoints existing
separately is the whole point, and this is what makes a read-only audience able to
*read*.

Four render paths, chosen by the server's `can_preview` and `mime_type`: PDF in an
iframe (the browser's own viewer is itself sandboxed), images, `<video>`/`<audio>`
with `controlsList="nodownload"`, and **text fetched and printed into a `<pre>`**.
That last one is deliberate: an `<iframe>` would ask the browser to *interpret* the
bytes, and the one thing a file must never do is decide how it is rendered.
Printing it as React text means a file full of markup shows its markup — which is
also the plain-text view the brief asked for. Text is capped at 200k characters,
because nobody reads past the first screen of a preview and a multi-megabyte log
pasted into the DOM freezes the tab.

`controlsList="nodownload"` is a courtesy, not a control — the network tab is still
right there. That is the honest limit of protecting playback without DRM, and it is
the same ceiling items 5 and 6 will hit.

**Actions now follow the per-file level, not the role.**
`permissions.has("resource.update")` asks whether the role may edit resources *in
general*, which is how a tutor was offered Delete on a file merely shared with
them. The dialog derives `canDownload` / `canEdit` / `canManage` from the server's
`my_level` and hides what would 403; a viewer sees "View only — you cannot download
this file" instead of a button that fails. The **list** deliberately keeps the role
gate: a row carries no `my_level`, because resolving one per row is a query per row.

**One inconsistency the lint error exposed:** `canManage` was unused, which
surfaced that `grant_permission` was gated only on the route's global
`resource.update` while `share` already required MANAGE. Handing someone access to
a file is at least as consequential as sharing it, so it now requires MANAGE too.

**Move uses Drive's own model** — pick the file, walk to the destination, confirm —
because `/folders` lists children of one parent and a tree picker would need a new
endpoint. Rename is a field in the detail dialog. Both ride the existing
`PATCH /resources/{id}`.

**Verified live as Super Admin**, not only by test: a text file and a PNG uploaded,
previewed and byte-checked (`<b>not bold</b>` renders as literal text, unicode
intact, PNG magic bytes correct, `inline` + `nosniff` + `sandbox` headers present);
a file moved root → folder and renamed, both 200; every test artefact purged after.

**A hostile SVG is refused at upload**, before it ever reaches the preview layer —
the storage MIME allowlist rejects `image/svg+xml` with a 422. The preview
allowlist is the second line, not the only one.

**Still not built:** drag-and-drop move, folder rename/delete UI, a grid view, and
Office-document rendering (no browser renders `.docx` natively — it needs either
server-side conversion or an external viewer, and that is a decision, not an
oversight).

## Live class join and protected recording playback

Items 4 and 5 of the six-subsystem brief. The organising finding, and the reason
this was not a frontend task: **the meeting link and the recording link were in
every session payload, to every role.** A Join button greyed out until thirty
minutes before start enforces nothing while the URL it would open is sitting in
the network response, and "authorised users should not be given a direct
external recording link" was false by construction.

**New:** `backend/core/live_class.py`, `backend/api/streaming.py`,
`session.override` in the permission catalogue, `open_range`/`size` on the
storage port and both adapters, migration `e5c71a4d9b02` adding
`batch_sessions.recording_resource_id`, five routes, and two frontend components
(`join-class-button.tsx`, `class-recording.tsx`).

**The link is withheld in five payloads, not hidden in one page.**
`SessionResponse`, `SessionSummary`, `SessionOverview` and `CalendarSession` now
populate `meeting_link`/`recording_link` only for callers holding
`session.update` — the people who *set* them — and everyone else receives
`join_opens_at` / `join_closes_at` / `can_join_now` / `has_recording` instead.
`SessionBrief`, the dashboard's row, lost `meeting_link` outright: it is drawn
for students, and there was nothing for it to be used for that the join endpoint
does not do better.

**Seven decisions worth not re-litigating:**

1. **`join` is a POST, not a GET.** Handing out a meeting link is an act that is
   recorded, not a property of the session. A GET invites a prefetch or a cache
   to perform it on the caller's behalf, and the audit row would then describe
   something nobody did.
2. **`join_state()` and `join()` are the same rule, twice.** One renders the
   button, one opens the door. Two implementations drift, and the drift is
   always visible to the user as a button that refuses or a hidden one that
   would have worked.
3. **A window with no end still closes.** Two hours, because a class with no
   recorded length must stop being joinable at some point, and an end recorded
   *before* its start is bad data rather than licence to leave the room open
   forever.
4. **"No meeting link yet" is a 409, not a 403.** The caller is entitled to
   join; the tutor has not recorded a link. Reporting that as a permission
   failure sends a student to an administrator about a scheduling omission.
5. **A recording is an ordinary `resources` row.** It inherits the permission
   ladder, versioning and soft-delete built in the previous pass rather than
   growing a parallel set, and `ON DELETE SET NULL` means deleting the file does
   not delete the record that the class happened.
6. **Publishing a recording needs EDIT on the file, not sight of it.**
   Attaching makes it playable by a whole batch, so the bar is "this is yours to
   publish" — otherwise a tutor could expose any document they had been sent.
7. **The playback audit is per playback, not per byte range.** A player issues a
   request per seek; a viewer scrubbing through an hour would otherwise write
   dozens of identical rows. The *permission check* still runs on every one of
   those requests.

**Range support is the difference between a video and a download.** A player
that asks for bytes forty minutes in and is handed the whole file with a 200
restarts from zero on every scrub. `stream_for_playback` answers 206 with a
correct `Content-Range`, understands `bytes=-N` (how an MP4's trailing index is
read before playback can start at all), answers 416 **with the real length** so
a player can correct itself, and caps one answer at 8 MiB so `bytes=0-` on a
two-hour recording cannot pin a worker to one viewer.

**Two things the design deliberately does not claim.** This is not DRM —
anything a browser renders can be captured, and `controlsList="nodownload"` only
hides the player's own save button. What it buys is that the obvious routes
(copy the link, share the URL, open it signed out) all lead back through the
permission check rather than around it. And the *external* provider URL is still
a URL: it is withheld from everyone who cannot edit the session, which is the
most that can be done about a link Zoom minted.

**A performance defect I introduced and removed before it shipped:** the first
version gave `BatchSession` a `recording` relationship with `lazy="selectin"`.
`Resource` eager-loads six relationships of its own, so a 3000-row calendar
window would have pulled all of them per session to answer a question almost no
caller asks. The relationship is gone; `recording()` loads the row by id.
Separately, `join_state` is called per row, so the actor's flattened permissions
are resolved once per service instance rather than re-walked per session.

**Mutation-tested, seven guards, each failing exactly the matching test and
passing on restore:** moving the window to 45 minutes, deleting the
negative-window guard, removing the window gate from `join()`, making everyone
count as staff, dropping the soft-delete filter on the recording, returning
`external_url` to everyone, and dropping the EDIT requirement on publishing.

**`session.override` must be seeded.** Re-run the identity bootstrap after
upgrading, or the override silently does not exist:
`bootstrap_identity` reported `permissions_created: 1, roles_regranted: 2` here.

**Driven live against a running server, not only through fakes.** 34 checks over
a real socket -- `scripts/_live_check_drive.py`, fed by `_live_check_setup.py`,
which builds and destroys its own `livechk` accounts so nothing borrows a real
one. Proven: a student's session payload carries no link while `can_join_now` is
true; a class six hours away is a 409 naming both times; an outsider is 404 and
never 403; `session.override` opens a shut door and the ticket says so while the
same account's in-window join does not; a seek returns 206 with
`bytes 100-199/4096` and **byte-exact** content. The audit trail then showed
`outside_window: true` on exactly one row, and one `RECORDING_VIEW` per playback
rather than one per Range request.

Two things that check found which nothing else would have:
- **The server on :8000 was serving stale code** -- its OpenAPI had none of the
  three new paths. A dev API here has no `--reload`, so "the tests pass" and
  "the running system does this" are different claims; restart with
  `python -m backend.main`, which is also the only entrypoint that sets the
  Windows selector event-loop policy before uvicorn creates a loop.
- **`users.can_login` defaults to false**, so a seeded account cannot sign in
  whatever its password. Correct, and the reason is in the column comment, but
  it means any fixture that logs in over HTTP must opt itself in.

**Not verified through the browser.** The Chrome extension was not connected for
this session, and signing in as the operator is not something to work around, so
the console side is proven by `tsc --noEmit`, `eslint` (0 errors) and
`npm run build` only. Clicking the Join button and scrubbing the player in a
real browser is the obvious next check and is deliberately not claimed as done.

**Status:** full backend suite green (~808 tests, exit 0), plus 49 new ones --
11 for the window, 16 for `Range` parsing, 17 join/recording integration against
live Postgres, 5 end-to-end streaming. `npm run build` compiles 25 routes.

## Realtime messaging, notifications and Web Push

Item 1 of the six-subsystem brief. Before this, an unread badge was a 60-second
poll and an open messages screen never refreshed at all; `redis` had been a
declared dependency since the start and was imported by nothing.

**New:** `backend/core/events.py`, `backend/realtime/bus.py`,
`backend/api/v1/realtime.py` (SSE), `backend/services/push_service.py`,
`backend/api/v1/push.py`, `backend/models/push.py` + migration `f2a8d3b61c94`,
`backend/cli/generate_vapid_keys.py`, `RealtimeSettings` and `PushSettings`,
plus `frontend/src/lib/realtime.ts`, `frontend/src/lib/push.ts` and
`frontend/public/sw.js`.

**Three rules shape the whole layer, and each is the answer to a way it could
go wrong:**

1. **An event is a hint, never a payload.** It says "your unread count
   changed", not what the message says. `core/privacy.py` decides per *reader*
   whether a name or an email address is visible, and an event is composed once
   by whoever performed the write -- so a payload assembled there would be
   assembled for the wrong viewer and would sail straight past the masking. The
   browser is told something changed and re-reads it through the ordinary
   endpoint, where the rule still applies. Proven live: the `message.received`
   frame carries `data: {}`.
2. **Nothing is published until the transaction commits.** A notification is
   staged inside the caller's transaction on purpose, so a tray cannot announce
   a grade whose insert rolled back -- and a chime that beat the commit would
   reintroduce that bug in the form people actually notice. Events are queued on
   the session and promoted by SQLAlchemy's own `after_commit`; `after_rollback`
   and `after_soft_rollback` discard them.
3. **An event is addressed to one user, and the channel is derived from the
   authenticated id.** There is no parameter anywhere that selects a channel,
   which is the only reason a subscription needs no authorization check of its
   own.

**Six decisions worth not re-litigating:**

1. **SSE, not WebSocket.** The traffic is one-directional. A WebSocket adds a
   second protocol, a second auth path and a second thing for a proxy to get
   wrong, in exchange for an upstream channel nothing needs. SSE is an ordinary
   GET, so it inherits the console's BFF proxy and its cookie auth unchanged.
2. **The SSE route authenticates by hand instead of using `CurrentUser`.**
   FastAPI closes a `yield` dependency *after* the response body ends -- which
   for a stream is half an hour later -- so `DBSession` would pin one pooled
   connection per open tab. A handful of tabs would starve every other request
   in the process. The caller is resolved in a session this route opens and
   closes itself, and the stream then holds no database connection at all.
3. **`Subscription.next_event(timeout)` rather than an async iterator.**
   `asyncio.wait_for` around a generator's `__anext__` **finalises the
   generator** on timeout, so an iterator-shaped API would end every connection
   on its first idle heartbeat -- which is every connection, almost always.
4. **`memory` is refused in a deployed environment.** With several workers an
   in-memory fan-out reaches only the browsers connected to the worker that did
   the write, so delivery appears to work and fails for most users,
   intermittently, with nothing in the logs. `build_bus` raises rather than
   leaving that as an inherited default. **The Redis adapter is written but has
   not been run against a real Redis** -- none is available on this machine --
   and that is stated rather than implied.
5. **A message raises two events, and a notification preference silences only
   one.** Switching off the *notification* for messages must not make the
   **inbox badge** stale; those are different questions and tying them together
   would make "don't notify me" quietly mean "show me a wrong number".
6. **Push is sent unconditionally and the service worker decides whether to
   show it.** Server-side presence is wrong often enough to matter -- a tab open
   in a background window holds a live stream and is read by nobody -- and
   across workers it would need a Redis key with a TTL whose every edge is a
   notification somebody never gets. `clients.matchAll()` can see whether a
   window is open **and focused**, which is the actual question, and only the
   browser can answer it.

**A push payload carries a title and nothing else.** It lands on a device that
may be unlocked on a desk, and it is composed at write time -- before the reader,
and therefore the privacy rules that apply to them, are known. Verified live:
neither the message subject nor the sender's name appears anywhere in the
encrypted body.

**Web Push was proven without a browser**, by standing up a real HTTP server
that plays the part of Mozilla's or Google's push endpoint and pointing a real
subscription row at it. That makes the send a real network call through
`pywebpush` with real P-256 key material, which is the only way to learn whether
the key format `generate_vapid_keys` produces is one the library accepts. A
mocked `webpush()` would only assert that I called my own wrapper.
`tests/integration/test_web_push.py` asserts the VAPID `Authorization` header,
`Content-Encoding: aes128gcm`, that the plaintext title is absent from the body,
that a **410 deletes the subscription** and that a **503 does not** -- the second
being what stops "forgotten" passing because every failure deletes.

### Two defects found by running it rather than reading it

1. **`generate_vapid_keys` printed environment variable names that do not
   work.** It emitted `PUSH__VAPID_PUBLIC_KEY`; this project's settings use a
   *single* underscore (`APP_NAME`, `STORAGE_MODE`, so `PUSH_VAPID_PUBLIC_KEY`).
   Pasting its output into `.env` would leave `configured` false and push
   silently off -- exactly the failure the `enabled: false` field on
   `GET /push/key` exists to prevent, reintroduced by the tool that sets it up.
   Found because the live check reported `enabled: False` after I exported the
   names the generator told me to. `REALTIME__*` in the bus's refusal messages
   was wrong the same way and is fixed.
2. **The key format was verified against `py_vapid`, not assumed.** Before
   wiring it in, the generated private key was loaded with `Vapid01.from_string`
   and the derived public key compared byte-for-byte with the printed one (65
   bytes, uncompressed point). A format that merely looks right is how a
   "working" push config fails on its first real send.

A third thing, caught by the React Compiler lint rather than at runtime:
`usePushSubscription` set state synchronously inside an effect, which triggers
cascading renders. Fixing it properly (detect-then-set, with the effect owning
every write) also added the cancellation it was missing, so navigating away
mid-check can no longer set state on an unmounted component.

### Verified

**Live, over a real socket** (`scripts/_live_check_realtime.py`,
`_live_check_push.py`): a stream opens and announces itself; a sent message
arrives as an event in **0.46s** direct and **0.31s through the console's BFF
proxy** -- the number that proves the proxy is not buffering, which is the exact
layer that once destroyed binary uploads by reading bodies as text; another
user's stream stays silent while the addressee's fires; no token and a bad token
are both 401. With VAPID configured, `POST /messages` put a **VAPID-signed,
aes128gcm-encrypted push on the wire in 1.3s while the sender waited 0.36s**,
and unsubscribing removed the device.

**Mutation-tested, six guards:** publishing before the commit (3 tests fail),
dropping the badge invalidation on a remote read, inventing a sender name in the
message toast, treating any push failure as a dead device, and an unscoped
`unregister` -- each fails exactly the matching test and passes when restored.

**Status:** full backend suite green -- **824 tests**, exit 0 -- including 16 new ones (8 after-commit and bus, 8 Web Push), plus 10 new frontend tests for the hook. `npm run build`,
`tsc --noEmit`, `eslint src` (0 errors) and `vitest` (103 tests) all pass.

**Not verified through a browser.** The Chrome extension is not connected in
this session and signing in is not something to work around, so the permission
prompt, the service worker's focus check and the toast are proven by unit tests
and by the protocol-level live checks, not by clicking. **The Redis bus and a
real vendor push endpoint (Google/Mozilla) are likewise unexercised** -- both
need infrastructure this machine does not have.

## Staff-only media — the last item of the six-subsystem brief

Video and audio that colleagues can share without it reaching students,
guardians or corporate managers. **The audit changed what needed building:**
the obvious reading is "add a sharing feature", but this module already had
three ways to reach a file and a fourth that bypasses authentication
altogether. What was missing was an *audience* rule, and a working level on the
share that already existed.

**New:** `resource.view_restricted` in the permission catalogue,
`resources.is_restricted` (migration `a93e17c0d5b8`), and a `level` on the
share request. **Re-run `bootstrap_identity` after upgrading** -- the permission
is in the catalogue but not in any deployment's `role_permissions` until the
seeder runs, and until then the switch does nothing for anybody.

**A permission, not a role check.** `permissions.py` already argues this for
`institution.view_all`: an institution will eventually want a registrar or an
external examiner who may see restricted media and little else, and
`if role in (ADMIN, TUTOR)` scattered through the service layer cannot express
that without a code change. Granted to SUPER_ADMIN, ADMIN and TUTOR; withheld
from exactly the three roles the brief names.

**The flag lives on the resource and is not inherited from a folder.** A file
dragged out of a "Staff only" folder would otherwise become visible to a class
as a silent side effect of tidying up.

**Four doors, and a guard on `get()` alone would have left three open:**

1. **Opening it** -- refused *before* reachability is even computed, so a
   restricted file is refused to a student **even when it was shared with them
   directly**. A restriction a share could override would protect nothing, and
   sharing is exactly how this material travels between staff. 404, never 403.
2. **The listing** -- filtered in the SQL rather than after it, so the paging
   total cannot reveal that there are files here the reader is not allowed to
   name.
3. **Sharing** -- allowed to colleagues, refused to anyone who could not have
   seen the file anyway. A share row that `get()` then refuses reads to the
   recipient as the system losing a file.
4. **The public share link** -- refused at issue time *and* checked again at
   redemption, and restricting a file clears any token it already had. A link
   that needs no sign-in cannot respect an audience rule: anyone holding the
   string is outside every check this platform makes.

**`shared_resources.level` was decorative and is now reachable.** The column
shipped with its own migration and `effective_level` read it, but `share()`
never *set* it -- so every share silently took the server default of DOWNLOAD
and "watch it, don't keep it" could not be expressed at all, which is the whole
of what the brief asks for. The API now takes a level, defaulting to **VIEW**:
the narrower of the two, so a share that forgets to say grants the less.
Re-sharing updates an existing row rather than skipping it, or "share this
read-only" would silently do nothing to someone who already had DOWNLOAD.

**`/resources/{id}/preview` gained Range support** for video and audio, reusing
the player written for class recordings. Without it a browser asking for the
bytes forty minutes into a shared recording is handed the whole file with a 200
and restarts the download on every scrub.

### The test that passed for the wrong reason, found by mutation

Five guards were mutated one at a time. Four killed tests. **Removing the
`resolve_share_link` restriction check killed nothing** -- because `update()`
clears the token when a file is restricted, so the token lookup fails first and
the audience check is never reached. The guard is a real second line of defence
(a migration, a backfill or a future code path could set the flag without
clearing the token) but it was untested, and a green suite said otherwise.
`test_a_token_that_outlived_the_restriction_still_opens_nothing` sets the flag
on the row directly so the token survives; deleting the guard now fails it.

**A second fixture defect, the same shape.** The first draft gave the guardian
and the corporate manager no link to the student, so they could not reach *any*
file on that course -- every refusal would have passed with the audience rule
deleted entirely. They now hold a real `student_guardians` row and a real
organisation membership, so the refusals are about the rule rather than about
being unconnected.

### Verified

**25 live checks over HTTP** (`scripts/_live_check_restricted.py`): a student
opens a file and sees it listed, a public link works unauthenticated; the tutor
marks it staff-only; the student then gets **404 and not 403**, the row vanishes
from their listing and stays in the tutor's flagged, sharing it to them is
**422**, the old public link is **404** and a new one is **422**; the tutor
streams it with `Accept-Ranges: bytes` and a `Range` request returns **206 with
exactly 40 bytes**, while the student's stream is **404**; unmarking restores
all of it.

**19 integration tests** against real Postgres and the real seeded roles, plus
the five mutations above.

**Status:** full backend suite green, `npm run build`, `tsc --noEmit`,
`eslint src` (0 errors) and `vitest` (103 tests) all pass.

**Not verified through a browser**, for the same reason as the two passes
before it: the Chrome extension is not connected in this session. The staff-only
switch, the badge and the share-level picker are proven by typecheck, lint,
build and the HTTP checks behind them, not by clicking.

### Shown in a real browser, at last

The three previous passes could only be proven at the protocol level, because
the Chrome extension was not connected. This one was driven in the built-in
browser pane while signed in as Super Admin, and four things are now confirmed
by clicking rather than by `curl`:

* **The timetable payload carries no `meeting_link` field at all** -- only
  `join_opens_at`, `join_closes_at`, `can_join_now`, `has_recording`. A 10:00
  session reports `join_opens_at` of 09:30, so the thirty-minute rule is visible
  in the response rather than asserted in a docstring.
* **The Join button renders disabled with a live countdown** ("Opens in 86
  days"), and the session page shows the recording panel with its
  publish-from-library control.
* **The Staff only switch works end to end** -- toggling it persists,
  renders the explanation, and **greys out the Public link switch beside it**;
  toggling it back restores both.
* **The SSE stream connects through the BFF proxy in a real browser** and
  delivers its `ready` frame. That was the one claim the earlier protocol-level
  checks could not make.

Two things the browser found that nothing else had:

1. **The share-level picker was clipped.** `w-40` cut "Watch / read only" to
   "Watch / read o...", and a control whose label is truncated is one nobody can
   be sure of. Now auto-width.
2. **`channels_note` had become false.** It told every reader that "push is
   modelled but has no transport" -- true when it was written, and untrue since
   Web Push shipped. Rewritten. A note that asserts a property which has stopped
   holding is worse than no note, because it stops the next person checking.

One false alarm, recorded because the reasoning matters: the Staff only switch
appeared to go stale after a toggle. It had not -- the reading was taken while
the invalidation was still in flight. A reload showed server and UI agreeing.


## Selection and table systems — built, then actually wired in

A Staff-Frontend-Architect brief asked for an enterprise selection system
(Select / multi / Combobox / async Combobox; `DropdownMenu` for **actions
only**) and a TanStack-backed table with ~25 **opt-in** capabilities. The
first pass built all of it and migrated 81 selectors. The user's review was
blunt and correct: *"go to any table like /users, Can I resize the column???
check any of the dropdown/select, for example country, can I search or
filter, check the city? ... you haven't done anything I asked you"*.

They were right, and the system/application gap was the whole problem — the
components existed, the screens barely used them, and **two capabilities did
not work at all**.

### Column resizing was a prop that did nothing

The handle rendered, `header.getResizeHandler()` fired, TanStack's state
updated — and no column ever changed width. Under the default
`table-layout: auto` a `width` on a `<th>` is a *suggestion* the browser is
free to discard, and it did: every column sat at its content width while the
inline style said `150px`.

The fix is two parts, and **the first attempt at the second part was wrong in
a way that was worse than the bug**:

1. **`table-layout: fixed`, adopted at the start of a drag.** Switching every
   table to `fixed` unconditionally would throw away the content-based widths
   that make these tables readable. So on `mousedown` the table measures its
   own rendered columns, hands those widths to TanStack and switches to
   `fixed`. Because the widths adopted are the ones already on screen, the
   hand-over is invisible. `flushSync`, deliberately: the very next statement
   is TanStack's own handler, which reads the column's current width to anchor
   the drag, and under normal batching it would still see the default.
2. **The table is sized to its columns, not its container.** Left at
   `width: 100%`, `fixed` layout shares any difference between the column
   total and the table width across every column — so a 150px drag moved the
   edge **519px** and shrank its neighbours. A drag that does not track the
   pointer is worse than one that does nothing, because the person can see it
   responding and still cannot land a width.

Seeding on hover was tried first and abandoned: a pointer already resting on
the header when the table mounts never fires an enter event, so the first drag
after a reload silently did nothing.

**`getTotalSize()` is the wrong number here.** This component does its own
column filtering rather than handing visibility state to TanStack, so the
instance still counts a hidden column at its default width — the table
rendered exactly 150px wider than its contents the moment one column was
hidden. Summed over the visible columns instead.

### Column visibility shipped and no screen used it

It existed as a controlled `{hidden, onChange}` prop, which meant state, a
`ColumnToggle[]` and a toolbar in every page — identical boilerplate 25 times,
so it was written nowhere. `columnsKey="users"` now does all of it, and 17 list
pages name one.

`useTableView` reads the stored choice through **`useSyncExternalStore`**, not
state seeded in an effect: `localStorage` does not exist during the server
render, and the effect version both renders twice and is what the React
Compiler rules reject. `getSnapshot` must return a stable reference, so the
parse is cached against the raw string it came from.

### Batch and course pickers: `limit: 200` into an unsearchable list

Twenty call sites built their own option list that way — unreadable at 200
rows, and silently missing the 201st. `BatchPicker` / `CoursePicker`
(`components/domain/entity-pickers.tsx`) search server-side and absorb the
API's inconsistent parameter names (`/batches?q=` vs `/courses?query=`) so no
screen has to know about it. They also carry the `batch.read` / `course.read`
check each page used to make for itself — folding the gate into the control
keeps it in one place instead of nine, and means a new caller cannot forget it
and add a request that 403s.

### Three combobox defects the browser found and nothing else could

1. **The selection was rendered as the `placeholder`**, in muted
   "nothing-selected" styling — a form with five answered fields looked like a
   form with five empty ones. It is now the input's real value, with the typed
   term taking over only while it is being typed, derived from events rather
   than synced in an effect.
2. **The field fell back to the raw value** once a search returned a page not
   containing the selection — a live profile showed
   `bc94d2ff-a158-4ca3-...` where "London" belonged. Controlling `inputValue`
   was not enough: Base UI *also* derives display text through
   `itemToStringLabel`, which saw only `options`. The selected option is now
   part of the list the control resolves against.
3. **Leaving a field never reset the caller's search**, so the list stayed
   filtered by a term nobody could see, and the next read could not find its
   own value in it.

Also: gender rendered as `MALE`. `optionsFromValues` has existed for exactly
this since the system was built.

### A test that could not fail, and one that could

jsdom has no layout engine, so **the resizing tests passed throughout the
period when resizing did not work** — they asserted the handle existed. The
replacement stubs `getBoundingClientRect` and pins the two things that made
widths take effect: `fixed` layout, and a width in pixels rather than `100%`.
Mutation-tested 4/4, including reintroducing the original bug.

A second trap cost an hour: four new menu tests failed in the suite and passed
in isolation, which looked exactly like cross-test pollution. It was not —
Base UI's menu popup mounts a tick after the click, so `getByRole` is simply
too early and `findByRole` is required. Pointer-event shims were added to the
test setup on that false diagnosis, then **removed after a mutation showed
they changed nothing**.

### Still not built, from the brief

Enabled nowhere, though built: row selection + bulk actions, expandable rows,
column pinning. Deliberate — checkboxes with no bulk action behind them are
the decorative-capability problem again.

Not built at all: global search, per-column filtering, faceted/date/range
filters, column ordering UI, grouping/aggregation, export, density toggle UI,
URL/query-state sync, virtualisation.

**Keyboard column resizing is a real gap.** The handle is `aria-hidden` and
pointer-only, because a labelled handle inside the `<th>` made every header
read "Role Resize Role" to a screen reader.

**There is still no frontend test runner for the BFF proxy**, so its fixes
are guarded by live proof only.

## Academic assessment brief, phases 13–14 — notifications, calendar, reports

Phases 1–12 of the §42 sequence were already built (assessment scoping, the
performance engine, grade book, grading schemes, transcripts, the §37
drill-down, dashboards with a guardian/corporate panel). These two phases
closed what was left, and most of the work was finding what was decorative.

### Six notification types nobody had ever sent

Counting emitters per type found six codes listed on the preferences screen
-- so a person is offered a switch and told they can turn it off -- that
nothing in the system emitted: `exam_result_published`, `grade_recorded`,
`guardian_linked`, `enrollment_status_changed`, and the two **mandatory**
security warnings `account_locked` and `password_changed`.

The catalogue's own docstring says the mandatory pair exist "so a person
notices a compromise" and cannot be switched off. An account locked by
repeated failed sign-ins, or a password changed by whoever now holds the
account, told its owner nothing. Only the *admin-initiated* security events
were wired. `quiz_service` and `exam_service` contained zero notification
calls of any kind.

Decisions worth keeping:

* **Publishing notifies on the transition only.** Re-saving must not
  re-announce, and retraction announces nothing -- "your exam is scheduled"
  arriving as it is cancelled serves nobody.
* **Exam results go to students who have a result row**, not the eligible
  roster. An absent student with no row has nothing to read.
* **Grade-book notifications fire for manual entries only.** Every synced
  entry already has an emitter at its source, so announcing it here too
  notifies one student twice for one mark, from two services that do not know
  about each other. §23's single-source-of-truth rule applied to
  notifications.
* **The lockout warning runs in its own transaction**, because the sign-in
  path raises immediately afterwards and that rollback would discard the
  warning -- docs' rollback pitfall, in the shape where the record of an
  attack disappears because the attack was refused. It can never fail the
  request.

`tests/unit/test_every_notification_type_is_emitted.py` makes it
unrepeatable. It parses the backend with `ast` rather than grepping, so a
mention in a docstring cannot satisfy it, and carries a meta-test because the
first version of a guard like this will happily scan the wrong directory and
pronounce every type healthy.

### The calendar carried no deadlines

`/calendar/{token}.ics` served sessions only, so a student saw their classes
and none of the work those classes set. Published assignment deadlines, quiz
windows and exam sittings now merge into it.

**The feed is a capability URL** -- calendar clients cannot send an
`Authorization` header, so the token is in the link and anyone holding the
link is the audience. That makes scoping the whole change, and it is why the
existing session query deliberately avoids `ScopeResolver`: "everything this
user may see" would put other cohorts into a forwardable link.

The first version piped descriptions, instructions and online joining links
into it. None of that belongs in a link that can be forwarded -- exam
instructions are content and a joining link is a way in -- so it carries a
title, a time, and a physical venue. `CalendarFeed`'s docstring claimed it
"exposes only session times and titles", which had stopped being true the
moment this landed, so it was rewritten rather than left to mislead.

### §35's statistics, and a denominator that was never real

The performance report returned an average and nothing else, while the
console described it as "scores and pass rates". It now carries lowest,
median and highest.

**The average and the spread deliberately disagree.** The average stays
mark-weighted (`SUM(score) / SUM(max_score)`) because a 1-mark quiz and a
100-mark exam are not equal halves of anyone's performance; the spread is
taken across students, each reduced to their own weighted percentage, because
"lowest" and "median" are questions about people. An average of 68% over a
cohort whose median is 81% is a cohort with a few students in serious
trouble, which a single mean hides completely.

The new coursework report (`GET /v1/reports/coursework`) covers three of
§34's reports -- submission, missing work, grading status -- as three
readings of one grouped query. **Its denominator is the point:** a submission
rate computed over `assignment_submissions` is 100% by construction, because
the student who handed in nothing has no row to count, and it looks entirely
plausible on screen. The population comes from the eligibility rule instead.
Drafts are excluded (work set for nobody cannot be missing), and a rate over
an empty population is `null`, never `0`.

### One scope rule, not three

`covers_batch` now sits beside `eligible_student_ids_stmt` in
`assessment_scope.py`, used by both the coursework report and the calendar
feed. The feed had its own copy, written two commits earlier in the same
session -- the exact shape that cost this codebase a closed cohort on a live
mark sheet when the exam service's private copy of the join lost
`Batch.is_active`.

### Two things the tests only found by being made harsher

* A `DISTINCT ON` deduplicating submissions by `attempt_number` was **dead
  code**: `uq_assignment_submissions_assignment_student` means a replacement
  updates the row in place. Found by writing the fixture that would exercise
  it and watching Postgres reject it.
* Mutation testing had survivors twice, both because a fixture was too kind
  -- an exam with no `instructions` made "no free text reaches the feed" pass
  whatever the code did, and a single-batch cohort could not tell the scope
  rule from a naive "same course" join. 8/8 and 7/7 after the fixtures were
  fixed.

**Not done:** §39 course completion and §40 certificate eligibility. Nothing
computes either -- `Enrollments.can_download_certificate` is a plain boolean
with no rule behind it and `Certificate.criteria` is an unread JSON column.
They are the next instance of the same pattern.


## Quiz settings that do nothing, grade-book entries nobody triggered, and a grid that took 55 seconds

Three pieces of one brief, and all three were the same shape: a field stored
and never read, or read wrongly, with nothing failing.

### §47's first arrow, for the other two marking paths

"Tutor publishes result -> result automatically enters Gradebook" was true of
quizzes only. `AssignmentService.grade` and `ExamService.record_results` now
go through the same `GradeBookService.record_component`, so the grade book no
longer disagrees with the marks it derives from until somebody presses Sync.

Decisions worth keeping:

* **The hook writes the row the sweep would have written.** Out of the
  assignment's own `max_score` and the exam's own `total_marks` -- matching
  `_sync_assignments` and `_sync_exams` -- so running `sync_batch` afterwards
  reports them *unchanged* rather than rewriting every row.
* **Exam marks enter at recording, not at publication**, which reads
  backwards against §47's wording and is the only choice that keeps the two
  writers in agreement: `_sync_exams` writes every result that has a mark,
  published or not. Withholding here would mean the next sweep introduced
  rows this path declined to write.
* **Fail-open, loudly.** A derived row that cannot be written must not undo a
  mark a tutor has given. `sync_batch` is the reconciler.
* The assignment hook has **no `grade is None` guard**: `grade()` assigns it
  from a required payload field immediately above the call, so one would be
  unreachable. The exam hook does have one, and needs it --
  `record_results` rewrites the whole mark sheet, so saving one student's
  mark hands every other candidate's row to the hook, including candidates
  nobody has marked.

Two defects in my own first attempt, both caught by reading the file rather
than the tests: the call had landed in `submit()` instead of `grade()`, and
the insertion had stolen `_late_penalty`'s `@staticmethod` decorator, leaving
a method that would have failed on its first call.

Mutation-tested 7/7, including the one that matters: an unmarked candidate
stays out of the grade book **and produces no error in the log**. Without
that second assertion the guard looked load-bearing when it was not --
`Decimal(str(None))` raises and the fail-open handler swallows it, so no
wrong row appears either way, and an operator would be chasing a marking
failure for every unmarked student on every save.

### Five quiz settings that were switches wired to nothing

`questions_per_attempt`, `auto_submit_on_expiry`, `show_result_immediately`,
`show_correct_answers` and `show_explanations` were written at creation and
read by no code. The console offered switches for them. **A switch that does
nothing is worse than an absent one** -- somebody sets it and believes the
paper is a random draw, or that marks are withheld until they release them.

Three of them could not have been implemented as the schema stood, which is
presumably why they were not. Migration `f17c4a9b0e23` adds what they were
missing:

* `quizzes.results_released_at` -- `show_result_immediately` had no opposite.
  Marking and releasing are separate acts for assignments
  (`SubmissionState.PUBLISHED`) and exams (`exam_results.is_published`);
  quizzes had no equivalent, so "immediately" meant nothing.
* `questions.explanation` -- `show_explanations` had nothing to show.
* `quiz_attempts.auto_submitted` -- nowhere to record that the clock closed
  an attempt. Deliberately **not** `submitted_late`, which is the opposite
  case: the timer was advisory and the student submitted by hand afterwards.
  Both exist, and a tutor needs to tell them apart.
* `question_options.match_text`, for the new question types below.

**`_paper_for` is now the single definition of what one sitting was served**,
and it has to be: the same list decides what the student is shown, what their
submission may answer, and what their percentage is out of. Three separate
seeds, all from the attempt's own id and never the clock -- `p:` draws the
sample, `q:` orders the questions, `a:...:<question>` orders each question's
options. The draw is seeded separately from the display so that toggling
`shuffle_questions` on an unsat quiz does not change *which* questions are
drawn.

**The defect that made `questions_per_attempt` unusable rather than merely
inert:** submission graded every question in the bank. A student answering
all four of their four drawn questions correctly scored four marks out of
ten. `_recompute_score` now takes its denominator from the answer rows --
one per question the sitting was served -- rather than from a question list
the caller passes, which both callers were filling with the whole bank.

**`auto_submit_on_expiry` enforces the clock, and closes abandoned sittings.**
On: nothing is accepted after `duration_minutes` plus the existing grace, and
an expired attempt is closed at its cutoff (not at the moment somebody
noticed) with whatever the server holds -- which is nothing, because no answer
is stored until submit. Harsh, and the honest outcome of a paper that never
arrived; it also fixes a real trap, because an attempt whose timer ran out
while the tab was shut stayed "in progress" for ever, refusing the student
every further attempt they were entitled to and leaving the tutor waiting for
a result that could not arrive. Off: the limit is advisory, a late submission
is still marked and flagged, and an abandoned attempt is left alone because it
is still theirs to submit. The honest limitation is that answers are not saved
as they are chosen; that is the fix worth building next.

**Closing is done in `start_attempt`, never in the same transaction as a
refusal.** Recording the closure and then raising would roll the closure back
-- the rollback pitfall this codebase keeps meeting. For the student who has
used every attempt and so never calls `start_attempt` again, there is
`POST /quizzes/{id}/close-expired-attempts`, because there is no scheduler
here and somebody has to be able to ask.

`results_visible_to` gates the mark, the pass flag, every per-question score
**and** the answer key together: a total hidden while the per-question marks
are listed beside it is not hidden. It withholds from the student *and their
guardian*, since releasing to one and not the other is a leak in one
direction and a bug in the other, and it asks `quiz.grade` as a permission
rather than checking a role -- a Guardian holds `grade.read`.

### Four question types, and three answer keys that were being handed out

Fill in the blank, matching, ordering and numeric (§9). Their keys live where
they fit: `settings` for fill-in-the-blank and numeric (the shapes differ per
type, so a column each would be null for every other question), `order` for
ordering, and the new `match_text` for matching -- one row per pair, so a
half-deleted pair cannot exist.

Marking rules worth keeping: text comparison collapses whitespace and folds
case unless the question says the case matters, because **marking "  paris "
wrong is what makes automatic text marking untrustworthy**; a missing numeric
tolerance means exact, never infinite; words typed into a numeric box are
**wrong, not unmarkable**, since `None` means "a human must mark this" and
would hold the whole attempt's score up waiting for a tutor with nothing to
do; and matching and ordering are all-or-nothing, like MCQ_MULTIPLE, because
partial credit needs a rule nobody has specified.

**Three leaks, found by writing the tests rather than by the types:**

1. `question_options.order` **is** the answer to an ordering question, and it
   was sent to the student with every option. The student now gets their
   position in the list they were served, which also makes re-sorting by it
   harmless rather than a way to undo the shuffle.
2. The right-hand column of a matching question was being served beside the
   prompt it belongs to. It is now sorted by its own text, so its order
   cannot encode the pairing -- and ordering and matching options are always
   scrambled regardless of `shuffle_answers`, because for them the authored
   order is the key.
3. `questions.settings` was served verbatim, which was harmless while it held
   a code question's language and became the whole answer key once it held
   `accepted` and `answer`. The student's copy is now built by removing the
   keyed fields rather than by trusting every future writer of that column.

One rule set for answer keys (`answer_key_problem` in `schemas/quiz.py`),
raised as a pydantic `ValueError` on create and as the API's
`ValidationError` on edit. The rules had been written out twice and the
copies had already drifted: the service's understood options only, so editing
a numeric question's answer to something unparseable went straight in.

### The console

A **Settings tab** on the quiz page shows and edits every setting, with the
release control and the close-expired button. Deliberately not more fields on
the create dialog: these are decisions a tutor revisits. Save is not disabled
once a quiz has attempts, because the response does not say whether it has
any and guessing would either block a tutor who could still edit or promise
one who cannot -- the server's 409 is the gate and it explains itself.

The question editor grows an answer-key form per type (accepted answers one
per line, numeric answer and tolerance, orderable items, pairs) and an
explanation field. Taking a quiz grows two widgets, extracted to
`components/domain/quiz-answers.tsx` with their own vitest -- the frontend
half of two contracts no type error can catch: an ordering answer that loses
its order submits a set, and the server marks a set against a sequence as
wrong for everybody; and a matching widget that read each prompt's own
`match_text` would offer a list of one and show the student the answer.

A student's finished attempt now says *why* a mark is missing when the quiz
withholds it, and shows the key and the explanation once released. The
attempts table distinguishes **Timed out** from **Late**.

### The grade-book grid: 10,267 queries in 55 seconds, for eight students

Profiled rather than guessed at, and the causes were three layers deep:

1. **`User` eager-loaded seventeen collections**, including `audit_logs` --
   every row that person had ever generated. A `User` is loaded on every
   authenticated request to resolve permissions, and again for every row of
   anything that references one. Five of them had already been changed to
   `lazy="raise"` for exactly this reason; the rest now are too. **None of
   the seventeen is read as an attribute anywhere** in the backend, the tests
   or the scripts -- checked before changing, not assumed. `roles` stays
   eager, because permission resolution reads it on every request.
2. **`_assignment_marks`, `_quiz_marks` and `_exam_marks` selected ORM
   entities when they read five scalar columns.** `Exam` eager-loads its
   course, batch, invigilators and *every result*, and each result its
   student; that one query cost 1,070 queries and 5 seconds. They select
   columns now, and the quiz's question total comes from a correlated
   subquery instead of a follow-up query per quiz per student.
3. **`_evaluate` loaded the whole `Batch` entity for one integer**, pulling
   in its tutor reviews and their students.

**55s -> 0.3s, 10,267 -> 89 queries.** Guarded by a query *count*, not a
clock: latency on one laptop is not an assertion, and the count is exactly
what regressed -- by a factor of a hundred, with every correctness test
passing.

**And a wrong mark, found while reading that code.** `Mark.percentage` is
`earned / possible`, and `_quiz_marks` passed a percentage as `earned` with
the quiz's raw question total as `possible`. An 80% attempt on a 12-point
quiz contributed **666.67%** to the quiz component, and with any quiz in a
scheme the whole overall mark was wrong -- on a figure students appeal
against and transcripts print. Measured, not inferred: reverting the fix
reproduces 666.67 exactly. Nothing caught it because the engine's tests build
marks by hand and the service's tests had no quiz in them at all.

### Mutation testing, and two survivors worth more than the kills

25 mutations applied across the quiz settings, the question types and the
performance work; 24 caught. The two instructive moments:

* **A survivor that was right about the test, not the code.** Making every
  `User` collection eager again failed nothing, because after the
  column-select fix the grid loads no `User` entity at all. The model change
  protects every *other* authenticated request, so the answer was a second
  guard measuring what one user load costs (23 queries before, 5 after) --
  not reverting a fix that no longer had a witness.
* **A fixture too kind, for the third time in this codebase.** Restoring the
  entity select in `_exam_marks` also survived, because the cost fixture had
  no exams in it. With an exam and an assignment per student it fails at 247
  queries.

A third: `test_two_students_draw_different_questions` failed twice during
mutation runs against correct code -- two students drawing the same four
questions from ten is a 1-in-210 coincidence, which is often enough. The bank
is twenty now. And the pool quiz must set `shuffle_questions=False`
explicitly, because `bool_column()` defaults to **true**: with the display
shuffle on, the test passed against an implementation that drew the front of
the bank every time.

### The browser pass, which found two things no test had

Driven as a tutor and then as an enrolled student, against a second API and a
second console on their own ports so the user's running servers were never
touched. Both throwaway accounts and everything they made were deleted
afterwards, and the deletion was verified by counting rows.

What it proved: every setting saved from the Settings tab and came back from
the database; releasing and withholding worked from the button; a drawn paper
really was four of five questions; all four new types were authored through
the dialog and marked correctly on submission (100%, including a numeric
answer typed as `3,14`); and with results withheld the student's own list
showed `—` while staff saw 100.00.

What it found, both only visible from a student's seat:

1. **The ordering answer was on the page before the attempt started.**
   `questions_for_attempt` returns the authored order when nobody is sitting
   the quiz, which is right for an author previewing and hands a student the
   exact sequence they are about to be asked for. Ordering and matching are
   now scrambled in that view too, seeded by the question rather than the
   attempt -- every student sees the same scrambled order, which is fine,
   because what has to stay hidden is the *authored* one.
2. **The question list printed "France = Lima"** to students -- the right-hand
   column detached and alphabetised, rendered beside the prompts by the
   author's renderer. It read as an answer key that was not one. Students now
   get the prompts and a separate "Match these:" line.

Also from the pass: the answer-key list showed a tutor nothing for four of
the five types -- ordering had no positions, matching no pairs, and
fill-in-the-blank and numeric keep their key in `settings`, which the list
never read. All four are rendered now, on the screen whose entire job is the
answer key.

One thing the comma rule is worth stating: a numeric answer typed `3,14` is
3.14, not 314. A single comma followed by one or two digits, in a string with
no dot, is a decimal separator; every other comma is grouping and is removed.
Much of the world writes the first, and stripping it silently would mark a
correct answer wrong.

### Not done, and said so rather than left to be discovered

* **Answers are not saved as they are chosen**, so an auto-submitted attempt
  scores zero. It is the right next piece of work and the honest cost of the
  timer being enforceable at all.
* The create-quiz dialog still exposes two of the settings; the rest are
  edited on the Settings tab after creation. The API accepts them all at
  creation.
* A tutor marking an attempt sees the per-question answer key only when the
  quiz is set to show it to students, because one mapper serves both
  audiences and `results_visible` cannot tell them apart. The answer-key
  route is the tutor's way to it, and it is the route built for that.
* `_sync_assignments` and `_sync_quizzes` ignore an assessment's own batch
  scope -- they match on course only -- so for a student in two cohorts of
  one course the sweep writes a batch-scoped mark into both, while the
  automatic hook writes it into one. The hook's narrower behaviour is
  deliberate and tested; the sweep's is pre-existing and left alone, because
  changing it moves existing grade-book rows.


## Corporate managers are linked to students, not to a company's payroll

A manager's roster used to be derived: manager -> `organization_managers` ->
`organization_memberships` -> every employee of that company. Visibility was
a side effect of the org chart, so a company with four managers and two
hundred employees gave each of those managers all two hundred, and "these
thirty are yours" could not be said at all.

`manager_students` (migration `b2f9d4c7a1e8`) is the same shape as
`student_guardians`, and for the same reasons: many managers per student,
many students per manager, its own history, and a direct relationship between
two people rather than a view over a third thing. It is now the **only** rule
-- `ScopeResolver._managed_student_ids` reads it, and everything
student-scoped reads `ScopeResolver`.

**The company stays, and keeps everything that was actually about
employment**: who works where, their employee code and department, which
company a manager works for, and `enrollments.organization_id` -- the record
of who sponsored a past enrolment, which is the one fact here that could not
be reconstructed if it were dropped.

The module docstring on `models/organization.py` used to argue *against* a
direct link, on the grounds that `corporate_manager_id` on Student is a
one-column answer to a many-row question. That argument was right about a
**column** and says nothing about a join table; it has been rewritten rather
than left to contradict the schema beneath it.

### The backfill is the half that matters

Every (active manager, visible member) pair in the same organization became a
row, so the day this ships every manager sees exactly the students they saw
yesterday. Without it every corporate manager opens the console to an empty
roster. Administrators then narrow the rosters deliberately, which is the
point of the change. Verified on the dev database: the one active manager's
seven employees became seven links.

### Two accesses that used to end by themselves

This is the regression a change like this leaves behind, and it took the two
longest comments in the diff.

* **Leaving the company.** Visibility was read from the membership row, so
  `REMOVED` simply stopped resolving. Nothing would notice now -- a former
  employee would stay on their old manager's dashboard, with their current
  coursework, indefinitely. `set_member_status` deletes that student's links
  to *that company's* managers, and records how many went in the audit entry.
* **Revoking the appointment.** `is_active` was read on every resolution.
  `revoke_manager` now deletes that manager's links to that company's
  members.

Both are scoped to the company in question: a manager who also looks after
somebody elsewhere keeps that, because it was never justified by this
employment.

### Adding an employee links the person who added them, and nobody else

`organization.invite` is a manager's power, and before the change adding an
employee made them visible at once -- same row. Dropping that entirely would
leave a manager inviting somebody they then cannot see until an administrator
intervenes, which is a dead end in a workflow the permission exists to
support. So the inviting manager is linked, and only them; a colleague
managing the same company still sees nothing. An administrator adding a
member links nobody, because they are not the person who will be looking
after them.

### Everything downstream followed from one definition

Reports, dashboards, My Team, enrollments, attendance, submissions, quiz
attempts, exam results, the grade book, performance and transcripts all read
`ScopeResolver` and needed no change. The ones that had their own copy of the
join did:

* **Enrolment sponsorship** asked one question that was really two. *May this
  manager enrol this student?* is now the roster; *who is paying?* is the
  student's own employment. A managed student with no company on file is
  enrolled **unsponsored** rather than refused -- that combination could not
  happen before and is ordinary now.
* **Mail audience** went out through the company and back, which let two
  strangers at a large employer write to each other because a manager sat
  between them. It is now the same direct-link-read-both-ways pair that
  guardians already used.
* **The session roster** and **Google Calendar guest list** listed every
  manager of the sponsoring company. A guest list is outward-facing: that put
  managers on an invitation for a class none of their own people were in.
* **My Team** showed a manager a blank relationship, because only
  guardianship was asked about -- their connection was a column on a
  different table.

### Where the decision is pinned, and why not in an API test

Mutating `permissions.py` to let a manager create their own links **failed
nothing**: the running app resolves permissions from `role_permissions` rows,
so an API test proves what the database happens to be seeded with, not what
the catalogue says. `tests/unit/test_care_relationship_grants.py` asserts the
catalogue directly, for both relationships at once -- a guardian and a
manager may read their own links and may not write them, an administrator may
do both, and a student holds neither side. That one does fail when mutated.

**Mutation-tested, 6 of 6:** the derived roster restored (8 tests fail),
removal not unlinking, revocation not unlinking, the inviting manager not
linked, the invite linking every manager of the company, and the calendar
guest list resolved through the sponsoring company again.

That last one **survived its first run**, for the fourth time in this
codebase: the calendar fixture had one manager who was both an active
manager of the sponsoring company *and* linked to the student, so the old
query and the new one returned the same person. A second manager of the same
company, linked to nobody, is what tells them apart. A fixture that cannot
distinguish the two implementations is not a test of either.

### Driven in a browser

Against the running API on `:8000` with a build served on `:3001` -- the
`next dev` server on `:3000` was wedged (sign-in produced no network request
at all, HMR failing), which is the stale-compile failure already recorded
above; its own process was left alone rather than restarted.

Carla Gordon's seven backfilled links render on **Manager assignments**, with
filters, the first-contact switch and unassign. A link created through the
console reached `ScopeResolver` -- she went from seven people to eight,
checked against the resolver itself rather than a screen -- and unassigning
restored her roster to exactly the seven it started with.

**Residue cleaned afterwards.** The first runs of the new integration test
aborted their cleanup on `audit_logs`, which is append-only at the database
level, so the whole cleanup transaction rolled back and left 84 users and 22
links behind. That is the right behaviour from the database and a bug in the
test's teardown, which no longer tries to delete audit rows: an audit record
outlives the account it describes, which is why `actor_user_id` carries no
foreign key.

### Status

**1,098 tests, all green** (`pytest tests`, exit 0), with the quiz and
performance work from the previous pass included. Frontend: `tsc`, `eslint`,
`npm run build` and 164 vitest tests clean. Migration head
`b2f9d4c7a1e8`.

**Re-run `backend.bootstrap.seeders.identity.seed_identity` after pulling** --
four new permissions (`managed_student.*`) and three regranted roles. The
`backend.cli.seed` CLI does the same thing but prompts for a super-admin
password and resets it, so for a permissions-only refresh call the seeder
directly.

### Not changed, deliberately

* `visible_organization_ids` still answers "which companies may this person
  administer" from `organization_managers`. That is employment, not
  visibility of people.
* One company per person at a time, both for managers and for employees. The
  partial unique indexes are about employment and still hold; they no longer
  decide who reads whom.
* `enrollments.organization_id` keeps its historical meaning and is still
  derived server-side, never accepted from a request body.


## A class recorded on Zoom was published to nobody

A tutor pastes the Zoom cloud link into a session and the class is, as far as
they can tell, published: `has_recording` comes back true and the link is on
their screen. Every student, guardian and corporate manager entitled to that
class saw **"No recording yet"**.

Both halves were deliberate once. `recording_link` was returned only to
callers who may edit the session, because it is a URL that works outside the
LMS, signed out, for anyone holding it. The student-facing route was
`playback_url`, a file in the library streamed by us. Nothing joined them, so
the only recording a student could watch was one nobody had ever published:
across the whole database, 2 sessions carried a link and **0** carried a
stored file.

### The viewer gets a path of ours, not the provider's URL

`GET /sessions/{id}/recording` now also returns `embed_url`, which the session
page frames. It is a path on this API that re-checks permission on every
request and then redirects (307) to the player. So the provider's URL is in
neither the response nor the page's DOM, the only route to it is one that
checks each time that this caller still has the class, and a student removed
from the batch loses the recording rather than keeping a working link.

The audience is whoever `SessionService.get` already admits -- the enrolled,
their guardians, their corporate manager, the tutor, administrators -- so it
needed no audience of its own. `external_url`, the link in the clear, still
goes only to staff: they set it and need to check what they entered.

A **stored** recording wins outright and suppresses the frame. We serve those
bytes ourselves, ranged and re-checked, so offering the provider's player
beside it would only be a weaker route to the same class.

### What the embed can and cannot promise

It is a redirect and not a proxy because **there are no bytes for us to
serve**. Measured, not assumed: the share link resolves to Zoom's own player,
whose `<video>` src is a signed CloudFront URL, and that URL returns **403**
to our server even with the right `Referer` -- it is bound to Zoom's session
cookies. Importing the file would need Zoom's API and credentials this
deployment does not hold.

So the player on the other side is the provider's, including whatever download
control they offer; Zoom's page has one. Said plainly in the route and in the
component rather than implied, because it bounds the promise: **a recording
that must not be downloadable at all belongs in the library**, where
`playback_url` serves it under our rules with `nodownload` and no link that
survives leaving the batch. The indirection still buys the thing that was
missing -- copy the URL, share it, open it signed out, and every route leads
back through the permission check.

### Two smaller corrections that came with it

* **`has_recording` meant "staff can see a link"**, so a student's timetable
  told them a recorded class had no recording. It now means "this caller has
  something to watch", on the session and on the summary row both.
* **Watching was audited only for a stored file.** A class watched through the
  provider left no record that anyone had watched it. Still written once per
  playback, not once per seek.

### On all screen sizes, and in full screen

The frame sits in a 16:9 box (`aspect-video`) with `allowFullScreen` and
`allow="fullscreen; ..."`: a bare iframe has no intrinsic size and collapses
on a phone, and without the attribute the player inside cannot ask for the
screen. The stored-file player moved from `max-h-[70vh]` to
`max-h-[80svh]` -- `svh` is the viewport a mobile browser actually leaves
after its own chrome.

### Pinned where it can fail

`tests/integration/test_recording_access.py` (14) drives `SessionService` and
the real route: all four kinds of entitled viewer parametrised, because each
reaches the session by a different rule and the recording must not be the one
thing that forgets three of them; both kinds of outsider refused with 404
rather than an empty recording; stored beating the frame; the 307 with its
`Location`, `no-store` and `no-referrer`. `class-recording.test.tsx` (5)
pins the browser half, including that a viewer who was not handed the provider
URL cannot read it out of the page.

**Mutation-tested, 8 of 8:** the embed withheld from non-staff as the link
was, the frame offered beside a stored recording, the provider URL handed to
every viewer, the redirect trusting the page that led there, the audit written
only for stored files, `has_recording` back to staff-only, and both response
headers dropped. The first frontend attempt **survived** -- the leak assertion
only ran on a payload with no provider URL in it, so framing
`external_url ?? embed_url` changed nothing it looked at. The staff case now
asserts the frame is still ours, which fails it. Fifth "fixture too kind" in
this codebase.


## Sharing a file is a decision about people, not a user-id field

Three things were true at once: `resource.update` let a tutor share any file
they managed with **any user id on the platform**, the picker showed one person
at a time, and both the picker and the resulting list printed `username` --
which in this deployment is the person's email address.

### The audience is the server's answer, not a filtered directory

`backend/services/resource_audience.py` answers "who may *this* caller share
with", once, for both directions:

* **`search`** draws the picker. `GET /resources/share-audience`.
* **`resolve`** is the gate every write goes through, and refuses the whole
  request if one recipient is outside the audience.

The rule: an administrator reaches everybody; a tutor reaches the
administrators, the students in the batches they teach, and those students'
guardians. Nobody else -- including a **corporate manager who employs one of
those students**. They may read that employee's grades, so "can see them" and
"may be sent their class material" are different questions, and this is where
they part.

Drawing the list from `/users` and narrowing it in the browser would have put
the rule where it is a suggestion. The old code did the opposite of that and
got away with it for the same reason: the picker only ever offered sensible
people, so nobody noticed the body was unchecked.

### The batch and the course are not decoration

Two students called Sarah is the ordinary case, and the consequence of picking
the wrong one is a file reaching a class that should not have it. So each row
carries the cohort -- and for a tutor it is **their own** cohort, not every one
the student is in: surfacing a colleague's batch would both disclose a class
the tutor has nothing to do with and bury the line that identifies the student
here. A guardian's own name says nothing about which class they are connected
to, so their row reads "Guardian of Jane Doe" with that student's batch.

### No address, by construction

`ShareCandidateResponse` has no field that could carry one, and the directory
matches on first and last name only -- matching the login name would make the
box an address checker. Two further leaks were closed on the way:

* `_share_response` used `visible_username`, which hands the login name to any
  viewer holding `user.view_contact`. Correct for a staff directory; wrong for
  "who has this file", which is read dozens of times a day.
* `display_name` does **not** fall back to `username`, which every other
  directory in this codebase does. An account with no name recorded shows as
  "Unnamed account" -- visibly a data problem an administrator can fix, rather
  than an address nobody notices.

The audit entry records recipients by `public_id` for the same reason: a share
must not copy an address into a second table.

### Several files, several people, one act

`POST /resources/share` takes both lists and is **all or nothing**: every file
is authorised and every recipient resolved before the first row is written. A
partial share is the worst outcome available -- the sharer is told it failed
and half the class has the file anyway. The library grew tick boxes and a
sticky "N files selected · Share" bar to feed it; uploading several at once
already worked.

### The library is staff-only; "Shared with me" is everyone's

The nav entry moved from `resource.read` -- which every signed-in role holds --
to `resource.create`. A student reaching the library could browse folders and
open the Share panel, and every control on it would answer 403. What they have
instead is "Shared with me", which is their whole relationship with resources.

The sidebar matrix test proves a link matches *whatever* permission its item
names, so it would have stayed green with the permission put back. The per-role
assertions are written out separately for exactly that reason.

### Pinned where it can fail

`tests/integration/test_resource_share_audience.py` (12), driven over HTTP.
**Mutation-tested, 6 of 6**: no gate at all, guardians dropped, every cohort
shown instead of the sharer's own, a nameless account named by its login name,
the directory made searchable by address, and the share list naming people by
login name.

The last two **survived the first run**: every account in the fixture had a
name, so nothing exercised the fallback, and the one share in the suite was
read back by a tutor, who lacks `user.view_contact` and so sees a name either
way. A nameless account and an administrator-side read kill both. Sixth
"fixture too kind" in this codebase, and the second in a day.


## The Shared Resources page is a viewer, not a list of download links

A student's only relationship with resources is "files someone sent me", and
the screen for it showed a filename, who shared it, and a Download button. To
read a handout you took a copy of it, left the LMS, and opened it in whatever
the operating system felt like.

`/shared-with-me` is now a split view: the list on the left, the file open on
the right, and nothing in between.

### The list is metadata; only the viewer fetches bytes

`/shared-with-me` gained `resource_type`, `mime_type` and `size`, which is
enough to draw a type icon, run the search and work the type filter. So forty
shared files cost forty rows and **no file contents** until one is chosen, and
`viewerKind` decides which renderer to mount before a byte is requested.

One renderer is mounted at a time, keyed by the file, so switching unmounts the
previous one -- which is what releases a PDF's worker and aborts an in-flight
request. Swapping a `src` on a single mounted viewer would leave both behind.

The filter buttons are drawn from what the person actually has
(`availableFilters`), because a student with three PDFs should not be handed
five empty buttons to press.

### Which viewer, decided from the type and then the extension

MIME first: the server recorded it against the upload allowlist, so it is the
better evidence. The extension breaks the two ties it cannot: browsers send
`application/octet-stream` for perfectly ordinary files, and a `.md` arrives as
`text/plain` because `text/markdown` is not in the allowlist -- reading markdown
as plain text is not wrong, but it is worse.

### PDF, and why not an iframe

`pdfjs-dist`, loaded by a dynamic `import()` so a student with no PDFs never
downloads it. An `<iframe>` at the preview endpoint would be fewer lines and
fails twice over: the preview response carries a `sandbox` CSP, which blocks
the built-in plugin outright, and the toolbar it would draw is the browser's --
not stylable, not translatable, and carrying a save button on a file that may
have been shared view-only.

Renders are cancellable, because clicking through five files in a second leaves
four renders in flight and the last to *finish* would otherwise win.

### `.docx` and `.xlsx` are parsed here, not by a library

The obvious choices are SheetJS and mammoth. The npm build of SheetJS is a
version behind its own security fixes, and mammoth returns an HTML **string** --
`innerHTML` on a file a tenant uploaded, which is the one thing this codebase
has repeatedly refused to do. Both are also an order of magnitude larger than
what is needed to show somebody their mark sheet.

Both formats are ZIPs of XML, so `office.ts` reads them with `fflate` (8 KB)
and `DOMParser` and returns **data**; the components build elements from it.
Deliberately partial -- paragraphs, headings, bold and italic runs, lists,
tables, cells with shared strings -- and a file it cannot read gets the
download panel rather than a bad rendering.

The cases that actually break naive parsers are the tested ones: a row with a
gap (`A1` and `D1`, with no `B` element at all, which shifts every later column
left if cells are appended in order), a shared string split across styled runs,
a CSV field with the separator inside quotes, and a heading level that lives in
`w:pStyle`.

### Two Office types joined the preview allowlist, and why that is still safe

`PREVIEWABLE_TYPES` excluded them, so the viewer got a 422. The allowlist's
reasoning is about **the browser interpreting bytes a stranger uploaded** --
which is why `image/svg+xml` and `text/html` are excluded despite rendering
perfectly, since both execute script at this origin. The OOXML types are the
same reasoning read the other way: the browser never interprets them. The
console fetches, unzips, parses with `DOMParser` (which executes nothing) and
builds elements. The legacy binary `.doc` and `.xls` stay out, because nothing
here can read them and a clear "download this" beats a parse error.

That decision had no test at all. `tests/unit/test_previewable_types.py` (26)
now pins both halves, including that a `charset` parameter neither defeats the
check nor smuggles `text/html` past it.

### Every file was fetched twice, and only the browser could say so

`useFile` took the parser as a callback, and every caller passed an inline
`async (response) => ...`: a new function each render, so the effect re-ran the
moment the first response set state. The network panel showed **two requests
per file**, the first aborted by the cleanup of the render it had triggered --
two downloads per file being the whole of what this screen exists to avoid.

Fixed by splitting fetching from parsing: `useFile(src, "bytes" | "text")` has
two primitive dependencies, and `useParsed` turns the payload into a grid or a
document. A `useCallback` at each call site would also have worked and is one
forgotten wrapper away from bringing it back.

### What is not here, and is not pretended to be

The brief asks for YouTube, Vimeo and web links. `shared_links` and
`shared_link_targets` exist in the schema with **no service, no API and no UI**,
so nothing in the product can put a link in anybody's list -- building the
renderers for them would be dead code on an unreachable branch. The "Links"
filter is therefore absent, matching the brief's own instruction to use only
the types the LMS already supports. Wiring that table up is a separate change.

### Pinned where it can fail

`kinds.test.ts` (12) and `office.test.ts` (11). **Mutation-tested, 4 of 4** on
the parsers: cells appended in order instead of by address, a shared string
taken from its first run only, quoting ignored so a comma splits a field, and
the heading level dropped.


## Assessment: the authoring tools, the files, and what a candidate is told

Nine items across quizzes, assignments and examinations. Three of them were
one bug wearing three hats -- a field stored and read by nobody who mattered,
which this codebase keeps producing.

### "Something went wrong" was never a crash

The Mark Sheet tab failed on every examination, and the message was
`ErrorState`'s own title. `PageParams` caps `limit` at 200 and answers **422**
above it; the mark sheet asked for **500**, on both of its queries. Every
other screen in the console already used 200 -- this was the one that missed
it, so the cap was known and the screen was wrong.

Two things the original also left out, fixed with it:

* **`roster.error` was never checked**, only `results.error`. A refused roster
  fell through to *"Nobody is confirmed on this exam's batch"*, which is a
  claim about the cohort rather than about the request.
* **A cohort over 200 now says so.** Silently truncating a mark sheet is worse
  than admitting it is incomplete: the marks entered save correctly, and the
  missing names read as absences.

Driven end to end afterwards: tutor schedules, mark sheet renders (8
candidates, 24 inputs), marks of 72 and 35 save -- *"Recorded 2 result(s)"* --
with the Pass and Fail badges computed against the pass mark.

### What a candidate is told, in three places

`GET /quizzes/{id}` returned the **whole configuration** to every student set
it: shuffle, how many are drawn from the bank, whether answers come back
immediately. The console drew them a Settings tab with the inputs disabled,
which is the giveaway -- the fields were in the payload and only the styling
withheld them. Knowing them is an advantage: "answers shown immediately" and
"ten drawn from forty" both change how a paper is best attempted.

Swept the other two while there:

* **Assignment** -- `instructions_path` is a storage key that *nothing reads*
  (the generated types are its only other mention), published to every
  student set the work. `submission_count` and `eligible_count` are facts
  about classmates.
* **Examination** -- `result_count` and `published_result_count`.
  "28 of 30 published" tells a student whose mark is missing that theirs is
  one of the two being withheld, which is exactly what the release step
  exists to avoid saying.

Withheld on the server in all three, not behind a hidden tab. `null`, not a
default: a client rendering a missing shuffle flag as "questions are in
order" would be stating something it was not told. The invigilator list was
already safe -- `visible_username` gives a name, not a login name.

### A paper now has a total

`total_marks` on quizzes (migration `c4a7e1f93d20`), **nullable**: every quiz
written before it has no stated ceiling, and inventing one from its current
questions would both fabricate a decision and start refusing the next
question added. Enforced on add *and* edit, with the room left named in the
refusal.

The edit path subtracts the question's own current marks. Without that,
raising a 6 to a 7 on a full paper is measured as 10 + 7 and refused -- so the
last question written could never be touched again. A limit that cannot be
recovered from is a dead end, not a limit.

### Files that are actually files

`assignment_submissions.files` was JSON written **straight from the request
body** -- `[{"filename": "...", "path": "..."}]`. No byte was ever stored, and
`path` was caller-controlled; the only reason it was not a file-read
primitive is that nothing read it back. The console said so in its own copy:
*"the API's submission endpoint has no upload of its own -- upload the file
under Resources and paste its link here."*

`assignment_submission_files` (migration `d5b8c2e71f43`) owns the key, the
size and the type. `submission_id` is nullable because the order is attach,
check, submit -- the rows are claimed when the work goes in. `files` left the
request entirely, which moved "did they submit anything?" from a body
validator to the service, the only place that can see both halves.

**The bug the tests caught.** The first `resolve_attachment` authorised a
non-owner with `get(assignment)`, reasoning that it is scoped to the courses
a caller teaches. It is not scoped that way for a *student* -- their own
assignment is one they can get -- so **a classmate could download anybody's
coursework**. It now uses `work_visibility`, the predicate `get_submission`
uses, which gives guardians and corporate managers the right access for free.

### Rich text, and where the sanitising lives

A brief needs tables (a mark scheme *is* a table) and code blocks; an email
does not, so `rich_text.py` shares `mail_html`'s primitives and not its
allow-list. The editor is a request; the server re-parses and nothing
downstream re-sanitises, which is the contract that makes
`dangerouslySetInnerHTML` correct at the one place it is used.

`RichText` **detects** plain text rather than assuming HTML. Every assignment
and question written before the editor holds plain text, and `x < 5` is an
ordinary thing to write in a question.

### Smaller, and worth keeping

* **True/False** -- the labels were the symptom. Saving one kept the type and
  replaced its options with two *blank* rows. `optionsFor(type)` is now the
  single answer the picker and the post-save reset both read.
* **"Save & add another"** keeps the type and the points, because a tutor
  writing a paper writes ten of the same kind.
* **Grading maxima** -- `points_possible` was gated on `results_visible`, so a
  tutor marking a quiz that withholds marks could not see what they were
  marking out of. Students already get `points` while sitting, so it is not a
  result. The server refused over-awards already, but it refused the *whole*
  submission on the first one: one typo lost eleven other marks.

### Result visibility, driven rather than reasoned about

Before release the student saw **0** results though her mark existed; after,
exactly **1** -- her own -- and not the other two candidates'. The corporate
manager saw exactly the three marked students, all on her roster, by name.
Her performance breakdown rolls up ASSIGNMENT / ATTENDANCE / FINAL_EXAM /
PRACTICAL / QUIZ.

Guardians go through the same `work_visibility` resolver and are pinned by
`test_recording_access.py`; there are no guardian links in the dev data to
drive live, and that is stated rather than claimed.

### Pinned, and the fixtures that were too kind

`test_quiz_total_marks.py` (5), `test_rich_text.py` (19),
`test_submission_attachments.py` (13), `test_quiz_settings_are_private.py`
(29). **Mutation-tested, 20 of 20** once the fixtures were fixed.

Four survived first time, all the same way -- the fixture could not tell the
mutation from the truth:

* the pricing catalogue change needed an **Administrator** in the fixture;
* `instructions_path` was **null** on the fixture's assignment, so publishing
  it again changed nothing;
* the exam had **no results**, so both counts were zero for staff and
  candidate alike;
* and the ordering mutation had **no test over `/sessions`** at all.

Seventh, eighth and ninth instances in this codebase. The rule holds: assume a
new negative test passes for the wrong reason until a mutation says otherwise.

## LAIT's corporate managers, read through rather than synced

Two upstream endpoints surfaced for the first time:

    GET /api/v1/integrations/lait/delegate-managers
    GET /api/v1/integrations/lait/delegate-managers/{customer_id}/delegates

`backend/api/v1/lait_delegates.py` + `backend/schemas/lait_delegates.py`, two
new methods on the existing `LaitClient`, and nothing else. **No new
credential, no new setting, no migration.** The key is the one already in
`LaitSettings`, read into an `X-API-Key` header by the client at request time.

**Read-through, deliberately not a sync.** `manager_links` already records who
looks after whom -- an administrator's assertion, which `ScopeResolver`
enforces -- and that is *not* derived from this feed. These two answer a
different question: what does the upstream system say right now? Which is what
somebody reconciling the two needs, and what nothing in the console could
previously show. They are tagged **Corporate managers** so they sit beside
`/manager-links` in Swagger, with every summary saying "held by LAIT".

**Four decisions worth not re-litigating:**

1. **`organization.read`, not `user.sync`.** A delegate manager is a company's
   contact and their delegates are its employees, so this is the corporate
   directory, governed by the permission that already governs organizations.
   `user.sync` is a *write* grant -- reading a list must not require the
   authority to overwrite the roster. Super Admin, Administrator and Corporate
   Manager hold it; tutors, students and guardians get 403, **decided before
   the external call**, so a refused caller cannot drive traffic at LAIT on our
   key.
2. **An external source is not a way around the contact rule.** Upstream a
   manager's `username` *is* their email address. It is returned as `email`
   only to a holder of `user.view_contact` and is `null` otherwise -- the same
   rule `core/privacy.py` applies to every other directory here. The field
   exists either way, so `null` means withheld rather than absent. Proven live:
   the same 103 rows carried 103 addresses for a Super Admin and 0 for a
   Corporate Manager.
3. **The delegate list is wrapped, so "nobody" is expressible.** A bare `[]`
   cannot distinguish an empty company from a `customer_id` LAIT has never
   heard of -- and upstream *does* distinguish them, answering 404 for the
   second. `{customer_id, count, delegates}` keeps both facts. Verified against
   the live service: id 1 → 3 delegates, id 99999999 → **404**.
4. **An upstream failure is 503, never 500**, and relays nothing. A refused
   key, a timeout and an upstream 500 all mean "this integration is not
   answering", which is an operator's problem rather than the caller's. The
   body is withheld because on these two routes it is people's names and
   addresses -- `LaitApiError` is built from a status and a path by design.

The path id is `ge=1` and typed `int` because it is interpolated into an
upstream URL; `0`, `-1` and `abc` are all 422 **before** any call is made.

**Nothing leaks.** Checked rather than asserted: the configured key appears in
neither the OpenAPI document, nor any response body, nor any of the 26 log
lines emitted across three real calls, and the header name is absent from the
spec too.

`test_lait_delegate_endpoints.py` (33) drives both routes over real HTTP with a
`MockTransport` upstream, so it needs no network and can exercise the failure
modes a live call cannot. **Mutation-tested, 5 of 5:** removing the email gate,
flattening 404 to an empty list, dropping `ge=1`, relaying the upstream body,
and removing the permission dependency each fail tests that pass when restored.

**The dev server on :8000 runs without `--reload`, so it must be restarted
before these routes are reachable there.** Swagger UI is `/docs`.

## "Sync All Data": six synchronisations as one ordered operation

The platform had two synchronisations, two buttons on two different screens,
and no way to say "import everything". Pressed in the wrong order they produce
exactly the per-record errors their error lists are full of: a batch whose
course does not exist yet, an enrolment whose student was never imported. The
order is now explicit, recorded, and pressable from the dashboard.

New: `sync_pipeline_runs` + `sync_pipeline_jobs` (migration `e9a1c74f0b36`),
`services/sync_pipeline_service.py`, `services/manager_link_sync.py`,
`services/sync_schedule.py`, `api/v1/sync_pipeline.py` (6 routes under
`/sync/all`), `cli/sync_all.py`, and `components/domain/sync-panel.tsx` on the
dashboard.

**Nothing re-implements a synchronisation.** Each step drives the service that
already owns it: `LaitSyncService` for users, the new `ManagerLinkSyncService`
for managers, and `LaitAcademicSyncService` for the other four, which it does
in one run.

**Five decisions worth not re-litigating:**

1. **The duplicate guard is a partial unique index, not a check.** Both this
   table and `user_sync_runs` carry one over `status = 'RUNNING'`. Two presses,
   two API processes, or a press racing the scheduled worker all reach the same
   index and exactly one wins. A service that checked first would be correct
   only until the second process existed. Proven live: the second press is 409.
2. **The four academic steps share one transaction, and are still reported as
   four jobs.** That transaction is what makes "a batch without its course"
   impossible, so it was not split; instead `LaitAcademicSyncService` gained an
   optional `on_stage` callback (ignored by every existing caller) and the
   console watches four steps advance. The cost, stated rather than hidden:
   retrying any one of them re-runs the academic sync, which is idempotent.
3. **A failed step skips the ones that depend on it.** Importing enrolments
   after the user import failed attaches people to nothing and then reports
   hundreds of per-record errors with one cause.
4. **Managers are matched by email and delegates by `external_student_id`.**
   The email rule is also forced -- `users.email` is unique and
   `_assert_free` refuses to create an account whose email belongs to somebody
   else -- so an upstream manager already in the LMS is *used*, never
   duplicated. Delegates are matched on the stable external id because name
   matching attaches a person's coursework to the wrong manager the first time
   two delegates share a name.
5. **A manager with no match is created through `LaitSyncService.upsert_record`**,
   not a second account-creation path, so they get `can_login=False` and the
   same audit row as every other imported account. Without this the step is
   nearly a no-op: measured against live data, only **7 of 103** upstream
   managers already existed here.

**Scheduling reuses the existing shape: a separate CLI process**, like
`sync_lait_users` and `sync_lait_academic`, so it is independent of the API
process as well as of user sessions:

```bash
python -m backend.cli.sync_all            # loop, obeying the console
python -m backend.cli.sync_all --once     # one pass
```

The on/off switch and frequency live in `system_settings`
(`sync.automatic.enabled`, `sync.automatic.interval_hours`), read fresh on
every pass, so the dashboard toggle takes effect with nothing to restart.
`--interval` overrides the cadence but never the off switch.

### What the live run found, that the tests could not

1. **The migration declared `public_id` as `sa.CHAR(32)`.** `PublicIdMixin`
   uses `sa.Uuid()`; CHAR(32) is how that *renders*, not the column to declare.
   Every insert died with "value too long for type character(32)".
2. **The schedule route read its session after committing it** --
   `InvalidRequestError: Can't operate on closed transaction`. The settings
   were written and the response was a 500, so the UI showed the new value and
   an error at the same time. Both handlers now share one builder that opens
   its own session.
3. **Unmatched delegates were counted as failures.** 454 of 471 delegates
   upstream have never taken a course here, so they are not in `users` and no
   retry will put them there. Counting them as failures made every run read
   PARTIAL for ever, which trains an operator to ignore the status.
4. **Sessions reported "0 processed, 46 succeeded".** They are *generated* from
   each batch's schedule, not fetched, so `fetched` is legitimately 0.
5. **"Last successful" said Never, for ever.** One upstream manager has no
   email address, so every real run is PARTIAL. It now means "every step ran",
   with per-record failures reported separately -- the operator's question is
   "when did data last come in?", and Never was a false answer to it.

**Verified live, not only in tests:** a full run from the dashboard; a **full
page load to another route mid-run** with the pipeline still at 83% afterwards
and finishing while the browser was elsewhere; 409 on the second press; the
schedule saved from the UI into `system_settings` and then obeyed by a
separate worker process, which idled when switched off; +95 manager accounts
(sign-in disabled) and +10 links on the first run, then **+0 courses, batches,
sessions and enrolments on the second** -- the upserts are idempotent. After
the run: 0 orphan batches, 0 self-links, 0 duplicate manager links, and every
join resolves.

`test_sync_pipeline.py` (15) fakes the three steps so a test can fail step 2 on
demand, which a live run cannot do without breaking the upstream API.
**Mutation-tested, 4 of 4:** a failure no longer stopping downstream steps, the
academic sync running once per step instead of once, a retry resetting
completed steps, and the stale-run reaper removed each fail tests that pass
when restored.

### Found during the review, not fixed

* ~~Academic setup → Academic years does not refresh after a create.~~
  **This was a false positive and there is no defect** -- see "The academic
  years refresh was not broken" below.
* **`/api/v1/users/sync/test`** is a stub marked `# SHOHEL` that is declared
  `-> list[dict]` and returns `{}`. Dead, and wrong about its own type.
* **A category named `ac884656 Category`** is residue from
  `test_lait_academic_sync.py`'s fixtures (0 courses, 0 sub-categories).
* ~~Administrators can press "Sync All Data" too.~~ **Done** -- see
  "Importing from LAIT is now Super Admin only" below.


## Importing from LAIT is now Super Admin only

`user.sync` and `course.sync` are subtracted from `_ADMIN` in
`core/permissions.py`. Both go together on purpose: the pipeline is gated on
holding both, so leaving an Administrator either one would let them achieve
the same import in two presses from the Users and Batches screens -- a gate
that looks closed and is not.

`google.sync` is deliberately **not** withdrawn (it writes to a calendar, not
to the institution's records), and `managed_student.*` stays, so an
Administrator still manages manager assignments by hand.

### Editing `core/permissions.py` does nothing until the catalogue is reseeded

**This is the trap, and it was walked into.** `resolve_permissions` flattens
`user.roles[].permissions[]` -- **`role_permissions` rows**. The constant in
`core/permissions.py` is only the source the seeder reads. A unit-style
assertion over `ROLE_PERMISSIONS` passed while a real Administrator session
still got **202** from `POST /sync/all`, because the rows were untouched.

    python -m backend.cli.seed          # or bootstrap_identity directly

The seeder is idempotent and **code wins**: an out-of-band grant added
straight into the database is reverted by it. **After any change to
`core/permissions.py`, this must run as part of the deploy.**

`test_sync_pipeline.py` now asserts the **database** grants, not just the
catalogue, so a forgotten reseed fails a test instead of shipping. Verified by
mutation: restoring the grants in the constant and reseeding fails it with
*"ADMIN must not be able to import from LAIT"*; reverting and reseeding passes.

**Proven live, from a throwaway Administrator session** (created, used,
deleted): `POST /sync/all`, `GET /sync/all/status`, `POST /users/sync` and
`POST /courses/sync` all **403**, while `/users`, `/courses`, `/batches` and
`/manager-links` all still **200** -- and the Super Admin is unaffected. The
first run of that same probe, before the reseed, returned 202/200/409/202,
which is what made the trap visible at all.

19 pipeline tests pass; 214 frontend tests, `tsc` and `eslint src` (0 errors)
are clean.

## The academic years refresh was not broken

Reported in the previous pass as "POST returns 201 and the list stays empty
until a reload". **It does not reproduce, and the earlier report was wrong.**

Three attempts, each creating a year and reading the table back:

* straight after a fresh page load -- the row appears at once;
* after walking Semesters → Departments → Categories → Tags and back, which
  was the original path -- appears at once;
* submitting twice in quick succession (201 then 409), which is what the
  original run actually did -- appears at once.

Then checked against a **production build** (`next build` + `next start` on
:3100, signed in for real): the row appears immediately there too.

The Next dev log also rules out the obvious explanation -- the refetch after
the original POST completed in **51 ms**, well inside the 2.5 s window the
check waited. The wiring is ordinary and correct: `queryKey:
["academic-years", limit, offset]`, `invalidate: [["academic-years"]]`, and
the global defaults set no `refetchOnMount: false`.

Most likely a dev-server Fast Refresh artifact in that session; a full reload
cleared it, which fits. **No code was changed**, because changing working code
to chase an unreproducible symptom is how a real defect gets introduced.

## Managers are matched, never invented -- and three bugs that only a second run could show

The previous pass created an LMS account for every upstream manager with no
match. That is reversed: **the manager step matches by email and skips
otherwise.** An external directory saying somebody is a corporate contact is
not a reason for them to exist here.

The 95 accounts the old behaviour created were removed, identified from the
audit trail (`details->>'source' = 'manager'`, `result = 'created'`) rather
than by a `can_login = false` heuristic -- which would have swept up five
corporate managers the *student and tutor* feeds had legitimately created.
Checked first: none could sign in, none held another role, none had
enrolments, attendance or taught a session. Removed through the API, so each
went through the ordinary service and left an audit entry.

**Nothing in this step is a failure any more.** A manager with no LMS account,
a manager LAIT holds no email for, and a delegate who is not a student here
are facts about two systems holding different people -- counted as skipped,
never failed. That is what turned a permanently PARTIAL run into a COMPLETED
one. Only the LAIT API refusing to answer is an error, because only that is
worth retrying.

Skips are recorded with a reason and **nothing else**: `{"customer_id": "1",
"reason": "no LMS user has this email address"}`. The list is stored on the
run and rendered in the console, so "which record" is answerable without
publishing a third party's name, email or employer. A test asserts the address
cannot appear there.

### Three defects, each found by running it rather than reading it

1. **`rowcount` is `-1`, and `-1` is truthy.** The link upsert decided
   "created" vs "already linked" from `result.rowcount` after an
   `ON CONFLICT DO NOTHING` insert. This driver reports `-1` when there is
   nothing to fetch, so **every** link counted as newly created and
   `already_linked` sat at 0 for ever -- on runs that wrote nothing at all.
   The database was always right; only the report lied. Now
   `.returning(ManagedStudent.id)`, where a conflict yields no row and the two
   cases are genuinely distinguishable.
2. **Soft-deleted users were matched.** Users are soft-deleted because
   `audit_logs` references the row, so a deleted person keeps their email.
   Immediately after removing those 95 accounts the next run matched all 95
   again and re-linked two of them -- quietly undoing the deletion. Both
   lookups now require `deleted_at IS NULL` and `status != DELETED`.
3. **A known error was reported as a crash.** A step that hit the
   `user_sync_runs` single-RUNNING-row lock -- shared with the "Sync now"
   buttons on the Users and Batches screens -- failed the whole pipeline with
   *"COURSES: Unexpected ConflictError"*, skipping the three steps after it.
   Two fixes: `_readable` passes an `AppError`'s own message through, and a
   step now **waits out** the competing run (3 minutes, polling every 3s)
   instead of dying on a condition that resolves itself in under a minute.

### Verified

Four consecutive runs from the dashboard, all **COMPLETED**, `failed = 0`, and
the last three byte-identical in their manager figures:

    managers  : fetched 103, matched 7, no_lms_account 95, no_email 1
    delegates : fetched 18, linked 0, already_linked 8, unmatched 3, self 7

`linked: 0` on a repeat run is the idempotence proof the old `rowcount` bug
had been hiding. Delegate fetches also fell from 471 to 18, because only a
matched manager's list is now requested -- less upstream traffic for the same
result.

Afterwards: 82 live users, 7 live corporate managers, 15 links, **0 duplicate
links, 0 self links, 0 links pointing at a deleted account, 0 orphan batches
or sessions**, and courses/batches/sessions/enrolments unchanged at
28/26/66/41.

Permissions re-checked live: corporate manager, student and tutor all **403**
on `POST /sync/all` and `GET /sync/all/status`; anonymous **401**; a second
press **409**; retrying an all-succeeded run **409**.

`test_manager_link_sync.py` (14) drives the service against real Postgres with
a faked LAIT API, with a fixture holding one manager of each kind the live
feed has. **Mutation-tested, 6 of 6:** treating an unmatched manager as
matched, counting skips as failures, counting every link as created, leaking
the email into a skip reason, and dropping either soft-delete filter each fail
tests that pass when restored. 214 frontend tests, `tsc` and `eslint src`
(0 errors) clean.

### Still true, and worth knowing

* Only 7 of 103 upstream managers have an LMS account. That is the honest
  state of the two systems, not a fault, and the console now says so in words
  rather than leaving "7 of 103" to look like a failure.
* `customer_id` 131 has no email address upstream, so it can never be matched
  until LAIT holds one.

## A public Help Center, starting with the Super Admin guide

`/help` is a public documentation site inside the console: 41 articles, 50
screenshots of the real screens, readable without signing in and shareable by
link. Full progress record and feature coverage matrix:
[docs/help-center-progress.md](docs/help-center-progress.md).

**It is outside the `(app)` route group, and that is the whole trick.** That
group's layout holds the sign-in guard, so anything inside it redirects a
signed-out visitor to the login screen. `/help` sits beside it, where no guard
runs — no middleware was added and no existing route changed. The pages are
prerendered at build time from content files, so they make no API call and
have no session to leak.

**Articles are typed data, not Markdown or MDX** (`content/help/types.ts`).
Three reasons, each of which is a thing that otherwise rots:

1. **The template is enforced.** Every article must say what the reader will
   learn, what they need first, the steps, what they should see afterwards and
   what to do when it goes wrong. Prose lets an author skip the last two,
   which are the ones beginners need most.
2. **Links cannot rot.** `related` holds article ids, and a test fails on an
   id that names nothing.
3. **Search needs no service.** The index is built in the browser from the
   same data the page renders.

Zero new dependencies. The pages reuse the console's design tokens, so the
Help Center and the application look like one product.

### Writing it from the application, not from memory

A Playwright pass signed in as a Super Admin walked all 34 routes, recorded
each page's real headings, tabs, buttons, columns and filters to JSON, and
photographed it. A second pass opened what a list page cannot show: the quiz's
four tabs and its answer key, the examination's mark sheet and its two
visibility switches, the grade book's three tabs, both attendance tabs, and
**twelve create dialogs — opened to read their real field names, then closed
without saving**. Every field name in the guide is a field name on screen.

**Nothing was submitted, published, graded or synced to produce
documentation.** Where a workflow could not be completed safely against real
institution data, the article describes the screen and the buttons and does
not claim an outcome that was not observed; `docs/help-center-progress.md`
lists those cases explicitly.

### Personal data is blurred before the shutter opens

The console is full of real students, tutors and guardians. A capture script
blurs, in the page, every table cell under a column named for a person or a
contact detail, **and** any element whose own text looks like an email
address — 264 elements across 34 pages. Blurring rather than blanking keeps
the shape of the screen, which is what a reader needs.

The first attempt used `blur(5px)` and the email column was still partly
legible when enlarged. It is `blur(11px)`, checked by cropping and enlarging
the Users, Audit log and Quiz attempts captures.

### One console change, and why

`SessionProvider` asked `/auth/me` on every page. On a public help page that
is a guaranteed 401 per visitor for a page with no session, so the query is
disabled under `/help`. Every other route is unchanged. Verified: zero console
errors on a public page, where there was one per page before.

### Sidebar

A **Help** group at the foot of the rail, chosen from the roles the *server*
reports rather than from the screens the sidebar happens to render. It opens
in a new tab and has a copy-link button beside it, because the commonest thing
to do with a guide is send it to somebody.

**A role whose guide is not written gets no link at all.** A link to an empty
guide teaches people that the help is useless. Verified live: present for a
Super Admin, absent for a Tutor and a Student.

### Verified in a browser, signed out

41/41 articles return 200 with no redirect in a fresh profile with no cookies;
0 broken internal links; search returns results for real terms and an honest
empty state otherwise; table-of-contents anchors land on headings that exist;
click-to-enlarge opens and closes with Escape; at 375px there is no horizontal
overflow and the contents drawer opens; in print media the header, sidebar,
breadcrumbs, search and previous/next all collapse to nothing while the steps
and screenshots stay.

`help-content.test.ts` (19) checks what TypeScript cannot: that every `related`
id names a real article, that every screenshot referenced **exists on disk**,
that every screenshot has alternative text, and that **no email address or
test credential appears in any article**. 233 frontend tests pass; `tsc`,
`eslint src` (0 errors) and `npm run build` are clean.

**One defect found in my own verification, not in the product:** a "broken
image" on the quizzes article was a lazy-loaded screenshot below the fold.
It loads on scroll and returns 200; the check was measuring too early.

## Tutor guide — the second Help Center role

`/help/tutor`: 25 articles, 32 screenshots, same shell and content model as the
Super Admin guide. Registered in `GUIDES` and in `ROLE_TO_GUIDE`, which is all
it takes for the Help Center listing, the sitemap, the search and the sidebar
link to pick it up.

**A tutor's guide is defined by what a tutor cannot reach.** Twelve screens a
Super Admin opens are absent from a tutor's menu — Users, Roles, Permissions,
Organizations, Guardians, Manager assignments, My team, Integrations, System
settings, Audit log, Security and Operations — so they have no articles. Where
a tutor can see a screen but not act on it (Grading schemes, Transcripts,
Academic setup) the article says so and names who to ask.

That list was **established, not assumed**: the capture pass records every
button on every screen, so a diff of Tutor against Super Admin produces the
restrictions. It is how the guide knows there is no **Export CSV** on a
tutor's Reports, no **New scheme**, no **FEE** column and no **Add year**.

Scoping was checked against the API as both roles rather than inferred from
the screen: courses 28 → 9, batches 26 → 3, sessions 66 → 14, enrolments
41 → 12, users 82 → 11.

### Three things the capture got wrong first, and how

1. **Two tutor screens were recorded as empty.** The capture waited for
   `networkidle`, which these pages reach while still showing a loading
   skeleton — they fetch after mount. Enrollments read "0 rows" when the API
   had 12, and Batches read "No batches" with 3. The capture now waits for the
   word "Loading" to leave the page, and both screens were re-taken. **Neither
   was a product defect**, and reporting one would have been wrong.
2. **Batches do not open from a link.** The row navigates on click
   (`onRowClick`), with the same destination on the row's **Actions** menu.
   The Super Admin guide said "click the batch code", which was wrong; both
   guides now describe the row click and the Actions menu.
3. **The tutor's create dialogs were not assumed to match the Super Admin's.**
   They were opened as the tutor and read: they are identical, which is now a
   checked fact rather than a guess.

### The content test earned its place twice

`help-content.test.ts` failed on the tutor content for two real reasons before
anything shipped: four screenshots referenced before the optimiser had written
them, and two article titles ("… (read only)") breaking the action-oriented
title rule. Both were fixed rather than the rule weakened — the titles became
"What transcripts and grading schemes are for" and "What Academic setup is
for".

### Housekeeping

Captures include screens the role cannot reach, so unreferenced screenshots
are pruned: 18 from the tutor folder and 7 superseded duplicates from the
Super Admin folder. Four tutor captures were *used* rather than deleted
(the batch Overview tab, announcements, discussions and notifications).

**Verified signed out, fresh profile:** 25/25 Tutor articles HTTP 200, 0
broken links, search/TOC/lightbox pass, no horizontal overflow at 375px, 0
console errors. Sidebar: Super Admin → "Super Admin guide", Tutor → "Tutor
guide", Student → no link (guide not written). 233 frontend tests, `tsc`,
`eslint src` (0 errors) and `npm run build` all clean.

## Corporate Manager guide — the third Help Center role

`/help/corporate-manager`: 22 articles, 19 screenshots. Three guides now ship
from one shell; adding this one changed two lines of `content/help/index.ts`.

**The account used to write it is not the role it documents.** The test
manager holds **both** `CORPORATE_MANAGER` and `STUDENT`, so it can open
Announcements, Discussions, Resources and Grading schemes — none of which the
corporate-manager role grants. Documenting what that account sees would have
produced a guide that is wrong for every manager who is not also a learner.

So the pure-role view was **computed** — the permission catalogue intersected
with the permission each nav item declares in `navigation.ts` — rather than
read off the screen. A pure corporate manager sees 19 sidebar items, and the
guide covers those. The sidebar article tells a reader who sees extra items
why, and points them at the Student guide for them.

This also exercises the "most privileged role wins" rule in `ROLE_TO_GUIDE`:
signed in, that same account is offered the **Corporate Manager** guide, not
the Student one. Verified live.

### The manager's single write action, found by searching rather than clicking

A corporate manager holds `enrollment.create`, but the Enrollments screen has
no create button and neither does their organization page. Grepping the
frontend for the permission found it in exactly one place — the batch
workspace's Enrollments tab — and opening a batch as the manager confirmed an
**Enroll** button appears there. Without that search the guide would have said
a manager cannot enrol anybody, which is wrong.

Everything else is reading. Their batch workspace has **three** tabs where a
tutor's has four: no Attendance tab, because they cannot mark a register.

### Scoping, checked as both roles

courses 28 → 28 (managers hold `course.view_all`, so they browse the whole
catalogue), batches 26 → 1, sessions 66 → 6, enrolments 41 → 7, users 82 → 8,
manager assignments 15 → 7, organizations 14 → 1.

### The title rule was widened, deliberately

The content test rejected "Why you can see some people and not others". That
title is exactly the question its readers arrive with, so the rule gained
`why` rather than the title being bent to fit — with the reason written into
the test. The rule exists to stop bare-noun titles, not to ban good questions.

**Verified signed out, fresh profile:** 22/22 articles HTTP 200, 0 broken
links, search/TOC/lightbox pass, no horizontal overflow at 375px, 0 console
errors. Sidebar across four accounts: Super Admin, Tutor and Corporate Manager
each get their own guide; a Student still gets no link. 233 frontend tests,
`tsc`, `eslint src` (0 errors) and `npm run build` clean.

## Guardian guide — written only after the data to write it from existed

`/help/guardian`: 19 articles, 18 screenshots. Four guides now ship.

**The role could not be inspected at first, and that was the finding.** The
two accounts the brief named (`gina@lmsdemo.com`, `cal@lmsdemo.com`) are not
in this database, **no account held the GUARDIAN role at all**, and
`student_guardians` was empty. Checked three ways — sign-in returned 401, the
users table had no such rows, and the role count was zero — before stopping
and asking rather than writing a guide from the permission catalogue and
calling it documentation.

With the user's approval one guardian was created through the API as an
administrator would, linked to a student with real attendance and marks, used
for the screenshots, then removed: link deleted, account soft-deleted,
confirmed afterwards at **0 links, 0 live GUARDIAN accounts**. The soft-delete
is the schema's doing — `audit_logs` references `users` — so that row and its
audit entries remain, which is stated in the progress file rather than glossed.

### What distinguishes a guardian, all verified on screen

* **No write action whatsoever.** A corporate manager has exactly one
  (enrolling from a batch); a guardian has none. The guide leads with that
  instead of letting a reader hunt for buttons.
* **No Reports screen** — guardians lack `report.read`, where managers have it.
* **Announcements, which managers do not get** — `announcement.read` is a
  guardian permission and not a manager one.
* **Performance shows only their own student**, despite the screen being
  organised by class group. One row, not the cohort.

### The capture kept being too fast, a third time

Courses and Timetable recorded as "Loading" even after a 17-second wait.
Driving them by hand for twelve seconds showed 28 courses and 6 sessions, all
API calls 200, no console errors. The settle now waits for the page text to
**stop changing** rather than only for the word "Loading" to leave, which is
what finally held. Three roles in, the lesson is the same each time: a screen
that looks empty to a scraper is usually a screen that had not finished.

**Verified signed out, fresh profile:** 19/19 articles HTTP 200, 0 broken
links, search/TOC/lightbox pass, no horizontal overflow at 375px, 0 console
errors. Sidebar across five accounts: Super Admin, Tutor, Corporate Manager
and Guardian each get their own guide; a Student still gets none. 233 frontend
tests, `tsc`, `eslint src` (0 errors) and `npm run build` clean.

## Managed Student guide — the fifth Help Center role

`/help/managed-student`: 23 articles, 20 screenshots. Five guides now ship.

**A managed student is not a distinct role.** They hold the same `STUDENT`
role and the same 27 permissions as any other student, and see the same 17
menu items. What makes them "managed" is a row in another table: a corporate
manager or guardian linked to their account. The account used was a student
with one enrolment and **two corporate managers watching**.

### What the guide says that the product does not

* **The student has no screen listing who can see them.** There is no My team
  and no Guardians item on a student's menu. Rather than leave a reader
  hunting, the guide states it and says to ask the office.
* **They are told once, when a link is created.** `guardian_linked` and
  `manager_linked` are sent to both sides, naming the person. The comment in
  `managed_student_service.py` says why: *"The student finding out is the
  point -- it is the only moment they could object."* So the guide tells them
  to read notifications rather than clear them, because this one arrives
  nowhere else.
* **Watchers can read but cannot act.** `assignment.submit` is held by
  `STUDENT` and by neither `CORPORATE_MANAGER` nor `GUARDIAN` — checked rather
  than assumed, because "your manager can sort it out" is exactly the wrong
  thing for a guide to imply.

### Two findings from checking rather than reading

* **"All submissions" on the assignment page is scoped, not a leak.** The label
  invites the opposite reading, so it was measured over the API: the same
  assignment returns 6 submissions to an administrator and **1** to the
  student, because `list_submissions` filters on `work_visibility`. The guide
  explains the label instead of repeating it.
* **18 of the 38 captured PNGs were stale** — a prior route sweep into the same
  folder, 22:58–23:00 against the real capture's 23:01–23:04. Only the 20
  screens present in `deep.json` were published. Publishing a folder because it
  is the output folder is how an admin screen ends up in a student's guide.

### The privacy policy had two holes, and real names were in the frame

`privacy.js` blurred table cells under person-ish headers and anything shaped
like an email. Two things escaped: **the signed-in person's own name**, which
is a page heading on `/account` and not a table cell, and **"recorded … by
Firstname Lastname"** credits under a `RECORDED` column. A student's name on a
public page beside their own absence record is the thing the brief forbids, so
the policy gained two rules and the six affected screens were re-photographed.

The supplied names are read from the account page **at capture time** and
passed in as `window.__redactNames`. A list of names written into the script
would be stale the moment the data changed, and would itself be a published
name.

Cost, stated because it is visible: the `RECORDED` column now blurs its
timestamp along with the credit, since they are one text node.

### Residue from the Guardian pass, cleaned

The temporary guardian created for the previous guide had been removed, but the
notification it caused had not — a real student's feed still said a guardian who
no longer exists could read their record, and it was in frame on the
notifications screenshot. One row deleted by id, after re-reading it and
refusing to act unless it matched on both type and body (10 → 9 notifications),
then the screen re-photographed.

### One role, two guides — an open decision

`ROLE_TO_GUIDE` maps a role to a single guide, and the Individual Student guide
will share the `STUDENT` role. Nothing in a student's own token says whether
anyone is linked to them, so the console cannot tell them apart. `STUDENT`
currently maps to `managed-student`, which means an individual student is
offered it too — verified, and recorded rather than hidden. A chooser is
probably the answer once the second guide exists.

## Individual Student guide — the sixth role, and the Help Center is complete

`/help/individual-student`: 23 articles, 20 screenshots. **All six guides now
ship: 153 articles and 164 screenshots.**

**Nothing in the software distinguishes this role from the managed student.**
Same `STUDENT` role, same 27 permissions, same 17 menu items. The account used
has zero managers, zero guardians and no employer membership, against the
managed student's two managers and one membership — otherwise the two are
matched (1 enrolment, 1 submission, 3 attendance records each). So the guide
differs in framing, not in which screens it covers, and says so rather than
inventing a distinction.

* **Nobody chases them**, so the guide points repeatedly at the dashboard as
  the thing that does.
* **"Private" would have been the wrong word.** Tutors and administrators read
  their record, and a link can be created later. `privacy` sets out who sees
  what in a table instead of implying nobody does, and `if-linked` describes
  the notification *before* it arrives so a later-sponsored student recognises
  it.

### One role, two guides — resolved with a typed pointer

`Guide.sibling` is new and optional: a companion guide, rendered as one line on
the landing page — *"If nobody at an employer or at home follows your progress,
read the Individual Student guide instead."* and the reverse. Followed in a
browser both ways.

It was needed because `ROLE_TO_GUIDE` maps a role to one guide and nothing in a
student's own token says whether anyone is linked to them. `STUDENT` maps to
`managed-student`; the pointer is how the other half of the audience arrives.
Deliberately **not** done by adding links to body markup: `markup.tsx` supports
only `**bold**` precisely so content cannot render a link, an image or raw HTML,
and there is no sanitiser to get wrong. A typed field on the guide keeps that.

### The privacy policy had a third hole, and it was in the shipped guide

The managed student's dashboard read **"Welcome back, Ibn"** in clear. The name
rule matched on whole names scraped from the account page, and the greeting
renders a *shorter* form of the same name, so it never matched. The individual
student's dashboard had the same leak with a `gmail.com` account.

Fixed by taking the names from `/auth/me` at capture time — first, middle and
last name, their combinations, the username and the email — instead of scraping
page headings. The scraped list had also been swallowing UI labels like "My
Account", which is why matching on word fragments would not have been safe with
it. Both student guides were re-photographed and re-checked by eye.

**The lesson is the one this file keeps relearning: a redaction rule is only
proven by looking at the picture.** The scan that said the managed guide was
clean searched for `Ibn Benin`, so "Welcome back, Ibn" passed it. Three rules
and two review passes went by before an eye on the crop caught it.

### My own title rule said no, and the rule was wrong

`"Who can see your work"` failed the action-oriented-title test, whose allowed
openings did not include "who". The rule already carried a note explaining that
"why" was added because *"Why you can see some people and not others"* is the
question its readers arrive with. The same argument applies verbatim: a student
opens the help looking for "who can see my work". The rule was widened and the
reason recorded, rather than the title contorted to fit it.

## Assessment verification and video sharing — what driving it found

A verification pass over the seven assessment components against all six
roles, and over how videos are shared and watched. Everything below was found
by signing in and using the system, not by reading it.

### A Tutor could issue official transcripts

`POST /batches/{id}/transcripts/generate` was gated on `grade.update`, which a
Tutor holds in order to mark work. The catalogue defines a separate
`transcript.generate`, grants it to the academic office alone, and explains
why in as many words: a transcript is an *official* document, and "somebody
may be entitled to see a mark without being entitled to issue the document
that certifies it". Nothing checked it — `transcript.read` and
`transcript.generate` were both seeded, both shown in the role editor, and
both enforced by no route at all.

Driven as the Tutor it returned **200 and created a transcript**. The Tutor
user guide already said "generating them is an administrator's job", so the
documentation was right and the route was wrong.

Fixed by pointing the three transcript routes at the transcript permissions.
`quiz.publish` and `exam.grade` were decorative in the same way and are now
enforced; both have the same holders as the permission they replaced, so that
half is behaviour-neutral and guards against future drift.

`tests/unit/test_assessment_route_permissions.py` reads the required codes out
of each route's dependency closure and compares them with a written-down
expectation. Mutation-tested: reverting the gate fails three of its four tests.

### Class performance was a 500 on every save, and it stopped every transcript

`PUT /class-performance/sessions/{id}` returned 500 whatever you sent. The
service flushed newly created marks and returned them; the route's response
mapper then read `row.student` to name the student, and on a row created
moments earlier that relationship had never been loaded — in async SQLAlchemy
that is `MissingGreenlet`, not a slow query. The mark was written and the
caller was told the save had failed.

The *read* path builds its rows from enrollments and never touches that
relationship, which is why every test of the sheet passed while the write was
unusable.

It was not confined to one screen. PRACTICAL ("Class performance") is one of
five weighted components of the default grading scheme, and the performance
engine withholds a final percentage until every weighted component is
assessed. With class performance impossible to record, **no transcript in the
database had a `final_percentage`** — 11 of 11 null — and `finalise` refuses
without one. So no transcript could ever be certified, and since students,
guardians and corporate managers are shown only finalised transcripts, their
Transcripts screen was empty by construction.

Both write paths now eager-load the relationship.
`tests/integration/test_class_performance_save.py` asserts it by doing exactly
what the response mapper does; removing the fix reproduces `MissingGreenlet`.

### Video links were stored unvalidated, and YouTube could not play

`recording_link` accepted anything. `javascript:alert(1)` and `not-a-url` were
both stored and handed back to the browser, which writes them into an `href`
and an `iframe src`.

`backend/core/video_links.py` now validates and normalises in one place:
scheme allowlist (not a blocklist), no credentials in the authority, and each
recognised provider mapped to its *documented* embed endpoint, because the
address a tutor copies is the page and not the player. An unrecognised but
valid host is offered as a link rather than framed, which is honest about what
a blank iframe would have been.

**The referrer finding is the one worth keeping.** Framing YouTube with
`referrerpolicy="no-referrer"` renders "Video player configuration error —
Error 153" and plays nothing: its player checks which site is embedding it.
Measured in a browser, two iframes of the same video side by side, one with
the attribute and one without; Vimeo played identically either way. The
attribute was on our own iframe, where it is the floor for the whole redirect
chain, so no backend header could loosen it. The element now sends
`strict-origin-when-cross-origin` — our origin and nothing more — and the
route tightens it back to `no-referrer` for the providers that do not need it.

**A false positive worth remembering:** a Playwright probe for a player
element reported success on the Error 153 page, because that page contains
one. Only looking at the screenshot showed the failure. The same probe is why
the first fix appeared to work and had not.

### Every invalid form in the console said the same unhelpful thing

FastAPI's 422 is `{"detail": [...]}`; the console reads `{"code", "message",
"details"}`, the envelope every `AppError` already uses. With nothing bridging
them, `ApiError` found no message and fell back to "The request could not be
completed." for *every* rejected field in the application. The reason was
computed, serialised, and thrown away at the last step. `main.py` now maps
validation errors into the same envelope, keyed by field so a form can mark
the input.

### What the verification showed working

Scoping is correct and consistent across all six roles on all seven
components, at the API and in the console: a Corporate Manager sees their
roster, a Guardian sees their linked student, a student sees themselves, and
a record somebody may not see answers 404 rather than 403. Grading schemes are
withheld from four roles in the menu *and* refused on direct navigation. The
quiz answer key is refused to everyone without marking rights, and `is_correct`
is absent from the payload a student receives.

The full lifecycle was driven end to end on an isolated `DEMO-ASMT` course:
author → publish → submit and attempt → mark → publish results → grade-book
sync → performance → transcript → finalise. Auto-marking scored 100% and 0%
for right and wrong answers; a Tutor was refused at `results/publish` and an
administrator allowed; finalising made the transcript visible to the student
and their corporate manager and to nobody else.

### Guides corrected

Four guides said a transcript appears once the school *generates* it. It
appears once the school *finalises* it — proven by finalising one and watching
it appear for the student and their manager. The Super Admin guide promised to
explain "finalised" and never did; it now has the step, what it publishes, and
why finalising is sometimes refused. Two articles were missing entirely and
are now written from the real screens: marking class performance, and sharing
a class recording or video.

## Permanent deletion and the complete system reset

Two Super-Admin-only operations, built to the "hard warning, no MFA, no
CAPTCHA" instruction. Both are gated **twice**: on a new permission
(`system.purge` / `system.reset`) *and* on the Super Admin role, because
`role_permissions` is editable data and a permission alone could be granted to
a lesser role by somebody who did not appreciate what they were handing over.
The permission makes the gate discoverable and auditable; the role check is the
floor underneath it. **Re-run the identity seeder** (or `bootstrap_identity`)
after upgrading — the catalogue went from 127 to 129.

### The dependency plan is read from `pg_constraint`, never hand-written

A hand-kept list of "things to delete first" is wrong the moment somebody adds
a table, and wrong *silently*: the delete either fails with a foreign-key error
an administrator cannot act on, or — where the constraint happens to be
`ON DELETE CASCADE` — succeeds and takes rows nobody listed. So `PurgeService`
reads the graph at run time. It cannot drift from the schema because it *is*
the schema.

The three kinds of dependency are reported differently, because they are
different outcomes. On `users` this database has 25 CASCADE, 22 SET NULL, 26
NO ACTION and 1 RESTRICT. Cascades the database deletes itself; `SET NULL` rows
**survive with a link removed** and are shown apart (merging them into one
"47 rows affected" figure would overstate the damage by however many records
the person had ever touched); NO ACTION and RESTRICT are deleted first,
deepest-first, in the same transaction. The single RESTRICT in the whole schema
is `class_performance_marks.recorded_by -> users`, and it is the best proof
available that blockers are handled: a cascade-only implementation fails on it
loudly.

**Rows are addressed by nested subquery, never by a materialised id list.**
Fetching child ids to recurse on needs a cap, and a cap on a *delete* path is
the worst kind — the parent delete still takes every child, so exceeding it
leaves orphaned grandchildren, found when the transaction aborts or not at all.

**One transaction, and the service never commits**: the caller owns it, so the
audit record and the deletion land together or neither does.

### Four protections, and why each is unrecoverable without it

The last active Super Admin (nothing in the product creates the first one);
self-deletion; the permission catalogue (deleting a permission row removes the
*check*, not the ability — the one deletion that grants access rather than
withdrawing it); and the audit trail.

**`audit_logs` turned out to be stronger than assumed, in two ways.** It has
**no foreign keys in either direction**, so the record survives the records it
describes — which is what makes it possible to delete a person and still answer
who deleted them. And `trg_audit_logs_append_only` is a BEFORE DELETE OR UPDATE
OR TRUNCATE trigger that raises. An earlier draft of the reset offered a "clear
the audit trail too" option; it could only ever have **failed at run time**, so
it was removed rather than worked around. Defeating the trigger from an HTTP
route was never on the table: an append-only guarantee an endpoint can switch
off is not one.

### The reset refuses by default, four ways

`APP_SYSTEM_RESET_ENABLED` is off unless somebody turns it on, in deployment
configuration rather than the interface — the person who may *run* a reset and
the person who may *enable* one hold different kinds of access. Production is
refused outright, with no setting that changes it. A verified recent backup
must exist, and **an unset backup path is itself a refusal**: "there is no
backup configured" and "the backup is fine" must never look the same to the
person about to erase everything. The typed phrase names the database, so a
screen left open against staging cannot reset something else. A running
synchronisation is a refusal, not something the reset terminates — killing a
pipeline mid-flight leaves the external system believing it handed over records
that no longer exist here.

The backup check verifies a recent, non-empty, readable file. It **cannot**
verify that a dump restores, and the refusal message says so rather than
implying otherwise.

Re-seeding calls the same `bootstrap_identity` / `bootstrap_geo` /
`bootstrap_grading` a new deployment runs, so "reset" and "freshly installed"
cannot drift apart. `TRUNCATE ... RESTART IDENTITY` rather than `DELETE`,
because a fresh installation whose first course is number 4,312 is not what
anybody means by the word. The one remaining account keeps the operator's own
username and email with a **new** password shown once: leaving the old one
working would mean the credentials of a system somebody just erased are still
the credentials of the new one.

### Tested on data created for the purpose, never on real records

`tests/integration/test_permanent_deletion.py` (13) creates every row it
touches, tagged, and asserts the untouched tables hold exactly as many rows
afterwards as before. **`execute` is never called with a real administrator's
id**, even to prove the last-Super-Admin refusal — a test that can cause the
accident it checks for is not worth the coverage, so that blocker is proven
through the read-only preview and the "blockers mean refusal" half through a
tagged row.

`test_system_reset_on_a_disposable_database.py` (7) **creates its own
PostgreSQL database**, migrates it with the project's own Alembic config (so it
has the real triggers, not a `metadata.create_all` approximation), seeds it,
resets it for real, and drops it. It skips rather than failing if the role
cannot `CREATEDB`: a test that cannot isolate itself must not fall back to a
shared database. `test_system_reset_guards.py` (11) asserts every gate against
the dev installation without ever calling `execute` in a way that could get
through.

**Mutation-tested: 10/10 on the purge, 12/12 on the reset.** Only the
disposable-database suite is mutated, for the reason above. One miss on the
first run was a genuine coverage hole — nothing had a *two-level* blocker
chain, so a mutation stopping the recursion at one level passed everything.
`courses -> assignments -> assignment_submissions` closed it.

### Found by running it, invisible to a green suite

* **`Row.t` and `Row.n` collide with SQLAlchemy `Row`'s own attributes** and
  resolve to the wrong object. This was in the reset's production `_impact`
  query, not only in a test — the preview returned wrong labels. Column aliases
  are now `tbl` / `cnt`.
* **`text(":t::regclass")` is a syntax error**: `text()`'s parser reads the
  second colon as another bind parameter. `CAST(:t AS regclass)` says the same
  thing unambiguously.
* Four copy defects only the browser showed: "1 people" and "1 records"; "1 of
  the 1 numbers you entered do not exist. Only the 0 that do will be deleted.";
  a raw table name (`batches`) where the label map had no entry; and
  "Enrolments(via Enrolments)", a parent reference that only ever repeated the
  child's own name. The singular now comes from the server
  (`Entity.singular`), because the server already owns that vocabulary.

### Driven in the browser, on isolated records

A tagged account previewed, confirmed and deleted (audit row written naming the
real actor and the target; user count returned to its original 224). A tagged
`course -> batch -> enrolment` chain deleted through the UI: **the student
survived**, correctly — an enrolment is deleted but the person is not. A
partial confirmation phrase leaves the button disabled. The reset card shows
"Not available on this installation", both blockers in full, the real impact
(2,658 records) — and **renders no confirmation controls at all**.

### What is deliberately absent

No second factor and no CAPTCHA, by instruction. The gate is a Super Admin
session, an explicit permission, the role check, a dependency preview, and a
typed confirmation carrying the real record count. The screen says so in as
many words, under "What stands between a click and a loss" — an operator who
believes a second factor stands behind this will treat it more casually than
they should.

## Live badges, dashboard and presence, without a refresh

Two complaints, one cause each. Badges abbreviated to "99+" with no way to see
the real figure; and badge counts, dashboard KPIs and Active Users only moved
on a page load.

### The per-user channel was never enough, and that is why the dashboard was stale

`core/events.py` addresses every event to one person, for a stated reason:
fan-out happens where recipients are already resolved, under audience rules the
transport cannot evaluate. Right for "your grade was published"; it cannot
express "the course list changed", which is what a badge counts. **Nobody is
notified when an administrator adds a batch**, so those numbers could only
correct themselves on the next refetch.

Worse, `["dashboard"]` was in no invalidation map *and* had no
`refetchInterval` -- so the dashboard was the one surface with no refresh
mechanism at all. That is the screen the complaint was about.

**New: topics** (`core/topics.py`). Five coarse ones -- `directory`,
`academic`, `assessment`, `announcements`, `presence`. A topic event carries
the topic name and **nothing else**: every subscriber re-reads through the
ordinary endpoint, so `core/privacy.py` and every permission check still decide
what each of them sees. That is what makes a shared channel safe here where one
carrying content would not be. Subscription is resolved from permissions at
connect time, from the token: a student is not subscribed to `directory`, and
`presence` additionally needs `institution.view_all`, matching the gate on
`GET /presence/active` exactly.

### One hook, so no service has to remember

Detection is a single SQLAlchemy listener over the session, mapping written
tables to topics. Forty call sites would each have to announce themselves, and
forgetting is invisible -- a screen that quietly never updates. A table nobody
mapped stays silent rather than guessing, which is why `audit_logs`, `tokens`
and `sync_pipeline_runs` raise nothing.

**It is bound to `after_flush`, and that is the whole correctness of it.** The
obvious hook is `before_commit`, which is what the first version used and what
every test here passed against. Creating a course through the real endpoint
then announced nothing, because a service that calls `flush()` to obtain an id
has already emptied `session.new`:

```
with an explicit flush:  after_flush sees 1, before_commit sees 0
without a flush:         after_flush sees 1, before_commit sees 1
```

So `before_commit` catches exactly the case a test writes and none of the cases
the application performs. Flushing is not committing, so this only *stages* the
event; `after_commit` promotes and `after_rollback` discards, as for any
notification.

### Bounded, in three places

* **Per transaction, server side.** Twelve marks saved together are one piece
  of news to a badge, so one frame.
* **Across transactions, client side.** A leading-edge throttle per topic
  (`REFETCH_WINDOW_MS`): the first event refetches immediately so the screen is
  live, and the rest of a burst collapses into one trailing refetch. Measured:
  **12 writes produced 5 refetches, not 12.**
* **Presence reports transitions only.** `touch()` is called on every
  heartbeat; returning True each time would mean one person at their desk
  publishing to every administrator for ever. Arrivals and clean departures
  announce; heartbeats do not. A browser that was *killed* cannot announce
  anything -- nothing runs when a window lapses -- which is why a slow poll
  stays underneath.

Polling is now a backstop rather than the mechanism: dashboard 10 min (was: no
interval at all), today's classes 5 min (was 1), presence 90 s (was 30) while
the stream is up, and the short intervals when it is not. `useRealtimeLive()`
shares that flag through `useSyncExternalStore`, because the connection is
opened in the topbar and the dashboard is its sibling, not its child.

### The badge shows the exact figure on hover, and on tap

`components/ui/count-badge.tsx`, used by both the sidebar and the topbar.

* The sidebar now abbreviates at **999** rather than 99, so most counts simply
  show in full and need no reveal.
* **Hover or focus** reveals the exact figure; **tapping** does too, because
  touch has no hover. The badge takes that tap instead of following the link
  underneath -- a deliberate exception, since it is a ~20px target inside a much
  larger one and somebody aiming at it wants the number. Everything else on the
  row navigates as before, and a badge that is *not* abbreviated stays inert
  rather than swallowing taps for nothing.
* **A span, never a button**: these render inside `<Link>`, and a button inside
  an anchor is invalid HTML that hydrates inconsistently -- a trap already hit
  once here, in the tenant switcher. The exact count reaches assistive
  technology through `aria-label` on every render, so a screen reader never
  hears "99 plus" and never depends on the reveal.

### Verified live, which is what found the real defect

Driven in a browser against the running stack. A course created through the
real endpoint moved the sidebar badge **32 to 33 with no reload**, and one
write triggered exactly three refetches (`/sidebar/counts`, `/dashboard`,
`/dashboard/today` -- the last by prefix match) and nothing else. Twelve
messages sent from a *second user's session* moved the topbar badges to "9+"
and the dashboard KPIs to 12, live; hovering showed "12 unread messages", and
at 375px a tap showed the same. A second user connecting from another session
appeared in Active Users within seconds, and their login also raised a
`directory` frame -- the hook working on a path nobody wrote code for.

**Tests:** 753 backend (15 new topic tests, 9 detection, 4 presence
transitions), 267 frontend (7 new topic/throttle, 10 badge). Mutation-tested
**12/12** on the topic layer plus the presence transition, including the
regression that would put detection back on `before_commit`.

### A pre-existing test that could not fail

While mutating the rollback listeners, the whole suite stayed green with both
removed. `test_a_rolled_back_transaction_announces_nothing` queued an event,
rolled back, and drained -- but draining reads the *committed* list, which a
transaction that never committed has not filled, so the assertion held whether
the discard ran or not. What `_discard` actually prevents needs a second
transaction: the abandoned event is still queued, and the *next* commit on that
session promotes it. The test now does that, and fails without the listeners.

**Not changed:** writes made outside the application -- direct SQL, another
service against the same database -- raise no event, because the hook is on the
ORM session. Those still correct on the next poll or focus.
