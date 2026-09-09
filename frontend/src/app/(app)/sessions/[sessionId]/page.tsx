"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, ExternalLink, Save, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  AttendanceResponse,
  AttendanceStatus,
  PageAttendanceResponse,
  PageEnrollmentResponse,
  SessionSessionResponse,
} from "@/lib/api/types";
import { AttendanceStatusValues, PlatformsValues } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "@/lib/format/datetime";
import { cn, humanise } from "@/lib/utils";

interface RegisterRow {
  studentId: string;
  username: string;
  status: AttendanceStatus;
  remarks: string;
}

const STATUS_TONE: Record<AttendanceStatus, string> = {
  PRESENT: "border-success bg-success/15 text-success",
  LATE: "border-warning bg-warning/20 text-warning",
  ABSENT: "border-danger bg-danger/15 text-danger",
  EXCUSED: "border-info bg-info/15 text-info",
};

/**
 * The register.
 *
 * Marked in one request for the whole class, because that is how a register
 * is actually taken -- thirty separate calls would leave a half-marked
 * register if the fifteenth failed, and the API is shaped accordingly.
 */
function Register({ session }: { session: SessionSessionResponse }) {
  const { permissions } = useSession();
  const canMark = permissions.has("attendance.create");

  const roster = useQuery({
    queryKey: ["enrollments", session.batch_id, "confirmed"],
    queryFn: () =>
      api.get<PageEnrollmentResponse>("/enrollments", {
        query: { batch_id: session.batch_id, status: "CONFIRMED", limit: 200 },
      }),
  });

  const existing = useQuery({
    queryKey: ["attendance", session.public_id],
    queryFn: () =>
      api.get<PageAttendanceResponse>("/attendance", {
        query: { session_id: session.public_id, limit: 200 },
      }),
  });

  const [rows, setRows] = useState<RegisterRow[] | null>(null);

  const initial = useMemo<RegisterRow[]>(() => {
    const marks = new Map<string, AttendanceResponse>();
    for (const record of existing.data?.items ?? []) marks.set(record.student_id, record);
    return (roster.data?.items ?? []).map((enrollment) => {
      const mark = marks.get(enrollment.student_id);
      return {
        studentId: enrollment.student_id,
        username: enrollment.student_username ?? enrollment.student_id,
        // Defaulting to PRESENT is the honest default only because the whole
        // register is submitted at once and the marker sees every row before
        // saving -- there is no way to save a row nobody looked at.
        status: mark?.status ?? "PRESENT",
        remarks: mark?.remarks ?? "",
      };
    });
  }, [roster.data, existing.data]);

  useEffect(() => setRows(null), [initial]);

  const current = rows ?? initial;

  const save = useApiMutation<AttendanceResponse[], RegisterRow[]>({
    mutationFn: (entries) =>
      api.put<AttendanceResponse[]>(`/sessions/${segment(session.public_id)}/attendance`, {
        body: {
          entries: entries.map((row) => ({
            student_id: row.studentId,
            status: row.status,
            remarks: row.remarks || null,
          })),
        },
      }),
    success: (result) => `Register saved for ${result.length} student(s).`,
    invalidate: [["attendance"], ["sessions"], ["dashboard"]],
    onSuccess: () => setRows(null),
  });

  if (roster.isPending || existing.isPending) return <LoadingState rows={5} />;
  if (roster.error) return <ErrorState error={roster.error} onRetry={() => void roster.refetch()} />;
  if (existing.error) {
    return <ErrorState error={existing.error} onRetry={() => void existing.refetch()} />;
  }

  if (current.length === 0) {
    return (
      <CardBody>
        <p className="text-sm text-muted-foreground">
          Nobody is confirmed on this batch, so there is no register to take. Confirm enrollments on
          the batch first.
        </p>
      </CardBody>
    );
  }

  function update(studentId: string, patch: Partial<RegisterRow>) {
    setRows((previous) =>
      (previous ?? initial).map((row) => (row.studentId === studentId ? { ...row, ...patch } : row)),
    );
  }

  function setAll(status: AttendanceStatus) {
    setRows((previous) => (previous ?? initial).map((row) => ({ ...row, status })));
  }

  const dirty = rows !== null;

  return (
    <>
      <CardBody className="space-y-3">
        {canMark ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Mark everyone:</span>
            {AttendanceStatusValues.map((status) => (
              <Button key={status} size="sm" variant="secondary" onClick={() => setAll(status)}>
                {humanise(status)}
              </Button>
            ))}
          </div>
        ) : null}

        <ul className="divide-y divide-border rounded-lg border border-border">
          {current.map((row) => (
            <li key={row.studentId} className="flex flex-wrap items-center gap-3 px-3 py-2">
              <Link
                href={`/users/${row.studentId}`}
                className="min-w-40 flex-1 truncate text-sm font-medium hover:underline"
              >
                {row.username}
              </Link>
              <div className="flex flex-wrap gap-1">
                {AttendanceStatusValues.map((status) => (
                  <label
                    key={status}
                    className={cn(
                      "cursor-pointer rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                      row.status === status
                        ? STATUS_TONE[status]
                        : "border-border text-muted-foreground hover:border-border-strong",
                      !canMark && "cursor-not-allowed opacity-70",
                    )}
                  >
                    <input
                      type="radio"
                      className="sr-only"
                      name={`status-${row.studentId}`}
                      checked={row.status === status}
                      disabled={!canMark}
                      onChange={() => update(row.studentId, { status })}
                    />
                    {humanise(status)}
                  </label>
                ))}
              </div>
              <Input
                className="w-full sm:w-56"
                placeholder={row.status === "EXCUSED" ? "Reason (recommended)" : "Remarks"}
                aria-label={`Remarks for ${row.username}`}
                value={row.remarks}
                disabled={!canMark}
                onChange={(event) => update(row.studentId, { remarks: event.target.value })}
              />
            </li>
          ))}
        </ul>
      </CardBody>

      {canMark ? (
        <div className="border-t border-border px-4 py-3">
          <FormActions>
            <Button variant="ghost" disabled={!dirty} onClick={() => setRows(null)}>
              Reset
            </Button>
            <Button loading={save.isPending} onClick={() => save.mutate(current)}>
              <Save /> Save register
            </Button>
          </FormActions>
        </div>
      ) : null}
    </>
  );
}

