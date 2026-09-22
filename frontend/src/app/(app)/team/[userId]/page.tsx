"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { TeamAssignment, TeamEnrollment, TeamMemberDetail } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Column, DataTable } from "@/components/ui/data-table";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { AttendanceBadge } from "@/components/domain/attendance-badge";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

const ASSIGNMENT_TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "info"> = {
  GRADED: "success",
  SUBMITTED: "info",
  PENDING: "neutral",
  OVERDUE: "danger",
};
const ATTENDANCE_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  PRESENT: "success",
  LATE: "warning",
  ABSENT: "danger",
  EXCUSED: "neutral",
};

export default function TeamMemberPage({ params }: { params: Promise<{ userId: string }> }) {
  const { userId } = use(params);
  const timeZone = useDisplayTimeZone();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["team", userId],
    queryFn: () => api.get<TeamMemberDetail>(`/team/${segment(userId)}`),
  });

  if (isPending) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const enrollmentColumns: Column<TeamEnrollment>[] = [
    {
      key: "course",
      header: "Course",
      cell: (e) => (
        <div className="min-w-0">
          <p className="font-medium">{e.course_title ?? e.batch_code}</p>
          <p className="font-mono text-xs text-muted-foreground">{e.batch_code}</p>
        </div>
      ),
    },
    { key: "status", header: "Status", cell: (e) => <Badge tone={e.status === "COMPLETED" ? "success" : "info"}>{humanise(e.status)}</Badge> },
    {
      key: "attendance",
      header: "Attendance",
      align: "right",
      cell: (e) => (
        <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
          <AttendanceBadge rate={e.attendance_rate} />
          <span className="text-xs text-muted-foreground tabular-nums">
            {e.attendance.present}P · {e.attendance.late}L · {e.attendance.absent}A · {e.attendance.excused}E
          </span>
        </span>
      ),
    },
    { key: "score", header: "Score", align: "right", secondary: true, cell: (e) => (e.score_percent == null ? "—" : `${e.score_percent}%`) },
    { key: "grade", header: "Grade", align: "right", secondary: true, cell: (e) => (e.overall_grade ? `${e.overall_grade}${e.gpa != null ? ` (${e.gpa.toFixed(2)})` : ""}` : "—") },
  ];

  const assignmentColumns: Column<TeamAssignment>[] = [
    {
      key: "title",
      header: "Assignment",
      cell: (a) => (
        <div className="min-w-0">
          <p className="font-medium">{a.title}</p>
          <p className="text-xs text-muted-foreground">{a.course_title}</p>
        </div>
      ),
    },
    { key: "due", header: "Due", secondary: true, cell: (a) => formatDateTime(a.due_date, { timeZone }) },
    { key: "status", header: "Status", cell: (a) => <Badge tone={ASSIGNMENT_TONE[a.status] ?? "neutral"}>{humanise(a.status)}</Badge> },
    { key: "grade", header: "Grade", align: "right", cell: (a) => (a.grade == null ? "—" : `${a.grade}${a.max_score ? ` / ${a.max_score}` : ""}`) },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title={data.full_name}
        description={[data.relationship, data.organization, data.department, data.employee_code].filter(Boolean).join(" · ") || undefined}
        breadcrumbs={[{ label: "My team", href: "/team" }, { label: data.full_name }]}
      />

      {data.needs_attention ? (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-warning/50 bg-warning/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <ul className="space-y-0.5">
            {(data.attention_reasons ?? []).map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <StatGrid>
        <Stat label="Active courses" value={data.enrollments_active} hint={data.enrollments_completed ? `${data.enrollments_completed} completed` : undefined} />
        <Stat label="Attendance" value={data.attendance_rate == null ? null : `${data.attendance_rate}%`} hint={`${data.sessions_recorded} sessions recorded`} tone={data.attendance_rate != null && data.attendance_rate < 75 ? "danger" : "default"} />
        <Stat label="Assignments" value={`${data.assignments_submitted}/${data.assignments_total}`} hint={data.assignments_overdue ? `${data.assignments_overdue} overdue` : "none overdue"} tone={data.assignments_overdue ? "danger" : "default"} />
        <Stat label="Average score" value={data.average_score == null ? null : `${data.average_score}%`} hint={data.gpa != null ? `GPA ${data.gpa.toFixed(2)}` : undefined} />
      </StatGrid>

      <Card>
        <CardHeader title="Courses" description={data.next_session ? `Next session: ${formatDateTime(data.next_session.start, { timeZone })} (${data.next_session.batch_code})` : "No upcoming sessions."} />
        <DataTable columns={enrollmentColumns} rows={data.enrollments ?? []} rowKey={(e) => e.batch_id} emptyMessage="Not enrolled on any course." />
      </Card>

      <Card>
        <CardHeader title="Assignments" description="On the courses they are enrolled on." />
        <DataTable columns={assignmentColumns} rows={data.assignments ?? []} rowKey={(a) => `${a.title}-${a.due_date}`} emptyMessage="No assignments." />
      </Card>

      <Card>
        <CardHeader title="Recent attendance" description={`Times are shown in ${timeZone}.`} />
        <CardBody>
          {(data.recent_attendance ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No attendance has been recorded yet.</p>
          ) : (
            <ul className="divide-y divide-border-subtle">
              {(data.recent_attendance ?? []).map((r) => (
                <li key={`${r.session_start}-${r.batch_code}`} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span>
                    {formatDateTime(r.session_start, { timeZone })} <span className="text-muted-foreground">· {r.course_title ?? r.batch_code}</span>
                  </span>
                  <Badge tone={ATTENDANCE_TONE[r.status] ?? "neutral"}>{humanise(r.status)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
