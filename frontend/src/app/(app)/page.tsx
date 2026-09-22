"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Boxes,
  CalendarClock,
  ClipboardCheck,
  ClipboardList,
  GraduationCap,
  Mail,
  Megaphone,
  Percent,
  Users,
} from "lucide-react";
import { api, type ApiError } from "@/lib/api/client";
import type { AssignmentBrief, DashboardResponse, SessionBrief } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Badge, Card, CardHeader, SectionHeader } from "@/components/ui/primitives";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { JoinClassButton } from "@/components/domain/sessions/join-class-button";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";

function percent(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `${value.toFixed(1)}`;
}

function UpcomingSessions({ sessions }: { sessions: SessionBrief[] }) {
  const timeZone = useDisplayTimeZone();
  if (sessions.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-xs text-subtle-foreground">
        No classes scheduled.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border-subtle">
      {sessions.map((session) => (
        <li
          key={session.public_id}
          className="flex items-center justify-between gap-3 px-4 py-2 transition-colors duration-200 ease-out hover:bg-surface-muted/60"
        >
          <div className="min-w-0">
            <Link
              href={`/sessions?session=${session.public_id}`}
              className="block truncate text-[13px] font-medium decoration-border-strong underline-offset-2 hover:underline"
            >
              {session.course_title}
            </Link>
            <p className="truncate text-2xs text-subtle-foreground">
              {session.batch_code}
              {session.classroom ? ` · ${session.classroom}` : ""}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-2xs font-medium tabular-nums text-muted-foreground">
              {formatDateTime(session.starts_at, { timeZone })}
            </p>
            {/* `SessionBrief` deliberately carries no meeting link: this panel
                is drawn for students too, and the join window is enforced by
                the API rather than by what a dashboard chooses to render. */}
            <JoinClassButton
              sessionId={session.public_id}
              canJoinNow={session.can_join_now ?? false}
              opensAt={session.join_opens_at}
              closesAt={session.join_closes_at}
              size="xs"
              className="justify-end"
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Deadlines({ items }: { items: AssignmentBrief[] }) {
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  if (items.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-xs text-subtle-foreground">Nothing due.</p>
    );
  }
  return (
    <ul className="divide-y divide-border-subtle">
      {items.map((item) => (
        <li
          key={item.public_id}
          className="flex items-center justify-between gap-3 px-4 py-2 transition-colors duration-200 ease-out hover:bg-surface-muted/60"
        >
          <div className="min-w-0">
            <Link
              href={`/assignments/${item.public_id}`}
              className="block truncate text-[13px] font-medium decoration-border-strong underline-offset-2 hover:underline"
            >
              {item.title}
            </Link>
            <p className="truncate text-2xs text-subtle-foreground">{item.course_title}</p>
          </div>
          <div className="shrink-0 text-right">
            {item.is_overdue ? <Badge tone="danger">Overdue</Badge> : null}
            <p className="mt-0.5 text-2xs tabular-nums text-subtle-foreground" title={formatDateTime(item.due_date, { timeZone })}>
              {formatRelative(item.due_date, locale)}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function DashboardPage() {
  const { user } = useSession();
  const timeZone = useDisplayTimeZone();

  const { data, isPending, error, refetch } = useQuery<DashboardResponse, ApiError>({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardResponse>("/dashboard"),
  });

  const firstName = user?.first_name || user?.username || "there";

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome back, ${firstName}`}
        description={
          data
            ? `Generated ${formatDateTime(data.generated_at, { timeZone })}. Panels are chosen by what your roles let you see.`
            : "Your dashboard."
        }
      />

      {isPending ? (
        <LoadingState rows={4} label="Loading your dashboard" />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : !data ? null : (
        <div className="space-y-7">
          <StatGrid>
            <Stat
              label="Unread messages"
              value={data.personal.unread_messages}
              icon={Mail}
              tone={data.personal.unread_messages ? "warning" : "default"}
            />
            <Stat
              label="Unread notifications"
              value={data.personal.unread_notifications}
              icon={ClipboardList}
            />
            <Stat label="Live announcements" value={data.personal.live_announcements} icon={Megaphone} />
            <Stat
              label="Your timezone"
              value={timeZone}
              icon={CalendarClock}
              hint="Stored in UTC, shown in your timezone."
            />
          </StatGrid>

          {data.student ? (
            <section className="space-y-3.5">
              <SectionHeader title="Your studies" />
              <StatGrid>
                <Stat label="Enrolled batches" value={data.student.enrolled_batches} icon={GraduationCap} />
                <Stat label="Active courses" value={data.student.active_courses} icon={BookOpen} />
                <Stat
                  label="Attendance"
                  value={percent(data.student.attendance_rate)}
                  suffix="%"
                  icon={Percent}
                  tone={
                    data.student.attendance_rate !== null &&
                    data.student.attendance_rate !== undefined &&
                    data.student.attendance_rate < 75
                      ? "warning"
                      : "default"
                  }
                />
                <Stat
                  label="Overdue assignments"
                  value={data.student.assignments_overdue}
                  icon={ClipboardList}
                  tone={data.student.assignments_overdue ? "danger" : "default"}
                  hint={
                    data.student.assignments_outstanding
                      ? `${data.student.assignments_outstanding} outstanding in total`
                      : undefined
                  }
                />
              </StatGrid>
              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader title="Next sessions" />
                  <UpcomingSessions sessions={data.student.upcoming_sessions ?? []} />
                </Card>
                <Card>
                  <CardHeader title="Next deadlines" />
                  <Deadlines items={data.student.next_deadlines ?? []} />
                </Card>
              </div>
            </section>
          ) : null}

          {data.teaching ? (
            <section className="space-y-3.5">
              <SectionHeader title="Your teaching" />
              <StatGrid>
                <Stat label="Batches" value={data.teaching.batches_taught} icon={GraduationCap} />
                <Stat label="Students" value={data.teaching.students_taught} icon={Users} />
                <Stat
                  label="Awaiting grading"
                  value={data.teaching.submissions_awaiting_grading}
                  icon={ClipboardCheck}
                  tone={data.teaching.submissions_awaiting_grading ? "warning" : "default"}
                  hint={
                    data.teaching.quiz_attempts_awaiting_grading
                      ? `${data.teaching.quiz_attempts_awaiting_grading} quiz attempts too`
                      : undefined
                  }
                />
                <Stat
                  label="Sessions next 7 days"
                  value={data.teaching.sessions_next_7_days}
                  icon={CalendarClock}
                />
              </StatGrid>
              <Card>
                <CardHeader title="Your next sessions" />
                <UpcomingSessions sessions={data.teaching.upcoming_sessions ?? []} />
              </Card>
            </section>
          ) : null}

          {data.care ? (
            <section className="space-y-3.5">
              <SectionHeader title="People in your care" />
              <StatGrid>
                <Stat label="People" value={data.care.people} icon={Users} />
                <Stat
                  label="Attendance"
                  value={percent(data.care.attendance_rate)}
                  suffix="%"
                  icon={Percent}
                />
                <Stat
                  label="Overdue assignments"
                  value={data.care.assignments_overdue}
                  icon={ClipboardList}
                  tone={data.care.assignments_overdue ? "danger" : "default"}
                />
              </StatGrid>
              <Card>
                <CardHeader title="Their next sessions" />
                <UpcomingSessions sessions={data.care.upcoming_sessions ?? []} />
              </Card>
            </section>
          ) : null}

          {data.institution ? (
            <section className="space-y-3.5">
              <SectionHeader title="Institution" />
              <StatGrid>
                <Stat
                  label="Active users"
                  value={data.institution.active_users}
                  icon={Users}
                  hint={
                    data.institution.suspended_users
                      ? `${data.institution.suspended_users} suspended`
                      : undefined
                  }
                />
                <Stat
                  label="Published courses"
                  value={data.institution.courses_published}
                  icon={BookOpen}
                  hint={
                    data.institution.courses_draft
                      ? `${data.institution.courses_draft} still in draft`
                      : undefined
                  }
                />
                <Stat label="Active batches" value={data.institution.active_batches} icon={Boxes} />
                <Stat
                  label="Attendance (30d)"
                  value={percent(data.institution.attendance_rate_30d)}
                  suffix="%"
                  icon={Percent}
                />
              </StatGrid>
              <StatGrid>
                <Stat
                  label="Confirmed enrollments"
                  value={data.institution.enrollments_confirmed}
                  icon={GraduationCap}
                />
                <Stat
                  label="Submissions awaiting grading"
                  value={data.institution.submissions_awaiting_grading}
                  icon={ClipboardCheck}
                  tone={data.institution.submissions_awaiting_grading ? "warning" : "default"}
                />
              </StatGrid>
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
