"""Permanently deleting a record, proven against the real schema.

**Why this cannot be a unit test.** The whole design reads the foreign-key
graph out of `pg_constraint` at run time, precisely so it cannot drift from the
schema. A fake graph would test the walker against a fiction and prove nothing
about this database -- which is the only thing anybody cares about, because the
failure mode being guarded against is "somebody added a table and the delete
now fails, or quietly takes more than it listed".

**Every row these tests touch is created by them**, with a unique tag in the
username and title, and every assertion about what *survived* is made against
counts taken before the purge. Nothing pre-existing is selected, and the final
check is that the untouched tables hold exactly as many rows as they did at the
start.

The case that matters most is `class_performance_marks.recorded_by`, the single
`RESTRICT` foreign key in the entire schema. Postgres refuses to delete a user
who recorded a participation mark, so a purge that did not delete blockers
first would fail on exactly this row -- and only against the real constraint
can that be demonstrated.
"""

from __future__ import annotations

import asyncio
import selectors
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.services.purge_admin_service import PurgeAdminService
from backend.services.purge_service import PurgeService

#: Tables asserted to be the same size afterwards. If the walker ever reaches
#: beyond what it was asked for, one of these moves.
#:
#: **This needs the database to itself.** The assertion is a global row count,
#: which is what makes "and nothing else changed" mean anything -- and it fails
#: spuriously if a second test run is inserting rows at the same time. Observed
#: for real: `users` went *up* by two mid-test with another pytest session
#: going. Do not run two suites against this database at once; weakening the
#: assertion to tolerate it would delete the only thing it proves.
WITNESS_TABLES = (
    "users",
    "courses",
    "batches",
    "roles",
    "permissions",
    "role_permissions",
    "grading_schemes",
    "countries",
)


@pytest.fixture()
def env():
    tag = "pg" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="purge-tests")

    def run(fn):  # noqa: ANN001, ANN202
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)

        return loop.run_until_complete(go())

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run)))
    try:
        yield ns
    finally:
        # Belt and braces: the tests delete their own rows, but a failure
        # halfway through must not leave fixtures behind in a shared database.
        #
        # The audit entries these tests write are **not** cleaned up, and
        # cannot be: `trg_audit_logs_append_only` refuses DELETE, UPDATE and
        # TRUNCATE on that table. They are honest records of real deletions
        # that really happened, carrying the test tag in `actor_email`, and the
        # schema's position is that such records are not ours to remove.
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                await s.execute(
                    text(
                        "DELETE FROM class_performance_marks WHERE student_id IN "
                        "(SELECT id FROM users WHERE username LIKE :t) "
                        "OR recorded_by IN (SELECT id FROM users WHERE username LIKE :t)"
                    ),
                    {"t": f"{tag}%"},
                )
                for stmt in (
                    "DELETE FROM assignment_submissions WHERE student_id IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM attendances WHERE student_id IN (SELECT id FROM users WHERE username LIKE :t) OR recorded_by IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM enrollments WHERE student_id IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM assignments WHERE title LIKE :t",
                    "DELETE FROM batch_sessions WHERE tutor_id IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM batches WHERE batch_code LIKE :t",
                    "DELETE FROM courses WHERE title LIKE :t",
                    "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE username LIKE :t)",
                    "DELETE FROM users WHERE username LIKE :t",
                ):
                    await s.execute(text(stmt), {"t": f"{tag}%"})

        loop.run_until_complete(cleanup())
        loop.run_until_complete(db.dispose())
        loop.close()


async def _counts(s, tables=WITNESS_TABLES) -> dict[str, int]:
    # Column names chosen to avoid `Row.t` / `Row.n`, which collide with
    # Row's own underscored attributes and resolve to the wrong thing.
    union = " UNION ALL ".join(f"SELECT '{t}' AS tbl, count(*) AS cnt FROM \"{t}\"" for t in tables)
    rows = await s.execute(text(union))
    return {r.tbl: int(r.cnt) for r in rows}


async def _make_user(s, tag: str, suffix: str) -> int:
    row = await s.execute(
        text(
            """
            INSERT INTO users (username, slug, hashed_password, public_id, status, first_name, last_name)
            VALUES (:u, :u, 'x-not-a-real-hash', gen_random_uuid(), 'ACTIVE', 'Test', :s)
            RETURNING id
            """
        ),
        {"u": f"{tag}-{suffix}", "s": suffix},
    )
    return int(row.scalar_one())


