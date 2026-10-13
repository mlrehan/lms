"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PageSessionSummary, SessionSummary } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Badge, Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Field, Input } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, fromLocalInputValue } from "@/lib/format/datetime";
import { JoinClassButton } from "@/components/domain/sessions/join-class-button";
import { humanise } from "@/lib/utils";
import { BatchPicker } from "@/components/domain/entity-pickers";
import { UserPicker, useCanPickUsers } from "@/components/domain/user-picker";

export default function TimetablePage() {
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(25);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const canPickUsers = useCanPickUsers();
  const [batchId, setBatchId] = useState<string | null>(null);
  const [tutorId, setTutorId] = useState<string | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["sessions", "list", from, to, batchId, tutorId, studentId, limit, offset],
    queryFn: () =>
      api.get<PageSessionSummary>("/sessions", {
        query: {
          // The filters are instants, so the wall-clock values typed here are
          // resolved against the display timezone before being sent.
          starts_after: from ? fromLocalInputValue(`${from}T00:00`, timeZone) : undefined,
          starts_before: to ? fromLocalInputValue(`${to}T23:59`, timeZone) : undefined,
          batch_id: batchId || undefined,
          tutor_id: tutorId || undefined,
          student_id: studentId || undefined,
          limit,
          offset,
        },
      }),
  });

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
      key: "duration",
      header: "Minutes",
      align: "right",
      secondary: true,
      cell: (session) => <span className="tabular-nums">{session.duration_minutes ?? "—"}</span>,
    },
    {
      key: "join",
      header: "",
      align: "right",
      // The link is not in this payload; the button asks the API for it.
      cell: (session) => (
        <JoinClassButton
          sessionId={session.public_id}
          canJoinNow={session.can_join_now ?? false}
          opensAt={session.join_opens_at}
          closesAt={session.join_closes_at}
          size="xs"
          className="justify-end"
        />
      ),
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
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Timetable"
        description={`Sessions you can see, shown in ${timeZone}.`}
      />

      <p className="flex items-start gap-2 rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
        <Info className="mt-px size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
        {/*
          Written from the reader's side of the screen. The previous copy named the
          endpoint and cited a file in the repository, which tells somebody running a
          timetable nothing they can act on -- what they need to know is that the
          course and tutor are one click away.
        */}
        <span>This list shows times only. Open a session to see its course, batch and tutor.</span>
      </p>

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="From" className="w-44">
            {({ id }) => (
              <Input
                id={id}
                type="date"
                value={from}
                onChange={(event) => {
                  setFrom(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          <Field label="Batch" className="w-56">
            {({ id }) => (
              <BatchPicker
                id={id}
                value={batchId}
                placeholder="Any batch"
                onValueChange={(next) => {
                  setBatchId(next);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          {/* Both are for narrowing a timetable that already spans other
              people. A student's does not, and they cannot look anybody up,
              so the fields -- and their labels -- are absent rather than
              present and unusable. */}
          {canPickUsers ? (
            <>
              <Field label="Tutor" className="w-56">
                {({ id }) => (
                  <UserPicker
                    id={id}
                    role="TUTOR"
                    value={tutorId}
                    placeholder="Any tutor"
                    onChange={(next) => {
                      setTutorId(next);
                      setPage({ limit, offset: 0 });
                    }}
                  />
                )}
              </Field>
              <Field label="Student" className="w-56">
                {({ id }) => (
                  <UserPicker
                    id={id}
                    role="STUDENT"
                    value={studentId}
                    placeholder="Any student"
                    onChange={(next) => {
                      setStudentId(next);
                      setPage({ limit, offset: 0 });
                    }}
                  />
                )}
              </Field>
            </>
          ) : null}
          <Field label="To" className="w-44">
            {({ id }) => (
              <Input
                id={id}
                type="date"
                value={to}
                onChange={(event) => {
                  setTo(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          {/*
            "Only sessions I teach" used to live here. It was never offered
            to anybody it helped: a student teaches nothing, an administrator
            teaches nothing, and a tutor's timetable is already scoped to the
            batches they take sessions in. The server-side scope
            (`ScopeResolver.visible_session_ids`) is what enforces that, and
            it does so whether or not a switch is on -- so removing the
            control narrows nothing and clears a row of the filter bar.
          */}
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columnsKey="sessions"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(session) => session.public_id}
              emptyMessage="No sessions in this range."
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
      </Card>
    </div>
  );
}
