from backend.models.identity.permission import Permission
from backend.models.identity.role import Role
from backend.models.identity.role_permission import RolePermission
from backend.models.identity.token import Token
from backend.models.identity.user_role import UserRole
from backend.models.identity.user import User, CurrentUser
from .geo import Country, City, TimeZone
from .administration import (
    AcademicYear, Semester, Department, Category, CategoryEditor, CourseEditor,
    Tag, CourseTag, SystemSetting,
)
from .audit import AuditLog
from .organization import (
    ManagedStudent,
    Organization,
    OrganizationManager,
    OrganizationMembership,
)
from .guardian import StudentGuardian
from .messaging import TutorReview, CourseDiscussion, DiscussionReply
from .mail import MailMessage, MailRecipient, MailAttachment
from .attendance_sheet import AttendanceSheet, AttendanceSheetEvent
from .course import Course, TutorCourse
from .batch import Batch, BatchSession
from .enrollment import Enrollments
from .attendance import Attendance
from .resource import Resource, SharedResource, ResourceFolder, ResourceVersion, ResourcePermission
from .assignment import Assignment, AssignmentSubmission, AssignmentSubmissionFile
from .quiz import Quiz, Question, QuestionOption, QuizAttempt, QuizAnswer
from .exam import Exam, ExamInvigilator, ExamResult
from .grading import GradingScheme, GradingSchemeComponent
from .class_performance import ClassPerformanceMark
from .gradebook import GradeBand, GradeBookEntry, Transcript
from .certificate import Certificate, CertificateIssued
from .badge import Badge, UserBadge
from .integration import CalendarFeed, WebhookDelivery, WebhookEndpoint
from .sync_pipeline import (
    PIPELINE_STEP_LABELS,
    PIPELINE_STEPS,
    SyncPipelineJob,
    SyncPipelineRun,
)
from .user_sync import UserSyncRun
from .google_connection import GoogleChangeRequest, GoogleConnection
from .notification import Notification, Announcement, AnnouncementRead
from .push import PushSubscription
from .shared_links import SharedLink, SharedLinkTarget
from .ai_embedding import ResourceEmbedding, AIConversationMessage

__all__ = [
    # AI & Embeddings
    "ResourceEmbedding", "AIConversationMessage",
    # Identity
    "User", "CurrentUser", "Role", "Permission", "Token", "UserRole", "RolePermission",
    # Geo
    "Country", "City", "TimeZone",
    # Administration
    "AcademicYear", "Semester", "Department", "Category", "CategoryEditor", "CourseEditor", "Tag", "CourseTag", "SystemSetting",
    # Audit
    "AuditLog",
    # Corporate organizations & guardianship
    "ManagedStudent",
    "Organization", "OrganizationManager", "OrganizationMembership", "StudentGuardian",
    # Messaging
    "MailMessage", "MailRecipient", "MailAttachment", "AttendanceSheet", "AttendanceSheetEvent", "TutorReview", "CourseDiscussion", "DiscussionReply",
    # Course & batch
    "Course", "TutorCourse", "Batch", "BatchSession",
    # Enrollment & attendance
    "Enrollments", "Attendance",
    # Resources
    "Resource", "SharedResource", "ResourceFolder", "ResourceVersion", "ResourcePermission",
    # Assignments
    "Assignment", "AssignmentSubmission", "AssignmentSubmissionFile",
    # Quiz
    "Quiz", "Question", "QuestionOption", "QuizAttempt", "QuizAnswer",
    # Examination
    "Exam", "ExamInvigilator", "ExamResult",
    # Grade book
    "GradeBand", "GradeBookEntry", "Transcript",
    "GradingScheme",
    "GradingSchemeComponent",
    "ClassPerformanceMark",
    # Certificates & badges
    "Certificate", "CertificateIssued", "Badge", "UserBadge",
    # Notifications
    "Notification",
    "PushSubscription", "Announcement", "AnnouncementRead",
    # Shared links
    "SharedLink", "SharedLinkTarget",
    # Background synchronisation
    "SyncPipelineRun", "SyncPipelineJob", "PIPELINE_STEPS", "PIPELINE_STEP_LABELS",
]