async def _fixture_graph(s, tag: str) -> dict[str, int]:
    """A student with a full academic footprint, all of it tagged.

    Deliberately includes one row behind each kind of foreign key: a cascade
    (`notifications`), a blocker (`enrollments`, `assignment_submissions`) and
    the schema's only RESTRICT (`class_performance_marks.recorded_by`).
    """
    student = await _make_user(s, tag, "student")
    tutor = await _make_user(s, tag, "tutor")

    course = int(
        (
            await s.execute(
                text(
                    "INSERT INTO courses (title, public_id, status) "
                    "VALUES (:t, gen_random_uuid(), 'DRAFT') RETURNING id"
                ),
                {"t": f"{tag}-course"},
            )
        ).scalar_one()
    )
    batch = int(
        (
            await s.execute(
                text(
                    "INSERT INTO batches (batch_code, course_id, public_id) "
                    "VALUES (:c, :co, gen_random_uuid()) RETURNING id"
                ),
                {"c": f"{tag}-batch", "co": course},
            )
        ).scalar_one()
    )
    session_id = int(
        (
            await s.execute(
                text(
                    "INSERT INTO batch_sessions (batch_id, tutor_id, public_id, session_start_time) "
                    "VALUES (:b, :t, gen_random_uuid(), :when) RETURNING id"
                ),
                {"b": batch, "t": tutor, "when": datetime.now(UTC)},
            )
        ).scalar_one()
    )
    await s.execute(
        text(
            "INSERT INTO enrollments (batch_id, student_id, public_id, status) "
            "VALUES (:b, :s, gen_random_uuid(), 'ACTIVE')"
        ),
        {"b": batch, "s": student},
    )
    assignment = int(
        (
            await s.execute(
                text(
                    "INSERT INTO assignments (course_id, title, due_date, max_score, submission_type, public_id) "
                    "VALUES (:c, :t, :d, 100, 'FILE', gen_random_uuid()) RETURNING id"
                ),
                {"c": course, "t": f"{tag}-assignment", "d": datetime.now(UTC) + timedelta(days=7)},
            )
        ).scalar_one()
    )
    await s.execute(
        text(
            "INSERT INTO assignment_submissions (assignment_id, student_id, submitted_at, public_id) "
            "VALUES (:a, :s, :w, gen_random_uuid())"
        ),
        {"a": assignment, "s": student, "w": datetime.now(UTC)},
    )
    await s.execute(
        text(
            "INSERT INTO notifications (user_id, channel, type, title, body, public_id) "
            "VALUES (:u, 'IN_APP', 'TEST', :t, 'body', gen_random_uuid())"
        ),
        {"u": student, "t": f"{tag}-notification"},
    )
    # The RESTRICT edge, twice over: the student is the subject and the tutor
    # is the recorder. Deleting either must work.
    await s.execute(
        text(
            "INSERT INTO class_performance_marks (public_id, session_id, student_id, recorded_by) "
            "VALUES (gen_random_uuid(), :sess, :stu, :tut)"
        ),
        {"sess": session_id, "stu": student, "tut": tutor},
    )
    return {
        "student": student,
        "tutor": tutor,
        "course": course,
        "batch": batch,
        "session": session_id,
        "assignment": assignment,
    }


class _Actor:
    """Stands in for the signed-in Super Admin. Never a real account row.

    The service only reads `id`, `email` and `username` off the actor, and
    using a real administrator here would put a live account id into an audit
    payload for a deletion that was a test.
    """

    def __init__(self, tag: str) -> None:
        self.id = -1
        self.email = f"{tag}-actor@test.invalid"
        self.username = f"{tag}-actor"


# =============================================================================
# The dependency plan
# =============================================================================


def test_the_plan_is_read_from_the_real_schema(env):
    """The walk finds the actual dependants, not a hand-written list."""

    async def check(s):  # noqa: ANN001, ANN202
        ids = await _fixture_graph(s, env.tag)
        plan = await PurgeService(s).plan("users", [ids["student"]])

        assert plan.found == 1
        tables = {d["table"] for d in _flat(plan.deleted)}
        # Each of these is reached only by following a real foreign key.
        assert "enrollments" in tables
        assert "assignment_submissions" in tables
        assert "notifications" in tables
        assert "class_performance_marks" in tables
        # The targets plus their dependants, so strictly more than one row.
        assert plan.total_deleted > plan.found

    env.run(check)