export default function SessionDetailPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["sessions", "detail", sessionId],
    queryFn: () => api.get<SessionSessionResponse>(`/sessions/${segment(sessionId)}`),
  });

  const [draft, setDraft] = useState<{
    start: string;
    end: string;
    platform: string;
    classroom: string;
    meeting_link: string;
    recording_link: string;
    tutor_notes: string;
    student_notes: string;
  } | null>(null);

  const update = useApiMutation<SessionSessionResponse, NonNullable<typeof draft>>({
    mutationFn: (values) =>
      api.patch<SessionSessionResponse>(`/sessions/${segment(sessionId)}`, {
        body: {
          session_start_time: values.start ? fromLocalInputValue(values.start, timeZone) : null,
          session_end_time: values.end ? fromLocalInputValue(values.end, timeZone) : null,
          platform: values.platform,
          classroom: values.classroom || null,
          meeting_link: values.meeting_link || null,
          recording_link: values.recording_link || null,
          tutor_notes: values.tutor_notes || null,
          student_notes: values.student_notes || null,
        },
      }),
    success: "Session updated.",
    invalidate: [["sessions"]],
    onSuccess: () => {
      setEditing(false);
      setDraft(null);
    },
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/sessions/${segment(sessionId)}`),
    success: "Session deleted.",
    invalidate: [["sessions"], ["batches"]],
    onSuccess: () => router.push("/sessions"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  function beginEdit() {
    if (!data) return;
    setDraft({
      start: toLocalInputValue(data.session_start_time, timeZone),
      end: toLocalInputValue(data.session_end_time, timeZone),
      platform: data.platform,
      classroom: data.classroom ?? "",
      meeting_link: data.meeting_link ?? "",
      recording_link: data.recording_link ?? "",
      tutor_notes: data.tutor_notes ?? "",
      student_notes: data.student_notes ?? "",
    });
    setEditing(true);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[
          { label: "Timetable", href: "/sessions" },
          ...(data.batch_code ? [{ label: data.batch_code, href: `/batches/${data.batch_id}` }] : []),
          { label: "Session" },
        ]}
        title={formatDateTime(data.session_start_time, { timeZone })}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{humanise(data.platform)}</Badge>
            {data.classroom ? <Badge tone="neutral">{data.classroom}</Badge> : null}
            {data.attendance_recorded ? (
              <Badge tone="success">Register taken</Badge>
            ) : (
              <Badge tone="warning">Register not taken</Badge>
            )}
            {data.course_title ? <span className="text-xs">{data.course_title}</span> : null}
            {data.tutor_username ? (
              <span className="text-xs">
                Tutor{" "}
                <Link href={`/users/${data.tutor_id}`} className="hover:underline">
                  {data.tutor_username}
                </Link>
              </span>
            ) : null}
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            {data.meeting_link ? (
              <a
                href={data.meeting_link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                Join <ExternalLink className="size-3.5" />
              </a>
            ) : null}
            {permissions.has("session.update") && !editing ? (
              <Button variant="secondary" size="sm" onClick={beginEdit}>
                Edit session
              </Button>
            ) : null}
            {permissions.has("session.delete") ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete session"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      {editing && draft ? (
        <Card>
          <CardHeader title="Edit session" description={`Times are entered in ${timeZone}.`} />
          <CardBody className="space-y-4">
            <FormGrid>
              <Field label="Starts">
                {({ id }) => (
                  <Input
                    id={id}
                    type="datetime-local"
                    value={draft.start}
                    onChange={(event) => setDraft({ ...draft, start: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Ends">
                {({ id }) => (
                  <Input
                    id={id}
                    type="datetime-local"
                    value={draft.end}
                    onChange={(event) => setDraft({ ...draft, end: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Platform">
                {({ id }) => (
                  <NativeSelect
                    id={id}
                    value={draft.platform}
                    onChange={(event) => setDraft({ ...draft, platform: event.target.value })}
                  >
                    {PlatformsValues.map((platform) => (
                      <option key={platform} value={platform}>
                        {humanise(platform)}
                      </option>
                    ))}
                  </NativeSelect>
                )}
              </Field>
              <Field label="Classroom">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.classroom}
                    onChange={(event) => setDraft({ ...draft, classroom: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Meeting link">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.meeting_link}
                    onChange={(event) => setDraft({ ...draft, meeting_link: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Recording link">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.recording_link}
                    onChange={(event) => setDraft({ ...draft, recording_link: event.target.value })}
                  />
                )}
              </Field>
            </FormGrid>
            <Field label="Tutor notes">
              {({ id }) => (
                <Textarea
                  id={id}
                  rows={2}
                  value={draft.tutor_notes}
                  onChange={(event) => setDraft({ ...draft, tutor_notes: event.target.value })}
                />
              )}
            </Field>
            <Field label="Notes for students">
              {({ id }) => (
                <Textarea
                  id={id}
                  rows={2}
                  value={draft.student_notes}
                  onChange={(event) => setDraft({ ...draft, student_notes: event.target.value })}
                />
              )}
            </Field>
            <FormActions>
              <Button
                variant="ghost"
                onClick={() => {
                  setEditing(false);
                  setDraft(null);
                }}
              >
                Cancel
              </Button>
              <Button loading={update.isPending} onClick={() => update.mutate(draft)}>
                Save session
              </Button>
            </FormActions>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader title="Details" />
          <CardBody className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <p className="text-xs text-muted-foreground">Ends</p>
              <p>{formatDateTime(data.session_end_time, { timeZone })}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Duration</p>
              <p>{data.duration_minutes ? `${data.duration_minutes} minutes` : "—"}</p>
            </div>
            {data.recording_link ? (
              <div className="sm:col-span-2">
                <p className="text-xs text-muted-foreground">Recording</p>
                <a
                  href={data.recording_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="break-all text-primary hover:underline"
                >
                  {data.recording_link}
                </a>
              </div>
            ) : null}
            {data.tutor_notes ? (
              <div className="sm:col-span-2">
                <p className="text-xs text-muted-foreground">Tutor notes</p>
                <p className="whitespace-pre-wrap break-words">{data.tutor_notes}</p>
              </div>
            ) : null}
            {data.student_notes ? (
              <div className="sm:col-span-2">
                <p className="text-xs text-muted-foreground">Notes for students</p>
                <p className="whitespace-pre-wrap break-words">{data.student_notes}</p>
              </div>
            ) : null}
          </CardBody>
        </Card>
      )}

      {permissions.has("attendance.read") ? (
        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <ClipboardCheck className="size-4 text-muted-foreground" aria-hidden /> Register
              </span>
            }
            description="Confirmed students on this batch. Saving records the whole class at once."
          />
          <Register session={data} />
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this session?"
        description="Its register goes with it."
        confirmLabel="Delete session"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
