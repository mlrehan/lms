"""Generate `frontend/src/lib/auth/permission-names.ts` from the backend's
permission catalog.

The catalog is validated at backend import time, so a name that reaches this
file is a name the API will actually accept in `require_permissions(...)`.
Typing them out by hand on the frontend is how a UI ends up gating on a
permission that does not exist -- which fails open in the worst way, because
`permissions.includes("user.mange")` is simply always false and the control
just quietly disappears for everyone.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.permissions import ALL_PERMISSIONS  # noqa: E402


def main() -> None:
    names = sorted(ALL_PERMISSIONS)
    lines = [
        "/* eslint-disable */",
        "/**",
        " * GENERATED from `backend/core/permissions.py` -- do not edit by hand.",
        " *",
        " *   python frontend/scripts/generate_permissions.py",
        " *",
        ' * The union type is the point: `can("user.creat")` is a compile error',
        " * rather than a control that silently never appears. The *values* still",
        " * come from the server at runtime -- this file only constrains the names a",
        " * screen is allowed to ask about.",
        " */",
        "",
        "export const PERMISSION_NAMES = [",
        *[f'  "{n}",' for n in names],
        "] as const;",
        "",
        "export type PermissionName = (typeof PERMISSION_NAMES)[number];",
        "",
        "/** Human-readable descriptions, as the backend catalog defines them. */",
        "export const PERMISSION_DESCRIPTIONS: Record<PermissionName, string> = {",
        *[f'  "{n}": "{ALL_PERMISSIONS[n]}",' for n in names],
        "};",
        "",
    ]
    out = ROOT / "frontend" / "src" / "lib" / "auth" / "permission-names.ts"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(names)} permissions -> {out}")


if __name__ == "__main__":
    main()