def test_set_null_dependants_are_reported_as_detached_not_deleted(env):
    """A row that survives with a cleared reference is not a deletion.

    `batch_sessions.tutor_id` is NO ACTION, but `users.created_by` and friends
    are SET NULL, so deleting a user that created another account detaches
    rather than destroys. Reporting those as deletions would overstate the
    damage by however many rows the person had ever touched.
    """

    async def check(s):  # noqa: ANN001, ANN202
        creator = await _make_user(s, env.tag, "creator")
        made = await _make_user(s, env.tag, "made")
        await s.execute(
            text("UPDATE users SET created_by = :c WHERE id = :m"), {"c": creator, "m": made}
        )

        plan = await PurgeService(s).plan("users", [creator])
        detached = {d["table"] for d in _flat(plan.detached)}
        deleted = {d["table"] for d in _flat(plan.deleted)}
        assert "users" in detached, "the account this person created should be detached"
        assert "users" not in deleted, "deleting a creator must not delete who they created"

        # And the account really does survive.
        await PurgeAdminService(s).purger.purge("users", [creator])
        still_there = (
            await s.execute(text("SELECT count(*) FROM users WHERE id = :m"), {"m": made})
        ).scalar_one()
        assert still_there == 1

    env.run(check)


def test_the_schema_has_no_foreign_key_the_walk_cannot_follow(env):
    """A multi-column foreign key would be silently skipped.

    Asserted rather than assumed: if a later migration adds one, this fails and
    says so, instead of the purge quietly leaving its rows behind.
    """

    async def check(s):  # noqa: ANN001, ANN202
        assert await PurgeService(s).unsupported_constraints() == []

    env.run(check)


# =============================================================================
# The deletion
# =============================================================================


def test_a_restricting_dependant_does_not_block_the_delete(env):
    """The schema's only RESTRICT is deleted first, in the same transaction.

    Postgres refuses `DELETE FROM users` while `class_performance_marks`
    references it. This is the one case a cascade-only implementation would
    fail on, and it fails loudly rather than silently -- which is why it is the
    best possible proof that blockers are handled.
    """

    async def check(s):  # noqa: ANN001, ANN202
        ids = await _fixture_graph(s, env.tag)

        # The plan names the RESTRICT edge as a blocker. Asserted on the plan
        # rather than on the database's error text, because Postgres reports
        # whichever blocking constraint it happens to check first and there are
        # several -- so pinning one constraint name is a flaky test, not a
        # stricter one.
        plan = await PurgeService(s).plan("users", [ids["tutor"]])
        blocking = {d["table"] for d in _flat(plan.deleted) if d["effect"] == "blocks"}
        assert "class_performance_marks" in blocking

        # And the refusal is real: a direct delete cannot go through.
        with pytest.raises(Exception) as refused:  # noqa: PT011 - DBAPIError subclass
            async with s.begin_nested():
                await s.execute(text("DELETE FROM users WHERE id = :i"), {"i": ids["tutor"]})
        assert "violates foreign key constraint" in str(refused.value)

        deleted = await PurgeService(s).purge("users", [ids["tutor"]])
        assert deleted == 1
        gone = (
            await s.execute(text("SELECT count(*) FROM users WHERE id = :i"), {"i": ids["tutor"]})
        ).scalar_one()
        assert gone == 0

    env.run(check)


def test_the_delete_takes_the_dependants_and_nothing_else(env):
    """Everything below the target goes; every witness table is unchanged."""

    async def check(s):  # noqa: ANN001, ANN202
        ids = await _fixture_graph(s, env.tag)
        before = await _counts(s)

        service = PurgeAdminService(s)
        preview = await service.preview("user", [ids["student"]], actor=_Actor(env.tag))
        result = await service.execute(
            "user",
            [ids["student"]],
            actor=_Actor(env.tag),
            confirmation=preview.confirmation_phrase,
        )
        assert result.found == 1

        for table, column in (
            ("enrollments", "student_id"),
            ("assignment_submissions", "student_id"),
            ("notifications", "user_id"),
            ("class_performance_marks", "student_id"),
        ):
            left = (
                await s.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column} = :i"),
                    {"i": ids["student"]},
                )
            ).scalar_one()
            assert left == 0, f"{table} still references the deleted student"

        after = await _counts(s)
        # Exactly one user fewer. Every other witness identical: the catalogue,
        # the reference data and the course and batch the student was in.
        assert after["users"] == before["users"] - 1
        for table in WITNESS_TABLES:
            if table == "users":
                continue
            assert after[table] == before[table], f"{table} changed and should not have"

    env.run(check)


