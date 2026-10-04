"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash, Clock, ShieldQuestion } from "lucide-react";
import { api } from "@/lib/api/client";
import type { AttendanceResponse, AttendanceSummaryResponse, PageAttendanceResponse } from "@/lib/api/types";
import { AttendanceStatusValues } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { Card, CardHeader } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Field, Input} from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { Stat, StatGrid } from "@/components/ui/stat";
import { StatusBadge } from "@/components/domain/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

/** The records already taken (read-only): for students, guardians and managers, and as a secondary view for staff. */
export function AttendanceRecords() {
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [status, setStatus] = useState("");
  const [batchId, setBatchId] = useState("");
  const [studentId, setStudentId] = useState("");

  const records = useQuery({
    queryKey: ["attendance", "list", status, batchId, studentId, limit, offset],
    queryFn: () =>
      api.get<PageAttendanceResponse>("/attendance", {
        query: {
          status: status || undefined,
          batch_id: batchId || undefined,
          student_id: studentId || undefined,
          limit,
          offset,
        },
      }),
  });

  // The summary endpoint needs at least one of the two scopes; asking for
  // "everyone, everywhere" is not a question it answers.
  const summaryEnabled = Boolean(batchId || studentId);
  const summary = useQuery({
    queryKey: ["attendance", "summary", batchId, studentId],
    queryFn: () =>
      api.get<AttendanceSummaryResponse>("/attendance/summary", {
        query: { batch_id: batchId || undefined, student_id: studentId || undefined },
      }),
    enabled: summaryEnabled,
  });

  const columns: Column<AttendanceResponse>[] = [
    {
      key: "session",
      header: "Session",
      cell: (row) => (
        <Link href={`/sessions/${row.session_id}`} className="font-medium hover:underline">
          {formatDateTime(row.session_start_time, { timeZone })}
        </Link>
      ),
    },
    {
      key: "batch",
      header: "Batch",
      secondary: true,
      cell: (row) => <span className="font-mono text-xs">{row.batch_code ?? "—"}</span>,
    },
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <Link href={`/users/${row.student_id}`} className="hover:underline">
          {row.student_username ?? row.student_id}
        </Link>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (row) => <StatusBadge value={row.status} kind="attendance" />,
    },
    {
      key: "remarks",
      header: "Remarks",
      secondary: true,
      cell: (row) => (
        <span className="block max-w-64 truncate text-xs text-muted-foreground">
          {row.remarks ?? "—"}
        </span>
      ),
    },
    {
      key: "recorded",
      header: "Recorded",
      secondary: true,
      cell: (row) => (
        <span className="text-xs text-muted-foreground">
          {formatDateTime(row.recorded_at, { timeZone })}
          {row.recorded_by_username ? ` by ${row.recorded_by_username}` : ""}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="Status" className="w-40">
            {({ id }) => (
              <Select
                id={id}
                value={(status) || null}
                onValueChange={(next) => {
                  setStatus((next ?? ""));
                  setPage({ limit, offset: 0 });
                }}
               placeholder="Any status" clearable options={optionsFromValues(AttendanceStatusValues, humanise)} />
            )}
          </Field>
          <Field label="Batch id" className="w-64">
            {({ id }) => (
              <Input
                id={id}
                value={batchId}
                placeholder="Scope to one batch"
                onChange={(event) => {
                  setBatchId(event.target.value.trim());
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          <Field label="Student id" className="w-64">
            {({ id }) => (
              <Input
                id={id}
                value={studentId}
                placeholder="Scope to one student"
                onChange={(event) => {
                  setStudentId(event.target.value.trim());
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
        </div>
      </Card>

      {summaryEnabled ? (
        <Card>
          <CardHeader
            title="Summary for this scope"
            description="The rate is (present + late) / (total - excused): an excused absence leaves the denominator rather than counting against the student."
          />
          <div className="p-4">
            <StatGrid>
              <Stat
                label="Present"
                value={summary.data?.present}
                icon={CheckCircle2}
                loading={summary.isPending}
                tone="success"
              />
              <Stat label="Late" value={summary.data?.late} icon={Clock} loading={summary.isPending} tone="warning" />
              <Stat
                label="Absent"
                value={summary.data?.absent}
                icon={CircleSlash}
                loading={summary.isPending}
                tone="danger"
              />
              <Stat
                label="Attendance rate"
                value={
                  summary.data?.attendance_rate === null || summary.data?.attendance_rate === undefined
                    ? null
                    : summary.data.attendance_rate.toFixed(1)
                }
                suffix="%"
                icon={ShieldQuestion}
                loading={summary.isPending}
                hint={
                  summary.data?.excused
                    ? `${summary.data.excused} excused, excluded from the rate`
                    : undefined
                }
              />
            </StatGrid>
          </div>
        </Card>
      ) : null}

      <Card>
        {records.isPending ? (
          <LoadingState />
        ) : records.error ? (
          <ErrorState error={records.error} onRetry={() => void records.refetch()} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={records.data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No attendance records match these filters."
            />
            <Pagination
              total={records.data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="records"
            />
          </>
        )}
      </Card>
    </div>
  );
}
