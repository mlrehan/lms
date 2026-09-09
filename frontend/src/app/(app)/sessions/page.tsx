"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PageSessionSummary, SessionSummary } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Badge, Card, Switch } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Field, Input } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, fromLocalInputValue } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

export default function TimetablePage() {
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(25);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [mineOnly, setMineOnly] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["sessions", "list", from, to, mineOnly, limit, offset],
    queryFn: () =>
      api.get<PageSessionSummary>("/sessions", {
        query: {
          // The filters are instants, so the wall-clock values typed here are
          // resolved against the display timezone before being sent.
          starts_after: from ? fromLocalInputValue(`${from}T00:00`, timeZone) : undefined,
          starts_before: to ? fromLocalInputValue(`${to}T23:59`, timeZone) : undefined,
          mine_only: mineOnly || undefined,
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

      <p className="flex items-start gap-2 rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          <code className="font-mono text-xs">GET /sessions</code> returns a summary that does not
          include the batch, course or tutor, so this list cannot show them. Opening a session shows
          all three. Recorded in <code className="font-mono text-xs">docs/BACKEND-GAPS.md</code>.
        </span>
      </p>

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border p-3">
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
          <label className="flex items-center gap-2 pb-2 text-sm">
            <Switch
              checked={mineOnly}
              onCheckedChange={(checked) => {
                setMineOnly(checked);
                setPage({ limit, offset: 0 });
              }}
            />
            Only sessions I teach
          </label>
        </div>

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
