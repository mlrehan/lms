"""The assessment routes ask for the permission the catalogue says they need.

A route gated on the *wrong* permission is invisible. It works, it returns
data, and the only way to notice is to hold one permission and not the other
and then be surprised. That is how this file came to exist: driving
`POST /batches/{id}/transcripts/generate` as a Tutor returned **200 and
created a transcript**, because the route asked for `grade.update` (which a
Tutor holds, to mark work) rather than `transcript.generate` (which the
catalogue grants only to the academic office).

The permission catalogue states the distinction in as many words -- a
transcript is an *official* document, and "somebody may be entitled to see a
mark without being entitled to issue the document that certifies it". The
catalogue was right, the route was wrong, and nothing compared the two.

So this does compare them, for every assessment route, by reading the codes
out of the dependency's own closure rather than trusting a docstring.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

import backend.main as main
from backend.core.permissions import ALL_PERMISSIONS

#: The gate every assessment route must carry, as (method, path) -> codes.
#: Written out rather than derived, because deriving the expectation from the
#: same source as the behaviour would make the test agree with any mistake.
EXPECTED: dict[tuple[str, str], set[str]] = {
    # Assignments
    ("GET", "/assignments"): {"assignment.read"},
    ("POST", "/courses/{course_id}/assignments"): {"assignment.create"},
    ("PUT", "/assignments/{assignment_id}/submission"): {"assignment.submit"},
    ("GET", "/submissions"): {"assignment.read"},
    ("PUT", "/submissions/{submission_id}/grade"): {"assignment.grade"},
    ("POST", "/assignments/{assignment_id}/publish-results"): {"assignment.publish"},
    # Quizzes. The answer key is deliberately gated on a *marking* permission,
    # not a reading one: a student holds `quiz.read` and must never reach it.
    ("GET", "/quizzes"): {"quiz.read"},
    ("GET", "/quizzes/{quiz_id}/answer-key"): {"quiz.update"},
    ("POST", "/quizzes/{quiz_id}/attempts"): {"quiz.attempt"},
    ("PUT", "/quizzes/{quiz_id}/publish"): {"quiz.publish"},
    ("PUT", "/quizzes/{quiz_id}/results"): {"quiz.grade"},
    # Examinations
    ("GET", "/exams"): {"exam.read"},
    ("POST", "/exams"): {"exam.create"},
    ("DELETE", "/exams/{exam_id}"): {"exam.delete"},
    ("PUT", "/exams/{exam_id}/publish"): {"exam.publish"},
    ("PUT", "/exams/{exam_id}/results"): {"exam.grade"},
    ("PUT", "/exams/{exam_id}/results/publish"): {"grade.publish"},
    # Gradebook
    ("GET", "/gradebook"): {"grade.read"},
    ("POST", "/batches/{batch_id}/gradebook/entries"): {"grade.update"},
    # Transcripts -- the three this file was written for.
    ("GET", "/transcripts"): {"transcript.read"},
    ("GET", "/transcripts/{transcript_id}"): {"transcript.read"},
    ("POST", "/batches/{batch_id}/transcripts/generate"): {"transcript.generate"},
    ("PUT", "/transcripts/{transcript_id}/finalise"): {"grade.publish"},
    # Grading schemes
    ("GET", "/grading-schemes"): {"grading_scheme.read"},
    ("POST", "/grading-schemes"): {"grading_scheme.manage"},
    ("PUT", "/grading-schemes/{scheme_id}/components"): {"grading_scheme.manage"},
}


def _routes() -> list[APIRoute]:
    """Every APIRoute, however it was included.

    `include_router` wraps the router rather than flattening it into
    `app.routes`, so a walk of `app.routes` alone finds a handful of routes and
    misses the entire API -- and every assertion below would then pass
    vacuously. `test_the_walk_finds_the_assessment_routes` guards that.
    """

    def walk(routes):  # noqa: ANN001, ANN202
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from walk(route.original_router.routes)
            elif hasattr(route, "routes"):
                yield from walk(route.routes)

    return list(walk(main.app.routes))


def _required_codes(dependant, seen: set[int] | None = None):  # noqa: ANN001, ANN202
    """The permission codes a route actually demands.

    `require_permissions` closes over its `required` tuple, so the codes are
    readable from the closure. Taking them from there rather than from the
    source text means this cannot be fooled by a comment, and reads the same
    object FastAPI will call.
    """
    seen = set() if seen is None else seen
    for sub in dependant.dependencies:
        call = sub.call
        if id(call) in seen:
            continue
        seen.add(id(call))
        closure = getattr(call, "__closure__", None)
        freevars = getattr(getattr(call, "__code__", None), "co_freevars", ())
        if closure and "required" in freevars:
            value = closure[freevars.index("required")].cell_contents
            if isinstance(value, (tuple, list)):
                yield from value
        yield from _required_codes(sub, seen)


def _gate_of(method: str, path: str) -> set[str] | None:
    for route in _routes():
        if route.path == path and method in route.methods:
            return set(_required_codes(route.dependant))
    return None


def test_the_walk_finds_the_assessment_routes() -> None:
    """Guards the guard: a broken walk must fail loudly, not silently pass."""
    paths = {r.path for r in _routes()}
    assert len(paths) > 150, f"the route walk only found {len(paths)} paths"
    for _, path in EXPECTED:
        assert path in paths, f"{path} is not in the application at all"


def test_every_assessment_route_asks_for_the_catalogued_permission() -> None:
    wrong: list[str] = []
    for (method, path), expected in EXPECTED.items():
        actual = _gate_of(method, path)
        if actual != expected:
            wrong.append(f"{method} {path}: expected {sorted(expected)}, gate asks {sorted(actual or [])}")
    assert not wrong, "assessment routes gated on the wrong permission:\n" + "\n".join(wrong)


def test_a_tutor_cannot_issue_an_official_transcript() -> None:
    """The specific regression, stated as the rule it protects.

    Marking work and certifying a result are different authorities. A Tutor
    holds `grade.update` for the first; only the academic office holds
    `transcript.generate` for the second.
    """
    from backend.core.permissions import ROLE_PERMISSIONS

    gate = _gate_of("POST", "/batches/{batch_id}/transcripts/generate")
    assert gate == {"transcript.generate"}
    assert "transcript.generate" not in ROLE_PERMISSIONS["TUTOR"]
    assert not gate & ROLE_PERMISSIONS["TUTOR"], (
        "a Tutor holds a permission this route accepts, so they can issue transcripts"
    )
    assert gate <= ROLE_PERMISSIONS["SUPER_ADMIN"]


def test_the_transcript_permissions_are_enforced_somewhere() -> None:
    """`transcript.read` and `transcript.generate` were seeded, documented,
    shown in the role editor -- and checked by nothing. A permission an
    administrator can grant and withdraw with no effect is worse than one that
    does not exist, because it reads as a control."""
    enforced: set[str] = set()
    for route in _routes():
        enforced |= set(_required_codes(route.dependant))
    for code in ("transcript.read", "transcript.generate", "quiz.publish", "exam.grade"):
        assert code in ALL_PERMISSIONS, f"{code} vanished from the catalogue"
        assert code in enforced, f"{code} is in the catalogue but no route enforces it"
