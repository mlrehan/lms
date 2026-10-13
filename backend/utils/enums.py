from enum import Enum


def enum_val(e):
    try:
        return e.value
    except Exception:
        return e


def enum_name(e):
    try:
        return e.name
    except Exception:
        return e


# =============================================================================
# Identity (spec §2, §4)
# =============================================================================


class UserStatus(str, Enum):
    """Spec §4's exact four account states. ``DELETED`` *is* the deletion
    signal for a user row — there is deliberately no separate ``is_deleted``
    boolean on ``User`` (see ``models/identity/user.py``); two independent
    flags claiming to answer "is this account gone?" is how they drift."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class Genders(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class Roles(str, Enum):
    """The platform's six roles: Super Admin, Administrator, Corporate
    Manager, Guardian, Tutor, Student. Corporate/guardian relationships live
    in dedicated tables (organization.py, guardian.py), never as a column on
    User or Student -- see those modules' docstrings for why."""

    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    CORPORATE_MANAGER = "CORPORATE_MANAGER"
    GUARDIAN = "GUARDIAN"
    TUTOR = "TUTOR"
    STUDENT = "STUDENT"


# =============================================================================
# Course & academic structure (spec §5, §23)
# =============================================================================


class CourseStatus(str, Enum):
    """Spec §5's exact lifecycle: Draft -> Published -> Running -> Completed
    -> Archived."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class Levels(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class Platforms(str, Enum):
    Zoom = "Zoom"
    Zoho = "Zoho"
    Google_Meet = "Google_Meet"
    Microsoft_Teams = "Microsoft_Teams"
    Classroom = "Classroom"


# =============================================================================
# Enrollment & attendance (spec §7, §9)
# =============================================================================


class EnrollmentStatus(str, Enum):
    """Spec §7's exact five states."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    """Spec §9's exact four states."""

    PRESENT = "PRESENT"
    LATE = "LATE"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class PerformanceLevel(str, Enum):
    poor = "poor"
    below_average = "below_average"
    average = "average"
    good = "good"
    excellent = "excellent"


# =============================================================================
# Quiz & examination (spec §13, §14)
# =============================================================================


class QuestionType(str, Enum):
    """Spec §13's question types. MCQ is split single/multiple because
    single-select and multi-select need different answer-storage and
    auto-grading logic even though the spec lists them under one bullet."""

    MCQ_SINGLE = "MCQ_SINGLE"
    MCQ_MULTIPLE = "MCQ_MULTIPLE"
    TRUE_FALSE = "TRUE_FALSE"
    SHORT_ANSWER = "SHORT_ANSWER"
    ESSAY = "ESSAY"
    # Four more a machine can mark, each needing its own answer-key shape --
    # which is why they are separate types rather than one "other". The
    # column is a VARCHAR (`native_enum=False`) with no CHECK constraint, so
    # adding a member needs no DDL; existing rows are untouched.
    FILL_BLANK = "FILL_BLANK"
    MATCHING = "MATCHING"
    ORDERING = "ORDERING"
    NUMERIC = "NUMERIC"


class ExamType(str, Enum):
    """Spec §14's exact five exam types."""

    MIDTERM = "MIDTERM"
    FINAL = "FINAL"
    PRACTICAL = "PRACTICAL"
    MOCK = "MOCK"
    CUSTOM = "CUSTOM"


# =============================================================================
# Assignments (spec §12)
# =============================================================================


class SubmissionType(str, Enum):
    FILE_UPLOAD = "FILE_UPLOAD"
    TEXT = "TEXT"
    LINK = "LINK"


# =============================================================================
# Grade book (spec §15)
# =============================================================================


class GradeComponentType(str, Enum):
    """Spec §15's exact list of what a grade book stores."""

    ASSIGNMENT = "ASSIGNMENT"
    QUIZ = "QUIZ"
    ATTENDANCE = "ATTENDANCE"
    PRACTICAL = "PRACTICAL"
    FINAL_EXAM = "FINAL_EXAM"


# =============================================================================
# Academic assessment (spec §3, §7, §13, §14)
# =============================================================================


class AssessmentScope(str, Enum):
    """Which population an assessment is set for.

    One enum shared by assignments, quizzes and examinations rather than three
    parallel implementations -- §3 says so explicitly, and the alternative is
    the same eligibility rule written out three times and drifting.

    The scope is stored alongside the ids it refers to, rather than inferred
    from which id happens to be non-null. "Set for the whole course" and "set
    for a batch we have not chosen yet" are different states, and an inference
    rule cannot tell them apart.
    """

    COURSE = "COURSE"
    BATCH = "BATCH"
    SESSION = "SESSION"


