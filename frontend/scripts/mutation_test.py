"""Mutation-test the console's guards.

Each entry breaks one guard and runs the test file that claims to cover it,
expecting that file to go red. A mutation the suite survives means the test is
not testing what its name says -- which is the failure mode this exists to
catch, because a negative assertion that cannot fail looks identical to one
that passes.

Naming the file per mutation rather than running everything keeps a full sweep
to a couple of minutes instead of an hour, and asserts something stronger:
that *the test written for this guard* is the one that catches it.

    python scripts/mutation_test.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (name, file to break, text to replace, replacement, test file that must fail)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "safeRedirect accepts anything",
        "src/lib/redirect.ts",
        'if (!trimmed.startsWith("/")) return "/";',
        "// mutated",
        "src/lib/redirect.test.ts",
    ),
    (
        "safeRedirect allows protocol-relative URLs",
        "src/lib/redirect.ts",
        'if (trimmed.startsWith("//")) return "/";',
        "// mutated",
        "src/lib/redirect.test.ts",
    ),
    (
        "refreshTokens does not share an in-flight call",
        "src/lib/server/upstream.ts",
        "  const existing = inFlight.get(refreshToken);\n  if (existing) return existing;",
        "  // mutated",
        "src/lib/server/upstream.test.ts",
    ),
    (
        "the proxy forwards the browser's cookies upstream",
        "src/lib/server/upstream.ts",
        '  "cookie",\n',
        "",
        "src/lib/server/upstream.test.ts",
    ),
    (
        "the proxy waits on an unresponsive API for ever",
        "src/lib/server/upstream.ts",
        "    return await fetch(input, { ...init, signal: controller.signal });",
        "    return await fetch(input, { ...init });",
        "src/lib/server/upstream.test.ts",
    ),
    (
        "an offset-less timestamp is read as local time",
        "src/lib/format/datetime.ts",
        'const normalised = hasTime && !hasZone ? `${trimmed.replace(" ", "T")}Z` : trimmed;',
        "const normalised = trimmed;",
        "src/lib/format/datetime.test.ts",
    ),
    (
        "the DST-aware offset is measured at 'now' instead of the instant",
        "src/lib/format/datetime.ts",
        "const offset = timeZoneOffsetMs(new Date(asUtc), timeZone);",
        "const offset = timeZoneOffsetMs(new Date(Date.UTC(2026, 0, 1)), timeZone);",
        "src/lib/format/datetime.test.ts",
    ),
    (
        "empty query values are sent rather than omitted",
        "src/lib/api/client.ts",
        'if (value === undefined || value === null || value === "") continue;',
        "if (value === undefined) continue;",
        "src/lib/api/client.test.ts",
    ),
    (
        "path segments are interpolated unencoded",
        "src/lib/api/client.ts",
        "return encodeURIComponent(String(value));",
        "return String(value);",
        "src/lib/api/client.test.ts",
    ),
    (
        "the sidebar stops filtering by permission",
        "src/components/shell/sidebar.tsx",
        "      if (item.anyPermission) return permissions.hasAny(...item.anyPermission);\n"
        "      if (!item.permission) return true;\n"
        "      return permissions.has(item.permission);",
        "      return true;",
        "src/components/shell/sidebar.test.tsx",
    ),
    (
        "an empty permission set reads as unrestricted",
        "src/lib/auth/permissions.ts",
        "    has: (permission) => set.has(permission),",
        "    has: (permission) => set.size === 0 || set.has(permission),",
        "src/lib/auth/permissions.test.ts",
    ),
    (
        "a form may submit as GET, putting its fields in the URL",
        "src/app/login/page.tsx",
        # Anchored together with the line after it: `method="post"` on its own
        # also matches the explanatory *comment* above the real attribute, and
        # removing the comment instead of the attribute is not the mutation
        # this entry means. That imprecision is what let the first version of
        # `forms.test.ts` survive.
        '      method="post"\n      className="space-y-4"',
        '      className="space-y-4"',
        "src/app/forms.test.ts",
    ),
    (
        "sign-out omits the bearer token, so the API revokes nothing",
        "src/app/api/auth/logout/route.ts",
        'const headers: Record<string, string> = { authorization: `Bearer ${accessToken}` };',
        "const headers: Record<string, string> = {};",
        "src/app/api/auth/logout/route.test.ts",
    ),
    (
        "sign-out sends no refresh token, so no session is identified",
        "src/app/api/auth/logout/route.ts",
        'body = JSON.stringify({ refresh_token: refreshToken ?? "" });',
        'body = JSON.stringify({});',
        "src/app/api/auth/logout/route.test.ts",
    ),
]


# Vitest on this host occasionally fails to spawn a worker and then hangs
# rather than erroring, so every run is bounded and a timeout is *reported*
# instead of stalling the sweep. A run that hangs is not evidence either way,
# and saying so is better than a number that quietly excludes it.
RUN_TIMEOUT_SECONDS = 300


def run(paths: list[str]) -> tuple[bool | None, str]:
    """(passed, tail). `None` means the run never finished."""
    try:
        result = subprocess.run(
            ["npx.cmd" if sys.platform == "win32" else "npx", "vitest", "run", "--reporter=dot", *paths],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None, f"vitest did not finish within {RUN_TIMEOUT_SECONDS}s"
    return result.returncode == 0, ((result.stdout or "") + (result.stderr or ""))[-500:]


def safe(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def restore_all() -> list[str]:
    """Put every mutated file back, from the copies taken before the run.

    `finally` restores a file after each mutation, but a *force-killed*
    process never reaches it -- which happened once here and left
    `datetime.ts` mutated on disk. The baseline check caught it on the next
    run, which is what that check is for; this makes the recovery automatic
    rather than a thing to remember.
    """
    repaired: list[str] = []
    for backup in ROOT.glob("**/*.mutation-backup"):
        original = backup.with_suffix("")
        original.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        backup.unlink()
        repaired.append(str(original.relative_to(ROOT)))
    return repaired


def main() -> int:
    repaired = restore_all()
    if repaired:
        print("recovered leftover mutations from an interrupted run:")
        for name in repaired:
            print(" -", name)
        print()

    files = sorted({mutation[4] for mutation in MUTATIONS})
    ok, output = run(files)
    if ok is None:
        print("BASELINE DID NOT FINISH -- vitest hung; rerun on a quieter machine.")
        return 1
    if not ok:
        print("BASELINE IS RED -- fix the suite before mutating.")
        print(safe(output))
        return 1
    print(f"baseline: green ({len(files)} files)\n")

    survivors: list[str] = []
    for name, relative, original, replacement, test_file in MUTATIONS:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        if original not in source:
            print(f"SKIP      {name}: anchor not found in {relative}", flush=True)
            survivors.append(f"{name} (anchor missing)")
            continue
        backup = path.with_suffix(path.suffix + ".mutation-backup")
        backup.write_text(source, encoding="utf-8")
        try:
            path.write_text(source.replace(original, replacement, 1), encoding="utf-8")
            passed, tail = run([test_file])
            if passed is None:
                print(f"INCONCLUSIVE  {name}  ({tail})", flush=True)
                survivors.append(f"{name} (run did not finish)")
            elif passed:
                print(f"SURVIVED  {name}  ({test_file} stayed green)", flush=True)
                survivors.append(name)
            else:
                print(f"caught    {name}  ({test_file})", flush=True)
        finally:
            path.write_text(source, encoding="utf-8")
            backup.unlink(missing_ok=True)

    ok, _ = run(files)
    print("\nrestored:", "green" if ok else "RED -- restoration failed")
    if survivors:
        print("\nSurvivors (tests that could not fail):")
        for name in survivors:
            print(" -", name)
        return 1
    print(f"\nAll {len(MUTATIONS)} mutations caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
