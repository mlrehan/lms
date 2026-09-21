"""Top-level API router, mounted under the configured `API_PREFIX`.

Operational endpoints (liveness/readiness) deliberately live outside this
router, in `backend/main.py`: a load balancer or Kubernetes probe is
configured against a fixed, unversioned path, not one nested under whatever
the API version happens to be this deployment.
"""

from fastapi import APIRouter

from backend.api.v1 import (
    academic,
    announcements,
    assignments,
    audit,
    attendance,
    auth,
    batches,
    courses,
    dashboard,
    discussions,
    enrollments,
    exams,
    geo,
    gradebook,
    guardians,
    team,
    google_calendar,
    integrations,
    messages,
    notifications,
    ops,
    organizations,
    quizzes,
    reports,
    resources,
    roles,
    search,
    security,
    sessions,
    settings,
    academic_sync,
    user_sync,
    users,
)

router = APIRouter()

router.include_router(auth.router)
router.include_router(user_sync.router)
router.include_router(users.router)
router.include_router(roles.router)
router.include_router(geo.router)
router.include_router(academic_sync.router)
router.include_router(courses.router)
router.include_router(batches.router)
router.include_router(sessions.router)
router.include_router(enrollments.router)
router.include_router(attendance.router)
router.include_router(assignments.router)
router.include_router(quizzes.router)
router.include_router(exams.router)
router.include_router(gradebook.router)
router.include_router(resources.router)
router.include_router(organizations.router)
router.include_router(guardians.router)
router.include_router(team.router)
router.include_router(messages.router)
router.include_router(notifications.router)
router.include_router(announcements.router)
router.include_router(discussions.router)
router.include_router(discussions.replies_router)
router.include_router(academic.years_router)
router.include_router(academic.semesters_router)
router.include_router(academic.departments_router)
router.include_router(academic.categories_router)
router.include_router(academic.tags_router)
router.include_router(settings.router)
router.include_router(dashboard.router)
router.include_router(reports.router)
router.include_router(audit.router)
router.include_router(security.router)
router.include_router(search.router)
router.include_router(google_calendar.router)
router.include_router(integrations.router)
router.include_router(ops.router)