class AssessmentState(str, Enum):
    """Whether an assessment is visible to the students it is set for.

    Distinct from `ResultState` below: this is the *question* becoming visible,
    that is the *mark* becoming visible, and an institution needs both.
    """

    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class SubmissionState(str, Enum):
    """Where one student stands on one assessment (spec §7).

    Eleven states because the four §38 insists on distinguishing -- scored
    zero, not yet assessed, absent, exempted -- are genuinely different facts,
    and a nullable mark plus a boolean cannot express them. Silently treating
    a missing mark as zero is the specific failure this enum exists to prevent.
    """

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    LATE = "LATE"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRADED = "GRADED"
    PUBLISHED = "PUBLISHED"
    ABSENT = "ABSENT"
    EXEMPTED = "EXEMPTED"
    RESUBMISSION_REQUIRED = "RESUBMISSION_REQUIRED"
    REASSESSED = "REASSESSED"

    @property
    def counts_toward_grade(self) -> bool:
        """Does this state contribute a number to the weighted result?

        `EXEMPTED` deliberately does not: an exempted component is removed from
        the denominator rather than scored zero, which is the whole point of
        exempting somebody. `ABSENT` does count -- an absence is a nil result
        the institution has decided about, not a gap in the record.
        """
        return self in {
            SubmissionState.GRADED,
            SubmissionState.PUBLISHED,
            SubmissionState.REASSESSED,
            SubmissionState.ABSENT,
        }

    @property
    def is_visible_to_student(self) -> bool:
        """Only a published mark reaches the student and their care circle
        (§14). Every other state is staff-facing."""
        return self in {SubmissionState.PUBLISHED, SubmissionState.REASSESSED}


class ResultState(str, Enum):
    """The lifecycle a set of marks moves through (spec §14)."""

    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIZED = "FINALIZED"
    PUBLISHED = "PUBLISHED"


class GradeScaleType(str, Enum):
    """How a computed percentage is expressed (spec §13)."""

    PERCENTAGE = "PERCENTAGE"
    LETTER = "LETTER"
    GPA = "GPA"
    PASS_FAIL = "PASS_FAIL"
    NUMERIC = "NUMERIC"
    COMPETENCY = "COMPETENCY"


class MissingMarkPolicy(str, Enum):
    """What the engine does with a component that has no mark (spec §38).

    Configurable because institutions genuinely differ, and because the wrong
    default produces a confidently wrong number. `EXCLUDE` is the safe one: it
    reports "82% of the 35 marks assessed so far" rather than "29%".
    """

    EXCLUDE = "EXCLUDE"
    ZERO = "ZERO"
    CARRY_FORWARD = "CARRY_FORWARD"


# =============================================================================
# Resources & files (spec §10, §11)
# =============================================================================


class ResourceType(str, Enum):
    lecture_sheet = "Lecture Sheet"
    lesson = "Lesson"
    document = "Document"
    video = "Video"
    audio = "Audio"
    recordings = "Recordings"
    presentation = "Presentation"
    quiz = "Quiz"
    assignment = "Assignment"
    project = "Project"
    certificate = "Certificate"
    progress_report = "Progress Report"
    announcement = "Announcement"
    policy_document = "Policy Document"
    custom_content = "Custom Content"


class FileStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    deleted = "deleted"


class ResourceScopeType(str, Enum):
    """Spec §11's permission cascade: Course -> Batch -> Session -> Individual."""

    COURSE = "COURSE"
    BATCH = "BATCH"
    SESSION = "SESSION"
    USER = "USER"


class ResourcePermissionLevel(str, Enum):
    VIEW = "VIEW"
    DOWNLOAD = "DOWNLOAD"
    EDIT = "EDIT"
    MANAGE = "MANAGE"


# =============================================================================
# Communication (spec §16, §21)
# =============================================================================


class NotificationChannel(str, Enum):
    """Spec §16/§21: one delivery record per channel, not four separate
    notification tables."""

    SYSTEM = "SYSTEM"
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


# =============================================================================
# Corporate organizations
# =============================================================================


class OrganizationMembershipStatus(str, Enum):
    """An employee's relationship to their sponsoring organization. A row
    with status REMOVED is kept, not deleted -- historical enrollments must
    still show which organization sponsored them."""

    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


# =============================================================================
# Authentication (spec §3)
# =============================================================================


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"
