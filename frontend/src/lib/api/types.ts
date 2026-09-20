/**
 * GENERATED from the LMS backend's OpenAPI document -- do not edit by hand.
 *
 * Regenerate after any backend schema change:
 *   python scripts/generate_api_types.py
 *
 * Every type here is a transcription of a shape the API actually returns.
 * If a screen needs a field that is absent from this file, the backend does
 * not provide it -- that is a gap to document, not a type to add.
 */

export interface AcademicYearCreateRequest {
  /** e.g. '2025-2026'. */
  label: string;
  start_date: string;
  end_date: string;
  /** Promoting a year to current demotes whichever held it. */
  is_current?: boolean;
}

export interface AcademicYearResponse {
  public_id: string;
  label: string;
  start_date: string;
  end_date: string;
  is_current?: boolean;
  semester_count?: number;
  /** Batches scheduled into this year; blocks deletion. */
  batch_count?: number;
}

export interface AcademicYearUpdateRequest {
  label?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  is_current?: boolean | null;
}

export interface AddMemberRequest {
  /** A user holding the STUDENT role. */
  user_id: string;
  employee_code?: string | null;
  department?: string | null;
  /** Create the membership ACTIVE rather than INVITED. An administrator adding a known employee is the acceptance step. */
  activate_immediately?: boolean;
}

export interface AdminSessionResponse {
  public_id: string;
  user_id: string;
  username: string;
  created_at?: string | null;
  expires_at?: string | null;
  user_agent?: string | null;
  ip_address?: string | null;
}

/**
 * An administrator resetting someone else's password. Distinct from
 * `ChangePasswordRequest`, which requires the *current* password because
 * the caller is acting on their own account.
 */
export interface AdminSetPasswordRequest {
  new_password: string;
}

export interface AnnouncementResponse {
  public_id: string;
  title: string;
  content: string;
  author?: PartyRef | null;
  course_id?: string | null;
  course_title?: string | null;
  batch_id?: string | null;
  batch_code?: string | null;
  role_scope?: Roles | null;
  start_at?: string | null;
  end_at?: string | null;
  pinned?: boolean;
  /** Whether the display window currently includes now. */
  is_live?: boolean;
}

export interface AnswerInput {
  question_id: string;
  selected_option_ids?: number[] | null;
  text_answer?: string | null;
}

export interface AnswerResponse {
  question_id: string;
  question_text?: string | null;
  selected_options?: unknown | null;
  score_awarded?: string | null;
}

export interface AppointManagerRequest {
  /** A user holding the CORPORATE_MANAGER role. */
  user_id: string;
  /** e.g. 'L&D Manager'. */
  title?: string | null;
}

export interface AssignmentBrief {
  public_id: string;
  title: string;
  course_title: string;
  due_date?: string | null;
  is_overdue?: boolean;
}

export interface AssignmentCreateRequest {
  title: string;
  description?: string | null;
  due_date: string;
  max_score: number | string;
  submission_type?: SubmissionType;
  instructions_path?: string | null;
  rubric?: unknown | null;
  allow_late_submissions?: boolean;
}

export interface AssignmentResponse {
  public_id: string;
  title: string;
  due_date: string;
  max_score: string;
  submission_type: SubmissionType;
  allow_late_submissions: boolean;
  description?: string | null;
  instructions_path?: string | null;
  rubric?: unknown | null;
  course_id: string;
  course_title?: string | null;
  submission_count?: number;
  /** Set when the caller has already submitted, so a client need not fetch the list to know. */
  my_submission_id?: string | null;
}

export interface AssignmentSummary {
  public_id: string;
  title: string;
  due_date: string;
  max_score: string;
  submission_type: SubmissionType;
  allow_late_submissions: boolean;
}

export interface AssignmentUpdateRequest {
  title?: string | null;
  description?: string | null;
  due_date?: string | null;
  max_score?: number | string | null;
  submission_type?: SubmissionType | null;
  instructions_path?: string | null;
  rubric?: unknown | null;
  allow_late_submissions?: boolean | null;
}

export interface AttemptResponse {
  public_id: string;
  quiz_id: string;
  quiz_title?: string | null;
  student_id: string;
  student_username?: string | null;
  attempt_number: number;
  started_at: string;
  finished_at?: string | null;
  score?: string | null;
  is_passed?: boolean | null;
  submitted_late?: boolean;
  feedback?: string | null;
  /** True when the attempt contains short-answer/essay questions a tutor has not yet scored. */
  awaiting_manual_grading?: boolean;
  answers?: AnswerResponse[];
}

export interface AttendanceEntry {
  student_id: string;
  status: AttendanceStatus;
  remarks?: string | null;
}

export type AttendanceGroupBy = "course" | "batch" | "tutor" | "student" | "month";
export const AttendanceGroupByValues = ["course", "batch", "tutor", "student", "month"] as const;

export interface AttendanceResponse {
  public_id: string;
  session_id: string;
  session_start_time?: string | null;
  batch_code?: string | null;
  student_id: string;
  student_username?: string | null;
  status: AttendanceStatus;
  remarks?: string | null;
  recorded_at?: string | null;
  recorded_by_username?: string | null;
}

/**
 * Spec §9's exact four states.
 */
export type AttendanceStatus = "PRESENT" | "LATE" | "ABSENT" | "EXCUSED";
export const AttendanceStatusValues = ["PRESENT", "LATE", "ABSENT", "EXCUSED"] as const;

/**
 * Spec §9's attendance reporting.
 */
export interface AttendanceSummaryResponse {
  present?: number;
  late?: number;
  absent?: number;
  excused?: number;
  total?: number;
  /** (present + late) / (total - excused), as a percentage. Excused absences leave the denominator rather than counting against the student. Null when there is nothing to divide by. */
  attendance_rate?: number | null;
}

/**
 * What a filter UI needs, so it never hardcodes the vocabulary.
 */
export interface AuditCatalogResponse {
  actions: string[];
  /** The subset surfaced by /security/events. */
  security_actions: string[];
  entity_types: string[];
  /** Entity types whose rows can be filtered by id (the rest have no public id). */
  filterable_entity_types: string[];
}

export interface AuditLogResponse {
  public_id: string;
  action: string;
  success?: boolean;
  /** Null for an action by a since-deleted account. */
  actor_id?: string | null;
  actor_email?: string | null;
  actor_username?: string | null;
  entity_type?: string | null;
  /** The entity's public identifier, resolved at read time. Null when the entity has been deleted or its table has no public id. */
  entity_id?: string | null;
  /** Human-readable name, e.g. a course title. Best effort. */
  entity_label?: string | null;
  details?: Record<string, unknown> | null;
  ip_address?: string | null;
  user_agent?: string | null;
  request_id?: string | null;
  created_at: string;
}

/**
 * One active refresh-token session -- spec §3's 'Session management',
 * i.e. 'which devices am I signed in on, and can I end one?'
 */
