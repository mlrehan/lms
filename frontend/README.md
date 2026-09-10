# LMS Console

The administration and learning console for the LMS API in `../backend`.

Next.js 16 (App Router) · TypeScript (strict) · Tailwind v4 · Base UI ·
TanStack Query · Zustand · react-hook-form + zod · Recharts · Vitest.

---

## Running it

```bash
cd frontend
npm install
cp .env.example .env.local     # then point LMS_API_URL at the API
npm run dev
```

The backend must be running separately:

```bash
python main.py                 # serves http://127.0.0.1:8000
```

`.env.local` needs one variable:

```
LMS_API_URL=http://127.0.0.1:8000/api/v1
```

There are deliberately **no `NEXT_PUBLIC_*` variables**. The browser never
talks to the API directly, so it has no reason to know where the API lives —
and telling it invites someone to call the API with a token this design is
built to withhold.

## Checks

```bash
npm run typecheck    # tsc --noEmit
npm run lint         # eslint src
npm test             # vitest run
npm run build        # next build
python scripts/mutation_test.py   # breaks each guard, expects the suite to fail
```

---

## The two rules everything else follows from

### 1. The browser never holds a token

Both the access and refresh tokens live in `httpOnly` cookies. Every API call
goes to `/api/backend/...`, a same-origin proxy
([`src/app/api/backend/[...path]/route.ts`](src/app/api/backend/%5B...path%5D/route.ts))
that attaches the bearer header server-side, refreshes once on a 401 and
retries, and passes status, headers and body through unchanged.

An XSS bug in this console could therefore make requests as the user — nothing
prevents that — but it could not **exfiltrate a credential that keeps working
after the tab is closed**.

Three details in the proxy that are not obvious and are load-bearing:

- **The request body is read as an `ArrayBuffer`, never `request.text()`.**
  Decoding a request as UTF-8 and re-encoding it replaces every byte that is
  not valid UTF-8 with `U+FFFD`. Multipart boundaries are ASCII, so the
  request stays well-formed, the upload still "succeeds", and the file's
  contents are destroyed. Responses stream for the same reason, and so a CSV
  export is not buffered whole in the Node process.
- **Refresh is serialised per token.** The backend rotates refresh tokens and
  treats a second presentation of a used one as theft, revoking the family. A
  page firing six queries at once, each getting a 401 and each refreshing
  independently, would sign the user out rather than recover. Concurrent
  callers share one in-flight refresh
  ([`src/lib/server/upstream.ts`](src/lib/server/upstream.ts)).
- **Sign-out is never retried and never refreshed.** Retrying it would present
  the refresh token the first call just revoked, and reuse detection would
  kill every session on every device.

### 2. The backend is the authorization layer

`can("user.create")` decides what to *show*. It decides nothing about what
anyone may *do*: every request a control would send is authorised again by
`require_permissions(...)` on the server. Someone who edits their permission
list in memory gets a page full of 403s, not access.

Permissions come from `GET /auth/me`, which returns the caller's **effective**
permissions after role resolution. Nothing in this console branches on a role
name — an institution that adds a `REGISTRAR` role holding
`institution.view_all` and no write rights must not need a frontend change,
and `role === "ADMIN"` cannot express that.

---

## Generated files — do not edit by hand

| File | Source | Regenerate |
|---|---|---|
| `src/lib/api/types.ts` | The API's own OpenAPI document (251 schemas) | `python scripts/generate_api_types.py` |
| `src/lib/auth/permission-names.ts` | `backend/core/permissions.py` (97 permissions) | `python scripts/generate_permissions.py` |
| `src/test/role-grants.ts` | the same, role grants — **test fixture only** | as above |

Transcribing 251 response shapes by hand is how a frontend ends up describing
an API that no longer exists. Generating them means a field that is not in the
backend cannot appear here, and one that changes shape becomes a type error
rather than `undefined` on a screen.

The permission union is the same idea one level up: `can("user.creat")` is a
compile error rather than a control that silently never appears for anybody.

`src/test/role-grants.ts` is under `src/test/` and not `src/lib/` on purpose.
It exists so the navigation matrix test can ask "what would a Tutor see?"
without a hand-maintained answer that goes stale — a role→permission map
sitting beside the permission helpers would be an invitation to branch on a
role name in the running console.

---

## Layout

```
src/
  app/
    (app)/                  the signed-in shell; every screen lives here
    api/auth/{login,logout} the only routes that see a token or a password
    api/backend/[...path]   the BFF proxy
    api/locale              server-side timezone discovery (spec §53)
    login/                  the one unauthenticated page
  components/
    ui/                     primitives: button, dialog, table, states, ...
    domain/                 status badges, the user picker
    shell/                  sidebar, top bar, global search, timezone menu
  lib/
    api/                    generated types, client, shared hooks
    auth/                   permissions, session context
    format/                 date and time
    server/                 cookies and upstream (server-only)
    navigation.ts           route → permission map (nav *and* route guard)
```

`src/lib/navigation.ts` is the single place a route is associated with the
permission that makes it usable, so the sidebar and the route guard cannot
disagree about who may open a page.

---

## Dates and times (spec §53)

The database stores UTC and the API returns UTC. Nothing here changes that;
`src/lib/format/datetime.ts` only decides how an instant is *shown*.

Display timezone resolves in this order: an explicit choice in this browser →
the account's stored `timezone` → the browser's own. The globe in the top bar
switches it, and the choice is kept in `localStorage` rather than written to
the profile, so a shared workstation does not silently rewrite a colleague's
setting.

`GET /api/locale` implements the spec's `icanhazip.com` → `ipapi.co` lookup.
It is deliberately **last** in that order and is only called when someone
opens the timezone picker: it involves telling two third parties an IP
address, and behind a proxy or in local development the address it finds is
the *server's*. The response reports which address was used, so a wrong answer
is diagnosable rather than mysterious.

Two conversions are worth knowing about. Instants with no offset are marked
UTC before parsing — read as local time, the whole display is wrong by the
viewer's offset, which looks like a data problem rather than a parsing one.
And `datetime-local` inputs are anchored to the display timezone at the
*candidate instant*, not at "now", so a tutor scheduling 09:00 in
Europe/London sends 08:00Z in summer and 09:00Z in winter.

---

## Testing

`npm test` covers the pieces where being wrong is silent: the permission set,
the route→permission map, the redirect allowlist, query building, date/time
conversion, header stripping in the proxy, refresh serialisation, and the
**RBAC navigation matrix** — what each of the six roles sees, driven from the
backend's real grants.

`python scripts/mutation_test.py` breaks each of those guards in turn and
expects the suite to go red. A negative assertion is worth nothing until a
mutation proves it can fail. Ten mutations, ten caught.

Writing the RBAC matrix from the specification's prose produced four failures,
and the implementation was right in all four: an Administrator holds
`setting.read` and `permission.read` (they may look, not change), a Student
holds `enrollment.read` (their own), and both Tutors and Guardians hold
`user.read` (to look up the people they are responsible for). Read access and
write access are separate grants, and the sidebar gates on read. The test now
says so.

---

## What is missing, and why

[`docs/BACKEND-GAPS.md`](docs/BACKEND-GAPS.md). No screen here fakes a feature
the API does not have: there is no password-reset page, no MFA panel, no
"Coming soon". Where the absence is visible, the screen says so at the point
someone would look for it.
