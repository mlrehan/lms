"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CalendarPlus, ClipboardCheck, Trash2, UserPlus } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  BatchResponse,
  EnrollmentResponse,
  PageAcademicYearResponse,
  PageEnrollmentResponse,
  PageSemesterResponse,
  PageSessionSummary,
  SessionSessionResponse,
  SessionSummary,
} from "@/lib/api/types";
import { EnrollmentStatusValues, PlatformsValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { BatchGoogleCard } from "@/components/domain/batch-google-card";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormActions, FormGrid, Input, Textarea } from "@/components/ui/form";
import { FormSelect } from "@/components/ui/form-controls";
import { Select, optionsFromValues } from "@/components/ui/select";
import { Stat, StatGrid } from "@/components/ui/stat";
import { StatusBadge } from "@/components/domain/status-badge";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatCalendarDate, formatDateTime, fromLocalInputValue } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";
import { durationLabel, shortMethod } from "@/lib/format/batch";
import { RecreateSessionsDialog } from "@/components/domain/recreate-sessions-dialog";
import { SessionQueue } from "@/components/domain/attendance/session-queue";
import { AttendanceSheetPanel } from "@/components/domain/attendance/sheet-panel";

/** The batch's timetable facts in one glance: the reason a batch page is the workspace, not one tab among several. */
function ScheduleCard({ batch }: { batch: BatchResponse }) {
  const facts: [string, string | null | undefined, string?][] = [
    ["Days", batch.training_days],
    ["Time", batch.training_start_time && batch.training_end_time ? `${batch.training_start_time} – ${batch.training_end_time}` : null, batch.schedule_timezone ?? undefined],
    ["Class length", durationLabel(batch.class_duration_minutes) || null],
    ["Method", shortMethod(batch.training_method) || null],
    ["Fee", batch.batch_fee == null ? null : `£${batch.batch_fee.toLocaleString("en-GB")}`],
    ["Tutor", batch.tutor_name],
  ];
  return (
    <Card>
      <CardBody className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
        {facts.map(([k, v, note]) => (
          <div key={k} className="min-w-0">
            <p className="eyebrow">{k}</p>
            <p className="truncate text-[13px] font-medium" title={[v, note].filter(Boolean).join(" · ") || undefined}>
              {v || <span className="text-subtle-foreground">—</span>}
            </p>
            {note && v ? (
              <p className="truncate text-2xs text-subtle-foreground" title={note}>{note}</p>
            ) : null}
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

/** Attendance for this batch only: pick a session, take or review its register, without leaving the workspace. */
function BatchAttendanceTab({ batchId }: { batchId: string }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <Card className="max-h-[32rem] overflow-y-auto">
        <SessionQueue batchId={batchId} tutorId="" range="all" state="" selectedId={sessionId} onSelect={(item) => setSessionId(item.session_id)} />
      </Card>
      <section aria-label="Attendance sheet" className="min-w-0">
        {sessionId ? (
          <AttendanceSheetPanel key={sessionId} sessionId={sessionId} onBack={() => setSessionId(null)} />
        ) : (
          <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed border-border-subtle p-8 text-center text-sm text-muted-foreground">
            Choose a session to take or review its attendance.
          </div>
        )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Overview                                                                    */
/* -------------------------------------------------------------------------- */

const batchSchema = z.object({
  batch_code: z.string().trim().min(1, "A batch code is required."),
  capacity: z.string().trim(),
  duration_hours: z.string().trim(),
  number_of_sessions: z.string().trim(),
  start_date: z.string().trim(),
  end_date: z.string().trim(),
  notes: z.string().trim(),
  is_active: z.boolean(),
  academic_year_id: z.string().trim(),
  semester_id: z.string().trim(),
});

type BatchValues = z.infer<typeof batchSchema>;

function OverviewTab({ batch, canEdit }: { batch: BatchResponse; canEdit: boolean }) {
  const { permissions } = useSession();
  const canReadAcademic = permissions.has("academic.read");

  const years = useQuery({
    queryKey: ["academic-years", "all"],
    queryFn: () => api.get<PageAcademicYearResponse>("/academic-years", { query: { limit: 100 } }),
    enabled: canReadAcademic,
    staleTime: 5 * 60_000,
  });

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    setValue,
    setError,
    formState: { errors, isDirty },
  } = useForm<BatchValues>({
    resolver: zodResolver(batchSchema),
    defaultValues: {
      batch_code: batch.batch_code,
      capacity: batch.capacity?.toString() ?? "",
      duration_hours: batch.duration_hours?.toString() ?? "",
      number_of_sessions: batch.number_of_sessions?.toString() ?? "",
      start_date: batch.start_date?.slice(0, 10) ?? "",
      end_date: batch.end_date?.slice(0, 10) ?? "",
      notes: batch.notes ?? "",
      is_active: batch.is_active,
      academic_year_id: batch.academic_year_id ?? "",
      semester_id: batch.semester_id ?? "",
    },
  });

  const academicYearId = watch("academic_year_id");

  const semesters = useQuery({
    queryKey: ["semesters", academicYearId],
    queryFn: () =>
      api.get<PageSemesterResponse>("/semesters", {
        query: { academic_year_id: academicYearId || undefined, limit: 100 },
      }),
    enabled: canReadAcademic,
    staleTime: 5 * 60_000,
  });

  const save = useApiMutation<BatchResponse, BatchValues>({
    mutationFn: (values) =>
      api.patch<BatchResponse>(`/batches/${segment(batch.public_id)}`, {
        body: {
          batch_code: values.batch_code,
          capacity: values.capacity ? Number(values.capacity) : null,
          duration_hours: values.duration_hours ? Number(values.duration_hours) : null,
          number_of_sessions: values.number_of_sessions ? Number(values.number_of_sessions) : null,
          start_date: values.start_date || null,
          end_date: values.end_date || null,
          notes: values.notes || null,
          is_active: values.is_active,
          academic_year_id: values.academic_year_id || null,
          semester_id: values.semester_id || null,
          // "Leave alone" and "unschedule" are different requests, and only
          // these flags can say the second one.
          clear_academic_year: values.academic_year_id === "" && Boolean(batch.academic_year_id),
          clear_semester: values.semester_id === "" && Boolean(batch.semester_id),
        },
      }),
    success: "Batch saved.",
    invalidate: [["batches"], ["courses"]],
    onSuccess: (updated) =>
      reset({
        batch_code: updated.batch_code,
        capacity: updated.capacity?.toString() ?? "",
        duration_hours: updated.duration_hours?.toString() ?? "",
        number_of_sessions: updated.number_of_sessions?.toString() ?? "",
        start_date: updated.start_date?.slice(0, 10) ?? "",
        end_date: updated.end_date?.slice(0, 10) ?? "",
        notes: updated.notes ?? "",
        is_active: updated.is_active,
        academic_year_id: updated.academic_year_id ?? "",
        semester_id: updated.semester_id ?? "",
      }),
    onError: (error) => {
      applyFieldErrors<BatchValues>(error, setError, [
        "batch_code",
        "start_date",
        "end_date",
        "capacity",
        "semester_id",
      ]);
    },
  });

  const isActive = watch("is_active");

  return (
    <form method="post" onSubmit={handleSubmit((values) => save.mutate(values))} className="space-y-4" noValidate>
      <StatGrid>
        <Stat label="Enrolled" value={batch.enrolled_count} />
        <Stat
          label="Seats available"
          value={batch.capacity === null || batch.capacity === undefined ? "Unlimited" : batch.seats_available}
          tone={batch.seats_available === 0 ? "warning" : "default"}
        />
        <Stat label="Planned sessions" value={batch.number_of_sessions} />
        <Stat label="Duration (hours)" value={batch.duration_hours} />
      </StatGrid>

      <Card>
        <CardHeader title="Batch details" />
        <CardBody className="space-y-4">
          <FormGrid>
            <Field label="Batch code" error={errors.batch_code?.message} required>
              {({ id }) => <Input id={id} disabled={!canEdit} {...register("batch_code")} />}
            </Field>
            <Field label="Capacity" hint="Blank means no limit." error={errors.capacity?.message}>
              {({ id }) => (
                <Input id={id} type="number" min={1} disabled={!canEdit} {...register("capacity")} />
              )}
            </Field>
            <Field label="Start date" error={errors.start_date?.message}>
              {({ id }) => <Input id={id} type="date" disabled={!canEdit} {...register("start_date")} />}
            </Field>
            <Field label="End date" error={errors.end_date?.message}>
              {({ id }) => <Input id={id} type="date" disabled={!canEdit} {...register("end_date")} />}
            </Field>
            <Field label="Planned sessions">
              {({ id }) => (
                <Input id={id} type="number" min={1} disabled={!canEdit} {...register("number_of_sessions")} />
              )}
            </Field>
            <Field label="Duration (hours)">
              {({ id }) => (
                <Input id={id} type="number" min={0} disabled={!canEdit} {...register("duration_hours")} />
              )}
            </Field>
            <Field label="Academic year">
              {({ id }) => (
                <Select
                  id={id}
                  disabled={!canEdit || !canReadAcademic}
                  value={(academicYearId) || null}
                  onValueChange={(next) => {
                    setValue("academic_year_id", (next ?? ""), { shouldDirty: true });
                    setValue("semester_id", "", { shouldDirty: true });
                  }}
                 placeholder="Not scheduled" clearable options={(years.data?.items ?? []).map((year) => ({ value: year.public_id, label: year.label }))} />
              )}
            </Field>
            <Field label="Semester" error={errors.semester_id?.message}>
              {({ id }) => (
                <FormSelect
                  id={id}
                  disabled={!canEdit || !canReadAcademic || !academicYearId}
                  
                 control={control} name="semester_id" placeholder="Not scheduled" clearable options={(semesters.data?.items ?? []).map((semester) => ({ value: semester.public_id, label: semester.name }))} />
              )}
            </Field>
          </FormGrid>

          <Field label="Notes">
            {({ id }) => <Textarea id={id} rows={3} disabled={!canEdit} {...register("notes")} />}
          </Field>

          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={isActive}
              disabled={!canEdit}
              onCheckedChange={(checked) => setValue("is_active", checked, { shouldDirty: true })}
            />
            <span>
              Active
              <span className="block text-xs text-muted-foreground">
                Closing a batch stops new enrollments. Existing ones are untouched.
              </span>
            </span>
          </label>
        </CardBody>
      </Card>

      {canEdit ? (
        <FormActions>
          <Button type="button" variant="ghost" onClick={() => reset()} disabled={!isDirty}>
            Discard changes
          </Button>
          <Button type="submit" loading={save.isPending} disabled={!isDirty}>
            Save batch
          </Button>
        </FormActions>
      ) : null}
    </form>
  );
}

/* -------------------------------------------------------------------------- */
/* Sessions                                                                    */
/* -------------------------------------------------------------------------- */

const sessionSchema = z.object({
  tutor_id: z.string().min(1, "Choose the tutor taking this session."),
  session_start_time: z.string().min(1, "Set a start time."),
  session_end_time: z.string(),
  platform: z.enum(PlatformsValues),
  classroom: z.string().trim(),
  meeting_link: z.string().trim(),
  tutor_notes: z.string().trim(),
});

type SessionValues = z.infer<typeof sessionSchema>;

function SessionsTab({ batch }: { batch: BatchResponse }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(10);
  const [createOpen, setCreateOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["batches", batch.public_id, "sessions", limit, offset],
    queryFn: () =>
      api.get<PageSessionSummary>(`/batches/${segment(batch.public_id)}/sessions`, {
        query: { limit, offset },
      }),
  });

  const {
    register,
    handleSubmit,
    control: sessionControl,
    reset,
    watch,
    setValue,
    setError,
    formState: { errors },
  } = useForm<SessionValues>({
    resolver: zodResolver(sessionSchema),
    defaultValues: {
      tutor_id: "",
      session_start_time: "",
      session_end_time: "",
      platform: "Classroom",
      classroom: "",
      meeting_link: "",
      tutor_notes: "",
    },
  });

  const create = useApiMutation<SessionSessionResponse, SessionValues>({
    mutationFn: (values) =>
      api.post<SessionSessionResponse>(`/batches/${segment(batch.public_id)}/sessions`, {
        body: {
          tutor_id: values.tutor_id,
          // The form collects wall-clock time in the viewer's timezone; the
          // API stores UTC. Converting here anchors "09:00" to the right
          // instant on both sides of a DST change.
          session_start_time: fromLocalInputValue(values.session_start_time, timeZone),
          session_end_time: values.session_end_time
            ? fromLocalInputValue(values.session_end_time, timeZone)
            : null,
          platform: values.platform,
          classroom: values.classroom || null,
          meeting_link: values.meeting_link || null,
          tutor_notes: values.tutor_notes || null,
        },
      }),
    success: "Session scheduled.",
    invalidate: [["batches", batch.public_id, "sessions"], ["sessions"]],
    onSuccess: () => {
      reset();
      setBanner(null);
      setCreateOpen(false);
    },
    onError: (error) => {
      if (
        !applyFieldErrors<SessionValues>(error, setError, [
          "tutor_id",
          "session_start_time",
          "session_end_time",
          "meeting_link",
        ])
      ) {
        setBanner(error.message);
      }
    },
  });

  const tutorId = watch("tutor_id");

  const columns: Column<SessionSummary>[] = [
    {
      key: "start",
      header: "Starts",
      cell: (session) => (
        <Link href={`/sessions/${session.public_id}`} className="font-medium hover:underline">
          {formatDateTime(session.session_start_time, { timeZone })}
        </Link>
      ),
    },
    {
      key: "end",
      header: "Ends",
      secondary: true,
      cell: (session) => formatDateTime(session.session_end_time, { timeZone }),
    },
    {
      key: "platform",
      header: "Where",
      cell: (session) => (
        <span className="flex items-center gap-2">
          <Badge tone="neutral">{humanise(session.platform)}</Badge>
          {session.classroom ? (
            <span className="text-xs text-muted-foreground">{session.classroom}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "duration",
      header: "Minutes",
      align: "right",
      secondary: true,
      cell: (session) => <span className="tabular-nums">{session.duration_minutes ?? "—"}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (session) =>
        permissions.has("attendance.read") ? (
          <Link
            href={`/sessions/${session.public_id}`}
            className={buttonVariants({ variant: "ghost", size: "sm" })}
          >
            <ClipboardCheck /> Register
          </Link>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Sessions"
        description={`Times are shown in ${timeZone}. They are stored in UTC.`}
        actions={
          permissions.has("session.create") ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <CalendarPlus /> Schedule session
            </Button>
          ) : null
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(session) => session.public_id}
            emptyMessage="Nothing scheduled for this batch yet."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="sessions"
          />
        </>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Schedule a session"
            description={`Times are entered in ${timeZone} and stored in UTC.`}
          />
          <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
            {banner ? (
              <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                {banner}
              </div>
            ) : null}
            <Field
              label="Tutor"
              error={errors.tutor_id?.message}
              required
              hint="Assigning a tutor grants them access to this batch's students."
            >
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="TUTOR"
                  value={tutorId || null}
                  onChange={(next) => setValue("tutor_id", next ?? "", { shouldValidate: true })}
                />
              )}
            </Field>
            <FormGrid>
              <Field label="Starts" error={errors.session_start_time?.message} required>
                {({ id }) => (
                  <Input id={id} type="datetime-local" {...register("session_start_time")} />
                )}
              </Field>
              <Field label="Ends" error={errors.session_end_time?.message}>
                {({ id }) => <Input id={id} type="datetime-local" {...register("session_end_time")} />}
              </Field>
              <Field label="Platform">
                {({ id }) => (
                  <FormSelect id={id} control={sessionControl} name="platform" options={PlatformsValues.map((platform) => ({ value: platform, label: humanise(platform) }))} />
                )}
              </Field>
              <Field label="Classroom">
                {({ id }) => <Input id={id} {...register("classroom")} />}
              </Field>
            </FormGrid>
            <Field label="Meeting link" error={errors.meeting_link?.message}>
              {({ id }) => <Input id={id} {...register("meeting_link")} />}
            </Field>
            <Field label="Tutor notes">
              {({ id }) => <Textarea id={id} rows={2} {...register("tutor_notes")} />}
            </Field>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending}>
                Schedule
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Enrollments                                                                 */
/* -------------------------------------------------------------------------- */

function EnrollmentsTab({ batch }: { batch: BatchResponse }) {
  const { permissions } = useSession();
  const { limit, offset, setPage } = useListState(25);
  const [status, setStatus] = useState("");
  const [enrollOpen, setEnrollOpen] = useState(false);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(true);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["enrollments", batch.public_id, status, limit, offset],
    queryFn: () =>
      api.get<PageEnrollmentResponse>("/enrollments", {
        query: { batch_id: batch.public_id, status: status || undefined, limit, offset },
      }),
  });

  const enroll = useApiMutation<EnrollmentResponse, { studentId: string; confirmed: boolean }>({
    mutationFn: ({ studentId: id, confirmed: isConfirmed }) =>
      api.post<EnrollmentResponse>("/enrollments", {
        body: { student_id: id, batch_id: batch.public_id, confirmed: isConfirmed },
      }),
    success: "Student enrolled.",
    invalidate: [["enrollments"], ["batches"]],
    onSuccess: () => {
      setStudentId(null);
      setEnrollOpen(false);
    },
  });

  const setEnrollmentStatus = useApiMutation<
    EnrollmentResponse,
    { enrollmentId: string; status: string }
  >({
    mutationFn: ({ enrollmentId, status: next }) =>
      api.put<EnrollmentResponse>(`/enrollments/${segment(enrollmentId)}/status`, {
        body: { status: next },
      }),
    success: "Enrollment updated.",
    invalidate: [["enrollments"], ["batches"]],
  });

  const columns: Column<EnrollmentResponse>[] = [
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <Link href={`/users/${row.student_id}`} className="font-medium hover:underline">
          {row.student_username ?? row.student_id}
        </Link>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (row) => (
        <span className="flex items-center gap-2">
          <StatusBadge value={row.status} kind="enrollment" />
          {row.is_transfer ? <Badge tone="info">Transferred in</Badge> : null}
        </span>
      ),
    },
    {
      key: "date",
      header: "Enrolled",
      secondary: true,
      cell: (row) => formatCalendarDate(row.enrollment_date),
    },
    {
      key: "performance",
      header: "Performance",
      secondary: true,
      cell: (row) =>
        row.performance_level ? (
          <Badge tone="neutral">{humanise(row.performance_level)}</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("enrollment.update") ? (
          <Select
            className="ml-auto w-auto"
            aria-label={`Status for ${row.student_username ?? "student"}`}
            value={row.status}
            disabled={setEnrollmentStatus.isPending}
            onValueChange={(next) => setEnrollmentStatus.mutate({
                enrollmentId: row.public_id,
                status: (next ?? ""),
              })
            }
           options={optionsFromValues(EnrollmentStatusValues, humanise)} />
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Enrollments"
        description={
          batch.capacity
            ? `${batch.enrolled_count ?? 0} of ${batch.capacity} seats taken.`
            : `${batch.enrolled_count ?? 0} enrolled. No capacity limit.`
        }
        actions={
          <div className="flex items-center gap-2">
            <Select
              className="w-auto"
              aria-label="Filter by status"
              value={(status) || null}
              onValueChange={(next) => {
                setStatus((next ?? ""));
                setPage({ limit, offset: 0 });
              }}
             placeholder="Any status" clearable options={optionsFromValues(EnrollmentStatusValues, humanise)} />
            {permissions.has("enrollment.create") ? (
              <Button size="sm" onClick={() => setEnrollOpen(true)}>
                <UserPlus /> Enroll
              </Button>
            ) : null}
          </div>
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="Nobody is enrolled in this batch yet."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="enrollments"
          />
        </>
      )}

      <Dialog open={enrollOpen} onOpenChange={setEnrollOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Enroll a student"
            description={`Into ${batch.batch_code}${batch.course_title ? ` (${batch.course_title})` : ""}.`}
          />
          <div className="space-y-4">
            <Field label="Student" required>
              {({ id }) => (
                <UserPicker id={id} role="STUDENT" value={studentId} onChange={(next) => setStudentId(next)} />
              )}
            </Field>
            <label className="flex items-center gap-3 text-sm">
              <Switch checked={confirmed} onCheckedChange={setConfirmed} />
              <span>
                Confirm immediately
                <span className="block text-xs text-muted-foreground">
                  You enrolling them directly is the approval step. Leave this off to create a
                  PENDING enrollment that someone approves later.
                </span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEnrollOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={enroll.isPending}
              disabled={!studentId}
              onClick={() => studentId && enroll.mutate({ studentId, confirmed })}
            >
              Enroll student
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function BatchDetailPage({ params }: { params: Promise<{ batchId: string }> }) {
  const { batchId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [recreate, setRecreate] = useState(false);
  const tabParam = useSearchParams().get("tab");
  const initialTab = ["overview", "sessions", "attendance", "enrollments"].includes(tabParam ?? "") ? (tabParam as string) : "overview";

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["batches", "detail", batchId],
    queryFn: () => api.get<BatchResponse>(`/batches/${segment(batchId)}`),
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/batches/${segment(batchId)}`),
    success: "Batch deleted.",
    invalidate: [["batches"], ["courses"]],
    onSuccess: () => router.push("/batches"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[
          { label: "Batches", href: "/batches" },
          ...(data.course_title
            ? [{ label: data.course_title, href: `/courses/${data.course_id}` }]
            : []),
          { label: data.batch_code },
        ]}
        title={data.batch_code}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={data.is_active ? "success" : "neutral"}>
              {data.is_active ? "Active" : "Closed"}
            </Badge>
            {data.academic_year_label ? <Badge tone="info">{data.academic_year_label}</Badge> : null}
            {data.semester_name ? <Badge tone="info">{data.semester_name}</Badge> : null}
            <span className="text-xs">
              {formatCalendarDate(data.start_date)} - {formatCalendarDate(data.end_date)}
            </span>
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            {permissions.has("session.create") && permissions.has("session.delete") ? (
              <Button variant="secondary" size="sm" onClick={() => setRecreate(true)}>
                <CalendarPlus /> Re-create sessions
              </Button>
            ) : null}
            {permissions.has("grade.read") ? (
              <Link
                href={`/gradebook?batch=${data.public_id}`}
                className={buttonVariants({ variant: "secondary", size: "sm" })}
              >
                Grade book
              </Link>
            ) : null}
            {permissions.has("batch.delete") ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete batch"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      <ScheduleCard batch={data} />

      <BatchGoogleCard batchId={data.public_id} />

      <Tabs defaultValue={initialTab}>
        <TabsList>
          <TabsTab value="overview">Overview</TabsTab>
          <TabsTab value="sessions">Sessions</TabsTab>
          {permissions.has("attendance.create") ? <TabsTab value="attendance">Attendance</TabsTab> : null}
          <TabsTab value="enrollments">Enrollments</TabsTab>
        </TabsList>
        <TabsPanel value="overview">
          <OverviewTab batch={data} canEdit={permissions.has("batch.update")} />
        </TabsPanel>
        <TabsPanel value="sessions">
          <SessionsTab batch={data} />
        </TabsPanel>
        <TabsPanel value="attendance">
          <BatchAttendanceTab batchId={data.public_id} />
        </TabsPanel>
        <TabsPanel value="enrollments">
          <EnrollmentsTab batch={data} />
        </TabsPanel>
      </Tabs>

      {recreate ? <RecreateSessionsDialog batchId={data.public_id} batchCode={data.batch_code} onClose={() => setRecreate(false)} /> : null}

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this batch?"
        description="Its sessions, register and enrollments go with it. Closing the batch keeps the record instead."
        confirmPhrase={data.batch_code}
        confirmLabel="Delete batch"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
