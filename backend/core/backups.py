"""Is there a recent, readable backup? One answer for every operation that asks.

Two operations refuse to run without one -- the complete system reset, and a
Super Admin's confirmed SQL change through the AI assistant -- and they must
not disagree about what counts. Both read the same configured dump file.

This verifies a real file: that it exists, that it is not empty, and that it
is recent. It does not and cannot verify that the dump is *restorable* -- only
a restore proves that, and claiming more than was checked is how a backup
policy becomes decoration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def backup_blockers(path: Path | None, *, max_age_hours: int, action: str) -> list[str]:
    """Reasons `action` may not run for want of a backup; empty means it may.

    `action` names the operation in the messages ("A reset", "This change").
    """
    if path is None:
        return [
            f"No backup has been configured (APP_SYSTEM_RESET_BACKUP_PATH). {action} "
            "cannot be undone, so it will not run without one. Note that this "
            "checks a recent dump file exists and is readable — only a test "
            "restore proves a backup is good."
        ]
    try:
        if not path.exists():
            return [f"The configured backup was not found at {path}."]
        stat = path.stat()
        if stat.st_size == 0:
            return [f"The configured backup at {path} is empty."]
        age_hours = (datetime.now(UTC).timestamp() - stat.st_mtime) / 3600
        if age_hours > max_age_hours:
            return [
                f"The configured backup at {path} is {age_hours:.0f} hours old; "
                f"{action[0].lower() + action[1:]} requires one no older than {max_age_hours} hours. "
                "Take a fresh backup first."
            ]
    except OSError as exc:
        # Unreadable is a refusal, not a pass: it means the state of the backup
        # is unknown, which is the one case where carrying on is least defensible.
        return [f"The configured backup at {path} could not be read: {exc}."]
    return []
