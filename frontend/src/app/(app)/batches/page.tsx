"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, CalendarPlus, ClipboardCheck, ExternalLink, Layers } from "lucide-react";
import { api } from "@/lib/api/client";
import type { BatchSummary, PageBatchSummary } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination, type SortState } from "@/components/ui/data-table";
import { TableToolbar } from "@/components/ui/table-toolbar";
import { NativeSelect } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { BooleanBadge } from "@/components/domain/status-badge";
import { LaitSyncControls } from "@/components/domain/lait-sync";
import { NewBatchDialog } from "@/components/domain/new-batch-dialog";
import { RecreateSessionsDialog } from "@/components/domain/recreate-sessions-dialog";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatCalendarDate, formatDateTime } from "@/lib/format/datetime";


// FullCalendar measures the DOM, so it is drawn on the client only.
const BatchCalendar = dynamic(() => import("@/components/domain/batch-calendar"), {
  ssr: false,
  loading: () => <LoadingState />,
});

/** "Classroom Training" -> "Classroom", so the column stays narrow. */
function shortMethod(method: string | null | undefined): string {
  return (method ?? "").replace(/\s*training\s*$/i, "").trim();
}

function duration(minutes: number | null | undefined): string {
  if (!minutes) return "";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h ? `${h}h` : ""}${m ? `${m}m` : ""}`;
}

export default function BatchesPage() {
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  // Ten to a page by default: a batch row is dense, and a long page hides the calendar beneath it.
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(10);
  const [active, setActive] = useState("");
  const [sort, setSort] = useState<SortState | null>(null);
  const [selected, setSelected] = useState<BatchSummary | null>(null);
  const [recreate, setRecreate] = useState<BatchSummary | null>(null);

  const { data, isPending, isFetching, error, refetch } = useQuery({
    queryKey: ["batches", "list", active, debouncedSearch, sort?.key, sort?.dir, limit, offset],
    queryFn: () =>
      api.get<PageBatchSummary>("/batches", {
        query: {
          is_active: active === "" ? undefined : active === "true",
          q: debouncedSearch || undefined,
          sort: sort?.key,
          dir: sort?.dir,
          limit,
          offset,
        },
      }),
    placeholderData: (previous) => previous, // keep the rows on screen while the next page loads
  });

  const canRecreate = permissions.has("session.create") && permissions.has("session.delete");

  const columns: Column<BatchSummary>[] = [
    {
      key: "batch",
      header: "Batch",
      sortable: true,
      sortKey: "batch_code",
      truncate: true,
      cell: (batch) => (
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] font-semibold leading-tight">{batch.batch_code}</p>
          <p className="truncate text-xs text-muted-foreground">{batch.course_title ?? "—"}</p>
        </div>
      ),
      title: (batch) => `${batch.batch_code} · ${batch.course_title ?? ""}`,
    },
    {
      key: "tutor",
      header: "Tutor",
      hideBelow: "lg",
      truncate: true,
      cell: (batch) => batch.tutor_name ?? <span className="text-muted-foreground">—</span>,
      title: (batch) => batch.tutor_name ?? undefined,
    },
    {
      key: "schedule",
      header: "Schedule",
      hideBelow: "xl",
      truncate: true,
      cell: (batch) =>
        batch.training_days ? (
          <span>
            {batch.training_days}
            {batch.class_duration_minutes ? <span className="text-muted-foreground"> · {duration(batch.class_duration_minutes)}</span> : null}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      title: (batch) => batch.training_days ?? undefined,
    },
    {
      key: "dates",
      header: "Dates",
      sortable: true,
      sortKey: "start_date",
      hideBelow: "md",
      className: "whitespace-nowrap",
      cell: (batch) => (
        <span className="tabular-nums">
          {formatCalendarDate(batch.start_date)}
          {batch.end_date && batch.end_date !== batch.start_date ? <span className="text-muted-foreground"> → {formatCalendarDate(batch.end_date)}</span> : null}
        </span>
      ),
    },
    {
      key: "method",
      header: "Method",
      sortable: true,
      hideBelow: "lg",
      cell: (batch) => (batch.training_method ? <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{shortMethod(batch.training_method)}</span> : <span className="text-muted-foreground">—</span>),
    },
    {
      key: "sessions",
      header: "Sessions",
      align: "right",
      hideBelow: "md",
      cell: (batch) => (
        <div className="leading-tight">
          <span className="tabular-nums">{batch.session_count ?? 0}</span>
          {batch.next_session_start ? <p className="whitespace-nowrap text-[11px] text-muted-foreground">next {formatDateTime(batch.next_session_start, { timeZone })}</p> : null}
        </div>
      ),
    },
    {
      key: "enrolled",
      header: "Enrolled",
      sortable: true,
      align: "right",
      cell: (batch) => (
        <span className="tabular-nums">
          {batch.total_enrollments ?? 0}
          {batch.capacity ? <span className="text-muted-foreground"> / {batch.capacity}</span> : null}
        </span>
      ),
    },
    {
      key: "fee",
      header: "Fee",
      sortable: true,
      align: "right",
      hideBelow: "xl",
      cell: (batch) => (batch.batch_fee == null ? <span className="text-muted-foreground">—</span> : `£${batch.batch_fee.toLocaleString("en-GB")}`),
    },
    {
      key: "state",
      header: "State",
      sortable: true,
      cell: (batch) => <BooleanBadge value={batch.is_active} trueLabel="Active" falseLabel="Closed" />,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Batches"
        description="The working space for every cohort: open one for its students, sessions, timetable and attendance."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {permissions.has("batch.create") ? (
              // The new batch is selected, so the calendar below is ready to schedule its first session.
              <NewBatchDialog onCreated={(batch) => setSelected(batch)} />
            ) : null}
            <LaitSyncControls canSync={permissions.has("course.sync")} runsPath="/courses/sync" label="Sync courses & batches" invalidate={[["courses"], ["batches"]]} />
          </div>
        }
      />

      <Card className="overflow-hidden">
        <TableToolbar
          search={search}
          onSearch={(value) => {
            setSearch(value);
          }}
          searchPlaceholder="Search code, course, days or method"
          filters={
            <NativeSelect
              className="h-8 w-auto text-[13px]"
              aria-label="Filter by state"
              value={active}
              onChange={(event) => {
                setActive(event.target.value);
                setPage({ limit, offset: 0 });
              }}
            >
              <option value="">Any state</option>
              <option value="true">Active only</option>
              <option value="false">Closed only</option>
            </NativeSelect>
          }
          summary={isFetching && !isPending ? "Updating…" : undefined}
        />

        {error && !data ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              caption="Batches"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(batch) => batch.public_id}
              loading={isPending}
              skeletonRows={limit > 10 ? 10 : limit}
              stickyHeader
              maxHeight="36rem"
              sort={sort}
              onSortChange={(next) => {
                setSort(next);
                setPage({ limit, offset: 0 });
              }}
              selectedKey={selected?.public_id ?? null}
              onRowClick={(batch) => router.push(`/batches/${batch.public_id}`)}
              rowActions={(batch) => [
                { label: "Open batch workspace", icon: <ExternalLink className="size-4" />, onSelect: () => router.push(`/batches/${batch.public_id}`) },
                { label: "Show in the calendar below", icon: <CalendarDays className="size-4" />, onSelect: () => setSelected((current) => (current?.public_id === batch.public_id ? null : batch)) },
                ...(permissions.has("attendance.create")
                  ? [{ label: "Take attendance", icon: <ClipboardCheck className="size-4" />, onSelect: () => router.push(`/attendance?batch=${batch.public_id}`) }]
                  : []),
                ...(canRecreate ? [{ label: "Re-create sessions…", icon: <CalendarPlus className="size-4" />, separatorBefore: true, onSelect: () => setRecreate(batch) }] : []),
              ]}
              emptyState={
                <EmptyState
                  icon={<Layers className="size-5" />}
                  title={debouncedSearch || active ? "No batches match" : "No batches yet"}
                  description={debouncedSearch || active ? "Try a different search, or clear the filters." : "Create one from a course, or sync them from LAIT."}
                />
              }
            />
            <Pagination total={data?.total ?? 0} limit={limit} offset={offset} onChange={setPage} label="batches" />
          </>
        )}
      </Card>

      <BatchCalendar batches={data?.items ?? []} selected={selected} onClearSelection={() => setSelected(null)} />

      {recreate ? <RecreateSessionsDialog batchId={recreate.public_id} batchCode={recreate.batch_code} onClose={() => setRecreate(null)} /> : null}
    </div>
  );
}