def test_a_two_level_chain_of_blockers_is_deleted_deepest_first(env):
    """Deleting a course needs its assignments gone, and theirs their submissions.

    `courses -> assignments` and `assignments -> assignment_submissions` are
    both NO ACTION, so this is a real two-level chain: deleting the assignments
    while a submission still references one is refused by the database.
    Depth-first ordering is the only thing that makes it work, and nothing else
    in these tests exercises more than one level -- a mutation that stopped the
    recursion at the first level passed the whole suite until this existed.
    """

    async def check(s):  # noqa: ANN001, ANN202
        ids = await _fixture_graph(s, env.tag)
        before = await _counts(s)

        plan = await PurgeService(s).plan("courses", [ids["course"]])
        flat = _flat(plan.deleted)
        # The chain is visible in the plan, with the submission below the
        # assignment rather than beside it.
        assert any(d["table"] == "assignments" and d["effect"] == "blocks" for d in flat)
        assert any(d["table"] == "assignment_submissions" for d in flat)

        deleted = await PurgeService(s).purge("courses", [ids["course"]])
        assert deleted == 1

        for table, column, value in (
            ("assignments", "course_id", ids["course"]),
            ("assignment_submissions", "assignment_id", ids["assignment"]),
            ("batches", "course_id", ids["course"]),
            ("enrollments", "batch_id", ids["batch"]),
            ("batch_sessions", "batch_id", ids["batch"]),
        ):
            left = (
                await s.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column} = :v"), {"v": value}
                )
            ).scalar_one()
            assert left == 0, f"{table} survived the deletion of its course"

        after = await _counts(s)
        assert after["courses"] == before["courses"] - 1
        # The two people stay: a course is not its students.
        assert after["users"] == before["users"]
        for table in ("roles", "permissions", "role_permissions", "countries"):
            assert after[table] == before[table]

    env.run(check)


def test_the_audit_record_outlives_the_record_it_describes(env):
    """The point of `audit_logs` having no foreign keys.

    The deleted user's id is in the audit payload, and the audit row is still
    readable after the user is gone -- in the same transaction that deleted
    them, so there is no window in which the deletion exists and its record
    does not.
    """

    async def check(s):  # noqa: ANN001, ANN202
        ids = await _fixture_graph(s, env.tag)
        actor = _Actor(env.tag)
        service = PurgeAdminService(s)
        preview = await service.preview("user", [ids["student"]], actor=actor)
        await service.execute(
            "user", [ids["student"]], actor=actor, confirmation=preview.confirmation_phrase
        )

        # The service stages the row in the caller's transaction by design --
        # the router is what commits. Here the test owns it, so flushing is the
        # test's job.
        await s.flush()
        row = (
            await s.execute(
                text(
                    "SELECT entity_type, details FROM audit_logs "
                    "WHERE actor_email = :e ORDER BY id DESC LIMIT 1"
                ),
                {"e": actor.email},
            )
        ).one()
        assert row.entity_type == "purge:user"
        assert row.details["permanent"] is True
        assert ids["student"] in row.details["ids"]
        assert row.details["rows_deleted_total"] >= 1

    env.run(check)


# =============================================================================
# The refusals
# =============================================================================


def test_a_stale_confirmation_is_refused(env):
    """The phrase carries the row count, so a changed plan cannot be confirmed.

    Driven by enrolling the student again between preview and execute, which is
    exactly the real race: two administrators, one screen each.
    """

    async def check(s):  # noqa: ANN001, ANN202
        ids = await _fixture_graph(s, env.tag)
        service = PurgeAdminService(s)
        preview = await service.preview("user", [ids["student"]], actor=_Actor(env.tag))

        second = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO batches (batch_code, course_id, public_id) "
                        "VALUES (:c, :co, gen_random_uuid()) RETURNING id"
                    ),
                    {"c": f"{env.tag}-batch2", "co": ids["course"]},
                )
            ).scalar_one()
        )
        await s.execute(
            text(
                "INSERT INTO enrollments (batch_id, student_id, public_id, status) "
                "VALUES (:b, :s, gen_random_uuid(), 'ACTIVE')"
            ),
            {"b": second, "s": ids["student"]},
        )

        with pytest.raises(ValidationError) as refused:
            await service.execute(
                "user",
                [ids["student"]],
                actor=_Actor(env.tag),
                confirmation=preview.confirmation_phrase,
            )
        assert "may have changed" in str(refused.value)

        still_there = (
            await s.execute(
                text("SELECT count(*) FROM users WHERE id = :i"), {"i": ids["student"]}
            )
        ).scalar_one()
        assert still_there == 1, "a refused confirmation must delete nothing"

    env.run(check)


