# Where this stopped

Written 2026-09-10. A precise snapshot so the next session resumes without
re-deriving anything. Durable architecture and decisions live in
[`../../CLAUDE.md`](../../CLAUDE.md) and [`../README.md`](../README.md); this
file is only "what state is the machine in, and what is left".

---

## Done and verified

The console is complete and was driven live against the real API and Postgres.

* **45 routes** — 41 pages and 4 API routes. `next build` lists 46 entries,
  the extra being its own built-in `/_not-found`.
* `npm run build` **green** (Next 16.3.4, Turbopack; TypeScript checked
  in-build). `tsc --noEmit` clean. `eslint src` **0 errors**, 7 informational
  `react-hooks/incompatible-library` warnings — the React Compiler declining
  to optimise components that use react-hook-form; not actionable without
  dropping RHF.
* **72 tests across 8 files, all passing** (`npx vitest run`, ~20s).
* **Mutation sweep: 14 of 14 caught, restored green** — one clean
  end-to-end run, `python -u scripts/mutation_test.py`.
* Live checks that passed, in a browser against the running stack:
  * sign in as `superadmin`, dashboard renders real data (17 users, 4
    published courses, 5 batches, 66.7% attendance);
  * sign in as `tina.tutor`, sidebar renders **20 of 32** screens, `/audit`
    refuses by name, and `audit-logs` / `roles` / `settings` /
    `security/summary` called straight through the proxy all return **403**
    from the API while `courses` returns 200;
  * `document.cookie` empty, `localStorage` and `sessionStorage` empty —
    the browser holds no token;
  * sign-out revokes for real (token created 17:51:54, `revoked_at`
    17:51:56); `?scope=all` revokes every session;
  * timezone switch re-renders the same stored instants 15:00 Asia/Dhaka →
    09:00 Europe/London;
  * `GET /api/locale` resolves `icanhazip` → `ipapi.co` → `Asia/Dhaka, BD,
    bn-BD`.

### Both branches of the audit fix are verified live

`backend/repositories/audit.py` changed two call sites. The **list** path was
verified during the console pass; the **`entity_id` filter** path
(`entity_pk`) was verified afterwards: filtering the audit log by an
enrollment's public id returns `200` with exactly 1 row of the 3 enrollment
audit rows present.

That the fix is load-bearing was proved directly rather than assumed —
`Enrollments` is keyed `enrollment_id`, `Enrollments.id` raises
`AttributeError`, and **exactly 1 of the 29 registry entries** lacks an `.id`.
That ratio is why the original 500 looked intermittent: it fired only on a
page that happened to contain an enrollment row. All 29 entries resolve a
primary key under the fix.

### Five defects found and fixed

All five, with the reasoning, are written up in `CLAUDE.md` under
**The console (frontend) → Five defects found by driving it**. In short: the
sign-in form could put the password in the URL; sign-out revoked nothing; the
proxy had no upstream timeout; `GET /audit-logs` 500'd on any page containing
an enrollment row (a **backend** fix, in `backend/repositories/audit.py`); and
the §53 IP lookup failed silently against `ipapi.co`'s user-agent rule.

---

## Left running / left changed on this machine

| Thing | State | To undo |
|---|---|---|
| LMS API on `:8000` | **running** (`python -m backend.main`) | `Stop-Process` the PID owning port 8000. |
| Postgres `postgresql-x64-17` | **running** (the user started it; start type is Manual, so it does not come back on its own) | `Stop-Service postgresql-x64-17`, elevated |
| Next dev server on `:3000` | stopped | `cd frontend && npm run dev` |
| `frontend/.env.local` | created, gitignored | contains only `LMS_API_URL=http://127.0.0.1:8000/api/v1` |
| Demo account passwords | **reset in the local database** | see below |
| `.claude/launch.json` | added an `lms-console` entry | note: the Browser-pane preview tool reads the *session root* config, which on this machine belongs to an unrelated project — start the dev server directly instead |

### Demo passwords

To drive the console live, five seeded accounts had their password set to a
single known value directly in the local development database:
`superadmin`, `nst_staff`, `tina.tutor`, `alice.student`, `gary.guardian`.

The value is **not recorded in this repository**. It is a throwaway credential
for a local Postgres containing only fake seed data; regenerate it in one step
if it is not to hand:

```python
# .venv/Scripts/python.exe, from the repo root
from backend.security.password import hash_password
# UPDATE users SET hashed_password = :digest WHERE username = ANY(:names)
```

If this database is ever shared or promoted, rotate these first.

---

## What is genuinely unfinished

Everything that was outstanding has been run. One thing remains, and it is
the user's call rather than a task:

1. **Nothing is committed.** The user committed mid-session
   (`911c813 second initial commit`, 2026-09-09 19:16) capturing the console
   in progress; everything after that — all five fixes, the tests, the
   generators, the docs — is uncommitted. ~72 paths are modified or untracked.
   Note that `frontend/AGENTS.md` and `frontend/CLAUDE.md` are written by
   `next dev` itself rather than by hand; Next re-creates them, so committing
   them with the work keeps the tree clean.

### Notes on the mutation harness

Two host-specific hazards, both handled by the script but worth knowing:
vitest occasionally hangs instead of failing to spawn a worker (each run is
bounded at 300s and a hang is reported `INCONCLUSIVE`, never counted as
caught), and a **force-killed** sweep leaves a mutated file on disk — it now
writes `.mutation-backup` copies and repairs them at the start of the next
run. That recovery has since fired for real twice, both times after a session
teardown killed a sweep mid-mutation.

---

## Known limits, stated rather than left to be discovered

* **ESLint 10 cannot load `next/core-web-vitals`** — the bundled
  `eslint-plugin-react` calls `context.getFilename()`, removed in ESLint 10.
  `eslint.config.mjs` assembles the TypeScript, React Hooks and Next
  core-web-vitals rules directly. Nothing is suppressed; what is lost is
  `eslint-plugin-jsx-a11y`, which cannot be imported on its own because it is
  nested inside `eslint-config-next`. Installing ESLint 9 would restore it —
  attempted here, but `npm install` repeatedly exceeded 10 minutes on this
  host and the lockfile stayed on 10.
* **Do not run the test suite beside `next dev` and the API.** They compete
  for the same cores; vitest then fails to spawn workers, and Argon2 sign-in
  through the API took 44 seconds under load.
* The full backend-gap list — what the console deliberately does *not* offer,
  and why — is [`BACKEND-GAPS.md`](BACKEND-GAPS.md), beside this file.
