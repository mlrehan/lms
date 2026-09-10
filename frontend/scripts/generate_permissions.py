"""Generate the frontend's permission constants from the backend catalog.

Writes two files:

* `src/lib/auth/permission-names.ts` -- every permission name the API
  recognises, as a TypeScript union. The catalog is validated at backend
  import time, so a name that reaches this file is a name the API will
  actually accept in `require_permissions(...)`. Typing them by hand on the
  frontend is how a UI ends up gating on a permission that does not exist,
  which fails open in the worst way: `permissions.includes("user.mange")` is
  simply always false, so the control quietly disappears for everyone and
  nothing reports a problem.

* `src/test/role-grants.ts` -- the role to permission map, **for tests
  only**. It is deliberately not in `src/lib/`: nothing in the running
  console may derive authority from a role name, and a role map sitting
  beside the permission helpers is an invitation to do exactly that.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS  # noqa: E402


def write_permission_names() -> int:
    names = sorted(ALL_PERMISSIONS)
    lines = [
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
        *[f'  "{name}",' for name in names],
        "] as const;",
        "",
        "export type PermissionName = (typeof PERMISSION_NAMES)[number];",
        "",
        "/** Human-readable descriptions, as the backend catalog defines them. */",
        "export const PERMISSION_DESCRIPTIONS: Record<PermissionName, string> = {",
        *[f'  "{name}": "{ALL_PERMISSIONS[name]}",' for name in names],
        "};",
        "",
    ]
    out = ROOT / "frontend" / "src" / "lib" / "auth" / "permission-names.ts"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(names)} permissions -> {out}")
    return len(names)


def write_role_grants() -> int:
    lines = [
        "/**",
        " * GENERATED from `backend/core/permissions.py` -- do not edit by hand.",
        " *",
        " *   python frontend/scripts/generate_permissions.py",
        " *",
        " * TEST FIXTURE ONLY. The console never branches on a role name; it asks",
        " * `GET /auth/me` what the caller may actually do. This map exists so the",
        " * navigation matrix test can be driven from the backend's real grants",
        " * rather than a hand-copied guess that quietly goes stale.",
        " */",
        "",
        "export const ROLE_GRANTS: Record<string, readonly string[]> = {",
    ]
    for role in sorted(ROLE_PERMISSIONS):
        members = ", ".join(f'"{name}"' for name in sorted(ROLE_PERMISSIONS[role]))
        lines.append(f"  {role}: [{members}],")
    lines += ["};", ""]

    out = ROOT / "frontend" / "src" / "test" / "role-grants.ts"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(ROLE_PERMISSIONS)} role grants -> {out}")
    return len(ROLE_PERMISSIONS)


def main() -> None:
    write_permission_names()
    write_role_grants()


if __name__ == "__main__":
    main()
