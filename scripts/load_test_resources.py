"""Load test for the resource library and sharing, at 25/50/75/100 users.

Run it against a **separate** API process, never the one somebody is using:

    SERVER_PORT=8010 python -m backend.main          # in one terminal
    python scripts/load_test_resources.py --base http://127.0.0.1:8010 --pid <that pid>

What it does:

1. **Builds its own fixture**, tagged ``lt<6 digits>``, sized like a busy
   course rather than a toy one: one course, 10 batches with 10 sessions each,
   70 students, 30 tutors, and a 12-file folder uploaded through the API (so
   the files are real objects in storage). The size matters: the defect this
   was written for scaled with how busy the *course* was, not with the request.
2. **Runs a mixed workload** for each stage. Each virtual user signs in once,
   then loops with a 0.5-1.5 s think time. Students (70%) read their dashboard,
   the course catalogue, "Shared with me", a shared folder and preview a file.
   Tutors (30%) list the folder, search the share audience, share all 12 files
   with their students, share the folder, and download a file.
3. **Runs a concentrated burst**: every tutor shares 12 files with 3 students
   at the same moment, five times over.
4. **Samples** database connections (`pg_stat_activity`) and the API
   process's CPU and memory (PowerShell `Get-Process`, so no extra dependency).
5. **Deletes everything it created**, including the stored files.

Server-side latency is what is measured: the files are small, so a download's
time is the server's time, not a transfer of a large file over the network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import selectors
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import get_settings  # noqa: E402
from backend.db.manager import DatabaseManager  # noqa: E402
from backend.models import *  # noqa: E402,F401,F403
from backend.models.batch import Batch, BatchSession  # noqa: E402
from backend.models.course import Course  # noqa: E402
from backend.models.enrollment import Enrollments  # noqa: E402
from backend.models.identity.role import Role  # noqa: E402
from backend.models.identity.user import User  # noqa: E402
from backend.security.password import hash_password  # noqa: E402
from backend.utils.enums import CourseStatus, EnrollmentStatus, Platforms, UserStatus  # noqa: E402

PASSWORD = "LoadTest!2026-resources"
STUDENTS, TUTORS, BATCHES, SESSIONS_PER_BATCH, FILES = 70, 30, 10, 10, 12
STAGES = (25, 50, 75, 100)

# A minimal valid PDF, padded so a preview is a real read of real bytes.
PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n" + b"%" + b"x" * 48_000 + b"\n"
)


# -- fixture ---------------------------------------------------------------------


async def build_fixture(db: DatabaseManager, tag: str) -> dict:
    async with db.session_factory.begin() as s:
        roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
        hashed = hash_password(PASSWORD)

        def user(name: str, role: str) -> User:
            return User(
                username=f"{tag}.{name}@t.test", slug=f"{tag}-{name}", email=f"{tag}.{name}@t.test",
                first_name=name.title(), last_name=tag, hashed_password=hashed, can_login=True,
                status=UserStatus.ACTIVE, roles=[roles[role]],
            )

        students = [user(f"s{i:03}", "STUDENT") for i in range(STUDENTS)]
        tutors = [user(f"t{i:03}", "TUTOR") for i in range(TUTORS)]
        course = Course(title=f"{tag} Data Analysis", code=f"{tag}c", status=CourseStatus.PUBLISHED)
        course.batches, course.resources, course.tags, course.tutors = [], [], [], []
        s.add_all([*students, *tutors, course])
        await s.flush()

        now = datetime.now(UTC)
        batches = []
        for b in range(BATCHES):
            batch = Batch(batch_code=f"{tag}-{b}", course_id=course.id, start_date=date.today(),
                          end_date=date.today() + timedelta(days=90), is_active=True, capacity=100)
            batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
            s.add(batch)
            batches.append(batch)
        await s.flush()
        for b, batch in enumerate(batches):
            for n in range(SESSIONS_PER_BATCH):
                start = now + timedelta(days=n + 1, hours=b)
                row = BatchSession(batch_id=batch.id, tutor_id=tutors[(b + n * BATCHES) % TUTORS].id,
                                   session_start_time=start, session_end_time=start + timedelta(hours=1),
                                   duration_minutes=60, platform=Platforms.Zoom)
                row.attendances = []
                s.add(row)
        for i, student in enumerate(students):
            s.add(Enrollments(batch_id=batches[i % BATCHES].id, student_id=student.id,
                              enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
        await s.flush()

        # Which students each tutor teaches: the ones in batches they take a session in.
        taught: dict[str, list[str]] = defaultdict(list)
        for b, batch in enumerate(batches):
            for n in range(SESSIONS_PER_BATCH):
                tutor = tutors[(b + n * BATCHES) % TUTORS]
                for i, student in enumerate(students):
                    if i % BATCHES == b and str(student.public_id) not in taught[tutor.username]:
                        taught[tutor.username].append(str(student.public_id))
        return {
            "course": str(course.public_id),
            "students": [u.username for u in students],
            "tutors": [u.username for u in tutors],
            "taught": dict(taught),
        }


async def sign_in(client: httpx.AsyncClient, username: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"identifier": username, "password": PASSWORD})
    response.raise_for_status()
    return response.json()["access_token"]


async def upload_material(client: httpx.AsyncClient, token: str, fixture: dict) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    folder = await client.post("/api/v1/folders", headers=headers,
                               json={"name": "Lecture Notes", "course_id": fixture["course"]})
    folder.raise_for_status()
    fixture["folder"] = folder.json()["public_id"]
    fixture["files"] = []
    for n in range(FILES):
        upload = await client.post(
            "/api/v1/resources", headers=headers,
            data={"name": f"Lecture {n + 1:02}.pdf", "resource_type": "Lecture Sheet",
                  "folder_id": fixture["folder"]},
            files={"file": (f"lecture-{n + 1:02}.pdf", PDF, "application/pdf")},
        )
        if upload.status_code >= 400:
            raise RuntimeError(f"upload refused: {upload.status_code} {upload.text[:300]}")
        fixture["files"].append(upload.json()["public_id"])


async def cleanup(db: DatabaseManager, tag: str) -> None:
    storage_root = Path(get_settings().storage.local_path)
    async with db.session_factory.begin() as s:
        keys = (await s.execute(text(
            "SELECT v.path FROM resource_versions v JOIN resources r ON r.id = v.resource_id "
            "WHERE r.course_id IN (SELECT id FROM courses WHERE code LIKE :c)"), {"c": f"{tag}%"})).scalars().all()
        p = {"c": f"{tag}%", "b": f"{tag}-%", "u": f"{tag}.%"}
        users = "(SELECT id FROM users WHERE username LIKE :u)"
        course = "(SELECT id FROM courses WHERE code LIKE :c)"
        for stmt in (
            f"DELETE FROM shared_resources WHERE resource_id IN (SELECT id FROM resources WHERE course_id IN {course})",
            f"DELETE FROM shared_folders WHERE folder_id IN (SELECT id FROM resource_folders WHERE course_id IN {course})",
            f"DELETE FROM resource_versions WHERE resource_id IN (SELECT id FROM resources WHERE course_id IN {course})",
            f"DELETE FROM resources WHERE course_id IN {course}",
            f"DELETE FROM resource_folders WHERE course_id IN {course}",
            "DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :b)",
            "DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :b)",
            "DELETE FROM batches WHERE batch_code LIKE :b",
            "DELETE FROM courses WHERE code LIKE :c",
            f"DELETE FROM notifications WHERE user_id IN {users}",
            f"DELETE FROM tokens WHERE user_id IN {users}",
            f"DELETE FROM user_roles WHERE user_id IN {users}",
            "DELETE FROM users WHERE username LIKE :u",
        ):
            await s.execute(text(stmt), p)
    for key in keys:
        target = storage_root / key
        if target.is_file():
            target.unlink()
    print(f"cleanup: removed fixture {tag} and {len(keys)} stored file(s)")


# -- measurement -----------------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.enabled = False

    async def call(self, client: httpx.AsyncClient, name: str, method: str, path: str, **kwargs):
        started = time.perf_counter()
        status = 0
        try:
            response = await client.request(method, path, **kwargs)
            status = response.status_code
            await response.aread()
        except httpx.TimeoutException:
            status = 599
        except httpx.HTTPError:
            status = 598
        elapsed = time.perf_counter() - started
        if self.enabled:
            self.samples[name].append(elapsed)
            if status >= 400:
                self.errors[name][status] += 1
        return status


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))] * 1000


async def sample_resources(db: DatabaseManager, pid: int | None, out: list[dict], stop: asyncio.Event) -> None:
    last_cpu = None
    while not stop.is_set():
        row = {"t": time.time()}
        async with db.session_factory() as s:
            # The API names its connections after APP_NAME (core/lifespan.py).
            # Any other API process on the same database is counted too.
            counts = (await s.execute(text(
                "SELECT count(*) FILTER (WHERE application_name = :n), "
                "count(*) FILTER (WHERE application_name = :n AND state = 'active') "
                "FROM pg_stat_activity"), {"n": get_settings().app.name})).one()
            row["db_conn"], row["db_active"] = int(counts[0]), int(counts[1])
        if pid:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"$p = Get-Process -Id {pid}; \"$($p.CPU) $($p.WorkingSet64)\""],
                capture_output=True, text=True,
            )
            try:
                cpu, rss = proc.stdout.split()
                cpu = float(cpu)
                if last_cpu is not None:
                    row["cpu_pct_one_core"] = (cpu - last_cpu[0]) / (row["t"] - last_cpu[1]) * 100
                last_cpu = (cpu, row["t"])
                row["rss_mb"] = int(rss) / 1_048_576
            except ValueError:
                pass
        out.append(row)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass


# -- virtual users ---------------------------------------------------------------


async def student_loop(base: str, rec: Recorder, token: str, fixture: dict, until: float) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60) as client:
        while time.monotonic() < until:
            await rec.call(client, "GET /auth/me", "GET", "/api/v1/auth/me")
            await rec.call(client, "GET /dashboard", "GET", "/api/v1/dashboard")
            await rec.call(client, "GET /courses", "GET", "/api/v1/courses", params={"limit": 20})
            await rec.call(client, "GET /shared-with-me/library", "GET", "/api/v1/shared-with-me/library")
            await rec.call(client, "GET /shared-with-me/folders/{id}", "GET",
                           f"/api/v1/shared-with-me/folders/{fixture['folder']}")
            await rec.call(client, "GET /resources/{id}/preview", "GET",
                           f"/api/v1/resources/{random.choice(fixture['files'])}/preview",
                           headers={"Range": "bytes=0-65535"})
            await asyncio.sleep(random.uniform(0.5, 1.5))


async def tutor_loop(base: str, rec: Recorder, token: str, students: list[str], fixture: dict,
                     until: float) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=60) as client:
        while time.monotonic() < until:
            await rec.call(client, "GET /resources (folder)", "GET", "/api/v1/resources",
                           params={"folder_id": fixture["folder"], "limit": 50})
            await rec.call(client, "GET /resources/share-audience", "GET",
                           "/api/v1/resources/share-audience", params={"limit": 50})
            people = random.sample(students, k=min(3, len(students)))
            await rec.call(client, "POST /resources/share (12 files)", "POST", "/api/v1/resources/share",
                           json={"resource_ids": fixture["files"], "user_ids": people,
                                 "level": random.choice(["VIEW", "DOWNLOAD"])})
            await rec.call(client, "POST /resources/share (folder)", "POST", "/api/v1/resources/share",
                           json={"folder_ids": [fixture["folder"]], "user_ids": people, "level": "VIEW"})
            await rec.call(client, "GET /resources/{id}/download", "GET",
                           f"/api/v1/resources/{random.choice(fixture['files'])}/download")
            await asyncio.sleep(random.uniform(0.5, 1.5))


async def run_stage(base: str, users: int, tokens: dict, fixture: dict, hold: float, ramp: float,
                    db: DatabaseManager, pid: int | None) -> dict:
    rec = Recorder()
    n_tutors = max(1, round(users * 0.3))
    n_students = users - n_tutors
    start = time.monotonic()
    until = start + ramp + hold
    tasks = []
    for i in range(n_students):
        name = fixture["students"][i % len(fixture["students"])]
        tasks.append(asyncio.create_task(_delayed(i * ramp / users,
                                                  student_loop(base, rec, tokens[name], fixture, until))))
    for i in range(n_tutors):
        name = fixture["tutors"][i % len(fixture["tutors"])]
        tasks.append(asyncio.create_task(_delayed((n_students + i) * ramp / users,
                                                  tutor_loop(base, rec, tokens[name],
                                                             fixture["taught"].get(name) or fixture["any_students"],
                                                             fixture, until))))
    await asyncio.sleep(ramp)
    rec.enabled = True
    stop = asyncio.Event()
    resources: list[dict] = []
    sampler = asyncio.create_task(sample_resources(db, pid, resources, stop))
    measured_from = time.monotonic()
    await asyncio.gather(*tasks)
    measured = time.monotonic() - measured_from
    stop.set()
    await sampler
    return summarise(f"{users} users", rec, measured, resources)


async def _delayed(delay: float, coro):  # noqa: ANN001, ANN202
    await asyncio.sleep(delay)
    return await coro


async def run_burst(base: str, tokens: dict, fixture: dict, db: DatabaseManager, pid: int | None) -> dict:
    """Every tutor shares 12 files with 3 students at the same instant, five times."""
    rec = Recorder()
    rec.enabled = True
    stop = asyncio.Event()
    resources: list[dict] = []
    sampler = asyncio.create_task(sample_resources(db, pid, resources, stop))
    started = time.monotonic()

    async def one(name: str) -> None:
        students = fixture["taught"].get(name) or fixture["any_students"]
        async with httpx.AsyncClient(base_url=base, headers={"Authorization": f"Bearer {tokens[name]}"},
                                     timeout=60) as client:
            await rec.call(client, "POST /resources/share (12 files) burst", "POST",
                           "/api/v1/resources/share",
                           json={"resource_ids": fixture["files"],
                                 "user_ids": random.sample(students, k=min(3, len(students))),
                                 "level": random.choice(["VIEW", "DOWNLOAD"])})

    for _ in range(5):
        await asyncio.gather(*(one(name) for name in fixture["tutors"]))
    measured = time.monotonic() - started
    stop.set()
    await sampler
    return summarise(f"burst: {len(fixture['tutors'])} tutors x 5 rounds", rec, measured, resources)


def summarise(label: str, rec: Recorder, seconds: float, resources: list[dict]) -> dict:
    endpoints = {}
    total = errors = 0
    for name, values in sorted(rec.samples.items()):
        failed = sum(rec.errors[name].values())
        total += len(values)
        errors += failed
        endpoints[name] = {
            "requests": len(values),
            "errors": dict(rec.errors[name]),
            "p50_ms": round(pct(values, 0.50), 1),
            "p95_ms": round(pct(values, 0.95), 1),
            "p99_ms": round(pct(values, 0.99), 1),
            "max_ms": round(max(values) * 1000, 1) if values else None,
        }
    cpu = [r["cpu_pct_one_core"] for r in resources if "cpu_pct_one_core" in r]
    return {
        "stage": label,
        "seconds": round(seconds, 1),
        "requests": total,
        "throughput_rps": round(total / seconds, 1) if seconds else None,
        "success_pct": round(100 * (total - errors) / total, 3) if total else None,
        "db_connections_max": max((r["db_conn"] for r in resources), default=None),
        "db_active_max": max((r["db_active"] for r in resources), default=None),
        "api_cpu_pct_one_core_mean": round(statistics.mean(cpu), 1) if cpu else None,
        "api_cpu_pct_one_core_max": round(max(cpu), 1) if cpu else None,
        "api_rss_mb_max": round(max((r.get("rss_mb", 0) for r in resources), default=0), 1) or None,
        "endpoints": endpoints,
    }


# -- driver ----------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    tag = f"lt{random.randint(100000, 999999)}"
    db = DatabaseManager(get_settings().database, application_name="load-test")
    results = []
    try:
        fixture = await build_fixture(db, tag)
        async with httpx.AsyncClient(base_url=args.base, timeout=60) as client:
            tokens = {}
            for name in fixture["tutors"] + fixture["students"]:
                tokens[name] = await sign_in(client, name)
            await upload_material(client, tokens[fixture["tutors"][0]], fixture)
            async with db.session_factory() as s:
                ids = (await s.execute(text(
                    "SELECT public_id::text FROM users WHERE username LIKE :u AND username LIKE '%.s%'"),
                    {"u": f"{tag}.%"})).scalars().all()
            fixture["any_students"] = list(ids)
            # Every student gets the folder, so the shared-folder screens have
            # something to read; one tutor does it, through the API.
            warm = await client.post(
                "/api/v1/resources/share",
                headers={"Authorization": f"Bearer {tokens[fixture['tutors'][0]]}"},
                json={"folder_ids": [fixture["folder"]], "user_ids": fixture["any_students"], "level": "VIEW"},
            )
            if warm.status_code != 200:
                # A tutor may share only with students they teach; an
                # administrator would be needed to reach all 70. Fall back to
                # each tutor sharing with their own students.
                for name in fixture["tutors"]:
                    taught = fixture["taught"].get(name) or []
                    if taught:
                        await client.post(
                            "/api/v1/resources/share",
                            headers={"Authorization": f"Bearer {tokens[name]}"},
                            json={"folder_ids": [fixture["folder"]], "user_ids": taught, "level": "VIEW"},
                        )
        for users in args.stages:
            print(f"stage: {users} users ...", flush=True)
            results.append(await run_stage(args.base, users, tokens, fixture, args.hold, args.ramp, db, args.pid))
        if args.burst:
            print("burst ...", flush=True)
            results.append(await run_burst(args.base, tokens, fixture, db, args.pid))
    finally:
        if not args.keep:
            await cleanup(db, tag)
        await db.dispose()

    out = Path(args.out)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for r in results:
        print(f"\n== {r['stage']}: {r['requests']} requests in {r['seconds']}s, "
              f"{r['throughput_rps']} req/s, success {r['success_pct']}%, "
              f"DB conn max {r['db_connections_max']} (active {r['db_active_max']}), "
              f"API CPU mean/max {r['api_cpu_pct_one_core_mean']}/{r['api_cpu_pct_one_core_max']}% of one core, "
              f"RSS max {r['api_rss_mb_max']} MB")
        for name, e in r["endpoints"].items():
            print(f"   {name:42} n={e['requests']:5}  p50={e['p50_ms']:7.1f}  p95={e['p95_ms']:7.1f}  "
                  f"p99={e['p99_ms']:7.1f}  max={e['max_ms']:7.1f}  errors={e['errors'] or '-'}")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--pid", type=int, default=None, help="API process id, for CPU/memory sampling")
    parser.add_argument("--stages", type=int, nargs="+", default=list(STAGES))
    parser.add_argument("--hold", type=float, default=60.0, help="seconds measured per stage")
    parser.add_argument("--ramp", type=float, default=10.0, help="seconds to start every user")
    parser.add_argument("--burst", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--keep", action="store_true", help="leave the fixture in place")
    parser.add_argument("--out", default="load-test-results.json")
    asyncio.SelectorEventLoop(selectors.SelectSelector()).run_until_complete(main(parser.parse_args()))
