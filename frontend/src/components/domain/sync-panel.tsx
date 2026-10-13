"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Clock,
  Minus,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  SyncJobResponse,
  SyncPipelineResponse,
  SyncPipelineStatusResponse,
} from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Separator,
  Switch,
} from "@/components/ui/primitives";
import { Input } from "@/components/ui/form";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { cn } from "@/lib/utils";

/**
 * "Sync All Data", and what it is doing.
 *
 * The panel **polls the server** rather than holding the run in React state,
 * which is the whole point: the pipeline is a background task in the API
 * process, so navigating away, signing out or closing the laptop does not
 * touch it, and whoever opens this page next sees the same progress. Polling
 * is fast while something is in flight and stops when nothing is.
 */

/** While a run is in flight. Fast enough to feel live, slow enough to be free. */
const POLL_RUNNING_MS = 2000;
/** While idle: only to notice a run somebody else (or the scheduler) started. */
const POLL_IDLE_MS = 30000;

function tone(status: string): "success" | "danger" | "warning" | "info" | "neutral" {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "PARTIAL":
      return "warning";
    case "RUNNING":
      return "info";
    default:
      return "neutral";
  }
}

function StepIcon({ status }: { status: string }) {
  const common = "size-3.5 shrink-0";
  if (status === "COMPLETED") return <Check className={cn(common, "text-success")} />;
  if (status === "FAILED") return <X className={cn(common, "text-danger")} />;
  if (status === "SKIPPED") return <Minus className={cn(common, "text-subtle-foreground")} />;
  if (status === "RUNNING")
    return <RefreshCw className={cn(common, "animate-spin text-info")} />;
  return <Clock className={cn(common, "text-subtle-foreground")} />;
}

/**
 * Counts a step reported that do not fit "succeeded / failed".
 *
 * The manager step passes over far more records than it acts on, and that is
 * the expected outcome rather than a problem: LAIT's corporate directory and
 * this institution's user list are not the same set of people. Saying so in
 * the panel is what stops "7 of 103" reading as a fault.
 */
function extras(job: SyncJobResponse): string | null {
  const detail = job.detail as Record<string, Record<string, number> | undefined> | null;
  if (!detail) return null;
  const managers = detail.managers;
  const delegates = detail.delegates;
  const parts: string[] = [];
  if (managers?.matched) parts.push(`${managers.matched} managers matched by email`);
  if (managers?.no_lms_account) parts.push(`${managers.no_lms_account} skipped (no LMS account)`);
  if (managers?.no_email) parts.push(`${managers.no_email} skipped (no email upstream)`);
  if (delegates?.linked) parts.push(`${delegates.linked} newly linked`);
  if (delegates?.already_linked) parts.push(`${delegates.already_linked} already linked`);
  if (delegates?.unmatched) parts.push(`${delegates.unmatched} delegates not in the LMS`);
  return parts.length ? parts.join(" · ") : null;
}

function Step({ job }: { job: SyncJobResponse }) {
  const note = extras(job);
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <span className="mt-0.5">
        <StepIcon status={job.status} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <span
            className={cn(
              "text-xs font-medium",
              job.status === "PENDING" || job.status === "SKIPPED"
                ? "text-subtle-foreground"
                : undefined,
            )}
          >
            {job.label}
          </span>
          {job.status === "PENDING" ? (
            <span className="text-2xs text-subtle-foreground">Waiting</span>
          ) : (
            <span className="text-2xs tabular-nums text-subtle-foreground">
              {(job.processed ?? 0).toLocaleString()} processed
              {job.failed ? ` · ${job.failed.toLocaleString()} failed` : ""}
            </span>
          )}
        </div>
        {note ? <p className="mt-0.5 text-2xs text-subtle-foreground">{note}</p> : null}
        {job.error ? (
          <p className="mt-0.5 text-2xs text-danger break-words">{job.error}</p>
        ) : null}
      </div>
    </li>
  );
}

function ProgressBar({ percent, running }: { percent: number; running: boolean }) {
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Overall synchronisation progress"
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500",
          running ? "bg-info" : "bg-success",
        )}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