export interface AuthSessionResponse {
  public_id: string;
  created_at: string;
  expires_at: string;
  user_agent?: string | null;
  ip_address?: string | null;
  /** True for the session making this request. */
  is_current?: boolean;
}

export interface BatchCreateRequest {
  /** Unique across the institution, e.g. 'MATH101-A'. */
  batch_code: string;
  capacity?: number | null;
  duration_hours?: number | null;
  number_of_sessions?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  notes?: string | null;
  academic_year_id?: string | null;
  /** Must belong to `academic_year_id` when both are given; naming only the semester implies its year. */
  semester_id?: string | null;
}

export interface BatchResponse {
  public_id: string;
  batch_code: string;
  is_active: boolean;
  start_date?: string | null;
  end_date?: string | null;
  capacity?: number | null;
  /** public_id of the owning course. */
  course_id: string;
  course_title?: string | null;
  academic_year_id?: string | null;
  academic_year_label?: string | null;
  semester_id?: string | null;
  semester_name?: string | null;
  duration_hours?: number | null;
  number_of_sessions?: number | null;
  notes?: string | null;
  /** Enrollments currently occupying a seat. */
  enrolled_count?: number;
  /** Null when the batch has no capacity limit. */
  seats_available?: number | null;
}

export interface BatchSummary {
  public_id: string;
  batch_code: string;
  is_active: boolean;
  start_date?: string | null;
  end_date?: string | null;
  capacity?: number | null;
}

export interface BatchUpdateRequest {
  batch_code?: string | null;
  capacity?: number | null;
  duration_hours?: number | null;
  number_of_sessions?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  notes?: string | null;
  is_active?: boolean | null;
  academic_year_id?: string | null;
  semester_id?: string | null;
  /** Unschedule from its academic year (and semester). */
  clear_academic_year?: boolean;
  /** Unschedule from its semester. */
  clear_semester?: boolean;
}

export interface BodyUploadResourceApiV1ResourcesPost {
  file: string;
  resource_type?: ResourceType;
  name?: string | null;
  folder_id?: string | null;
  course_id?: string | null;
  batch_id?: string | null;
}

export interface BodyUploadVersionApiV1ResourcesversionsPost {
  file: string;
  change_note?: string | null;
}

export interface CalendarFeedCreatedResponse {
  public_id: string;
  name: string;
  is_active?: boolean;
  created_at?: string | null;
  last_accessed_at?: string | null;
  access_count?: number;
  /** Shown once. Anyone holding this link can read the timetable. */
  url: string;
  warning?: string;
}

export interface CalendarFeedResponse {
  public_id: string;
  name: string;
  is_active?: boolean;
  created_at?: string | null;
  last_accessed_at?: string | null;
  access_count?: number;
}

/**
 * Guardians and corporate managers: the people in their care.
 */
export interface CarePanel {
  people?: number;
  attendance_rate?: number | null;
  assignments_overdue?: number;
  upcoming_sessions?: SessionBrief[];
}

export interface CategoryCreateRequest {
  name: string;
  /** Omit for a top-level category. */
  parent_id?: string | null;
}

export interface CategoryResponse {
  public_id: string;
  name: string;
  parent_id?: string | null;
  parent_name?: string | null;
  child_count?: number;
  course_count?: number;
}

