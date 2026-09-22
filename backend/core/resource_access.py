"""What a person may actually *do* with a file.

`ResourcePermissionLevel` has existed since the resource module was written --
VIEW / DOWNLOAD / EDIT / MANAGE, stored on every grant -- and nothing ever read
it back. Access was a single boolean: reachable, or not. Once a file was
reachable the level was ignored, so a student granted VIEW could call
`/download` and receive the bytes, and a tutor could delete a file that had been
shared with them read-only.

This module is the missing half. It is deliberately small and pure so the
ordering can be unit-tested without a database, and so every call site asks the
same question in the same words.

**The levels are a ladder, not a set.** MANAGE implies EDIT implies DOWNLOAD
implies VIEW. Modelling them as independent flags would mean every call site
re-deciding whether "can edit" also means "can read", and they would not all
decide the same way.
"""

from __future__ import annotations

from backend.utils.enums import ResourcePermissionLevel

#: Rank of each level. Higher is strictly more capable.
LEVEL_RANK: dict[ResourcePermissionLevel, int] = {
    ResourcePermissionLevel.VIEW: 0,
    ResourcePermissionLevel.DOWNLOAD: 1,
    ResourcePermissionLevel.EDIT: 2,
    ResourcePermissionLevel.MANAGE: 3,
}


def at_least(
    actual: ResourcePermissionLevel | None, required: ResourcePermissionLevel
) -> bool:
    """Does `actual` reach `required` on the ladder? `None` means no access."""
    if actual is None:
        return False
    return LEVEL_RANK[actual] >= LEVEL_RANK[required]


def highest(
    *levels: ResourcePermissionLevel | None,
) -> ResourcePermissionLevel | None:
    """The most capable of several routes to the same file.

    Someone can reach one file through a course grant *and* a direct share; the
    generous route wins, because refusing an action the person is entitled to by
    another path is the more surprising failure.
    """
    present = [level for level in levels if level is not None]
    if not present:
        return None
    return max(present, key=lambda level: LEVEL_RANK[level])