function Schedule({
  status,
  onSaved,
}: {
  status: SyncPipelineStatusResponse;
  onSaved: () => void;
}) {
  // Seeded from the server once. The server stays the authority: the caller
  // gives this component a `key` built from the stored values, so a change
  // made elsewhere remounts it with the new ones instead of an effect racing
  // the person typing into the field.
  const [enabled, setEnabled] = useState<boolean>(status.schedule_enabled ?? false);
  const [hours, setHours] = useState(String(status.schedule_interval_hours ?? 6));

  const save = useApiMutation<SyncPipelineStatusResponse, { enabled: boolean; hours: number }>({
    mutationFn: ({ enabled: on, hours: every }) =>
      api.put<SyncPipelineStatusResponse>("/sync/all/schedule", {
        body: { enabled: on, interval_hours: every },
      }),
    success: "Automatic synchronisation updated.",
    invalidate: [["sync-status"]],
    onSuccess: onSaved,
  });

  if (!status.can_configure_schedule) {
    return (
      <p className="text-2xs text-subtle-foreground">
        Automatic synchronisation is{" "}
        <strong className="font-medium">{status.schedule_enabled ? "on" : "off"}</strong>
        {status.schedule_enabled && status.schedule_interval_hours
          ? `, every ${status.schedule_interval_hours} hours`
          : ""}
        . Changing it needs the system-settings permission.
      </p>
    );
  }

  const parsed = Number(hours);
  const valid = Number.isFinite(parsed) && parsed >= 0.25 && parsed <= 168;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <label className="flex items-center gap-2 text-xs">
        <Switch checked={enabled} onCheckedChange={(next) => setEnabled(next === true)} />
        Run automatically
      </label>
      <label className="flex items-center gap-2 text-xs text-subtle-foreground">
        every
        <Input
          type="number"
          step="0.25"
          min="0.25"
          max="168"
          value={hours}
          onChange={(event) => setHours(event.target.value)}
          className="h-7 w-20 text-xs"
          aria-label="Hours between automatic synchronisations"
          disabled={!enabled}
        />
        hours
      </label>
      <Button
        size="sm"
        variant="secondary"
        disabled={!valid || save.isPending}
        onClick={() => save.mutate({ enabled, hours: parsed })}
      >
        {save.isPending ? "Saving…" : "Save"}
      </Button>
      {!valid ? (
        <span className="text-2xs text-danger">
          Between 0.25 and 168 hours.
        </span>
      ) : null}
      <p className="w-full text-2xs text-subtle-foreground">
        Obeyed by the <code className="font-mono">sync_all</code> worker process, which runs
        whether or not anyone is signed in.
      </p>
    </div>
  );
}

