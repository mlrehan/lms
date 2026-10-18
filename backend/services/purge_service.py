"""Permanently deleting a record, and everything that hangs off it.

**The plan is read from the database, never written by hand.** A hand-kept list
of "things to delete first" is wrong the moment somebody adds a table, and it is
wrong silently: the delete either fails with a foreign-key error an
administrator cannot act on, or -- where the constraint happens to be
`ON DELETE CASCADE` -- it succeeds and takes rows nobody listed. So the
dependency graph comes from `pg_constraint` at run time. It cannot drift from
the schema because it *is* the schema.

**The three kinds of dependency behave differently and are reported
differently.** On `users`, this database has 25 `CASCADE`, 22 `SET NULL`,
26 `NO ACTION` and 1 `RESTRICT`:

* `CASCADE` -- the database deletes these itself. Counted and shown, so
  "delete this person" never means more than the person approving it was told.
* `SET NULL` -- the row survives with the link removed. Shown separately,
  because "detached" and "deleted" are different outcomes and a preview that
  merges them is lying by omission. A tutor's `created_by` on somebody else's
  account becoming null is not the loss of that account.
* `NO ACTION` / `RESTRICT` -- the database will refuse. These are the ones this
  service deletes first, deepest-first, inside the same transaction. Without
  them, "delete this user" is a foreign-key error 27 ways.

**Rows are addressed by nested subquery, never by a materialised list of ids.**
Fetching child ids to recurse on would need a cap, and a cap on a *delete* path
is the worst kind: the parent delete would still take every child, so exceeding
it would leave grandchildren whose parent is gone -- found only when the
transaction aborts, or not at all where the constraint allowed it. A selector
costs one statement per table at any row count.

**One transaction.** A partial purge is the worst outcome available: half a
student's record gone and the half that explains it still there. Either the
whole graph goes or none of it does. This service therefore never commits --
the caller owns the transaction, so the audit record and the deletion land
together or not at all.

**Audit evidence is not part of the graph, by construction.** `audit_logs` has
no foreign keys at all -- `actor_user_id` is a plain integer with `actor_email`
stored beside it -- so the record of what was done survives the deletion of
whoever did it and of whatever it was done to. That is what makes it possible
to delete a person and still answer "who deleted them, and when".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import ConflictError, ValidationError
from backend.core.logging import get_logger

logger = get_logger(__name__)

#: How far to follow the graph.
#:
#: Bounded because a cycle -- or a chain nobody intended -- must not turn a
#: preview into an unbounded walk of the whole database while somebody waits.
#: Six is comfortably past the deepest real chain here (user -> enrollment ->
#: submission -> grade), and every self-referencing key in this schema is
#: `SET NULL` or `CASCADE`, so none of them can recurse through the blocking
#: path at all.
MAX_DEPTH = 6

#: Tables this service refuses to touch, whatever it is asked.
#:
#: `alembic_version` would leave the schema unrecognisable to migrations.
#: `permissions`, `roles` and `role_permissions` are the catalogue every gate is
#: resolved against, and deleting a row there does not remove an ability -- it
#: removes the *check* for one. It is the only deletion in this system that
#: grants access rather than withdrawing it.
#: `audit_logs` is the evidence this operation is recorded in.
PROTECTED_TABLES = frozenset(
    {
        "alembic_version",
        "permissions",
        "roles",
        "role_permissions",
        "audit_logs",
    }
)


@dataclass
class Dependency:
    """Rows in one table that depend on what is being deleted."""

    table: str
    column: str
    #: 'cascade' (the database deletes it), 'detach' (the row survives, the
    #: link is cleared) or 'blocks' (the database refuses; we delete it first).
    effect: str
    rows: int
    children: list["Dependency"] = field(default_factory=list)


@dataclass
class PurgePlan:
    table: str
    ids: list[int]
    #: How many of the requested ids actually exist. Fewer than asked for is
    #: worth showing: it usually means somebody else got there first.
    found: int
    deleted: list[Dependency] = field(default_factory=list)
    detached: list[Dependency] = field(default_factory=list)
    #: True if the walk stopped at MAX_DEPTH. The counts are then a floor, not
    #: a total, and must be presented as such rather than as a complete answer.
    truncated: bool = False

    @property
    def total_deleted(self) -> int:
        """Everything that will cease to exist, the targets included."""

        def walk(items: list[Dependency]) -> int:
            return sum(d.rows + walk(d.children) for d in items)

        return self.found + walk(self.deleted)

    @property
    def total_detached(self) -> int:
        def walk(items: list[Dependency]) -> int:
            return sum(d.rows + walk(d.children) for d in items)

        return walk(self.detached)


#: `confdeltype` from `pg_constraint`. 'd' (SET DEFAULT) is treated as blocking
#: rather than guessed at: this schema has none, and if one ever appears the
#: honest response is to refuse and make somebody look, not to assume the
#: default is a value the row can legally hold.
_EFFECT = {"c": "cascade", "n": "detach", "a": "blocks", "r": "blocks"}


class PurgeService:
    """Plan and perform an irreversible delete."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._children: dict[str, list[tuple[str, str, str]]] | None = None
        self._keys: dict[str, str | None] = {}
        #: The ids bound to `:ids` in every selector built during one call.
        #: Set by `plan()` and `purge()`; an instance attribute rather than a
        #: parameter threaded through the walk because every nested selector in
        #: a single call refers to the same root set.
        self._ids: list[int] = []

    # ---------------------------------------------------------------- schema

    async def _children_of(self, table: str) -> list[tuple[str, str, str]]:
        """Tables referencing `table`, as (child table, child column, effect).

        Read once per instance: the walk asks for the same parent repeatedly,
        and the catalogue cannot change under us inside one transaction.

        Multi-column foreign keys are skipped -- there are none in this schema,
        and a single-column selector cannot express one. They are reported by
        `unsupported_constraints()` so the gap is visible rather than assumed
        absent.
        """
        if self._children is None:
            rows = await self.session.execute(
                text(
                    """
                    SELECT c.confrelid::regclass::text AS parent,
                           c.conrelid::regclass::text  AS child,
                           a.attname                   AS child_column,
                           c.confdeltype               AS action
                    FROM pg_constraint c
                    JOIN pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                    WHERE c.contype = 'f'
                      AND array_length(c.conkey, 1) = 1
                      AND c.connamespace = 'public'::regnamespace
                    """
                )
            )
            graph: dict[str, list[tuple[str, str, str]]] = {}
            for parent, child, column, action in rows:
                graph.setdefault(parent, []).append(
                    (child, column, _EFFECT.get(action, "blocks"))
                )
            self._children = graph
        return self._children.get(table, [])

    async def _primary_key(self, table: str) -> str | None:
        """The single-column primary key, or None.

        None means this table cannot be descended *into*: its rows are still
        counted and still deleted by their foreign key, but their own children
        are not followed. The only such table here is `course_tags`, a join
        table with no children, so nothing is missed.
        """
        if table not in self._keys:
            result = await self.session.execute(
                text(
                    """
                    SELECT a.attname FROM pg_index i
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary
                    """
                ),
                {"t": table},
            )
            keys = [r for (r,) in result]
            self._keys[table] = keys[0] if len(keys) == 1 else None
        return self._keys[table]

    async def primary_key(self, table: str) -> str | None:
        """The table's single-column primary key, for callers that need to
        address rows by it. Public because `PurgeAdminService` builds the
        preview's "what you have selected" list from it, and reaching into a
        private helper to do so only hides the coupling."""
        return await self._primary_key(table)

    async def unsupported_constraints(self) -> list[str]:
        """Multi-column foreign keys, which the walk cannot follow.

        Exposed so that "there are none" is a measurement rather than an
        assumption. A deployment that grows one will see it here.
        """
        result = await self.session.execute(
            text(
                """
                SELECT c.conname FROM pg_constraint c
                WHERE c.contype = 'f' AND array_length(c.conkey, 1) > 1
                  AND c.connamespace = 'public'::regnamespace
                """
            )
        )
        return [r for (r,) in result]

    # ------------------------------------------------------------- selectors

    @staticmethod
    def _root_selector(table: str, pk: str) -> str:
        return f'SELECT "{pk}" FROM "{table}" WHERE "{pk}" = ANY(:ids)'

    @staticmethod
    def _child_selector(table: str, column: str, pk: str, parent: str) -> str:
        return f'SELECT "{pk}" FROM "{table}" WHERE "{column}" IN ({parent})'

    async def _count(self, table: str, column: str, parent: str) -> int:
        # Identifiers come from `pg_constraint` and `pg_index`, never from a
        # caller, so they cannot be anything but real names in this database.
        # The only caller-supplied value is `:ids`, which is bound.
        result = await self.session.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IN ({parent})'),
            {"ids": self._ids},
        )
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------ plan

    async def plan(self, table: str, ids: list[int]) -> PurgePlan:
        """What deleting these rows would destroy and what it would detach."""
        self._assert_allowed(table)
        if not ids:
            raise ValidationError("Nothing was selected.")

        pk = await self._primary_key(table)
        if pk is None:
            raise ValidationError(f"{table} has no single-column primary key to delete by.")

        self._ids = ids
        found = int(
            (
                await self.session.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE "{pk}" = ANY(:ids)'),
                    {"ids": ids},
                )
            ).scalar_one()
            or 0
        )
        plan = PurgePlan(table=table, ids=list(ids), found=found)
        if found == 0:
            return plan

        root = self._root_selector(table, pk)
        plan.deleted, plan.detached, plan.truncated = await self._walk(table, root, depth=0)
        return plan

    async def _walk(
        self, table: str, selector: str, *, depth: int
    ) -> tuple[list[Dependency], list[Dependency], bool]:
        if depth >= MAX_DEPTH:
            return [], [], True

        deleted: list[Dependency] = []
        detached: list[Dependency] = []
        truncated = False

        for child, column, effect in await self._children_of(table):
            rows = await self._count(child, column, selector)
            if rows == 0:
                continue
            node = Dependency(table=child, column=column, effect=effect, rows=rows)

            if effect == "detach":
                # The row survives, so nothing below it is affected and there is
                # nothing to walk.
                detached.append(node)
                continue

            child_pk = await self._primary_key(child)
            if child_pk is not None:
                sub = self._child_selector(child, column, child_pk, selector)
                node.children, sub_detached, sub_truncated = await self._walk(
                    child, sub, depth=depth + 1
                )
                detached.extend(sub_detached)
                truncated = truncated or sub_truncated

            deleted.append(node)

        return deleted, detached, truncated

    # ----------------------------------------------------------------- purge

    async def purge(self, table: str, ids: list[int]) -> int:
        """Delete the rows, and first anything that would otherwise block them.

        Returns how many of the target rows were deleted. Not committed: the
        caller owns the transaction so that the audit record and the deletion
        are one atomic act.
        """
        self._assert_allowed(table)
        pk = await self._primary_key(table)
        if pk is None:
            raise ValidationError(f"{table} has no single-column primary key to delete by.")

        self._ids = ids
        root = self._root_selector(table, pk)
        await self._delete_blockers(table, root, depth=0)
        result = await self.session.execute(
            text(f'DELETE FROM "{table}" WHERE "{pk}" = ANY(:ids)'), {"ids": ids}
        )
        return int(result.rowcount or 0)

    async def _delete_blockers(self, table: str, selector: str, *, depth: int) -> None:
        """Depth-first: a blocker's own blockers go before it does.

        Reaching the depth limit raises rather than carrying on. Carrying on
        would issue a delete the database then refuses, which aborts the
        transaction with a foreign-key error instead of the sentence an
        administrator can act on.
        """
        if depth >= MAX_DEPTH:
            raise ConflictError(
                "This record's dependencies are nested deeper than this tool follows. "
                "Delete the dependent records first, or raise it with support."
            )
        for child, column, effect in await self._children_of(table):
            if effect != "blocks":
                continue
            child_pk = await self._primary_key(child)
            if child_pk is not None:
                sub = self._child_selector(child, column, child_pk, selector)
                await self._delete_blockers(child, sub, depth=depth + 1)
            # Deleted by the foreign key, so this covers every matching row
            # regardless of how many there are -- see the module docstring on
            # why ids are never materialised.
            await self.session.execute(
                text(f'DELETE FROM "{child}" WHERE "{column}" IN ({selector})'),
                {"ids": self._ids},
            )

    # ------------------------------------------------------------ safeguards

    @staticmethod
    def _assert_allowed(table: str) -> None:
        if table in PROTECTED_TABLES:
            raise ConflictError(
                f"{table} cannot be deleted from here. Removing a row from the "
                "permission catalogue does not withdraw an ability -- it removes "
                "the check for one; and the audit trail is the record this "
                "operation is itself written to."
            )
