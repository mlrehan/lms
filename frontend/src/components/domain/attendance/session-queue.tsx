"use client";

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CalendarCheck2 } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PageQueueItem, QueueItem } from "@/lib/api/types";
import { Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Skeleton } from "@/components/ui/primitives";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

export type Range = "today" | "week" | "month" | "all";
export type StateFilter = "PENDING" | "DRAFT" | "FINALIZED" | "";

const DAY = 86_400_000;

/** The window of sessions to list, as instants. The upper bound is "a little ahead", so today's evening class is in. */
export function rangeBounds(range: Range): { from?: string; to?: string } {
  const now = Date.now();
  const to = new Date(now + 2 * DAY).toISOString();
  if (range === "today") return { from: new Date(now - DAY).toISOString(), to: new Date(now + DAY).toISOString() };
  if (range === "week") return { from: new Date(now - 7 * DAY).toISOString(), to };
  if (range === "month") return { from: new Date(now - 30 * DAY).toISOString(), to };
  return {};
}

const STATE_TONE = { NOT_STARTED: "neutral", DRAFT: "warning", FINALIZED: "success" } as const;

function label(item: QueueItem): string {
  if (item.state === "FINALIZED") return item.submitted_on_behalf ? "Done · on behalf" : "Done";
  if (item.state === "DRAFT") return `Draft ${item.marked}/${item.enrolled}`;
  return "Pending";
}

/**
 * The sessions somebody may take or review attendance for, most recent first.
 *
 * A tutor is only ever offered the sessions assigned to them (the server decides; nothing here filters by role).
 * The Super Admin sees them all and narrows by batch and tutor.
 */
export function SessionQueue({
  batchId,
  tutorId,
  range,
  state,
  selectedId,
  onSelect,
}: {
  batchId: string;
  tutorId: string;
  range: Range;
  state: StateFilter;
  selectedId: string | null;
  onSelect: (item: QueueItem) => void;
}) {
  const timeZone = useDisplayTimeZone();
  const [limit, setLimit] = useState(25);

  const queue = useQuery({
    queryKey: ["attendance", "queue", batchId, tutorId, range, state, limit],
    queryFn: () => {
      const { from, to } = rangeBounds(range);
      return api.get<PageQueueItem>("/attendance/queue", {
        query: { batch_id: batchId || undefined, tutor_id: tutorId || undefined, state: state || undefined, starts_from: from, starts_to: to, limit },
      });
    },
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });

  if (queue.error && !queue.data) return <div className="p-3"><ErrorState error={queue.error} onRetry={() => void queue.refetch()} /></div>;
  if (queue.isPending)
    return (
      <div className="space-y-2 p-3" aria-busy>
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );

  const items = queue.data?.items ?? [];
  if (items.length === 0)
    return <EmptyState icon={<CalendarCheck2 className="size-5" />} title="Nothing to take attendance for" description={state === "PENDING" ? "Every class in this period has its attendance taken." : "No sessions match these filters."} />;

  return (
    <div>
      <ul className="divide-y divide-border-subtle" aria-label="Sessions">
        {items.map((item) => {
          const selected = item.session_id === selectedId;
          return (
            <li key={item.session_id}>
              <button
                type="button"
                onClick={() => onSelect(item)}
                aria-current={selected ? "true" : undefined}
                className={cn("flex w-full items-start gap-3 px-3 py-2 text-left transition-colors hover:bg-muted", selected && "bg-primary/10 shadow-[inset_3px_0_0_0_var(--primary)]")}
              >
                <span className="w-16 shrink-0 pt-0.5 text-xs tabular-nums text-muted-foreground">
                  {item.start_time ? (
                    <>
                      <span className="block font-medium text-foreground">{formatTime(item.start_time, { timeZone })}</span>
                      <span className="block">{formatDateTime(item.start_time, { timeZone }).replace(/,?\s*\d{2}:\d{2}$/, "")}</span>
                    </>
                  ) : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium leading-tight">{item.course_title ?? item.batch_code}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    <span className="font-mono">{item.batch_code}</span> · {item.tutor.name} · {item.enrolled} students
                  </span>
                </span>
                <Badge tone={STATE_TONE[item.state]} className="shrink-0">
                  {label(item)}
                </Badge>
              </button>
            </li>
          );
        })}
      </ul>
      {(queue.data?.total ?? 0) > items.length ? (
        <div className="p-2 text-center">
          <Button variant="ghost" size="sm" onClick={() => setLimit((n) => n + 25)}>
            Show more ({(queue.data?.total ?? 0) - items.length} more)
          </Button>
        </div>
      ) : null}
    </div>
  );
}
