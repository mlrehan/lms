"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, segment } from "@/lib/api/client";
import type { PageSyncRunResponse, SyncRunResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogHeader } from "@/components/ui/dialog";
import { LoadingState } from "@/components/ui/states";
import { formatDateTime } from "@/lib/format/datetime";
import { useDisplayTimeZone } from "@/lib/preferences";

type Counts = { created?: number; updated?: number; skipped?: number };

const POLL_MS = 1500;
/** Give up watching (the run itself carries on server-side) after this long. */
const MAX_WATCH_MS = 10 * 60_000;

function tone(status: string): "success" | "danger" | "warning" | "neutral" {
  if (status === "SUCCEEDED") return "success";
  if (status === "FAILED") return "danger";
  if (status === "PARTIAL") return "warning";
  return "neutral";
}

function summarise(run: SyncRunResponse): string {
  const stats = (run.stats ?? {}) as Record<string, Record<string, number> | undefined>;
  // The Google run reports events and calendars, not people: say what a person would ask about.
  if (stats.events && "deleted" in stats.events) {
    const e = stats.events;
    const pulled = stats.pulled?.time_changes ?? 0;
    return `${stats.calendars?.created ?? 0} calendars created · ${e.created ?? 0} events created · ${e.updated ?? 0} updated · ${e.deleted ?? 0} removed${pulled ? ` · ${pulled} time change(s) taken from Google` : ""}`;
  }
  // Users report {students, tutors}; the academic sync reports {courses, batches, sessions, enrollments}.
  // Anything shaped like a counts object contributes, so both read the same way.
  let created = 0;
  let updated = 0;
  let skipped = 0;
  for (const value of Object.values(run.stats ?? {})) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const c = value as Counts;
      if (typeof c.created === "number") {
        created += c.created;
        updated += c.updated ?? 0;
        skipped += c.skipped ?? 0;
      }
    }
  }
  return `${created} created · ${updated} updated · ${skipped} skipped`;
}

/**
 * "Sync now" plus a history dialog.
 *
 * The button starts a run and **watches it**: the API answers 202 straight
 * away, and a button that only said "started" would leave an operator guessing
 * whether it finished, or failed on an invalid key. The run is polled to
 * completion and the outcome is reported as a toast.
 */
export function LaitSyncControls({
  canSync,
  runsPath = "/users/sync",
  label = "Sync from LAIT",
  invalidate = [["users"]],
  startPath,
  previewLabel,
}: {
  canSync: boolean;
  /** `/users/sync` or `/courses/sync`: runs are watched and listed under this path. */
  runsPath?: string;
  /** Where a run is started, when that is not `runsPath` itself. */
  startPath?: string;
  label?: string;
  /** Adds a second button that starts a dry run: report what would change, write nothing. */
  previewLabel?: string;
  invalidate?: string[][];
}) {
  const queryClient = useQueryClient();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [watching, setWatching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  function watch(run: SyncRunResponse, startedAt: number) {
    const finish = (final: SyncRunResponse) => {
      setWatching(false);
      for (const key of invalidate) void queryClient.invalidateQueries({ queryKey: key });
      void queryClient.invalidateQueries({ queryKey: ["sync-runs", runsPath] });
      if (final.status === "FAILED") {
        toast.error(final.failure_reason ?? "The synchronisation failed.");
      } else if (final.status === "PARTIAL") {
        toast.warning(`Synchronised with problems: ${summarise(final)}. See the history for details.`);
      } else {
        toast.success(`Synchronised: ${summarise(final)}.`);
      }
    };

    const tick = async () => {
      try {
        const latest = await api.get<SyncRunResponse>(`${runsPath}/runs/${segment(run.public_id)}`);
        if (latest.status !== "RUNNING") return finish(latest);
      } catch {
        // A transient read failure must not end the watch; the run is unaffected.
      }
      if (Date.now() - startedAt > MAX_WATCH_MS) {
        setWatching(false);
        toast.info("Still running. Check the history for the result.");
        return;
      }
      timer.current = setTimeout(() => void tick(), POLL_MS);
    };
    timer.current = setTimeout(() => void tick(), POLL_MS);
  }

  const target = startPath ?? runsPath;
  const start = useApiMutation<SyncRunResponse, boolean>({
    mutationFn: (dryRun) => api.post<SyncRunResponse>(dryRun ? `${target}${target.includes("?") ? "&" : "?"}dry_run=true` : target),
    onSuccess: (run) => {
      setWatching(true);
      watch(run, Date.now());
    },
    invalidate: [["sync-runs", runsPath]],
  });

  return (
    <>
      {canSync ? (
        <Button
          variant="secondary"
          loading={start.isPending || watching}
          onClick={() => start.mutate(false)}
        >
          <RefreshCw /> {watching ? "Syncing…" : label}
        </Button>
      ) : null}
      {canSync && previewLabel ? (
        <Button variant="ghost" disabled={start.isPending || watching} onClick={() => start.mutate(true)}>
          {previewLabel}
        </Button>
      ) : null}
      {canSync ? (
        <Button variant="ghost" onClick={() => setHistoryOpen(true)} aria-label="Synchronisation history">
          <History /> History
        </Button>
      ) : null}
      {canSync ? <SyncHistoryDialog open={historyOpen} onOpenChange={setHistoryOpen} runsPath={runsPath} /> : null}
    </>
  );
}

function SyncHistoryDialog({ open, onOpenChange, runsPath }: { open: boolean; onOpenChange: (open: boolean) => void; runsPath: string }) {
  const timeZone = useDisplayTimeZone();
  const { data, isPending } = useQuery({
    queryKey: ["sync-runs", runsPath],
    queryFn: () => api.get<PageSyncRunResponse>(`${runsPath}/runs`, { query: { limit: 20 } }),
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">
        <DialogHeader
          title="Synchronisation history"
          description={runsPath === "/integrations/google" ? "Each run, whether started here or by the scheduled worker. A preview reports what would change and writes nothing." : runsPath === "/users/sync" ? "Each run, whether started here or by the scheduled worker. Accounts arrive with sign-in switched off until a Super Admin enables it." : "Each run, whether started here or by the scheduled worker. Sessions are generated from each batch's schedule; nothing is deleted because LAIT stopped listing it."}
        />
        {isPending ? (
          <LoadingState />
        ) : (data?.items ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No synchronisation has run yet.</p>
        ) : (
          <ul className="space-y-3">
            {data?.items.map((run) => (
              <li key={run.public_id} className="rounded-lg border border-border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={tone(run.status)}>{run.status}</Badge>
                  <span className="font-medium">
                    {run.trigger_type === "SCHEDULED" ? "Scheduled" : "Manual"}
                    {run.dry_run ? " (dry run)" : ""}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(run.started_at, { timeZone })}
                  </span>
                </div>
                {run.failure_reason ? (
                  <p className="mt-2 text-danger">{run.failure_reason}</p>
                ) : (
                  <p className="mt-2 text-muted-foreground">{summarise(run)}</p>
                )}
                {(run.errors ?? []).length > 0 ? (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-muted-foreground">
                      {run.errors?.length} record(s) with problems
                    </summary>
                    <ul className="mt-2 space-y-1 text-xs">
                      {run.errors?.map((error, index) => (
                        <li key={index} className="break-words">
                          <span className="font-mono">{String(error.source)}</span>{" "}
                          <span className="font-mono text-muted-foreground">{String(error.external_id)}</span>
                          {" — "}
                          {String(error.reason)}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
