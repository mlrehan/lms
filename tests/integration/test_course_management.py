"""CourseService against real Postgres: code suggestion, uploaded images, tutor/student filters."""

from __future__ import annotations

import asyncio
import io
import random
import selectors
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import UploadFile
from PIL import Image
from sqlalchemy import select, text

from backend.core.config import get_settings
from backend.core.errors import AuthorizationError, NotFoundError, ValidationError
from backend.db.manager import DatabaseManager
from backend.models.batch import Batch, BatchSession
from backend.models.course import Course, TutorCourse
from backend.models.enrollment import Enrollments
from backend.models.identity.role import Role
from backend.models.identity.user import User
from backend.schemas.base import PageParams
from backend.schemas.course import CourseCreateRequest
from backend.services.course_service import CourseService
from backend.storage import get_storage
from backend.utils.enums import CourseStatus, EnrollmentStatus, UserStatus


def _png(size=(800, 400)) -> bytes:  # noqa: ANN001
    out = io.BytesIO()
    Image.new("RGB", size, (20, 90, 200)).save(out, "PNG")
    return out.getvalue()


def _upload(data: bytes, name: str = "x.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture()
def env():
    tag = "cm" + uuid.uuid4().hex[:8]
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    db = DatabaseManager(get_settings().database, application_name="course-tests")
    keys: list[str] = []  # storage objects to remove afterwards

    def run(fn):  # noqa: ANN001, ANN202
        """One transaction, committed on success."""
        async def go():  # noqa: ANN202
            async with db.session_factory.begin() as s:
                return await fn(s)
        return loop.run_until_complete(go())

    async def actor(s, *, admin=True):  # noqa: ANN001, ANN202
        if admin:
            return (await s.execute(select(User).where(User.username == "superadmin"))).scalar_one()
        role = (await s.execute(select(Role).where(Role.name == "STUDENT"))).scalar_one()
        u = User(username=f"{tag}.low", slug=f"{tag}-low", email=f"{tag}.low@t.test", hashed_password="x",
                 status=UserStatus.ACTIVE, roles=[role])
        s.add(u)
        await s.flush()
        return u

    ns = type("Env", (), dict(tag=tag, run=staticmethod(run), actor=staticmethod(actor), loop=loop, db=db, keys=keys))
    try:
        yield ns
    finally:
        async def cleanup() -> None:
            async with db.session_factory.begin() as s:
                ids = "(SELECT id FROM courses WHERE title LIKE :t)"
                await s.execute(text(f"DELETE FROM enrollments WHERE batch_id IN (SELECT id FROM batches WHERE course_id IN {ids})"), {"t": f"{tag}%"})
                await s.execute(text(f"DELETE FROM batch_sessions WHERE batch_id IN (SELECT id FROM batches WHERE course_id IN {ids})"), {"t": f"{tag}%"})
                await s.execute(text(f"DELETE FROM batches WHERE course_id IN {ids}"), {"t": f"{tag}%"})
                await s.execute(text(f"DELETE FROM tutor_courses WHERE course_id IN {ids}"), {"t": f"{tag}%"})
                # Stored files first, so a failed test leaves nothing on disk.
                for k in (await s.execute(text("SELECT course_image, small_course_image FROM courses WHERE title LIKE :t"), {"t": f"{tag}%"})).all():
                    for v in k:
                        if v and not v.lower().startswith("http"):
                            keys.append(v)
                await s.execute(text("DELETE FROM courses WHERE title LIKE :t"), {"t": f"{tag}%"})
                await s.execute(text("DELETE FROM users WHERE username LIKE :u"), {"u": f"{tag}.%"})
        loop.run_until_complete(cleanup())
        for k in set(keys):
            try:
                loop.run_until_complete(get_storage().delete(k))
            except Exception:  # noqa: BLE001
                pass
        loop.run_until_complete(db.dispose())
        loop.close()


def _create(e, title: str, **kw):  # noqa: ANN001, ANN202
    async def f(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        c = await CourseService(s).create(CourseCreateRequest(title=f"{e.tag} {title}", **kw), actor=a)
        return c.public_id, c.code
    return e.run(f)


# --------------------------------------------------------------------- codes


def test_a_course_created_without_a_code_gets_a_unique_generated_one(env) -> None:
    e = env
    _, first = _create(e, "Python Programming for Beginners")
    _, second = _create(e, "Python Programming for Beginners Two")  # same initials, so the same prefix
    (p1, n1), (p2, n2) = (first.rsplit("-", 1), second.rsplit("-", 1))
    assert p1 == p2 and int(n2) == int(n1) + 1  # sequential, never a duplicate


def test_a_supplied_code_is_kept_exactly_and_must_be_unique(env) -> None:
    e = env
    _, code = _create(e, "Alpha Course", code=f"{e.tag}-X1")
    assert code == f"{e.tag}-X1"
    from backend.core.errors import ConflictError

    with pytest.raises(ConflictError):
        _create(e, "Beta Course", code=f"{e.tag}-X1")


def test_the_suggestion_skips_numbers_already_taken(env) -> None:
    e = env

    async def f(s):  # noqa: ANN001, ANN202
        svc = CourseService(s)
        prefix = svc._abbreviation(f"{e.tag} Zebra Quantum Studies")  # noqa: SLF001
        for n in (1, 2, 5):
            s.add(Course(title=f"{e.tag} seed {n}", code=f"{prefix}-{n:03d}", status=CourseStatus.DRAFT))
        await s.flush()
        return prefix, await svc.suggest_code(f"{e.tag} Zebra Quantum Studies")

    prefix, suggestion = e.run(f)
    assert suggestion == f"{prefix}-006"  # the highest, plus one -- gaps are not reused


# -------------------------------------------------------------------- images


def test_an_uploaded_image_is_stored_served_by_path_and_replaced_cleanly(env) -> None:
    e = env
    pid, _ = _create(e, "Pictured")

    async def upload(s, kind):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        c = await CourseService(s).set_image(pid, kind, _upload(_png()), actor=a)
        return c.small_course_image if kind == "small" else c.course_image, c.small_course_image_url, c.course_image_url

    key1, small_url, _ = e.run(lambda s: upload(s, "small"))
    assert key1.startswith(f"courses/{pid}/small/") and key1 not in (small_url or "")  # the key never leaves the server
    assert small_url.startswith(f"/courses/{pid}/image/small?v=")

    async def exists(k):  # noqa: ANN001, ANN202
        return await get_storage().exists(k)

    assert e.loop.run_until_complete(exists(key1))
    key2, _, _ = e.run(lambda s: upload(s, "small"))
    e.keys.append(key2)
    assert key2 != key1 and not e.loop.run_until_complete(exists(key1))  # the old file was deleted, not orphaned


def test_removing_an_image_deletes_the_file_and_clears_the_column(env) -> None:
    e = env
    pid, _ = _create(e, "Removable")

    async def up(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        return (await CourseService(s).set_image(pid, "full", _upload(_png()), actor=a)).course_image

    key = e.run(up)

    async def rm(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        return (await CourseService(s).remove_image(pid, "full", actor=a)).course_image

    assert e.run(rm) is None
    assert not e.loop.run_until_complete(get_storage().exists(key))


def test_a_bad_upload_changes_nothing(env) -> None:
    e = env
    pid, _ = _create(e, "Untouched")

    async def bad(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        await CourseService(s).set_image(pid, "full", _upload(b"<svg><script>1</script></svg>", "x.svg"), actor=a)

    with pytest.raises(ValidationError):
        e.run(bad)

    async def read(s):  # noqa: ANN001, ANN202
        return (await s.execute(select(Course.course_image).where(Course.public_id == pid))).scalar_one()

    assert e.run(read) is None


def test_an_external_image_url_is_never_deleted_or_streamed(env, monkeypatch: pytest.MonkeyPatch) -> None:
    e = env
    deleted: list[str] = []
    storage = get_storage()
    real_delete = storage.delete

    async def spy(key: str) -> None:
        deleted.append(key)
        await real_delete(key)

    monkeypatch.setattr(storage, "delete", spy)
    pid, _ = _create(e, "External", course_image="https://cdn.test/a.jpg")

    async def key(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        return await CourseService(s).image_key(pid, "full", actor=a)

    with pytest.raises(NotFoundError):
        e.run(key)  # served by its own host, not by us

    async def replace(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        return (await CourseService(s).set_image(pid, "full", _upload(_png()), actor=a)).course_image

    new_key = e.run(replace)
    e.keys.append(new_key)
    assert new_key.startswith("courses/")
    assert deleted == []  # replacing an external URL must not try to delete it as a stored file


def test_one_courses_key_cannot_be_read_through_another(env) -> None:
    e = env
    a_id, _ = _create(e, "Has image")
    b_id, _ = _create(e, "No image")

    async def up(s):  # noqa: ANN001, ANN202
        act = await e.actor(s)
        return (await CourseService(s).set_image(a_id, "full", _upload(_png()), actor=act)).course_image

    e.keys.append(e.run(up))

    async def read_b(s):  # noqa: ANN001, ANN202
        act = await e.actor(s)
        return await CourseService(s).image_key(b_id, "full", actor=act)

    with pytest.raises(NotFoundError):
        e.run(read_b)


# ------------------------------------------------------- tutor / student filters


def _world(e):  # noqa: ANN001, ANN202
    """Two courses; tutor T teaches a session of course A; student S is enrolled in course B."""
    async def f(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        svc = CourseService(s)
        ca = await svc.create(CourseCreateRequest(title=f"{e.tag} Course A"), actor=a)
        cb = await svc.create(CourseCreateRequest(title=f"{e.tag} Course B"), actor=a)
        for c in (ca, cb):
            c.status = CourseStatus.PUBLISHED
        tutor = User(username=f"{e.tag}.tutor", slug=f"{e.tag}-tutor", email=f"{e.tag}.tutor@t.test", hashed_password="x", status=UserStatus.ACTIVE, roles=[])
        student = User(username=f"{e.tag}.student", slug=f"{e.tag}-student", email=f"{e.tag}.student@t.test", hashed_password="x", status=UserStatus.ACTIVE, roles=[])
        s.add_all([tutor, student])
        await s.flush()
        for course, code in ((ca, "A"), (cb, "B")):
            b = Batch(batch_code=f"{e.tag}-{code}", course_id=course.id, start_date=date.today(), end_date=date.today(), is_active=True)
            b.sessions, b.enrollments, b.student_reviews = [], [], []
            s.add(b)
            await s.flush()
            if code == "A":
                sess = BatchSession(batch_id=b.id, tutor_id=tutor.id, session_start_time=datetime.now(timezone.utc), session_end_time=datetime.now(timezone.utc) + timedelta(hours=1), duration_minutes=60)
                sess.attendances = []
                s.add(sess)
            else:
                s.add(Enrollments(batch_id=b.id, student_id=student.id, enrollment_date=datetime.now(timezone.utc), status=EnrollmentStatus.CONFIRMED))
        await s.flush()
        return tutor.public_id, student.public_id
    return e.run(f)


def _titles(e, **filters):  # noqa: ANN001, ANN202
    async def f(s):  # noqa: ANN001, ANN202
        a = await e.actor(s)
        rows, _ = await CourseService(s).list_courses(PageParams(limit=100, offset=0), actor=a, query=e.tag, **filters)
        return sorted(c.title.removeprefix(f"{e.tag} ") for c in rows)
    return e.run(f)


def test_filtering_by_tutor_finds_courses_they_teach_a_session_of(env) -> None:
    e = env
    tutor, _ = _world(e)
    assert _titles(e, tutor_id=tutor) == ["Course A"]  # no tutor_courses row exists: the synced case


def test_filtering_by_tutor_also_honours_an_explicit_assignment(env) -> None:
    e = env
    tutor, _ = _world(e)

    async def assign(s):  # noqa: ANN001, ANN202
        uid = (await s.execute(select(User.id).where(User.public_id == tutor))).scalar_one()
        cid = (await s.execute(select(Course.id).where(Course.title == f"{e.tag} Course B"))).scalar_one()
        s.add(TutorCourse(tutor_id=uid, course_id=cid))

    e.run(assign)
    assert _titles(e, tutor_id=tutor) == ["Course A", "Course B"]


def test_filtering_by_student_finds_courses_they_are_enrolled_in(env) -> None:
    e = env
    _, student = _world(e)
    assert _titles(e, student_id=student) == ["Course B"]


def test_a_dropped_enrolment_no_longer_counts(env) -> None:
    e = env
    _, student = _world(e)

    async def drop(s):  # noqa: ANN001, ANN202
        await s.execute(text("UPDATE enrollments SET status = 'DROPPED' WHERE student_id = (SELECT id FROM users WHERE public_id = :p)"), {"p": student})

    e.run(drop)
    assert _titles(e, student_id=student) == []


def test_both_filters_combine(env) -> None:
    e = env
    tutor, student = _world(e)
    assert _titles(e, tutor_id=tutor, student_id=student) == []  # A is theirs to teach, B theirs to study: no overlap


def test_an_unknown_person_is_a_404_not_an_empty_list(env) -> None:
    e = env
    with pytest.raises(NotFoundError):
        _titles(e, tutor_id=uuid.uuid4())


def test_only_institution_wide_callers_may_filter_by_person(env) -> None:
    e = env
    tutor, _ = _world(e)

    async def as_student(s):  # noqa: ANN001, ANN202
        low = await e.actor(s, admin=False)
        await CourseService(s).list_courses(PageParams(limit=10, offset=0), actor=low, tutor_id=tutor)

    with pytest.raises(AuthorizationError):
        e.run(as_student)