export interface CategoryUpdateRequest {
  name?: string | null;
  parent_id?: string | null;
  /** Detach from its parent. Overrides `parent_id`. */
  make_top_level?: boolean;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface CityResponse {
  public_id: string;
  name: string;
  population?: number | null;
  timezone?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  country_id: string;
  country_name?: string | null;
  country_code?: string | null;
}

export interface CitySummary {
  public_id: string;
  name: string;
  population?: number | null;
  timezone?: string | null;
}

export interface ComponentBreakdown {
  component_type: GradeComponentType;
  entries: number;
  earned: string;
  available: string;
  percentage?: string | null;
  weight: string;
}

/**
 * One row per correspondent, for a mailbox landing page.
 */
export interface ConversationResponse {
  counterpart: PartyRef;
  last_message_id: string;
  last_message_at?: string | null;
  last_subject?: string | null;
  last_snippet?: string | null;
  unread_count?: number;
  total_messages?: number;
}

export interface CountryResponse {
  public_id: string;
  name: string;
  code: string;
}

export interface CourseCreateRequest {
  title: string;
  code?: string | null;
  description?: string | null;
  level?: Levels;
  duration_hours?: number | null;
  prerequisites?: string | null;
  price?: number | null;
  course_link?: string | null;
  course_picture?: string | null;
  category_id?: string | null;
  department_id?: string | null;
}

export interface CourseResponse {
  public_id: string;
  title: string;
  code?: string | null;
  status: CourseStatus;
  level: Levels;
  duration_hours?: number | null;
  price?: number | null;
  course_picture?: string | null;
  description?: string | null;
  prerequisites?: string | null;
  course_link?: string | null;
  category_id?: string | null;
  category_name?: string | null;
  department_id?: string | null;
  department_name?: string | null;
  tags?: string[];
  created_at: string;
  updated_at?: string | null;
  /** Usernames of tutors assigned to this course. */
  tutors?: string[];
  batch_count?: number;
}

/**
 * Spec §5's exact lifecycle: Draft -> Published -> Running -> Completed
 * -> Archived.
 */
export type CourseStatus = "DRAFT" | "PUBLISHED" | "RUNNING" | "COMPLETED" | "ARCHIVED";
export const CourseStatusValues = ["DRAFT", "PUBLISHED", "RUNNING", "COMPLETED", "ARCHIVED"] as const;

/**
 * Spec §5's lifecycle. Legal transitions are enforced server-side --
 * see `services/course_service.py::_ALLOWED_TRANSITIONS`.
 */
export interface CourseStatusRequest {
  status: CourseStatus;
}

export interface CourseSummary {
  public_id: string;
  title: string;
  code?: string | null;
  status: CourseStatus;
  level: Levels;
  duration_hours?: number | null;
  price?: number | null;
  course_picture?: string | null;
}

export interface CourseTutorsRequest {
  /** The complete set of tutor public_ids for this course. */
  tutors: string[];
}

export interface CourseUpdateRequest {
  title?: string | null;
  code?: string | null;
  description?: string | null;
  level?: Levels | null;
  duration_hours?: number | null;
  prerequisites?: string | null;
  price?: number | null;
  course_link?: string | null;
  course_picture?: string | null;
  category_id?: string | null;
  department_id?: string | null;
  /** Uncategorise this course. */
  clear_category?: boolean;
  /** Detach this course from its department. */
  clear_department?: boolean;
}

export interface CreateAnnouncementRequest {
  title: string;
  content: string;
  course_id?: string | null;
  batch_id?: string | null;
  /** Narrow to one role. Omit for every role. */
  role_scope?: Roles | null;
  /** Defaults to now, i.e. publish immediately. */
  start_at?: string | null;
  /** Omit for an announcement that never expires. */
  end_at?: string | null;
  pinned?: boolean;
}

export interface CreateCalendarFeedRequest {
  name?: string;
}

export interface CreateDiscussionRequest {
  course_id: string;
  title: string;
  body: string;
}

export interface CreateGuardianLinkRequest {
  /** A user holding the GUARDIAN role. */
  guardian_id: string;
  /** A user holding the STUDENT role. */
  student_id: string;
  /** e.g. 'Parent', 'Legal Guardian'. */
  relationship_type?: string | null;
  /** Marks the main point of contact when a student has several guardians. */
  is_primary?: boolean;
}

export interface CreateWebhookRequest {
  name: string;
  target_url: string;
  /** Event codes from /integrations/webhooks/events. */
  events: string[];
  description?: string | null;
}

/**
 * `/auth/me`. Carries the caller's resolved permission set so a client
 * can render its navigation without guessing which role implies what --
 * the server stays the only authority on what is actually allowed.
 */
export interface CurrentUserResponse {
  public_id: string;
  username: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  full_name: string;
  status: UserStatus;
  profile_picture?: string | null;
  can_login?: boolean;
  is_synced?: boolean;
  external_student_id?: number | null;
  external_tutor_id?: number | null;
  title?: string | null;
  gender: Genders;
  date_of_birth?: string | null;
  phone_number?: string | null;
  mobile?: string | null;
  designation?: string | null;
  web?: string | null;
  company?: string | null;
  address?: string | null;
  postcode?: string | null;
  timezone?: string | null;
  country?: LocationRef | null;
  city?: LocationRef | null;
  bio?: string | null;
  is_public: boolean;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
  emergency_contact_relationship?: string | null;
  is_locked: boolean;
  last_login?: string | null;
  created_at: string;
  /** Role names held by this user. */
  roles?: string[];
  permissions?: string[];
}

export interface DashboardResponse {
  generated_at: string;
  /** Which panels are populated for this caller, in display order. */
  panels: string[];
  personal: PersonalPanel;
  student?: StudentPanel | null;
  teaching?: TeachingPanel | null;
  care?: CarePanel | null;
  institution?: InstitutionPanel | null;
}

export interface DepartmentCreateRequest {
  name: string;
  code?: string | null;
  /** Must be a user holding the TUTOR role. */
  head_tutor_id?: string | null;
}

export interface DepartmentResponse {
  public_id: string;
  name: string;
  code?: string | null;
  head_tutor_id?: string | null;
  head_tutor_username?: string | null;
  course_count?: number;
}

export interface DepartmentUpdateRequest {
  name?: string | null;
  code?: string | null;
  head_tutor_id?: string | null;
  /** Vacate the post. A separate flag because `head_tutor_id: null` is indistinguishable from 'not sent' once optional fields are omitted. */
  clear_head_tutor?: boolean;
}

export interface DiscussionReplyResponse {
  public_id: string;
  discussion_id: string;
  author?: PartyRef | null;
  body: string;
  created_at?: string | null;
}

export interface DiscussionResponse {
  public_id: string;
  course_id: string;
  course_title?: string | null;
  author?: PartyRef | null;
  title: string;
  body: string;
  is_pinned?: boolean;
  is_locked?: boolean;
  reply_count?: number;
  created_at?: string | null;
}

export interface EnrollRequest {
  student_id: string;
  batch_id: string;
  /** Create the enrollment already CONFIRMED rather than PENDING. An administrator enrolling someone directly is the approval step. */
  confirmed?: boolean;
}

export type EnrollmentGroupBy = "course" | "batch" | "status" | "month";
export const EnrollmentGroupByValues = ["course", "batch", "status", "month"] as const;

export interface EnrollmentResponse {
  public_id: string;
  status: EnrollmentStatus;
  enrollment_date?: string | null;
  is_transfer?: boolean;
  /** public_id of the enrolled student. */
  student_id: string;
  student_username?: string | null;
  /** public_id of the batch. */
  batch_id: string;
  batch_code?: string | null;
  course_title?: string | null;
  /** Set when a corporate organization sponsored this enrollment. */
  organization_id?: string | null;
  performance_level?: PerformanceLevel | null;
  can_download_certificate?: boolean;
  /** Set on a transfer, pointing at the enrollment this one replaced. */
  previous_enrollment_id?: string | null;
}

/**
 * Spec §7's exact five states.
 */
export type EnrollmentStatus = "PENDING" | "CONFIRMED" | "COMPLETED" | "DROPPED" | "CANCELLED";
export const EnrollmentStatusValues = ["PENDING", "CONFIRMED", "COMPLETED", "DROPPED", "CANCELLED"] as const;

export interface EnrollmentStatusRequest {
  status: EnrollmentStatus;
}

export interface ExamCreateRequest {
  title: string;
  exam_type: ExamType;
  scheduled_at: string;
  total_marks: number | string;
  passing_marks: number | string;
  duration_minutes?: number | null;
  venue_or_link?: string | null;
  instructions?: string | null;
  course_id?: string | null;
  batch_id?: string | null;
}

export interface ExamInvigilatorsRequest {
  /** The complete set of tutor public_ids invigilating this exam. */
  invigilators: string[];
}

export interface ExamPublishRequest {
  is_published: boolean;
}

export interface ExamResponse {
  public_id: string;
  title: string;
  exam_type: ExamType;
  scheduled_at: string;
  duration_minutes?: number | null;
  total_marks: string;
  passing_marks: string;
  is_published: boolean;
  venue_or_link?: string | null;
  instructions?: string | null;
  course_id?: string | null;
  course_title?: string | null;
  batch_id?: string | null;
  batch_code?: string | null;
  /** Usernames of assigned invigilators. */
  invigilators?: string[];
  result_count?: number;
  published_result_count?: number;
}

export interface ExamResultEntry {
  student_id: string;
  marks_obtained: number | string;
  grade?: string | null;
  remarks?: string | null;
}

export interface ExamResultResponse {
  public_id: string;
  exam_id: string;
  exam_title?: string | null;
  student_id: string;
  student_username?: string | null;
  marks_obtained?: string | null;
  grade?: string | null;
  remarks?: string | null;
  is_published: boolean;
  total_marks?: string | null;
  passing_marks?: string | null;
  /** Derived from marks_obtained vs the exam's passing_marks; null until marked. */
  is_passed?: boolean | null;
}

export interface ExamSummary {
  public_id: string;
  title: string;
  exam_type: ExamType;
  scheduled_at: string;
  duration_minutes?: number | null;
  total_marks: string;
  passing_marks: string;
  is_published: boolean;
}

/**
 * Spec §14's exact five exam types.
 */
export type ExamType = "MIDTERM" | "FINAL" | "PRACTICAL" | "MOCK" | "CUSTOM";
export const ExamTypeValues = ["MIDTERM", "FINAL", "PRACTICAL", "MOCK", "CUSTOM"] as const;

export interface ExamUpdateRequest {
  title?: string | null;
  exam_type?: ExamType | null;
  scheduled_at?: string | null;
  total_marks?: number | string | null;
  passing_marks?: number | string | null;
  duration_minutes?: number | null;
  venue_or_link?: string | null;
  instructions?: string | null;
}

export type ExportFormat = "json" | "csv";
export const ExportFormatValues = ["json", "csv"] as const;

export interface FinaliseTranscriptRequest {
  is_final: boolean;
}

export interface FolderCreateRequest {
  name: string;
  /** Omit to create a folder at the root of its course/batch. */
  parent_id?: string | null;
  course_id?: string | null;
  batch_id?: string | null;
}

export interface FolderResponse {
  public_id: string;
  name: string;
  created_at: string;
  parent_id?: string | null;
  course_id?: string | null;
  course_title?: string | null;
  batch_id?: string | null;
  batch_code?: string | null;
  created_by_username?: string | null;
  child_folder_count?: number;
  resource_count?: number;
  /** Folder names from the root down to and including this one. */
  path?: string[];
}

export interface FolderSummary {
  public_id: string;
  name: string;
  created_at: string;
}

/**
 * Renaming and moving are the same operation on a tree node.
 */
export interface FolderUpdateRequest {
  name?: string | null;
  /** New parent. Send explicitly as null to move to the root. */
  parent_id?: string | null;
}

export type Genders = "MALE" | "FEMALE" | "OTHER";
export const GendersValues = ["MALE", "FEMALE", "OTHER"] as const;

export interface GenerateTranscriptsResponse {
  generated?: number;
  updated?: number;
  /** Transcripts left alone because they are already finalised. */
  skipped_final?: number;
  /** Students with no grade book entries to aggregate. */
  skipped_no_grades?: number;
}

export interface GradeAnswerInput {
  question_id: string;
  score_awarded: number | string;
}

/**
 * Manual scoring for the questions auto-grading cannot mark.
 */
export interface GradeAttemptRequest {
  answers: GradeAnswerInput[];
  feedback?: string | null;
}

export interface GradeBandCreateRequest {
  min_score: number | string;
  max_score: number | string;
  letter_grade: string;
  gpa_points: number | string;
}

export interface GradeBandResponse {
  id: number;
  min_score: string;
  max_score: string;
  letter_grade: string;
  gpa_points: string;
}

export interface GradeBandUpdateRequest {
  min_score?: number | string | null;
  max_score?: number | string | null;
  letter_grade?: string | null;
  gpa_points?: number | string | null;
}

/**
 * A manually-recorded contribution -- PRACTICAL marks in particular have
 * no source row for `sync` to derive them from.
 */
export interface GradeBookEntryCreateRequest {
  student_id: string;
  component_type: GradeComponentType;
  score: number | string;
  max_score: number | string;
  weight?: number | string;
}

export interface GradeBookEntryResponse {
  public_id: string;
  student_id: string;
  student_username?: string | null;
  batch_id: string;
  batch_code?: string | null;
  component_type: GradeComponentType;
  reference_id?: number | null;
  score: string;
  max_score: string;
  weight: string;
  /** score / max_score as a percentage; null when max_score is 0. */
  percentage?: string | null;
  recorded_at: string;
}

export interface GradeBookEntryUpdateRequest {
  score?: number | string | null;
  max_score?: number | string | null;
  weight?: number | string | null;
}

/**
 * A student's standing in one batch, computed from their entries.
 */
export interface GradeBookSummaryResponse {
  student_id: string;
  student_username?: string | null;
  batch_id: string;
  batch_code?: string | null;
  components?: ComponentBreakdown[];
  /** Weighted average across components; null when nothing is recorded. */
  weighted_percentage?: string | null;
  letter_grade?: string | null;
  gpa_points?: string | null;
}

/**
 * Spec §15's exact list of what a grade book stores.
 */
export type GradeComponentType = "ASSIGNMENT" | "QUIZ" | "ATTENDANCE" | "PRACTICAL" | "FINAL_EXAM";
export const GradeComponentTypeValues = ["ASSIGNMENT", "QUIZ", "ATTENDANCE", "PRACTICAL", "FINAL_EXAM"] as const;

export interface GradeSubmissionRequest {
  grade: number | string;
  feedback?: string | null;
}

export interface GrantPermissionRequest {
  scope_type: ResourceScopeType;
  /** public_id of the course, batch, session or user this grant applies to. */
  scope_public_id: string;
  level: ResourcePermissionLevel;
}

export interface GuardianLinkResponse {
  public_id: string;
  guardian_id: string;
  guardian_username: string;
  guardian_name?: string | null;
  student_id: string;
  student_username: string;
  student_name?: string | null;
  relationship_type?: string | null;
  is_primary?: boolean;
  created_at?: string | null;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface InstitutionPanel {
  active_users?: number;
  suspended_users?: number;
  courses_published?: number;
  courses_draft?: number;
  active_batches?: number;
  enrollments_confirmed?: number;
  attendance_rate_30d?: number | null;
  submissions_awaiting_grading?: number;
}

export type Levels = "BEGINNER" | "INTERMEDIATE" | "ADVANCED";
export const LevelsValues = ["BEGINNER", "INTERMEDIATE", "ADVANCED"] as const;

/**
 * A minimal reference to a Country or City, embedded in a user's
 * profile. The full geo record (population, coordinates, ...) belongs to
 * `GET /geo/...`, not to every user response that mentions one.
 */
export interface LocationRef {
  public_id: string;
  name: string;
}

export interface LockedAccountResponse {
  public_id: string;
  username: string;
  email?: string | null;
  full_name?: string | null;
  failed_login_attempts?: number;
  /** Null means the lock has no expiry and needs an unlock. */
  locked_until?: string | null;
  /** The lock has lapsed; the next successful sign-in clears it. */
  is_expired?: boolean;
}

/**
 * Spec §3 allows signing in with either an email or a username, so this
 * is one field that accepts both rather than two mutually-exclusive ones.
 */
export interface LoginRequest {
  /** Email address or username. */
  identifier: string;
  password: string;
  /** Issues a longer-lived refresh token (spec §3 'Remember me'). */
  remember_me?: boolean;
}

export interface LogoutRequest {
  refresh_token: string;
}

export interface ManagerResponse {
  public_id: string;
  user_id: string;
  username: string;
  full_name?: string | null;
  email?: string | null;
  title?: string | null;
  is_active: boolean;
  invited_at?: string | null;
}

/**
 * Marking a register is inherently a bulk act -- a tutor records the
 * whole class at once. A one-student-at-a-time API would mean thirty
 * requests to take one register, and a half-finished register if the
 * fifteenth failed.
 */
export interface MarkAttendanceRequest {
  entries: AttendanceEntry[];
}

export interface MarkReadResponse {
  updated: number;
}

export interface MembershipResponse {
  public_id: string;
  user_id: string;
  username: string;
  full_name?: string | null;
  email?: string | null;
  employee_code?: string | null;
  department?: string | null;
  status: OrganizationMembershipStatus;
  invited_at?: string | null;
  joined_at?: string | null;
  organization_id: string;
  organization_name?: string | null;
}

export interface MembershipStatusRequest {
  status: OrganizationMembershipStatus;
}

export type MessageBox = "inbox" | "sent" | "all";
export const MessageBoxValues = ["inbox", "sent", "all"] as const;

export interface MessageResponse {
  public_id: string;
  sender: PartyRef;
  recipient: PartyRef;
  course_id?: string | null;
  batch_id?: string | null;
  subject?: string | null;
  body?: string | null;
  is_read?: boolean;
  read_at?: string | null;
  created_at?: string | null;
}

/**
 * Spec §16/§21: one delivery record per channel, not four separate
 * notification tables.
 */
export type NotificationChannel = "SYSTEM" | "EMAIL" | "SMS" | "PUSH";
export const NotificationChannelValues = ["SYSTEM", "EMAIL", "SMS", "PUSH"] as const;

export interface NotificationPreferenceResponse {
  type: string;
  category: string;
  description: string;
  enabled: boolean;
  /** Security notices cannot be switched off; the toggle is shown locked. */
  mandatory?: boolean;
}

export interface NotificationPreferencesResponse {
  /** Display order for grouping. */
  categories: string[];
  preferences: NotificationPreferenceResponse[];
  /** Stated rather than implied, so nobody expects an email. */
  channels_note?: string;
}

export interface NotificationResponse {
  public_id: string;
  channel: NotificationChannel;
  type: string;
  title: string;
  body: string;
  meta?: Record<string, unknown> | null;
  is_read?: boolean;
  sent_at?: string | null;
}

export interface OptionForAuthor {
  public_id?: string | null;
  id: number;
  option_text: string;
  order: number;
  is_correct: boolean;
}

/**
 * No `is_correct`. Not hidden, not excluded -- absent.
 */
export interface OptionForStudent {
  public_id?: string | null;
  id: number;
  option_text: string;
  order: number;
}

export interface OptionInput {
  option_text: string;
  is_correct?: boolean;
  order?: number;
}

export interface OrganizationCreateRequest {
  name: string;
  code?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
}

/**
 * An employee's relationship to their sponsoring organization. A row
 * with status REMOVED is kept, not deleted -- historical enrollments must
 * still show which organization sponsored them.
 */
export type OrganizationMembershipStatus = "INVITED" | "ACTIVE" | "SUSPENDED" | "REMOVED";
export const OrganizationMembershipStatusValues = ["INVITED", "ACTIVE", "SUSPENDED", "REMOVED"] as const;

export interface OrganizationResponse {
  public_id: string;
  name: string;
  code?: string | null;
  is_active: boolean;
  contact_email?: string | null;
  contact_phone?: string | null;
  created_at: string;
  manager_count?: number;
  /** Employees currently invited, active or suspended. */
  member_count?: number;
}

export interface OrganizationSummary {
  public_id: string;
  name: string;
  code?: string | null;
  is_active: boolean;
}

export interface OrganizationUpdateRequest {
  name?: string | null;
  code?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  is_active?: boolean | null;
}

export interface PageAcademicYearResponse {
  items: AcademicYearResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageAdminSessionResponse {
  items: AdminSessionResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageAnnouncementResponse {
  items: AnnouncementResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageAssignmentSummary {
  items: AssignmentSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageAttemptResponse {
  items: AttemptResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageAttendanceResponse {
  items: AttendanceResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageAuditLogResponse {
  items: AuditLogResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageBatchSummary {
  items: BatchSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageCategoryResponse {
  items: CategoryResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageCitySummary {
  items: CitySummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageConversationResponse {
  items: ConversationResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageCourseSummary {
  items: CourseSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageDepartmentResponse {
  items: DepartmentResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageDiscussionReplyResponse {
  items: DiscussionReplyResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageDiscussionResponse {
  items: DiscussionResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageEnrollmentResponse {
  items: EnrollmentResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageExamResultResponse {
  items: ExamResultResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageExamSummary {
  items: ExamSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageGradeBookEntryResponse {
  items: GradeBookEntryResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageGuardianLinkResponse {
  items: GuardianLinkResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageLockedAccountResponse {
  items: LockedAccountResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageMembershipResponse {
  items: MembershipResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageMessageResponse {
  items: MessageResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageNotificationResponse {
  items: NotificationResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageOrganizationSummary {
  items: OrganizationSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageQuizSummary {
  items: QuizSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageResourceSummary {
  items: ResourceSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageSemesterResponse {
  items: SemesterResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageSessionSummary {
  items: SessionSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageSettingResponse {
  items: SettingResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageSubmissionResponse {
  items: SubmissionResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageSyncRunResponse {
  items: SyncRunResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageTagResponse {
  items: TagResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageTranscriptResponse {
  items: TranscriptResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageUserSummary {
  items: UserSummary[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageWebhookDeliveryResponse {
  items: WebhookDeliveryResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

export interface PageWebhookEndpointResponse {
  items: WebhookEndpointResponse[];
  /** Total rows matching the query, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
}

/**
 * The other end of a message, named rather than referenced.
 *
 * An inbox that returns bare ids forces the client into an N+1 of user
 * lookups just to render a list of names.
 */
export interface PartyRef {
  public_id: string;
  username: string;
  full_name?: string | null;
}

export type PerformanceGroupBy = "course" | "batch" | "component" | "student";
export const PerformanceGroupByValues = ["course", "batch", "component", "student"] as const;

export type PerformanceLevel = "poor" | "below_average" | "average" | "good" | "excellent";
export const PerformanceLevelValues = ["poor", "below_average", "average", "good", "excellent"] as const;

export interface PermissionResponse {
  name: string;
  description?: string | null;
  module?: string | null;
  action?: string | null;
}

export interface PersonalPanel {
  unread_messages?: number;
  unread_notifications?: number;
  live_announcements?: number;
}

export type Platforms = "Zoom" | "Zoho" | "Google_Meet" | "Microsoft_Teams" | "Classroom";
export const PlatformsValues = ["Zoom", "Zoho", "Google_Meet", "Microsoft_Teams", "Classroom"] as const;

export interface PreferenceResetResponse {
  cleared: number;
}

export interface PublishResultsRequest {
  /** Publish or retract every recorded result for this exam. */
  is_published: boolean;
}

export interface QuestionCreateRequest {
  question_text: string;
  question_type: QuestionType;
  points: number | string;
  order?: number;
  settings?: unknown | null;
  options?: OptionInput[];
}

export interface QuestionForAuthor {
  public_id: string;
  question_text: string;
  question_type: QuestionType;
  points: string;
  order: number;
  settings?: unknown | null;
  options?: OptionForAuthor[];
}

export interface QuestionForStudent {
  public_id: string;
  question_text: string;
  question_type: QuestionType;
  points: string;
  order: number;
  settings?: unknown | null;
  options?: OptionForStudent[];
}

/**
 * Spec §13's question types. MCQ is split single/multiple because
 * single-select and multi-select need different answer-storage and
 * auto-grading logic even though the spec lists them under one bullet.
 */
export type QuestionType = "MCQ_SINGLE" | "MCQ_MULTIPLE" | "TRUE_FALSE" | "SHORT_ANSWER" | "ESSAY";
export const QuestionTypeValues = ["MCQ_SINGLE", "MCQ_MULTIPLE", "TRUE_FALSE", "SHORT_ANSWER", "ESSAY"] as const;

/**
 * Options are replaced wholesale when supplied, rather than patched
 * individually: a partial option edit has no stable identity to key on
 * once orders shift, and half-updated answer keys are worse than none.
 */
export interface QuestionUpdateRequest {
  question_text?: string | null;
  points?: number | string | null;
  order?: number | null;
  settings?: unknown | null;
  options?: OptionInput[] | null;
}

export interface QuizCreateRequest {
  title: string;
  instructions?: string | null;
  duration_minutes?: number | null;
  attempts_allowed?: number;
  passing_score: number | string;
  shuffle_questions?: boolean;
  is_auto_graded?: boolean;
  /** e.g. {'negative_marking': 0.25} to deduct a quarter of a question's points per wrong answer. */
  grading_policy?: unknown | null;
}

export interface QuizPublishRequest {
  is_published: boolean;
}

export interface QuizResponse {
  public_id: string;
  title: string;
  duration_minutes?: number | null;
  attempts_allowed: number;
  passing_score: string;
  is_published: boolean;
  instructions?: string | null;
  shuffle_questions: boolean;
  is_auto_graded: boolean;
  grading_policy?: unknown | null;
  course_id: string;
  course_title?: string | null;
  question_count?: number;
  total_points?: string;
  /** How many attempts the caller has already made. */
  my_attempts_used?: number;
}

export interface QuizSummary {
  public_id: string;
  title: string;
  duration_minutes?: number | null;
  attempts_allowed: number;
  passing_score: string;
  is_published: boolean;
}

export interface QuizUpdateRequest {
  title?: string | null;
  instructions?: string | null;
  duration_minutes?: number | null;
  attempts_allowed?: number | null;
  passing_score?: number | string | null;
  shuffle_questions?: boolean | null;
  is_auto_graded?: boolean | null;
  grading_policy?: unknown | null;
}

/**
 * Bulk, like attendance marking: an examiner enters a whole cohort's
 * marks in one pass, and a per-student endpoint would mean one request per
 * candidate with a half-entered mark sheet if any failed.
 */
export interface RecordExamResultsRequest {
  entries: ExamResultEntry[];
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface ReplyRequest {
  body: string;
}

export type ReportFormat = "json" | "csv";
export const ReportFormatValues = ["json", "csv"] as const;

export interface ReportResponse {
  report: string;
  group_by: string;
  generated_at: string;
  date_from?: string | null;
  date_to?: string | null;
  /** Metric names, in display order. */
  columns: string[];
  rows: ReportRow[];
  /** True when the result hit the group cap and is incomplete. */
  truncated?: boolean;
}

export interface ReportRow {
  /** Stable identifier for the group (a public_id, a status, or a month). */
  key: string;
  label: string;
  metrics: Record<string, number | null>;
}

export interface ResourceCopyRequest {
  target_folder_id?: string | null;
  name?: string | null;
}

export type ResourcePermissionLevel = "VIEW" | "DOWNLOAD" | "EDIT" | "MANAGE";
export const ResourcePermissionLevelValues = ["VIEW", "DOWNLOAD", "EDIT", "MANAGE"] as const;

export interface ResourcePermissionResponse {
  id: number;
  scope_type: ResourceScopeType;
  scope_id: number;
  /** Human-readable name of the course/batch/session/user. */
  scope_label?: string | null;
  level: ResourcePermissionLevel;
  resource_id?: string | null;
  folder_id?: string | null;
  granted_by_username?: string | null;
  created_at: string;
}

export interface ResourceResponse {
  public_id: string;
  name?: string | null;
  resource_type: ResourceType;
  mime_type?: string | null;
  size?: number | null;
  created_at: string;
  folder_id?: string | null;
  folder_name?: string | null;
  course_id?: string | null;
  course_title?: string | null;
  batch_id?: string | null;
  uploaded_by_username?: string | null;
  updated_at?: string | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  current_version?: number;
  versions?: ResourceVersionResponse[];
  /** True when a public share token has been issued. */
  has_share_link?: boolean;
}

/**
 * Spec §11's permission cascade: Course -> Batch -> Session -> Individual.
 */
export type ResourceScopeType = "COURSE" | "BATCH" | "SESSION" | "USER";
export const ResourceScopeTypeValues = ["COURSE", "BATCH", "SESSION", "USER"] as const;

export interface ResourceSummary {
  public_id: string;
  name?: string | null;
  resource_type: ResourceType;
  mime_type?: string | null;
  size?: number | null;
  created_at: string;
}

export type ResourceType = "Lecture Sheet" | "Lesson" | "Document" | "Video" | "Audio" | "Recordings" | "Presentation" | "Quiz" | "Assignment" | "Project" | "Certificate" | "Progress Report" | "Announcement" | "Policy Document" | "Custom Content";
export const ResourceTypeValues = ["Lecture Sheet", "Lesson", "Document", "Video", "Audio", "Recordings", "Presentation", "Quiz", "Assignment", "Project", "Certificate", "Progress Report", "Announcement", "Policy Document", "Custom Content"] as const;

/**
 * Metadata only. Replacing the *file* is a new version upload.
 */
export interface ResourceUpdateRequest {
  name?: string | null;
  resource_type?: ResourceType | null;
  folder_id?: string | null;
}

export interface ResourceVersionResponse {
  version_number: number;
  mime_type?: string | null;
  size?: number | null;
  change_note?: string | null;
  created_at: string;
  uploaded_by_username?: string | null;
}

export interface RevocationResponse {
  revoked: number;
}

export interface RoleCreateRequest {
  /** Uppercase identifier, e.g. TEACHING_ASSISTANT. */
  name: string;
  description?: string | null;
  /** Permission names to grant. Each must exist in the catalog. */
  permissions?: string[];
}

export interface RolePermissionsRequest {
  /** The complete set of permission names this role should hold. */
  permissions: string[];
}

export interface RoleResponse {
  name: string;
  description?: string | null;
  permissions?: string[];
}

export interface RoleUpdateRequest {
  description?: string | null;
}

/**
 * The platform's six roles: Super Admin, Administrator, Corporate
 * Manager, Guardian, Tutor, Student. Corporate/guardian relationships live
 * in dedicated tables (organization.py, guardian.py), never as a column on
 * User or Student -- see those modules' docstrings for why.
 */
export type Roles = "SUPER_ADMIN" | "ADMIN" | "CORPORATE_MANAGER" | "GUARDIAN" | "TUTOR" | "STUDENT";
export const RolesValues = ["SUPER_ADMIN", "ADMIN", "CORPORATE_MANAGER", "GUARDIAN", "TUTOR", "STUDENT"] as const;

export interface RotateSecretResponse {
  public_id: string;
  /** The new secret. The previous one stops working now. */
  secret: string;
}

export interface SearchGroup {
  type: SearchType;
  /** Matches this caller may see, ignoring the per-group cap. */
  total: number;
  items: SearchHit[];
  /** More matches exist than the per-group cap returns. */
  truncated?: boolean;
}

export interface SearchHit {
  type: SearchType;
  public_id: string;
  /** The primary name — a course title, a username. */
  label: string;
  /** Enough context to tell two similar hits apart. */
  subtitle?: string | null;
  created_at?: string | null;
}

export interface SearchResponse {
  query: string;
  generated_at: string;
  /** Types actually queried — the caller's permissions decide. */
  searched: SearchType[];
  /** Types omitted because the caller cannot read them at all. */
  skipped?: SearchType[];
  /** Sum across every group. */
  total: number;
  groups: SearchGroup[];
}

export type SearchType = "course" | "user" | "batch" | "resource" | "assignment" | "announcement" | "discussion";
export const SearchTypeValues = ["course", "user", "batch", "resource", "assignment", "announcement", "discussion"] as const;

export interface SecuritySummaryResponse {
  window_hours: number;
  failed_logins: number;
  accounts_locked_now: number;
  lockout_events: number;
  token_reuse_detections: number;
  permission_changes: number;
  active_sessions: number;
  generated_at: string;
}

export interface SemesterCreateRequest {
  academic_year_id: string;
  /** e.g. 'Fall', 'Spring'. Unique within its academic year. */
  name: string;
  start_date: string;
  end_date: string;
}

export interface SemesterResponse {
  public_id: string;
  academic_year_id: string;
  academic_year_label?: string | null;
  name: string;
  start_date: string;
  end_date: string;
  batch_count?: number;
}

export interface SemesterUpdateRequest {
  name?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface SendMessageRequest {
  recipient_id: string;
  subject?: string | null;
  body: string;
  /** Optional context: which course this is about. */
  course_id?: string | null;
  /** Optional context: which batch this is about. */
  batch_id?: string | null;
}

export interface SessionBrief {
  public_id: string;
  batch_code: string;
  course_title: string;
  starts_at?: string | null;
  ends_at?: string | null;
  classroom?: string | null;
  meeting_link?: string | null;
}

export interface SessionCreateRequest {
  /** The tutor taking this session. Assigning one grants them access to the batch's students, so it must be a user holding the TUTOR role. */
  tutor_id: string;
  session_start_time: string;
  session_end_time?: string | null;
  duration_minutes?: number | null;
  platform?: Platforms;
  classroom?: string | null;
  meeting_link?: string | null;
  tutor_notes?: string | null;
}

export interface SessionSessionResponse {
  public_id: string;
  session_start_time?: string | null;
  session_end_time?: string | null;
  duration_minutes?: number | null;
  platform: Platforms;
  classroom?: string | null;
  batch_id: string;
  batch_code?: string | null;
  course_title?: string | null;
  tutor_id: string;
  tutor_username?: string | null;
  meeting_link?: string | null;
  recording_link?: string | null;
  tutor_notes?: string | null;
  student_notes?: string | null;
  /** True once a register has been marked for this session. */
  attendance_recorded?: boolean;
}

export interface SessionSummary {
  public_id: string;
  session_start_time?: string | null;
  session_end_time?: string | null;
  duration_minutes?: number | null;
  platform: Platforms;
  classroom?: string | null;
}

export interface SessionUpdateRequest {
  tutor_id?: string | null;
  session_start_time?: string | null;
  session_end_time?: string | null;
  duration_minutes?: number | null;
  platform?: Platforms | null;
  classroom?: string | null;
  meeting_link?: string | null;
  recording_link?: string | null;
  tutor_notes?: string | null;
  student_notes?: string | null;
}

export interface SetCourseTagsRequest {
  /** The complete set. Tags omitted here are removed. */
  tag_ids?: string[];
}

export interface SetNotificationPreferenceRequest {
  enabled: boolean;
}

export interface SettingResponse {
  key: string;
  value?: string | null;
  description?: string | null;
}

export interface SettingWriteRequest {
  value?: string | null;
  description?: string | null;
}

export interface ShareLinkResponse {
  share_token?: string | null;
  /** Relative path a recipient can open without signing in. */
  url_path?: string | null;
}

export interface ShareResourceRequest {
  /** Users to share this resource with. */
  user_ids: string[];
}

export interface SharedResourceResponse {
  resource_id: string;
  resource_name?: string | null;
  shared_with_username?: string | null;
  shared_by_username?: string | null;
  created_at: string;
}

export interface StudentPanel {
  enrolled_batches?: number;
  active_courses?: number;
  /** Percentage; null when there is nothing assessable yet. */
  attendance_rate?: number | null;
  /** Mean percentage across recorded grade components. */
  average_score?: number | null;
  assignments_outstanding?: number;
  assignments_overdue?: number;
  upcoming_sessions?: SessionBrief[];
  next_deadlines?: AssignmentBrief[];
}

export interface SubmissionResponse {
  public_id: string;
  assignment_id: string;
  assignment_title?: string | null;
  student_id: string;
  student_username?: string | null;
  submitted_at: string;
  files?: unknown | null;
  content?: string | null;
  grade?: string | null;
  feedback?: string | null;
  graded_at?: string | null;
  graded_by_username?: string | null;
  /** Submitted after the assignment's due date. */
  is_late?: boolean;
}

export type SubmissionType = "FILE_UPLOAD" | "TEXT" | "LINK";
export const SubmissionTypeValues = ["FILE_UPLOAD", "TEXT", "LINK"] as const;

/**
 * Spec §12 lets a student "replace before deadline", so re-submitting
 * updates the existing row rather than creating a second one (enforced by
 * `uq_assignment_submissions_assignment_student`).
 */
export interface SubmitAssignmentRequest {
  content?: string | null;
  /** File metadata, e.g. [{'filename': 'project.zip', 'path': '...'}]. */
  files?: unknown | null;
}

export interface SubmitAttemptRequest {
  answers?: AnswerInput[];
}

export interface SyncResultResponse {
  created?: number;
  updated?: number;
  unchanged?: number;
  students_covered?: number;
  /** Source rows deliberately not synced because they are not marked yet. */
  skipped_ungraded?: number;
}

export interface SyncRunResponse {
  public_id: string;
  trigger_type: string;
  dry_run: boolean;
  status: string;
  started_at: string;
  finished_at?: string | null;
  stats?: Record<string, unknown> | null;
  errors?: (Record<string, unknown>)[] | null;
  failure_reason?: string | null;
}

export interface TagResponse {
  public_id: string;
  name: string;
  course_count?: number;
}

export interface TagWriteRequest {
  name: string;
}

export interface TeachingPanel {
  batches_taught?: number;
  courses_taught?: number;
  students_taught?: number;
  sessions_next_7_days?: number;
  submissions_awaiting_grading?: number;
  quiz_attempts_awaiting_grading?: number;
  upcoming_sessions?: SessionBrief[];
}

export interface TestDeliveryResponse {
  delivered: boolean;
  response_status?: number | null;
  error?: string | null;
  delivery_id: string;
}

export interface TimeZoneResponse {
  code: string;
  description?: string | null;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  /** Access token lifetime in seconds. */
  expires_in: number;
}

export interface TranscriptResponse {
  public_id: string;
  student_id: string;
  student_username?: string | null;
  batch_id: string;
  batch_code?: string | null;
  course_id: string;
  course_title?: string | null;
  gpa?: string | null;
  overall_grade?: string | null;
  generated_at: string;
  is_final: boolean;
}

/**
 * Spec §7 'Transfer batches'.
 *
 * Records history rather than overwriting: the existing enrollment is
 * closed and a new row is created pointing back at it, so "which batch was
 * this student in during March" stays answerable.
 */
export interface TransferRequest {
  target_batch_id: string;
}

export interface UnlockResponse {
  public_id: string;
  username: string;
  /** False when the account was already usable; the call is still a success. */
  was_locked: boolean;
}

export interface UnreadCountResponse {
  unread: number;
}

export interface UpdateAnnouncementRequest {
  title?: string | null;
  content?: string | null;
  role_scope?: Roles | null;
  start_at?: string | null;
  end_at?: string | null;
  pinned?: boolean | null;
}

export interface UpdateDiscussionRequest {
  title?: string | null;
  body?: string | null;
  is_pinned?: boolean | null;
  is_locked?: boolean | null;
}

export interface UpdateGuardianLinkRequest {
  relationship_type?: string | null;
  is_primary?: boolean | null;
}

export interface UpdateWebhookRequest {
  name?: string | null;
  target_url?: string | null;
  events?: string[] | null;
  description?: string | null;
  is_active?: boolean | null;
}

export interface UserCreateRequest {
  username: string;
  email: string;
  password: string;
  first_name?: string | null;
  last_name?: string | null;
  title?: string | null;
  gender?: Genders;
  date_of_birth?: string | null;
  phone_number?: string | null;
  mobile?: string | null;
  /** An administrator who types in a password is vouching for the account, so a manually created user can sign in. Synced accounts are the opposite: they start disabled. */
  can_login?: boolean;
  /** Role names to grant. Must already exist in the role catalog. */
  roles?: string[];
}

export interface UserLoginAccessRequest {
  can_login: boolean;
}

export interface UserLoginAccessResponse {
  can_login: boolean;
  /** True while the account still has the shared default password -- enabling login then hands the account to anyone who knows it. */
  default_password_in_use: boolean;
}

/**
 * The full profile, returned for a single-user read.
 */
export interface UserResponse {
  public_id: string;
  username: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  full_name: string;
  status: UserStatus;
  profile_picture?: string | null;
  can_login?: boolean;
  is_synced?: boolean;
  external_student_id?: number | null;
  external_tutor_id?: number | null;
  title?: string | null;
  gender: Genders;
  date_of_birth?: string | null;
  phone_number?: string | null;
  mobile?: string | null;
  designation?: string | null;
  web?: string | null;
  company?: string | null;
  address?: string | null;
  postcode?: string | null;
  timezone?: string | null;
  country?: LocationRef | null;
  city?: LocationRef | null;
  bio?: string | null;
  is_public: boolean;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
  emergency_contact_relationship?: string | null;
  is_locked: boolean;
  last_login?: string | null;
  created_at: string;
  /** Role names held by this user. */
  roles?: string[];
}

export interface UserRolesRequest {
  /** The complete set of role names this user should hold. */
  roles: string[];
}

/**
 * Spec §4's exact four account states. ``DELETED`` *is* the deletion
 * signal for a user row — there is deliberately no separate ``is_deleted``
 * boolean on ``User`` (see ``models/identity/user.py``); two independent
 * flags claiming to answer "is this account gone?" is how they drift.
 */
export type UserStatus = "ACTIVE" | "INACTIVE" | "SUSPENDED" | "DELETED";
export const UserStatusValues = ["ACTIVE", "INACTIVE", "SUSPENDED", "DELETED"] as const;

export interface UserStatusRequest {
  status: UserStatus;
}

/**
 * The shape used in lists and when a user is referenced from another
 * resource. Deliberately narrow: a roster of 10,000 students should not
 * ship everyone's address and emergency contact to render a table.
 */
export interface UserSummary {
  public_id: string;
  username: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  full_name: string;
  status: UserStatus;
  profile_picture?: string | null;
  can_login?: boolean;
  is_synced?: boolean;
}

/**
 * Every field optional: this is a PATCH. A field omitted is left alone;
 * a field sent as `null` is explicitly cleared.
 */
export interface UserUpdateRequest {
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  title?: string | null;
  gender?: Genders | null;
  date_of_birth?: string | null;
  phone_number?: string | null;
  mobile?: string | null;
  designation?: string | null;
  web?: string | null;
  company?: string | null;
  address?: string | null;
  postcode?: string | null;
  timezone?: string | null;
  /** A country's public_id, from GET /geo/countries. */
  country_id?: string | null;
  /** A city's public_id, from GET /geo/countries/{id}/cities. If set, must belong to country_id when both are given in the same request -- otherwise the city's own country is used. */
  city_id?: string | null;
  bio?: string | null;
  is_public?: boolean | null;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
  emergency_contact_relationship?: string | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

/**
 * The only response that carries the secret, and only at creation.
 *
 * Separated into its own model so the secret cannot be returned by any
 * other route by accident — a shared model with an optional field would
 * make that a one-line mistake.
 */
export interface WebhookCreatedResponse {
  public_id: string;
  name: string;
  target_url: string;
  events: string[];
  is_active?: boolean;
  description?: string | null;
  failure_count?: number;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_failure_reason?: string | null;
  created_at?: string | null;
  /** Shown once. Store it now; it is never returned again. */
  secret: string;
  signature_docs?: string;
}

export interface WebhookDeliveryResponse {
  public_id: string;
  event: string;
  status: string;
  attempts?: number;
  response_status?: number | null;
  error?: string | null;
  created_at?: string | null;
  delivered_at?: string | null;
  next_attempt_at?: string | null;
  payload?: Record<string, unknown> | null;
}

export interface WebhookEndpointResponse {
  public_id: string;
  name: string;
  target_url: string;
  events: string[];
  is_active?: boolean;
  description?: string | null;
  failure_count?: number;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_failure_reason?: string | null;
  created_at?: string | null;
}

export interface WebhookEventCatalogResponse {
  events: string[];
  note?: string;
}

