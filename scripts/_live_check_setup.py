"""Build a throwaway world for the live join/recording check, then tear it down.

Everything it creates is tagged `livechk`, and `--teardown` removes exactly those
rows. It never touches a real account: the two users it makes are its own, with
passwords it generates, so the check can log in over HTTP the way a browser does
without borrowing anyone's credentials.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import selectors
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.models.resource import Resource
from backend.security import password as pwd
from backend.utils.enums import (
    CourseStatus,
    EnrollmentStatus,
    Platforms,
    ResourceType,
    UserStatus,
)

TAG = "livechk"
LINK = "https://zoom.example.test/j/live-check"
EXTERNAL = "https://zoom.example.test/rec/live-check"
MEDIA = bytes(range(256)) * 16  # 4096 bytes; a slice is checkable by eye


async def build(session) -> dict:  # noqa: ANN001
    roles = {r.name: r for r in (await session.execute(select(Role))).scalars()}
    password = f"Lv-{secrets.token_urlsafe(12)}!"

    def user(name: str, role: str) -> User:
        return User(
            username=f"{TAG}.{name}", slug=f"{TAG}-{name}", email=f"{TAG}.{name}@t.test",
            first_name=name.title(), last_name="Check",
            hashed_password=pwd.hash_password(password), status=UserStatus.ACTIVE,
            # An account is closed until a Super Admin opens it; these three are
            # created and destroyed by this script, so it opens its own.
            can_login=True,
            roles=[roles[role]],
        )

    tutor, student, outsider = user("tutor", "TUTOR"), user("stu", "STUDENT"), user("out", "STUDENT")
    # Holds `session.override` and `institution.view_all`, so it is the one
    # account that can prove the authorised exception rather than the rule.
    admin = user("admin", "ADMIN")
    course = Course(title=f"{TAG} Course", code=TAG, status=CourseStatus.PUBLISHED)
    course.batches, course.resources, course.tags, course.tutors = [], [], [], []
    session.add_all([tutor, student, outsider, admin, course])
    await session.flush()

    batch = Batch(batch_code=f"{TAG}-A", course_id=course.id, start_date=date.today(),
                  end_date=date.today() + timedelta(days=30), is_active=True, capacity=10)
    batch.sessions, batch.enrollments, batch.student_reviews = [], [], []
    session.add(batch)
    await session.flush()

    now = datetime.now(timezone.utc)
    made = {}
    for name, start in (("live", now - timedelta(minutes=5)), ("soon", now + timedelta(hours=6))):
        row = BatchSession(batch_id=batch.id, tutor_id=tutor.id, session_start_time=start,
                           session_end_time=start + timedelta(hours=1), duration_minutes=60,
                           platform=Platforms.Zoom, meeting_link=LINK)
        row.attendances = []
        session.add(row)
        await session.flush()
        made[name] = str(row.public_id)

    # Real bytes on disk under the configured storage root, so the stream is a
    # stream and not a fixture pretending to be one.
    key = f"{TAG}/recording.mp4"
    root = Path(get_settings().storage.local_path)
    (root / TAG).mkdir(parents=True, exist_ok=True)
    (root / key).write_bytes(MEDIA)

    recording = Resource(
        name=f"{TAG} class recording.mp4", resource_type=ResourceType.video,
        course_id=course.id, batch_id=batch.id, path=key, mime_type="video/mp4",
        size=len(MEDIA), uploaded_by=tutor.id, modified_by=tutor.id,
        is_deleted=False, created_at=now,
    )
    recording.versions, recording.shared_resources = [], []
    session.add(recording)
    await session.flush()

    live = (await session.execute(
        select(BatchSession).where(BatchSession.public_id == made["live"])
    )).scalar_one()
    live.recording_resource_id = recording.id
    live.recording_link = EXTERNAL

    session.add(Enrollments(batch_id=batch.id, student_id=student.id,
                            enrollment_date=now, status=EnrollmentStatus.CONFIRMED))
    await session.flush()

    return {
        "password": password, "media_bytes": len(MEDIA), **made,
        "student": student.email, "tutor": tutor.email, "outsider": outsider.email,
        "admin": admin.email,
    }


async def teardown(session) -> None:  # noqa: ANN001
    p = {"c": f"{TAG}-%", "u": f"{TAG}.%", "t": f"{TAG}%"}
    await session.execute(text("UPDATE batch_sessions SET recording_resource_id = NULL WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
    await session.execute(text("DELETE FROM resource_versions WHERE resource_id IN (SELECT id FROM resources WHERE name LIKE :t)"), p)
    await session.execute(text("DELETE FROM resources WHERE name LIKE :t"), p)
    await session.execute(text("DELETE FROM attendances WHERE session_id IN (SELECT id FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c))"), p)
    await session.execute(text("DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
    await session.execute(text("DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE batch_code LIKE :c)"), p)
    await session.execute(text("DELETE FROM batches WHERE batch_code LIKE :c"), p)
    await session.execute(text("DELETE FROM courses WHERE code LIKE :t"), p)
    # The realtime and push checks send real messages, which create real
    # notifications and mail rows. Ordered child-first, because every one of
    # these has a foreign key to `users`.
    users = "(SELECT id FROM users WHERE username LIKE :u)"
    await session.execute(text(f"DELETE FROM push_subscriptions WHERE user_id IN {users}"), p)
    await session.execute(text(f"DELETE FROM notifications WHERE user_id IN {users}"), p)
    await session.execute(text(f"DELETE FROM notification_preferences WHERE user_id IN {users}"), p)
    await session.execute(text(f"DELETE FROM mail_recipients WHERE user_id IN {users}"), p)
    await session.execute(text(f"DELETE FROM mail_recipients WHERE message_id IN (SELECT id FROM mail_messages WHERE sender_id IN {users})"), p)
    await session.execute(text(f"DELETE FROM mail_attachments WHERE uploader_id IN {users}"), p)
    await session.execute(text(f"DELETE FROM mail_messages WHERE sender_id IN {users}"), p)
    await session.execute(text("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
    await session.execute(text("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE :u)"), p)
    await session.execute(text("DELETE FROM users WHERE username LIKE :u"), p)

    root = Path(get_settings().storage.local_path) / TAG
    for child in root.glob("*"):
        child.unlink()
    if root.exists():
        root.rmdir()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="live-check")

    async def go() -> None:
        async with db.session_factory.begin() as s:
            if mode == "teardown":
                await teardown(s)
                print("torn down")
            else:
                print(json.dumps(await build(s)))
        await db.dispose()

    loop.run_until_complete(go())
    loop.close()


if __name__ == "__main__":
    main()