export function SyncPanel({ canSync }: { canSync: boolean }) {
  const queryClient = useQueryClient();
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const [showSchedule, setShowSchedule] = useState(false);
  const invalidated = useRef<string | null>(null);

  const status = useQuery({
    queryKey: ["sync-status"],
    queryFn: () => api.get<SyncPipelineStatusResponse>("/sync/all/status"),
    enabled: canSync,
    refetchInterval: (query) =>
      query.state.data?.running ? POLL_RUNNING_MS : POLL_IDLE_MS,
    // Keep polling with the tab in the background: the point of the panel is
    // that the work does not depend on anyone watching it.
    refetchIntervalInBackground: true,
  });

  const current: SyncPipelineResponse | null | undefined =
    status.data?.running ?? status.data?.latest;

  // When a run finishes, the rest of the console is stale -- it has just
  // imported users, courses, batches, sessions and enrolments.
  useEffect(() => {
    if (!current || current.status === "RUNNING") return;
    if (invalidated.current === current.public_id) return;
    invalidated.current = current.public_id;
    for (const key of [
      ["users"], ["courses"], ["batches"], ["sessions"], ["enrollments"],
      ["dashboard"], ["manager-links"],
    ]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  }, [current, queryClient]);

  const start = useApiMutation<SyncPipelineResponse, void>({
    mutationFn: () => api.post<SyncPipelineResponse>("/sync/all", {}),
    success: "Synchronisation started. It continues even if you navigate away.",
    invalidate: [["sync-status"]],
  });

  const retry = useApiMutation<SyncPipelineResponse, string>({
    mutationFn: (runId) =>
      api.post<SyncPipelineResponse>(`/sync/all/${segment(runId)}/retry`, {}),
    success: "Retrying the steps that did not succeed.",
    invalidate: [["sync-status"]],
  });

  if (!canSync) return null;

  const running = Boolean(status.data?.running);
  const percent = current?.progress_percent ?? 0;
  const retryable =
    current &&
    current.status !== "RUNNING" &&
    (current.jobs ?? []).some((job) => job.status === "FAILED" || job.status === "SKIPPED");

  return (
    <Card>
      <CardHeader
        title="Data synchronisation"
        description="Users, managers, courses, batches, sessions and enrolments, imported from LAIT in that order."
        actions={
          <div className="flex items-center gap-2">
            {retryable ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={retry.isPending}
                onClick={() => current && retry.mutate(current.public_id)}
              >
                <RotateCcw className="size-3.5" />
                Retry failed steps
              </Button>
            ) : null}
            <Button
              size="sm"
              disabled={running || start.isPending}
              onClick={() => start.mutate()}
            >
              <RefreshCw className={cn("size-3.5", running ? "animate-spin" : undefined)} />
              {running ? "Synchronising…" : "Sync All Data"}
            </Button>
          </div>
        }
      />
      <CardBody className="space-y-4">
        {status.isPending ? (
          <p className="text-xs text-subtle-foreground">Checking…</p>
        ) : !current ? (
          <p className="text-xs text-subtle-foreground">
            Nothing has been synchronised yet. &ldquo;Sync All Data&rdquo; imports everything in
            dependency order and keeps running in the background.
          </p>
        ) : (
          <>
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <div className="flex items-center gap-2">
                  <Badge tone={tone(current.status)} dot>
                    {current.status === "PARTIAL" ? "Finished with problems" : current.status}
                  </Badge>
                  {current.trigger_type === "SCHEDULED" ? (
                    <span className="text-2xs text-subtle-foreground">Started automatically</span>
                  ) : null}
                </div>
                <span className="text-2xs tabular-nums text-subtle-foreground">{percent}%</span>
              </div>
              <ProgressBar percent={percent} running={running} />
            </div>

            {current.failure_reason ? (
              <p className="flex items-start gap-2 rounded-sm bg-danger/10 px-2.5 py-2 text-2xs text-danger">
                <AlertTriangle className="mt-px size-3.5 shrink-0" />
                <span className="break-words">{current.failure_reason}</span>
              </p>
            ) : null}

            <ul className="divide-y divide-border">
              {(current.jobs ?? []).map((job) => (
                <Step key={job.public_id} job={job} />
              ))}
            </ul>

            <Separator />

            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-2xs sm:grid-cols-4">
              <div>
                <dt className="text-subtle-foreground">Processed</dt>
                <dd className="tabular-nums font-medium">
                  {current.processed_total.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt className="text-subtle-foreground">Succeeded</dt>
                <dd className="tabular-nums font-medium">
                  {current.succeeded_total.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt className="text-subtle-foreground">Failed</dt>
                <dd
                  className={cn(
                    "tabular-nums font-medium",
                    current.failed_total ? "text-danger" : undefined,
                  )}
                >
                  {current.failed_total.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt className="text-subtle-foreground">Last successful</dt>
                <dd
                  className="font-medium"
                  title={
                    status.data?.last_successful_at
                      ? formatDateTime(status.data.last_successful_at, { timeZone })
                      : undefined
                  }
                >
                  {status.data?.last_successful_at
                    ? formatRelative(status.data.last_successful_at, locale)
                    : "Never"}
                </dd>
              </div>
            </dl>
          </>
        )}

        <Separator />

        <div>
          <button
            type="button"
            className="flex items-center gap-1.5 text-2xs text-subtle-foreground hover:text-foreground"
            onClick={() => setShowSchedule((open) => !open)}
            aria-expanded={showSchedule}
          >
            <ChevronDown
              className={cn("size-3 transition-transform", showSchedule ? "rotate-180" : undefined)}
            />
            Automatic synchronisation
            <Badge tone={status.data?.schedule_enabled ? "success" : "neutral"}>
              {status.data?.schedule_enabled ? "On" : "Off"}
            </Badge>
          </button>
          {showSchedule && status.data ? (
            <div className="mt-3">
              <Schedule
                key={`${status.data.schedule_enabled}:${status.data.schedule_interval_hours}`}
                status={status.data}
                onSaved={() => setShowSchedule(false)}
              />
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}
