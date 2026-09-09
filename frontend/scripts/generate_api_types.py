"""Generate `frontend/src/lib/api/types.ts` from the backend's own OpenAPI
document.

Hand-writing 251 response shapes is how a frontend ends up describing an API
that no longer exists. These are transcribed mechanically from the running
application's schema, so a field that is not in the backend cannot appear
here, and one that changes shape shows up as a type error rather than as
`undefined` on a screen.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@127.0.0.1:5432/unused")

from backend.main import app  # noqa: E402

SPEC = app.openapi()
SCHEMAS: dict = SPEC["components"]["schemas"]

RESERVED = {"Date", "Error", "Response", "Request"}


def ts_name(raw: str) -> str:
    # `backend__schemas__auth__SessionResponse` -> `AuthSessionResponse`
    if "__" in raw:
        parts = [p for p in raw.split("__") if p and p != "backend" and p != "schemas"]
        if len(parts) >= 2:
            module = "".join(w.capitalize() for w in parts[0].split("_"))
            raw = module + parts[-1]
        else:
            raw = parts[-1]
    # `Page_UserSummary_` -> `PageUserSummary`
    raw = raw.replace("-", "_")
    raw = "".join(w[:1].upper() + w[1:] for w in raw.split("_") if w)
    raw = re.sub(r"[^A-Za-z0-9]", "", raw)
    if raw in RESERVED:
        raw = "Api" + raw
    return raw


NAMES = {raw: ts_name(raw) for raw in SCHEMAS}
# Guard: two OpenAPI names must not collapse onto one TypeScript name --
# that would silently make one of them describe the other.
_seen: dict[str, str] = {}
for raw, name in NAMES.items():
    if name in _seen:
        raise SystemExit(f"name collision: {raw} and {_seen[name]} -> {name}")
    _seen[name] = raw


def render(schema: dict, depth: int = 0) -> str:
    if "$ref" in schema:
        return NAMES[schema["$ref"].split("/")[-1]]

    if "anyOf" in schema or "oneOf" in schema:
        members = schema.get("anyOf") or schema["oneOf"]
        rendered = [render(m, depth) for m in members]
        # collapse duplicates, keep order
        out: list[str] = []
        for r in rendered:
            if r not in out:
                out.append(r)
        return " | ".join(out)

    if "allOf" in schema:
        parts = [render(m, depth) for m in schema["allOf"]]
        return " & ".join(parts) if len(parts) > 1 else parts[0]

    if "const" in schema:
        return json.dumps(schema["const"])

    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])

    kind = schema.get("type")
    if kind == "array":
        inner = render(schema.get("items", {}), depth)
        return f"({inner})[]" if " " in inner else f"{inner}[]"
    if kind == "object":
        props = schema.get("properties")
        if props:
            return render_object(schema, depth)
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict) and extra:
            return f"Record<string, {render(extra, depth)}>"
        return "Record<string, unknown>"
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    return "unknown"


def render_object(schema: dict, depth: int) -> str:
    pad = "  " * (depth + 1)
    closing = "  " * depth
    required = set(schema.get("required", []))
    lines = ["{"]
    for prop, sub in schema.get("properties", {}).items():
        description = (sub.get("description") or "").strip().replace("*/", "* /")
        if description:
            for line in description.splitlines():
                lines.append(f"{pad}/** {line.strip()} */" if line.strip() else "")
        optional = "" if prop in required else "?"
        key = prop if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", prop) else json.dumps(prop)
        lines.append(f"{pad}{key}{optional}: {render(sub, depth + 1)};")
    lines.append(closing + "}")
    return "\n".join(lines)


out: list[str] = [
    "/* eslint-disable */",
    "/**",
    " * GENERATED from the LMS backend's OpenAPI document -- do not edit by hand.",
    " *",
    " * Regenerate after any backend schema change:",
    " *   python scripts/generate_api_types.py",
    " *",
    " * Every type here is a transcription of a shape the API actually returns.",
    " * If a screen needs a field that is absent from this file, the backend does",
    " * not provide it -- that is a gap to document, not a type to add.",
    " */",
    "",
]

for raw in sorted(SCHEMAS, key=lambda k: NAMES[k]):
    schema = SCHEMAS[raw]
    name = NAMES[raw]
    doc = (schema.get("description") or "").strip()
    if doc:
        out.append("/**")
        for line in doc.splitlines():
            out.append(f" * {line.rstrip()}".rstrip())
        out.append(" */")
    if "enum" in schema and schema.get("type") in ("string", "integer", None):
        values = " | ".join(json.dumps(v) for v in schema["enum"])
        out.append(f"export type {name} = {values};")
        const = ", ".join(json.dumps(v) for v in schema["enum"])
        out.append(f"export const {name}Values = [{const}] as const;")
    elif schema.get("type") == "object" or "properties" in schema:
        out.append(f"export interface {name} {render_object(schema, 0)}")
    else:
        out.append(f"export type {name} = {render(schema, 0)};")
    out.append("")

path = ROOT / "frontend" / "src" / "lib" / "api" / "types.ts"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote {len(SCHEMAS)} schemas -> {path}")