def test_deleting_your_own_account_is_refused(env):
    """The one mistake somebody makes while learning what this screen does."""

    async def check(s):  # noqa: ANN001, ANN202
        victim = await _make_user(s, env.tag, "self")
        actor = _Actor(env.tag)
        actor.id = victim

        service = PurgeAdminService(s)
        preview = await service.preview("user", [victim], actor=actor)
        assert any("your own account" in b for b in preview.blockers)

        with pytest.raises(ConflictError):
            await service.execute(
                "user", [victim], actor=actor, confirmation=preview.confirmation_phrase
            )

    env.run(check)


def test_the_last_active_super_admin_cannot_be_deleted(env):
    """Nothing in the product creates the first Super Admin.

    **`execute` is deliberately never called with a real administrator's id**,
    even to prove it refuses. If the protection were broken, that call would
    delete live accounts from a shared database -- and a test that can cause
    the accident it is checking for is not worth the coverage. So the blocker
    is proven through `preview`, which issues no writes at all, and the
    "blockers mean refusal" half is proven by the self-deletion test above,
    which reaches the identical `if blockers: raise` through a tagged row.

    The scenario is the realistic one: somebody selects the whole list of
    administrators rather than the one leaver they meant.
    """

    async def check(s):  # noqa: ANN001, ANN202
        real_supers = [
            int(r)
            for (r,) in await s.execute(
                text(
                    "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                    "JOIN roles r ON r.id = ur.role_id "
                    "WHERE r.name = 'SUPER_ADMIN' AND u.status = 'ACTIVE' AND u.deleted_at IS NULL"
                )
            )
        ]
        assert real_supers, "the dev database should have at least one Super Admin"

        mine = await _make_user(s, env.tag, "super")
        await s.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT :u, id FROM roles WHERE name = 'SUPER_ADMIN'"
            ),
            {"u": mine},
        )

        service = PurgeAdminService(s)

        # Read-only: selecting every Super Admin raises the blocker.
        everyone = sorted({*real_supers, mine})
        preview = await service.preview("user", everyone, actor=_Actor(env.tag))
        assert any("last active Super Admin" in b for b in preview.blockers)

        # Leaving the real ones in place, deleting only the tagged one is fine.
        ok = await service.preview("user", [mine], actor=_Actor(env.tag))
        assert ok.blockers == [], ok.blockers

        # And that deletion really does go through, so the blocker above is not
        # simply "any Super Admin is undeletable".
        await service.execute(
            "user", [mine], actor=_Actor(env.tag), confirmation=ok.confirmation_phrase
        )
        left = (
            await s.execute(text("SELECT count(*) FROM users WHERE id = :i"), {"i": mine})
        ).scalar_one()
        assert left == 0

    env.run(check)


def test_the_permission_catalogue_and_audit_trail_are_untouchable(env):
    """Refused at the service, whatever is asked, and before any query runs."""

    async def check(s):  # noqa: ANN001, ANN202
        service = PurgeService(s)
        for table in ("permissions", "roles", "role_permissions", "audit_logs", "alembic_version"):
            with pytest.raises(ConflictError):
                await service.plan(table, [1])
            with pytest.raises(ConflictError):
                await service.purge(table, [1])

    env.run(check)


def test_an_unknown_or_blocked_entity_is_refused_by_name(env):
    """A caller names an entity, never a table -- see the registry's docstring."""

    async def check(s):  # noqa: ANN001, ANN202
        service = PurgeAdminService(s)
        with pytest.raises(ValidationError):
            await service.preview("system_settings", [1], actor=_Actor(env.tag))
        with pytest.raises(ValidationError):
            await service.preview("countries", [1], actor=_Actor(env.tag))
        # Asked for by name, refused with the reason rather than "unknown".
        with pytest.raises(ConflictError) as refused:
            await service.preview("permission", [1], actor=_Actor(env.tag))
        assert "removes the check" in str(refused.value)

    env.run(check)


def test_deleting_records_that_no_longer_exist_changes_nothing(env):
    """Two administrators, one list each: the second must not half-succeed."""

    async def check(s):  # noqa: ANN001, ANN202
        victim = await _make_user(s, env.tag, "ghost")
        service = PurgeAdminService(s)
        preview = await service.preview("user", [victim], actor=_Actor(env.tag))
        await s.execute(text("DELETE FROM users WHERE id = :i"), {"i": victim})

        with pytest.raises(NotFoundError):
            await service.execute(
                "user", [victim], actor=_Actor(env.tag), confirmation=preview.confirmation_phrase
            )

    env.run(check)


def _flat(items, out=None):  # noqa: ANN001, ANN202
    out = [] if out is None else out
    for node in items:
        out.append({"table": node.table, "rows": node.rows, "effect": node.effect})
        _flat(node.children, out)
    return out
