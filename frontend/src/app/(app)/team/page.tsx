"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api } from "@/lib/api/client";
import type { TeamMemberSummary, TeamOverview } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Badge, Card } from "@/components/ui/primitives";
import { AttendanceBadge } from "@/components/domain/attendance-badge";
import { Column, DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/form";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

/**
 * The people in the caller's care: a corporate manager's employees, or a guardian's wards.
 *
 * The server decides who appears (the caller's own scope; there is nothing here to tamper with) and it never
 * sends an email address or phone number, so this page shows how people are doing, not how to reach them.
 * The ones who need a look come first, with the reason beside them.
 */
export default function TeamPage() {
  const timeZone = useDisplayTimeZone();
  const [term, setTerm] = useState("");
  const [onlyAttention, setOnlyAttention] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["team"],
    queryFn: () => api.get<TeamOverview>("/team"),
  });

  const rows = useMemo(() => {
    const needle = term.trim().toLowerCase();
    return (data?.items ?? []).filter(
      (m) => (!onlyAttention || m.needs_attention) && (!needle || m.full_name.toLowerCase().includes(needle) || (m.organization ?? "").toLowerCase().includes(needle)),
    );
  }, [data, term, onlyAttention]);

  const columns: Column<TeamMemberSummary>[] = [
    {
      key: "name",
      header: "Person",
      cell: (m) => (
        <div className="min-w-0">
          <Link href={`/team/${m.public_id}`} className="font-medium hover:underline">
            {m.full_name}
          </Link>
          <p className="truncate text-xs text-muted-foreground">
            {[m.relationship, m.department, m.employee_code].filter(Boolean).join(" · ") || m.organization || "—"}
          </p>
        </div>
      ),
    },
    {
      key: "courses",
      header: "Learning",
      secondary: true,
      cell: (m) =>
        (m.enrollments_active ?? 0) > 0 ? (
          <div className="min-w-0 max-w-64">
            <p className="truncate text-sm">{(m.courses ?? []).join(", ")}</p>
            <p className="text-xs text-muted-foreground">
              {m.enrollments_active} active{m.enrollments_completed ? ` · ${m.enrollments_completed} completed` : ""}
            </p>
          </div>
        ) : (
          <span className="text-muted-foreground">{m.enrollments_completed ? `${m.enrollments_completed} completed` : "Not enrolled"}</span>
        ),
    },
    { key: "attendance", header: "Attendance", align: "right", cell: (m) => <AttendanceBadge rate={m.attendance_rate} /> },
    {
      key: "work",
      header: "Assignments",
      align: "right",
      secondary: true,
      cell: (m) =>
        m.assignments_total === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className="tabular-nums">
            {m.assignments_submitted}/{m.assignments_total}
            {(m.assignments_overdue ?? 0) > 0 ? <Badge tone="danger" className="ml-1.5">{m.assignments_overdue} overdue</Badge> : null}
          </span>
        ),
    },
    {
      key: "score",
      header: "Average score",
      align: "right",
      secondary: true,
      cell: (m) => (m.average_score === null || m.average_score === undefined ? <span className="text-muted-foreground">—</span> : <span className="tabular-nums">{m.average_score}%</span>),
    },
    {
      key: "next",
      header: "Next session",
      secondary: true,
      cell: (m) => (m.next_session ? <span className="text-xs">{formatDateTime(m.next_session.start, { timeZone })}</span> : <span className="text-muted-foreground">—</span>),
    },
    {
      key: "attention",
      header: "",
      cell: (m) =>
        m.needs_attention ? (
          <Badge tone="warning" title={(m.attention_reasons ?? []).join("\n")}>
            <AlertTriangle className="size-3" aria-hidden /> Needs a look
          </Badge>
        ) : null,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="My team"
        description="How the people in your care are getting on: attendance, assignments, scores and what is coming up. Names only; contact details are never shown here."
      />

      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <StatGrid>
            <Stat label="People" value={data.people} />
            <Stat label="Need a look" value={data.needing_attention} tone={data.needing_attention > 0 ? "warning" : "default"} />
            <Stat label="Average attendance" value={data.average_attendance_rate === null || data.average_attendance_rate === undefined ? null : `${data.average_attendance_rate}%`} />
            <Stat label="Assignments overdue" value={data.assignments_overdue ?? 0} tone={(data.assignments_overdue ?? 0) > 0 ? "danger" : "default"} />
          </StatGrid>

          <Card>
            <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle p-3">
              <Input className="max-w-xs" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Search by name" aria-label="Search people" />
              <label className={cn("flex cursor-pointer items-center gap-2 text-sm", onlyAttention && "font-medium")}>
                <input type="checkbox" checked={onlyAttention} onChange={(event) => setOnlyAttention(event.target.checked)} className="size-4 accent-[var(--primary)]" />
                Only those who need a look
              </label>
            </div>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(m) => m.public_id}
              emptyMessage={data.people === 0 ? "Nobody is in your care yet. An administrator adds people to your organisation." : "Nobody matches."}
            />
          </Card>
        </>
      )}
    </div>
  );
}
