"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { BatchSummary, PageBatchSummary } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/form";
import { BooleanBadge } from "@/components/domain/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { formatCalendarDate } from "@/lib/format/datetime";

export default function BatchesPage() {
  const { limit, offset, setPage } = useListState();
  const [active, setActive] = useState("");

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["batches", "list", active, limit, offset],
    queryFn: () =>
      api.get<PageBatchSummary>("/batches", {
        query: { is_active: active === "" ? undefined : active === "true", limit, offset },
      }),
  });

  const columns: Column<BatchSummary>[] = [
    {
      key: "code",
      header: "Batch",
      cell: (batch) => (
        <Link
          href={`/batches/${batch.public_id}`}
          className="font-mono text-sm font-medium hover:underline"
        >
          {batch.batch_code}
        </Link>
      ),
    },
    {
      key: "active",
      header: "State",
      cell: (batch) => <BooleanBadge value={batch.is_active} trueLabel="Active" falseLabel="Closed" />,
    },
    {
      key: "start",
      header: "Starts",
      secondary: true,
      cell: (batch) => formatCalendarDate(batch.start_date),
    },
    {
      key: "end",
      header: "Ends",
      secondary: true,
      cell: (batch) => formatCalendarDate(batch.end_date),
    },
    {
      key: "capacity",
      header: "Capacity",
      align: "right",
      cell: (batch) => <span className="tabular-nums">{batch.capacity ?? "Unlimited"}</span>,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Batches"
        description="Every cohort you can see, across all courses. A batch carries the schedule, the register and the grade book."
      />

      {/*
        The API's batch list returns a summary that does not name the parent
        course, so this table cannot show one. Opening a batch does show it.
        Recorded in docs/BACKEND-GAPS.md rather than papered over with a
        request per row.
      */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <NativeSelect
            className="w-auto"
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
              rowKey={(batch) => batch.public_id}
              emptyMessage="No batches to show. Create one from a course."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="batches"
            />
          </>
        )}
      </Card>
    </div>
  );
}
