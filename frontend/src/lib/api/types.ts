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

/**
 * Which population an assessment is set for.
 *
 * One enum shared by assignments, quizzes and examinations rather than three
 * parallel implementations -- §3 says so explicitly, and the alternative is
 * the same eligibility rule written out three times and drifting.
 *
 * The scope is stored alongside the ids it refers to, rather than inferred
 * from which id happens to be non-null. "Set for the whole course" and "set
 * for a batch we have not chosen yet" are different states, and an inference
 * rule cannot tell them apart.
 */
export type AssessmentScope = "COURSE" | "BATCH" | "SESSION";
export const AssessmentScopeValues = ["COURSE", "BATCH", "SESSION"] as const;

/**
 * Whether an assessment is visible to the students it is set for.
 *
 * Distinct from `ResultState` below: this is the *question* becoming visible,
 * that is the *mark* becoming visible, and an institution needs both.
 */
export type AssessmentState = "DRAFT" | "SCHEDULED" | "PUBLISHED" | "CLOSED" | "ARCHIVED";
export const AssessmentStateValues = ["DRAFT", "SCHEDULED", "PUBLISHED", "CLOSED", "ARCHIVED"] as const;

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
  scope?: AssessmentScope;
  /** Required when scope is BATCH. */
  batch_id?: string | null;
  /** Required when scope is SESSION. */
  session_id?: string | null;
  /** DRAFT saves without notifying anybody; PUBLISHED sets it immediately. */
  state?: AssessmentState;
  publish_at?: string | null;
  available_from?: string | null;
  passing_score?: number | string | null;
  weight?: number | string;
  allowed_file_types?: string | null;
  max_upload_mb?: number | null;
  allow_multiple_submissions?: boolean;
  allow_resubmission?: boolean;
  late_penalty_percent_per_day?: number | string | null;
}

/**
 * Release marks. Omitting `student_ids` releases every graded submission.
 */
export interface AssignmentPublishResultsRequest {
  student_ids?: string[] | null;
}

export interface AssignmentResponse {
  public_id: string;
  title: string;
  due_date: string;
  max_score: string;
  submission_type: SubmissionType;
  allow_late_submissions: boolean;
  scope?: AssessmentScope;
  state?: AssessmentState;
  description?: string | null;
  instructions_path?: string | null;
  rubric?: unknown | null;
  course_id: string;
  course_title?: string | null;
  submission_count?: number;
  /** Set when the caller has already submitted, so a client need not fetch the list to know. */
  my_submission_id?: string | null;
  batch_id?: string | null;
  batch_code?: string | null;
  session_id?: string | null;
  /** One line a tutor can read: "Batch LMS-A". */
  scope_description?: string | null;
  /** How many students this was set for. */
  eligible_count?: number | null;
  publish_at?: string | null;
  available_from?: string | null;
  passing_score?: string | null;
  weight?: string;
  allowed_file_types?: string | null;
  max_upload_mb?: number | null;
  allow_multiple_submissions?: boolean;
  allow_resubmission?: boolean;
  late_penalty_percent_per_day?: string | null;
}

