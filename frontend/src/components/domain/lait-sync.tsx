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

type Counts = { fetched?: number; created?: number; updated?: number; unchanged?: number; skipped?: number };

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
  const s = (run.stats ?? {}) as { students?: Counts; tutors?: Counts };
  const created = (s.students?.created ?? 0) + (s.tutors?.created ?? 0);
  const updated = (s.students?.updated ?? 0) + (s.tutors?.updated ?? 0);
  const skipped = (s.students?.skipped ?? 0) + (s.tutors?.skipped ?? 0);
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
export function LaitSyncControls({ canSync }: { canSync: boolean }) {
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
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["sync-runs"] });
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
        const latest = await api.get<SyncRunResponse>(`/users/sync/runs/${segment(run.public_id)}`);
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

  const start = useApiMutation<SyncRunResponse, void>({
    mutationFn: () => api.post<SyncRunResponse>("/users/sync"),
    onSuccess: (run) => {
      setWatching(true);
      watch(run, Date.now());
    },
    invalidate: [["sync-runs"]],
  });

  return (
    <>
      {canSync ? (
        <Button
          variant="secondary"
          loading={start.isPending || watching}
          onClick={() => start.mutate()}
        >
          <RefreshCw /> {watching ? "Syncing…" : "Sync from LAIT"}
        </Button>
      ) : null}
      {canSync ? (
        <Button variant="ghost" onClick={() => setHistoryOpen(true)} aria-label="Synchronisation history">
          <History /> History
        </Button>
      ) : null}
      {canSync ? <SyncHistoryDialog open={historyOpen} onOpenChange={setHistoryOpen} /> : null}
    </>
  );
}

function SyncHistoryDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const timeZone = useDisplayTimeZone();
  const { data, isPending } = useQuery({
    queryKey: ["sync-runs"],
    queryFn: () => api.get<PageSyncRunResponse>("/users/sync/runs", { query: { limit: 20 } }),
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">
        <DialogHeader
          title="Synchronisation history"
          description="Each run, whether started here or by the scheduled worker. Accounts arrive with sign-in switched off until a Super Admin enables it."
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
                      {run.errors?.length} record(s) skipped
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
