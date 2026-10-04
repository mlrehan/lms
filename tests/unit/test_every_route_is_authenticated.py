"""Every route is authenticated unless it is on the list below (§20, §46).

§46 says not to create features that look functional on the frontend while
lacking backend enforcement, and §20 puts role-based access on the backend rather
than the console. Both are properties of *every* route, not of the routes anybody
remembers to check — and a route that forgets its dependency is invisible: it
works, it returns data, and nothing about it looks different from one that is
gated. The console around it behaves identically either way.

So this walks the real application, resolves each route's full dependency tree,
and fails on anything that reaches neither `get_current_user` nor
`require_permissions` unless it is named in `PUBLIC` with a reason.

The list is deliberately awkward to extend: adding a route to it means writing
down why the institution's data may be read without signing in, in a file a
reviewer reads. That is the point — the cost of making a route public should be
having to defend it, not editing a boolean.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

import backend.main as main

#: Routes that genuinely cannot require a signed-in caller, each with the reason.
#: A route is keyed by path alone: every method on these paths is public.
PUBLIC: dict[str, str] = {
    "/auth/login": "The caller has no session yet -- this is where one is issued.",
    "/auth/refresh": (
        "Presents a refresh token, not an access token. Requiring a live access "
        "token would defeat the purpose: refresh exists for when it has expired."
    ),
    "/livez": "A liveness probe is configured on a fixed path and carries no credentials.",
    "/readyz": "Same, and it must answer while the database it reports on is down.",
    "/integrations/calendar/{token}.ics": (
        "A calendar client (Outlook, Google, Apple) subscribes to a URL and cannot "
        "send an Authorization header. The unguessable token in the path IS the "
        "credential, which is why it is revocable per feed."
    ),
    "/shared/{token}": (
        "A share link is given to somebody who has no account by design. The token "
        "is the grant, and it carries its own expiry and permission level."
    ),
    "/realtime/stream": (
        "SSE: the browser's EventSource cannot set an Authorization header. The "
        "route authenticates the token by hand instead -- so it is not unguarded, "
        "it is guarded somewhere this scan cannot see."
    ),
}

#: What a dependency has to reach for the route to count as authenticated.
_AUTH_MARKERS = ("require_permissions", "get_current_user")


def _routes():  # noqa: ANN202
    """Every APIRoute in the running app, however it was included.

    FastAPI wraps an `include_router` call in `_IncludedRouter` rather than
    flattening it into `app.routes`, so walking `app.routes` directly finds the
    handful of routes defined on the app itself and misses the entire API. A
    check that silently inspected six routes and passed would be worse than no
    check at all.
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


def _dependency_names(dependant, seen: set[str] | None = None):  # noqa: ANN001, ANN202
    """Every callable in the route's dependency tree, not just the top level.

    `require_permissions` is usually reached through an `Annotated[CurrentUser,
    Depends(_READ)]` parameter, so a one-level check would miss it and report a
    properly gated route as open.
    """
    seen = set() if seen is None else seen
    for sub in dependant.dependencies:
        name = getattr(sub.call, "__qualname__", str(sub.call))
        if name in seen:
            continue
        seen.add(name)
        yield name
        yield from _dependency_names(sub, seen)


def test_the_route_walk_actually_finds_the_api() -> None:
    """Guards the guard.

    Without this, a change to how routers are included would quietly reduce the
    scan to a handful of routes and every assertion below would pass vacuously --
    the exact failure mode this file exists to prevent, one level up.
    """
    routes = _routes()
    assert len(routes) > 200, f"the route walk only found {len(routes)} routes"
    paths = {r.path for r in routes}
    # A representative route from three different routers, so the walk cannot be
    # finding one router and missing the rest.
    assert "/users" in paths
    assert "/class-performance/sessions/{session_id}" in paths
    assert "/transcripts/{transcript_id}" in paths


def test_every_route_requires_a_signed_in_caller() -> None:
    """The rule itself."""
    unguarded = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in _routes()
        if route.path not in PUBLIC
        and not any(
            marker in name
            for name in _dependency_names(route.dependant)
            for marker in _AUTH_MARKERS
        )
    )
    assert not unguarded, (
        "These routes reach neither get_current_user nor require_permissions, so "
        "anybody can call them:\n  " + "\n  ".join(unguarded) + "\n\nIf a route is "
        "genuinely meant to be public, add it to PUBLIC in this file with the "
        "reason."
    )


def test_the_public_list_has_no_stale_entries() -> None:
    """An allowlist nobody prunes stops being a list of exceptions and becomes a
    hole: a path removed from the API leaves its entry behind, and a later route
    reusing that path is public without anybody deciding so."""
    live = {route.path for route in _routes()}
    stale = sorted(path for path in PUBLIC if path not in live)
    assert not stale, f"PUBLIC names routes that no longer exist: {stale}"


def test_the_academic_routes_are_permission_gated_not_merely_authenticated() -> None:
    """Signing in is not authorisation (§21).

    The assessment surfaces carry marks, transcripts and the calculation engine's
    output -- a route there that checked only "is somebody logged in" would hand
    a student the whole institution's grade book. Checked as a group rather than
    per route so a new one is covered the day it is added.
    """
    prefixes = ("/class-performance", "/performance", "/transcripts", "/grading-schemes")
    checked = 0
    weak = []
    for route in _routes():
        if not route.path.startswith(prefixes):
            continue
        checked += 1
        names = set(_dependency_names(route.dependant))
        if not any("require_permissions" in name for name in names):
            weak.append(f"{sorted(route.methods)} {route.path}")

    assert checked >= 10, f"only {checked} academic routes found -- the prefixes are wrong"
    assert not weak, f"authenticated but not permission-gated: {weak}"