export interface AssignmentSummary {
  public_id: string;
  title: string;
  due_date: string;
  max_score: string;
  submission_type: SubmissionType;
  allow_late_submissions: boolean;
  scope?: AssessmentScope;
  state?: AssessmentState;
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
  state?: AssessmentState | null;
  publish_at?: string | null;
  available_from?: string | null;
  passing_score?: number | string | null;
  weight?: number | string | null;
  allowed_file_types?: string | null;
  max_upload_mb?: number | null;
  allow_multiple_submissions?: boolean | null;
  allow_resubmission?: boolean | null;
  late_penalty_percent_per_day?: number | string | null;
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

export interface BandPayload {
  min_score: number | string;
  max_score: number | string;
  letter_grade: string;
  gpa_points: number | string;
  is_pass?: boolean;
}

export interface BandResponse {
  min_score: string;
  max_score: string;
  letter_grade: string;
  gpa_points: string;
  is_pass?: boolean;
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
  /** Recounted from enrollments by the LAIT sync. */
  total_enrollments?: number;
  course_title?: string | null;
  training_days?: string | null;
  training_method?: string | null;
  batch_fee?: number | null;
  class_duration_minutes?: number | null;
  /** The tutor teaching most of the batch's sessions. */
  tutor_name?: string | null;
  session_count?: number;
  next_session_start?: string | null;
  /** public_id of the owning course. */
  course_id: string;
  training_start_day?: string | null;
  training_end_day?: string | null;
  /** HH:MM, in `schedule_timezone`. */
  training_start_time?: string | null;
  training_end_time?: string | null;
  schedule_timezone?: string | null;
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
  /** Recounted from enrollments by the LAIT sync. */
  total_enrollments?: number;
  course_title?: string | null;
  training_days?: string | null;
  training_method?: string | null;
  batch_fee?: number | null;
  class_duration_minutes?: number | null;
  /** The tutor teaching most of the batch's sessions. */
  tutor_name?: string | null;
  session_count?: number;
  next_session_start?: string | null;
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

export interface BodyPutImageApiV1Coursesput {
  file: string;
}

export interface BodySetMyPictureApiV1AuthMePicturePut {
  file: string;
}

export interface BodySetPictureApiV1UserspicturePut {
  file: string;
}

export interface BodyUploadAttachmentApiV1MessagesAttachmentsPost {
  file: string;
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

export interface CalendarResponse {
  items: CalendarSession[];
  /** True when the window held more sessions than the cap; narrow it. */
  truncated: boolean;
}

/**
 * One block on the calendar: enough to draw and filter it without a request per session.
 */
export interface CalendarSession {
  public_id: string;
  batch_id: string;
  batch_code: string;
  course_title?: string | null;
  tutor_id: string;
  tutor_name?: string | null;
  session_start_time: string;
  /** Start plus duration (an hour if neither is stored) when no end was saved. */
  session_end_time: string;
  platform: Platforms;
  classroom?: string | null;
  /** Only populated for callers who may edit the session (tutors and administrators). Everyone else joins through POST /sessions/{id}/join, which is what makes the join window enforceable rather than cosmetic. */
  meeting_link?: string | null;
  can_join_now?: boolean;
  origin?: string | null;
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

/**
 * One student's row on the grid.
 */
export interface ClassPerformanceEntry {
  student_id: string;
  participation?: number | string | null;
  interaction?: number | string | null;
  preparation?: number | string | null;
  practical?: number | string | null;
  presentation?: number | string | null;
  teamwork?: number | string | null;
  communication?: number | string | null;
  professionalism?: number | string | null;
  /** The tutor's own figure for the class. Null means 'average the criteria above', which is what most tutors want. */
  overall_score?: number | string | null;
  comment?: string | null;
  /** Institution-specific criteria, as {name: score}. */
  custom_scores?: Record<string, number | string> | null;
}

export interface ClassPerformanceMarkResponse {
  participation?: string | null;
  interaction?: string | null;
  preparation?: string | null;
  practical?: string | null;
  presentation?: string | null;
  teamwork?: string | null;
  communication?: string | null;
  professionalism?: string | null;
  public_id: string;
  student: MarkPerson;
  max_score: string;
  /** The tutor's own figure, if they gave one. */
  overall_score?: string | null;
  /** The score the calculation engine will actually use: the tutor's own figure, or the mean of the criteria they filled in. Null when nothing has been assessed -- which is excluded from the weighted result, never counted as zero. */
  average?: string | null;
  comment?: string | null;
  custom_scores?: Record<string, unknown> | null;
  state: ResultState;
  recorded_by?: MarkPerson | null;
  recorded_at?: string | null;
  updated_at?: string | null;
}

export interface ClassPerformanceSheetResponse {
  session: ClassPerformanceSheetSession;
  rows: ClassPerformanceSheetRow[];
  /** Whether this caller may record marks here. False for a reader, and false for a tutor who is not the session's assigned tutor -- the backend refuses the write either way; this only stops the console offering a form that cannot be saved. */
  can_edit: boolean;
  /** True when the caller may record but is not the assigned tutor -- the academic office correcting a record. Recorded in the audit trail and worth saying out loud on the screen. */
  would_be_on_behalf?: boolean;
  /** The common state of the marks recorded so far, or null when they disagree (or none exist). A sheet part-released is a real state and is reported honestly rather than rounded to one value. */
  state?: ResultState | null;
  marked?: number;
  total?: number;
}

export interface ClassPerformanceSheetRow {
  student: MarkPerson;
  /** Null until somebody has assessed this student. */
  mark?: ClassPerformanceMarkResponse | null;
}

export interface ClassPerformanceSheetSession {
  public_id: string;
  session_start_time?: string | null;
  session_end_time?: string | null;
  classroom?: string | null;
  batch_code?: string | null;
  course_title?: string | null;
  assigned_tutor?: MarkPerson | null;
}

export interface CodeSuggestion {
  code: string;
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
 * One line of the drill-down: `82 x 15% = 12.30`.
 */
export interface ComponentLine {
  component_type: GradeComponentType;
  label: string;
  weight_percentage: string;
  /** The student's mark in this component, out of 100. */
  percentage?: string | null;
  /** percentage x weight / 100. Null when the component does not count. */
  contribution?: string | null;
  marks_total: number;
  marks_scored: number;
  counted: boolean;
  /** Why it was left out, in words a tutor can act on. */
  excluded_reason?: string;
  is_mandatory?: boolean;
  meets_component_pass?: boolean | null;
}

export interface ComponentWeightPayload {
  component_type: GradeComponentType;
  label?: string | null;
  weight_percentage: number | string;
  /** A component that must be passed in its own right, whatever the total. */
  is_mandatory?: boolean;
  passing_percentage?: number | string | null;
}

export interface ComponentWeightResponse {
  public_id: string;
  component_type: GradeComponentType;
  label?: string | null;
  weight_percentage: string;
  is_mandatory?: boolean;
  passing_percentage?: string | null;
}

export interface ComposeRequest {
  to?: string[];
  cc?: string[];
  bcc?: string[];
  subject?: string;
  body_html?: string;
  attachment_ids?: string[];
  /** The message being replied to; puts this one in its thread. */
  reply_to_id?: string | null;
  /** Send (or update) this saved draft rather than starting a new message. */
  draft_id?: string | null;
  /** Also email a copy to my own address. */
  email_copy?: boolean;
}

export interface CountryResponse {
  public_id: string;
  name: string;
  code: string;
}

export interface CourseBatchBrief {
  public_id: string;
  batch_code: string;
  is_active: boolean;
  start_date?: string | null;
  end_date?: string | null;
  capacity?: number | null;
  total_enrollments?: number;
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
  course_image?: string | null;
  small_course_image?: string | null;
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
  /** Full-size image: an external URL, or an API path for an uploaded one. */
  course_image?: string | null;
  /** Thumbnail: an external URL, or an API path for an uploaded one. */
  small_course_image?: string | null;
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
  batches?: CourseBatchBrief[];
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
  /** Full-size image: an external URL, or an API path for an uploaded one. */
  course_image?: string | null;
  /** Thumbnail: an external URL, or an API path for an uploaded one. */
  small_course_image?: string | null;
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
  course_image?: string | null;
  small_course_image?: string | null;
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
  /** API path of the picture (fetch with the same credentials); null when none is set. */
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
  detected_timezone?: string | null;
  locale_city?: string | null;
  locale_country?: string | null;
  timezone_is_auto?: boolean;
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

export interface DirectoryResponse {
  items: MailPerson[];
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
  session_id?: string | null;
  scope?: AssessmentScope;
  is_online?: boolean;
  weight?: number | string;
}

export interface ExamInvigilatorsRequest {
  /** The complete set of tutor public_ids invigilating this exam. */
  invigilators: string[];
}

export interface ExamPublishRequest {
  is_published: boolean;
}

export interface ExamPublishResultsRequest {
  /** Publish or retract every recorded result for this exam. */
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

export interface ExistingSessions {
  total: number;
  /** Sessions that hold attendance, a recording or notes, and are never deleted by a re-create. */
  protected: number;
  replaceable: number;
  protected_reasons?: string[];
  first_start?: string | null;
  last_start?: string | null;
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
  /** Students with nothing to certify -- no grading scheme configured for the course, or no published marks in any weighted component. */
  skipped_no_grades?: number;
}

export interface GoogleBatchResponse {
  batch_id: string;
  has_calendar: boolean;
  calendar_url?: string | null;
  last_synced_at?: string | null;
  sessions: number;
  sessions_in_google: number;
}

export interface GoogleCallbackRequest {
  code: string;
  state: string;
}

export interface GoogleChangeRequestResponse {
  public_id: string;
  /** ENROL_ADD or ENROL_REMOVE */
  kind: string;
  /** PENDING, APPROVED, REJECTED or SUPERSEDED */
  status: string;
  email?: string | null;
  student_name?: string | null;
  batch_id: string;
  batch_code: string;
  note?: string | null;
  detected_at: string;
  decided_at?: string | null;
  decided_by?: string | null;
  /** Why an approval was refused, when it was. */
  last_error?: string | null;
}

export interface GoogleConnectResponse {
  /** Send the browser here to sign in with Google. */
  url: string;
}

export interface GoogleStatusResponse {
  /** GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are set. */
  configured: boolean;
  /** Why sign-in cannot work yet, if it cannot. */
  problem?: string | null;
  connected: boolean;
  account_email?: string | null;
  connected_at?: string | null;
  /** The account a Super Admin must sign in as. */
  expected_email?: string | null;
  /** Must be an Authorized redirect URI on the OAuth client in Google Cloud. */
  redirect_uri: string;
  invite_attendees: boolean;
  send_updates: string;
  share_with_admins: boolean;
  pull_session_times: boolean;
  /** Batches that currently have a Google calendar. */
  calendars: number;
  /** Enrolment changes made in Google that are waiting for a decision. */
  pending_changes?: number;
  admins_can_edit?: boolean;
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

/**
 * How a computed percentage is expressed (spec §13).
 */
export type GradeScaleType = "PERCENTAGE" | "LETTER" | "GPA" | "PASS_FAIL" | "NUMERIC" | "COMPETENCY";
export const GradeScaleTypeValues = ["PERCENTAGE", "LETTER", "GPA", "PASS_FAIL", "NUMERIC", "COMPETENCY"] as const;

export interface GradeSubmissionRequest {
  grade: number | string;
  feedback?: string | null;
  override_reason?: string | null;
  /** Defaults to GRADED. Marking and releasing are separate acts. */
  state?: SubmissionState | null;
}

export interface GradingSchemeCreateRequest {
  name: string;
  description?: string | null;
  scale_type?: GradeScaleType;
  /** EXCLUDE leaves unassessed work out of the total, which is the honest default. ZERO marks it as nothing -- a real policy some institutions hold, but never one to inherit by accident. */
  missing_mark_policy?: MissingMarkPolicy;
  passing_percentage?: number | string;
}

export interface GradingSchemeResponse {
  public_id: string;
  name: string;
  description?: string | null;
  is_default: boolean;
  is_active: boolean;
  scale_type: GradeScaleType;
  missing_mark_policy: MissingMarkPolicy;
  passing_percentage: string;
  /** The component weights added up. Shown because a scheme that does not total 100 cannot be activated, and an operator editing one needs to see how far off they are without doing the sum. */
  total_weight: string;
  component_count?: number;
  components?: ComponentWeightResponse[];
  bands?: BandResponse[];
  /** How many courses this scheme grades. Shown before a change, because editing a weight re-grades every student in every one of them at once. */
  courses_using?: number;
}

export interface GradingSchemeSummary {
  public_id: string;
  name: string;
  description?: string | null;
  is_default: boolean;
  is_active: boolean;
  scale_type: GradeScaleType;
  missing_mark_policy: MissingMarkPolicy;
  passing_percentage: string;
  /** The component weights added up. Shown because a scheme that does not total 100 cannot be activated, and an operator editing one needs to see how far off they are without doing the sum. */
  total_weight: string;
  component_count?: number;
}

export interface GradingSchemeUpdateRequest {
  name?: string | null;
  description?: string | null;
  scale_type?: GradeScaleType | null;
  missing_mark_policy?: MissingMarkPolicy | null;
  passing_percentage?: number | string | null;
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

export interface LinkPreviewRequest {
  url: string;
}

/**
 * What the course page says, offered as suggestions -- nothing is saved.
 */
export interface LinkPreviewResponse {
  price?: number | null;
  duration_hours?: number | null;
  level?: Levels | null;
  prerequisites?: string | null;
}

export interface LocaleRefreshResponse {
  ip_changed: boolean;
  timezone_changed: boolean;
  timezone?: string | null;
  detected_timezone?: string | null;
  city?: string | null;
  country?: string | null;
}

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

export interface MailAttachmentInfo {
  public_id: string;
  filename: string;
  content_type: string;
  size: number;
}

/**
 * How the email copies went. Only the sender sees this.
 */
export interface MailDelivery {
  /** False when email delivery is switched off for this deployment. */
  enabled: boolean;
  sent?: number;
  failed?: number;
  skipped?: number;
  pending?: number;
  /** SENT, FAILED or SKIPPED; null when no copy was asked for. */
  copy_to_me?: string | null;
  /** Recipient names whose email failed. */
  failures?: string[];
}

export type MailFolder = "inbox" | "sent" | "starred" | "drafts";
export const MailFolderValues = ["inbox", "sent", "starred", "drafts"] as const;

export interface MailListItem {
  public_id: string;
  thread_id: string;
  subject: string;
  snippet: string;
  sender: MailPerson;
  recipients_summary: string;
  sent_at?: string | null;
  updated_at?: string | null;
  is_read: boolean;
  is_starred: boolean;
  is_draft: boolean;
  has_attachments: boolean;
  thread_count?: number;
  is_mine?: boolean;
}

export interface MailMessageView {
  public_id: string;
  thread_id: string;
  parent_id?: string | null;
  subject: string;
  body_html: string;
  sender: MailPerson;
  to: MailPerson[];
  cc: MailPerson[];
  /** Only ever filled in for the sender. */
  bcc?: MailPerson[];
  you_were_bcc?: boolean;
  sent_at?: string | null;
  is_draft?: boolean;
  is_read?: boolean;
  is_starred?: boolean;
  is_mine?: boolean;
  attachments?: MailAttachmentInfo[];
  delivery?: MailDelivery | null;
}

export interface MailPerson {
  public_id: string;
  name: string;
  role?: string | null;
}

export interface MailThread {
  thread_id: string;
  subject: string;
  messages: MailMessageView[];
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

export interface MarkPerson {
  public_id: string;
  name: string;
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

/**
 * What the engine does with a component that has no mark (spec §38).
 *
 * Configurable because institutions genuinely differ, and because the wrong
 * default produces a confidently wrong number. `EXCLUDE` is the safe one: it
 * reports "82% of the 35 marks assessed so far" rather than "29%".
 */
export type MissingMarkPolicy = "EXCLUDE" | "ZERO" | "CARRY_FORWARD";
export const MissingMarkPolicyValues = ["EXCLUDE", "ZERO", "CARRY_FORWARD"] as const;

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
  /** Stated rather than implied, so nobody expects an email. Rewritten when Web Push gained a real transport: the previous wording said push was modelled and undeliverable, which had stopped being true and is the worst kind of note -- one that stops the reader checking. */
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

export interface OverviewBatch {
  public_id: string;
  batch_code: string;
  capacity?: number | null;
  enrolled?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  is_active: boolean;
}

export interface OverviewCourse {
  public_id: string;
  title: string;
  code?: string | null;
  level?: string | null;
}

export interface OverviewPerson {
  public_id: string;
  name: string;
  /** Only for administrators and the batch's tutors. */
  email?: string | null;
  phone?: string | null;
  /** A guardian's relationship, or a manager's job title. */
  detail?: string | null;
}

export interface OverviewRosterEntry {
  student: OverviewPerson;
  enrollment_status: string;
  attendance?: string | null;
  organization?: string | null;
  guardians?: OverviewPerson[];
  managers?: OverviewPerson[];
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

export interface PageGoogleChangeRequestResponse {
  items: GoogleChangeRequestResponse[];
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

export interface PageMailListItem {
  items: MailListItem[];
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

export interface PageQueueItem {
  items: QueueItem[];
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

/**
 * A student's standing, with every figure it was built from.
 */
export interface PerformanceResponse {
  student_id: string;
  student_name?: string | null;
  batch_id: string;
  batch_code?: string | null;
  scheme_name?: string | null;
  components: ComponentLine[];
  /** The share of the scheme's 100 that has been assessed (spec 38). */
  assessed_weight: string;
  total_weight: string;
  /** The mark out of what has been assessed. The figure to show mid-course. */
  current_percentage?: string | null;
  /** The mark out of the whole scheme. Null until every weighted component has been assessed -- spec 38's 'Not Yet Available'. A client must not substitute current_percentage here; they mean different things. */
  final_percentage?: string | null;
  grade?: string | null;
  gpa?: string | null;
  is_pass?: boolean | null;
  /** True when no grading scheme is configured. Every figure above is null. */
  unconfigured?: boolean;
  failed_mandatory?: GradeComponentType[];
  sessions_total?: number;
  sessions_attended?: number;
  attendance_percentage?: string | null;
}

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

export interface PlanPerson {
  public_id: string;
  name: string;
}

/**
 * Everything is optional except the zone: what is left out comes from the batch (or its existing sessions).
 */
export interface PlanRequest {
  /** The zone the dates, weekdays and clock times are read in. */
  timezone?: string;
  start_date?: string | null;
  end_date?: string | null;
  /** 0 = Monday ... 6 = Sunday. */
  weekdays?: number[] | null;
  start_time?: string | null;
  duration_minutes?: number | null;
  sessions?: number | null;
}

export interface PlanResponse {
  settings: PlanSettingsOut;
  sessions: PlannedSessionOut[];
  warnings: string[];
  existing: ExistingSessions;
  default_tutor?: PlanPerson | null;
  default_platform?: Platforms | null;
  batch_code: string;
  course_title?: string | null;
}

export interface PlanSettingsOut {
  timezone: string;
  weekdays: number[];
  training_days: string;
  start_time?: string | null;
  duration_minutes?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  sessions?: number | null;
  /** Where the defaults came from: the batch's schedule, its existing sessions, or nothing. */
  source: string;
  /** Explains a carry across time zones, when there was one. */
  note?: string | null;
}

export interface PlannedSessionOut {
  index: number;
  start_utc: string;
  end_utc: string;
  /** Wall-clock start in the plan's zone, `YYYY-MM-DDTHH:mm`. */
  start_local: string;
  duration_minutes: number;
  weekday: string;
}

export type Platforms = "Zoom" | "Zoho" | "Google_Meet" | "Microsoft_Teams" | "Classroom";
export const PlatformsValues = ["Zoom", "Zoho", "Google_Meet", "Microsoft_Teams", "Classroom"] as const;

export interface PreferenceResetResponse {
  cleared: number;
}

export interface PushDeviceResponse {
  public_id: string;
  user_agent?: string | null;
  created_at: string;
  last_used_at?: string | null;
}

/**
 * What a browser needs before it can subscribe at all.
 */
export interface PushKeyResponse {
  /** False when this deployment has no VAPID keys configured. */
  enabled: boolean;
  /** The VAPID application server key, passed to pushManager.subscribe. Public by design -- it identifies this deployment to a push service and authorises nothing. */
  public_key?: string | null;
}

/**
 * Exactly what `PushSubscription.toJSON()` produces in the browser.
 */
export interface PushSubscribeRequest {
  endpoint: string;
  p256dh: string;
  auth: string;
}

export interface PushUnsubscribeRequest {
  endpoint: string;
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

export interface QueueItem {
  session_id: string;
  start_time?: string | null;
  end_time?: string | null;
  batch_id: string;
  batch_code: string;
  course_title?: string | null;
  tutor: SheetPerson;
  enrolled: number;
  state: SheetState;
  marked?: number;
  submitted_on_behalf?: boolean;
  finalized_at?: string | null;
  can_edit?: boolean;
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
  scope?: AssessmentScope;
  batch_id?: string | null;
  session_id?: string | null;
  available_from?: string | null;
  available_until?: string | null;
  shuffle_answers?: boolean;
  /** Draw this many at random from the bank. Null means every question. */
  questions_per_attempt?: number | null;
  show_result_immediately?: boolean;
  show_correct_answers?: boolean;
  show_explanations?: boolean;
  auto_submit_on_expiry?: boolean;
  weight?: number | string;
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
  scope?: AssessmentScope;
  available_from?: string | null;
  available_until?: string | null;
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
  scope?: AssessmentScope;
  available_from?: string | null;
  available_until?: string | null;
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

export interface ReplaceRequest {
  sessions: ReplaceRow[];
  /** Required when the batch already has sessions that would be replaced. */
  confirm_replace?: boolean;
  schedule?: ScheduleToSave | null;
}

export interface ReplaceResponse {
  created: number;
  /** Existing sessions removed to make way for the new ones. */
  replaced: number;
  /** Existing sessions kept because they hold attendance, a recording or notes. */
  kept_protected: number;
  /** Proposed sessions not created because a protected session already starts then. */
  skipped: number;
  total_sessions: number;
}

export interface ReplaceRow {
  start_utc: string;
  end_utc?: string | null;
  duration_minutes?: number | null;
  tutor_id: string;
  platform?: Platforms;
  classroom?: string | null;
  meeting_link?: string | null;
}

/**
 * Who a reply would go to -- already limited to people the caller may write to, so replying to everyone
 * never includes somebody they are not allowed to message.
 */
export interface ReplyOptions {
  reply: MailPerson[];
  reply_all_to: MailPerson[];
  reply_all_cc: MailPerson[];
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
  /** Staff-only. Never true in a response to someone who may not see such files. */
  is_restricted?: boolean;
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
  /** Caller's effective level: VIEW < DOWNLOAD < EDIT < MANAGE. */
  my_level?: ResourcePermissionLevel | null;
  /** True when this type can be rendered in the browser. */
  can_preview?: boolean;
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
  /** Staff-only. A row carrying true is never returned to someone who may not see such files -- they are filtered out of the query. */
  is_restricted?: boolean;
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
  /** Staff-only. Hidden from students, guardians and corporate managers whatever else they have been granted, and cannot carry a public link. Only settable by someone who can see staff-only files. */
  is_restricted?: boolean | null;
}

export interface ResourceVersionResponse {
  version_number: number;
  mime_type?: string | null;
  size?: number | null;
  change_note?: string | null;
  created_at: string;
  uploaded_by_username?: string | null;
}

export interface ResubmissionRequest {
  reason: string;
}

/**
 * The lifecycle a set of marks moves through (spec §14).
 */
export type ResultState = "DRAFT" | "UNDER_REVIEW" | "FINALIZED" | "PUBLISHED";
export const ResultStateValues = ["DRAFT", "UNDER_REVIEW", "FINALIZED", "PUBLISHED"] as const;

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

export interface SaveClassPerformanceRequest {
  entries: ClassPerformanceEntry[];
  /** What each criterion is marked out of. Applies to every row in this request; omitted, existing rows keep their own and new ones get 10. */
  max_score?: number | string | null;
}

export interface SaveSheetRequest {
  entries?: SheetEntry[];
  notes?: string | null;
  /** False saves a draft. True finalizes (or, on a finalized sheet, records an edit). */
  submit?: boolean;
}

/**
 * The schedule these sessions were generated from, kept on the batch so the next re-create starts from it.
 */
export interface ScheduleToSave {
  timezone: string;
  weekdays?: number[];
  start_time?: string | null;
  duration_minutes?: number | null;
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

export interface SessionBrief {
  public_id: string;
  batch_code: string;
  course_title: string;
  starts_at?: string | null;
  ends_at?: string | null;
  classroom?: string | null;
  join_opens_at?: string | null;
  join_closes_at?: string | null;
  can_join_now?: boolean;
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

/**
 * One admission to one class.
 *
 * Returned by a POST rather than a GET on purpose: handing out a meeting link
 * is an act that is recorded, not a property of the session that a cache or a
 * prefetch may repeat on the caller's behalf.
 */
export interface SessionJoinResponse {
  meeting_link: string;
  platform: Platforms;
  classroom?: string | null;
  session_start_time: string;
  session_end_time?: string | null;
  join_opens_at: string;
  join_closes_at: string;
  /** True when the window was shut and the caller's session.override opened it. Shown back to them, and audited. */
  joined_outside_window: boolean;
}

export interface SessionOverview {
  /** Thirty minutes before the start. */
  join_opens_at?: string | null;
  /** The session's end. */
  join_closes_at?: string | null;
  /** True when this caller could join at this moment. The API re-checks on join; this only decides whether the button is live. */
  can_join_now?: boolean;
  /** True when a recording exists to play back. */
  has_recording?: boolean;
  public_id: string;
  number: number;
  total: number;
  session_start_time: string;
  session_end_time?: string | null;
  duration_minutes?: number | null;
  platform: Platforms;
  classroom?: string | null;
  /** Only populated for callers who may edit the session (tutors and administrators). Everyone else joins through POST /sessions/{id}/join, which is what makes the join window enforceable rather than cosmetic. */
  meeting_link?: string | null;
  /** Only populated for callers who may edit the session (tutors and administrators). Everyone else joins through POST /sessions/{id}/join, which is what makes the join window enforceable rather than cosmetic. */
  recording_link?: string | null;
  can_manage?: boolean;
  student_notes?: string | null;
  tutor_notes?: string | null;
  origin?: string | null;
  in_google: boolean;
  course: OverviewCourse;
  batch: OverviewBatch;
  tutor: OverviewPerson;
  roster: OverviewRosterEntry[];
  /** True when the caller sees only their own people, not the whole batch. */
  roster_is_partial: boolean;
  attendance_counts: Record<string, number>;
  can_see_contacts: boolean;
}

export interface SessionRecordingAttachRequest {
  /** A file already in the library. The caller needs EDIT on it. */
  resource_id: string;
}

/**
 * Where to play a recording, never where to download one.
 */
export interface SessionRecordingResponse {
  /** Relative to the API root (the same base every other call uses), so a browser that reaches this API through a proxy composes it the same way it composes everything else. Streams the recording after re-checking permission on every request, including every seek. Present only for recordings stored in the LMS. */
  playback_url?: string | null;
  /** The provider's own link. Only ever given to callers who may edit the session -- it is a link out of the LMS and past its checks. */
  external_url?: string | null;
  name?: string | null;
  mime_type?: string | null;
  size?: number | null;
}

export interface SessionSessionResponse {
  /** Thirty minutes before the start. */
  join_opens_at?: string | null;
  /** The session's end. */
  join_closes_at?: string | null;
  /** True when this caller could join at this moment. The API re-checks on join; this only decides whether the button is live. */
  can_join_now?: boolean;
  /** True when a recording exists to play back. */
  has_recording?: boolean;
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
  /** Only populated for callers who may edit the session (tutors and administrators). Everyone else joins through POST /sessions/{id}/join, which is what makes the join window enforceable rather than cosmetic. */
  meeting_link?: string | null;
  /** Only populated for callers who may edit the session (tutors and administrators). Everyone else joins through POST /sessions/{id}/join, which is what makes the join window enforceable rather than cosmetic. */
  recording_link?: string | null;
  /** True when this caller may edit the session. */
  can_manage?: boolean;
  tutor_notes?: string | null;
  student_notes?: string | null;
  /** True once a register has been marked for this session. */
  attendance_recorded?: boolean;
}

/**
 * The timetable row. Carries the join *state* but never the link: this is
 * the list a student actually looks at, so it is the list where a link would
 * have done the most damage.
 */
export interface SessionSummary {
  /** Thirty minutes before the start. */
  join_opens_at?: string | null;
  /** The session's end. */
  join_closes_at?: string | null;
  /** True when this caller could join at this moment. The API re-checks on join; this only decides whether the button is live. */
  can_join_now?: boolean;
  /** True when a recording exists to play back. */
  has_recording?: boolean;
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

export interface SetBandsRequest {
  bands: BandPayload[];
}

export interface SetClassPerformanceStateRequest {
  state: ResultState;
  /** Release or withdraw one student's mark instead of the whole class. */
  student_id?: string | null;
}

/**
 * Replace the whole set.
 *
 * Wholesale rather than one at a time because the set is what has to add up:
 * five individual edits mean four intermediate states that do not total 100,
 * and a concurrent reader would see one of them.
 */
export interface SetComponentsRequest {
  components: ComponentWeightPayload[];
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
  /** What the recipients may do. VIEW lets them watch or read it in place without keeping a copy; DOWNLOAD hands over the bytes. Defaults to VIEW -- the narrower of the two, so a share that forgets to say grants the less. */
  level?: ResourcePermissionLevel;
}

export interface SharedResourceResponse {
  resource_id: string;
  resource_name?: string | null;
  /** What the recipient may do with it. */
  level: ResourcePermissionLevel;
  shared_with_username?: string | null;
  shared_by_username?: string | null;
  created_at: string;
}

export interface SheetBatch {
  public_id: string;
  batch_code: string;
  course_title?: string | null;
  enrolled?: number;
}

export interface SheetChange {
  student: string;
  was?: string | null;
  now?: string | null;
  remarks_changed?: boolean;
}

export interface SheetEntry {
  student_id: string;
  /** Null clears a mark (draft only). */
  status?: AttendanceStatus | null;
  remarks?: string | null;
}

export interface SheetEvent {
  action: string;
  at: string;
  actor: SheetPerson;
  assigned_tutor: SheetPerson;
  on_behalf: boolean;
  counts?: Record<string, number>;
  changes?: SheetChange[];
  notes_changed?: boolean;
}

export interface SheetHistory {
  events: SheetEvent[];
}

export interface SheetMeta {
  state: SheetState;
  assigned_tutor: SheetPerson;
  started_by?: SheetPerson | null;
  started_at?: string | null;
  last_saved_by?: SheetPerson | null;
  last_saved_at?: string | null;
  finalized_by?: SheetPerson | null;
  finalized_at?: string | null;
  submitted_on_behalf?: boolean;
  /** Marked before sheets existed: finalized, with no record of who started it. */
  legacy?: boolean;
}

export interface SheetPermissions {
  can_edit: boolean;
  is_assigned_tutor: boolean;
  /** True when the caller may edit only because they may act for the assigned tutor. */
  would_be_on_behalf: boolean;
}

export interface SheetPerson {
  public_id: string;
  name: string;
}

export interface SheetRow {
  student: SheetPerson;
  /** Null until somebody has marked this student. */
  status?: AttendanceStatus | null;
  remarks?: string | null;
}

export interface SheetSession {
  public_id: string;
  start_time?: string | null;
  end_time?: string | null;
  platform?: Platforms | null;
  classroom?: string | null;
  cancelled?: boolean;
}

export type SheetState = "NOT_STARTED" | "DRAFT" | "FINALIZED";
export const SheetStateValues = ["NOT_STARTED", "DRAFT", "FINALIZED"] as const;

export interface SheetSummary {
  present?: number;
  late?: number;
  absent?: number;
  excused?: number;
  unmarked?: number;
  total?: number;
  /** (present + late) / (marked - excused), as a percentage. */
  rate?: number | null;
}

export interface SheetView {
  session: SheetSession;
  batch: SheetBatch;
  meta: SheetMeta;
  permissions: SheetPermissions;
  notes?: string | null;
  roster: SheetRow[];
  summary: SheetSummary;
}

export interface StateRequest {
  read?: boolean | null;
  starred?: boolean | null;
}

/**
 * §37's drill-down: every class behind one student's `PRACTICAL` figure.
 */
export interface StudentClassPerformanceResponse {
  marks: ClassPerformanceMarkResponse[];
  sessions?: number;
  /** The mean of the sessions that carry a score, as a percentage of `max_score`. Sessions with nothing assessed are excluded, not counted as zero. */
  average?: string | null;
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
  state?: SubmissionState;
  attempt_number?: number;
  raw_grade?: string | null;
  late_penalty_applied?: string | null;
  published_at?: string | null;
  override_reason?: string | null;
  overridden_at?: string | null;
}

/**
 * Where one student stands on one assessment (spec §7).
 *
 * Eleven states because the four §38 insists on distinguishing -- scored
 * zero, not yet assessed, absent, exempted -- are genuinely different facts,
 * and a nullable mark plus a boolean cannot express them. Silently treating
 * a missing mark as zero is the specific failure this enum exists to prevent.
 */
export type SubmissionState = "NOT_STARTED" | "PENDING" | "SUBMITTED" | "LATE" | "UNDER_REVIEW" | "GRADED" | "PUBLISHED" | "ABSENT" | "EXEMPTED" | "RESUBMISSION_REQUIRED" | "REASSESSED";
export const SubmissionStateValues = ["NOT_STARTED", "PENDING", "SUBMITTED", "LATE", "UNDER_REVIEW", "GRADED", "PUBLISHED", "ABSENT", "EXEMPTED", "RESUBMISSION_REQUIRED", "REASSESSED"] as const;

/**
 * Record an absence or an exemption -- neither of which is a mark.
 */
export interface SubmissionStateRequest {
  state: SubmissionState;
  reason?: string | null;
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
  kind?: string;
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

export interface TeamAssignment {
  title: string;
  course_title?: string | null;
  due_date: string;
  /** PENDING, OVERDUE, SUBMITTED or GRADED. */
  status: string;
  submitted_at?: string | null;
  grade?: number | null;
  max_score?: number | null;
}

export interface TeamAttendanceBreakdown {
  present?: number;
  late?: number;
  absent?: number;
  excused?: number;
}

export interface TeamAttendanceRecord {
  session_start: string;
  batch_code: string;
  course_title?: string | null;
  status: string;
}

export interface TeamEnrollment {
  batch_id: string;
  batch_code: string;
  course_title?: string | null;
  status: string;
  enrolled_at?: string | null;
  attendance: TeamAttendanceBreakdown;
  attendance_rate?: number | null;
  score_percent?: number | null;
  overall_grade?: string | null;
  gpa?: number | null;
}

export interface TeamMemberDetail {
  public_id: string;
  full_name: string;
  status: string;
  last_login?: string | null;
  organization?: string | null;
  department?: string | null;
  employee_code?: string | null;
  /** A guardian's relationship to this ward. */
  relationship?: string | null;
  enrollments_active?: number;
  enrollments_completed?: number;
  /** Titles of the courses they are currently enrolled on. */
  courses?: string[];
  /** Percent of recorded sessions attended (present, late or excused). */
  attendance_rate?: number | null;
  sessions_recorded?: number;
  assignments_total?: number;
  assignments_submitted?: number;
  assignments_overdue?: number;
  /** Percent, from the grade book. */
  average_score?: number | null;
  gpa?: number | null;
  next_session?: TeamNextSession | null;
  needs_attention?: boolean;
  attention_reasons?: string[];
  enrollments?: TeamEnrollment[];
  assignments?: TeamAssignment[];
  recent_attendance?: TeamAttendanceRecord[];
}

export interface TeamMemberSummary {
  public_id: string;
  full_name: string;
  status: string;
  last_login?: string | null;
  organization?: string | null;
  department?: string | null;
  employee_code?: string | null;
  /** A guardian's relationship to this ward. */
  relationship?: string | null;
  enrollments_active?: number;
  enrollments_completed?: number;
  /** Titles of the courses they are currently enrolled on. */
  courses?: string[];
  /** Percent of recorded sessions attended (present, late or excused). */
  attendance_rate?: number | null;
  sessions_recorded?: number;
  assignments_total?: number;
  assignments_submitted?: number;
  assignments_overdue?: number;
  /** Percent, from the grade book. */
  average_score?: number | null;
  gpa?: number | null;
  next_session?: TeamNextSession | null;
  needs_attention?: boolean;
  attention_reasons?: string[];
}

export interface TeamNextSession {
  start: string;
  batch_code: string;
  course_title?: string | null;
}

export interface TeamOverview {
  people: number;
  needing_attention: number;
  average_attendance_rate?: number | null;
  assignments_overdue?: number;
  items: TeamMemberSummary[];
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
  /** Null while the course is incomplete. A transcript never reports a mid-course standing as a final result (spec §38). */
  final_percentage?: string | null;
  total_marks_earned?: string | null;
  total_marks_possible?: string | null;
  is_pass?: boolean | null;
  /** The grading policy that produced these figures. Schemes change. */
  scheme_name?: string | null;
  sessions_total?: number | null;
  sessions_attended?: number | null;
  attendance_percentage?: string | null;
  /** The per-component arithmetic as it stood at issue (spec §37). */
  breakdown?: (Record<string, unknown>)[] | null;
  issued_at?: string | null;
  /** Who certified it (spec §5's verification). */
  issued_by_username?: string | null;
  /** True when every weighted component was assessed at issue. */
  is_complete?: boolean;
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
  /** API path of the picture (fetch with the same credentials); null when none is set. */
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
  /** API path of the picture (fetch with the same credentials); null when none is set. */
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

