"use client";

import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, segment } from "@/lib/api/client";
import type { PlanResponse, ReplaceResponse } from "@/lib/api/types";
import { PlatformsValues } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input} from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { Badge } from "@/components/ui/primitives";
import { InlineSpinner } from "@/components/ui/states";
import { UserPicker } from "@/components/domain/user-picker";
import { TimeZoneField } from "@/components/domain/timezone-field";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "@/lib/format/datetime";
import { cn, humanise } from "@/lib/utils";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface Row {
  key: string;
  startUtc: string;
  endUtc: string;
  tutorId: string | null;
  platform: string;
  classroom: string;
}

interface Settings {
  weekdays: number[];
  startTime: string;
  durationMinutes: number;
  startDate: string;
  endDate: string;
  sessions: string;
}

let rowCounter = 0;
const newKey = () => `row-${(rowCounter += 1)}`;

function minutesBetween(a: string, b: string): number {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60_000);
}

/**
 * Re-create a batch's sessions: propose them from its schedule, let the administrator adjust, then save.
 *
 * The proposal is built by the server (`services/session_planner.py`) in the zone chosen here, so the weekdays and
 * clock times mean what they say wherever the person is. Switching the zone re-displays the *same moments* in the
 * new zone and keeps any edits; "Regenerate" builds a fresh proposal from the settings above instead.
 *
 * Nothing is written until Create. Sessions that hold attendance, a recording or notes are never deleted, and
 * replacing the rest needs an explicit tick.
 */
export function RecreateSessionsDialog({ batchId, batchCode, onClose }: { batchId: string; batchCode: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { permissions } = useSession();
  const displayZone = useDisplayTimeZone();

  const [timeZone, setTimeZone] = useState(displayZone);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [edited, setEdited] = useState(false);
  const [ack, setAck] = useState(false);
  const [saving, setSaving] = useState(false);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [tutorForAll, setTutorForAll] = useState<string | null>(null);
  const [platformForAll, setPlatformForAll] = useState("");
  const generation = useRef(0);

  // The proposal, and the settings and rows seeded from it. Used for the first load and for every regenerate.
  function applyPlan(result: PlanResponse) {
    setPlan(result);
    setSettings({
      weekdays: result.settings.weekdays,
      startTime: result.settings.start_time ?? "",
      durationMinutes: result.settings.duration_minutes ?? 0,
      startDate: result.settings.start_date ?? "",
      endDate: result.settings.end_date ?? "",
      sessions: result.settings.sessions ? String(result.settings.sessions) : "",
    });
    setRows(
      result.sessions.map((s) => ({
        key: newKey(),
        startUtc: s.start_utc,
        endUtc: s.end_utc,
        tutorId: result.default_tutor?.public_id ?? null,
        platform: result.default_platform ?? "Zoom",
        classroom: "",
      })),
    );
    setEdited(false);
    setAck(false);
    setConflicts([]);
  }

  // First load: the batch's own schedule, read in the person's display zone.
  const first = useQuery({
    queryKey: ["session-plan", batchId, displayZone],
    queryFn: () => api.post<PlanResponse>(`/batches/${segment(batchId)}/session-plan`, { body: { timezone: displayZone } }),
    gcTime: 0, // a proposal is a moment-in-time answer, never reused for the next dialog
    staleTime: 0,
    retry: false,
  });
  const [seeded, setSeeded] = useState<PlanResponse | null>(null);
  if (first.data && seeded !== first.data) {
    // Adjusting state while rendering, the documented way to derive state from a fetched value (no effect, no flash).
    setSeeded(first.data);
    applyPlan(first.data);
    setLoading(false);
  }
  const firstError = first.error ? (first.error instanceof ApiError ? first.error.message : "The sessions could not be proposed.") : null;

  // Later proposals are explicit ("Regenerate") so they never silently replace an edit.
  const generate = useCallback(
    async (explicit: Settings | null, zone: string) => {
      const mine = ++generation.current;
      setLoading(true);
      setError(null);
      try {
        const body = explicit
          ? {
              timezone: zone,
              weekdays: explicit.weekdays,
              start_time: explicit.startTime,
              duration_minutes: explicit.durationMinutes,
              start_date: explicit.startDate || undefined,
              end_date: explicit.endDate || undefined,
              sessions: explicit.sessions ? Number(explicit.sessions) : undefined,
            }
          : { timezone: zone };
        const result = await api.post<PlanResponse>(`/batches/${segment(batchId)}/session-plan`, { body });
        if (mine === generation.current) applyPlan(result);
      } catch (e) {
        if (mine === generation.current) setError(e instanceof ApiError ? e.message : "The sessions could not be proposed.");
      } finally {
        if (mine === generation.current) setLoading(false);
      }
    },
    // `applyPlan` only calls state setters and a module counter, so it is stable in effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [batchId],
  );

  function regenerate() {
    if (edited && !window.confirm("Regenerating replaces the changes you made to the proposed sessions. Continue?")) return;
    void generate(settings, timeZone);
  }

  function patchRow(key: string, change: Partial<Row>) {
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...change } : r)));
    setEdited(true);
  }

  function setStart(row: Row, local: string) {
    const startUtc = fromLocalInputValue(local, timeZone);
    if (!startUtc) return;
    const length = minutesBetween(row.startUtc, row.endUtc);
    patchRow(row.key, { startUtc, endUtc: new Date(new Date(startUtc).getTime() + length * 60_000).toISOString() });
  }

  function setEnd(row: Row, local: string) {
    const endUtc = fromLocalInputValue(local, timeZone);
    if (endUtc) patchRow(row.key, { endUtc });
  }

  function addRow() {
    const last = rows[rows.length - 1];
    const start = last ? new Date(new Date(last.startUtc).getTime() + 7 * 86_400_000) : new Date(Date.now() + 86_400_000);
    const length = last ? minutesBetween(last.startUtc, last.endUtc) : settings?.durationMinutes || 60;
    setRows((current) => [
      ...current,
      { key: newKey(), startUtc: start.toISOString(), endUtc: new Date(start.getTime() + length * 60_000).toISOString(), tutorId: last?.tutorId ?? plan?.default_tutor?.public_id ?? null, platform: last?.platform ?? "Zoom", classroom: "" },
    ]);
    setEdited(true);
  }

  const replaceable = plan?.existing.replaceable ?? 0;
  const protectedCount = plan?.existing.protected ?? 0;
  const missingTutor = rows.some((r) => !r.tutorId);
  const canSave = rows.length > 0 && !missingTutor && (replaceable === 0 || ack) && !saving && !loading;

  async function save() {
    setSaving(true);
    setConflicts([]);
    setError(null);
    try {
      const result = await api.post<ReplaceResponse>(`/batches/${segment(batchId)}/sessions/replace`, {
        body: {
          confirm_replace: ack,
          sessions: rows.map((r) => ({ start_utc: r.startUtc, end_utc: r.endUtc, tutor_id: r.tutorId, platform: r.platform, classroom: r.classroom || null })),
          schedule: settings ? { timezone: timeZone, weekdays: settings.weekdays, start_time: settings.startTime || null, duration_minutes: settings.durationMinutes || null } : null,
        },
      });
      toast.success(
        `${result.created} session${result.created === 1 ? "" : "s"} created${result.replaced ? `, ${result.replaced} replaced` : ""}${result.kept_protected ? `, ${result.kept_protected} kept` : ""}.`,
      );
      for (const key of [["batches"], ["sessions"], ["attendance"]]) void queryClient.invalidateQueries({ queryKey: key });
      // Bring Google Calendar in line, when it is connected and this person may. Best effort: the LMS is the record.
      if (permissions.has("google.sync")) void api.post(`/integrations/google/sync?batch_id=${encodeURIComponent(batchId)}`).catch(() => undefined);
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
        const list = (e.details as { conflicts?: { session: number; starts: string; with_batch: string | null }[] } | undefined)?.conflicts;
        if (list) setConflicts(list.map((c) => `Session ${c.session} (${formatDateTime(c.starts, { timeZone })}) clashes with ${c.with_batch ?? "another class"}.`));
      } else {
        setError("The sessions could not be created.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !saving && onClose()}>
      <DialogContent size="xl" className="flex max-h-[calc(100dvh-1rem)] flex-col gap-0 overflow-hidden p-0">
        <div className="border-b border-border-subtle px-5 py-4">
          <DialogHeader title={`Re-create sessions · ${batchCode}`} description="Review the proposed sessions, adjust anything, then create them. Nothing is saved until you do." />
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {error ?? firstError ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              <p>{error ?? firstError}</p>
              {conflicts.length > 0 ? (
                <ul className="mt-1 list-disc pl-5 text-xs">
                  {conflicts.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {plan && plan.existing.total > 0 ? (
            <div className="rounded-lg border border-warning/50 bg-warning/10 p-3 text-sm">
              <p className="flex items-center gap-2 font-medium">
                <AlertTriangle className="size-4 text-warning" aria-hidden /> This batch already has {plan.existing.total} session{plan.existing.total === 1 ? "" : "s"}
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {protectedCount > 0 ? (
                  <li className="flex items-center gap-1.5">
                    <ShieldCheck className="size-3.5" aria-hidden /> {protectedCount} will be <strong className="text-foreground">kept</strong> ({(plan.existing.protected_reasons ?? []).join(", ")}). A proposed session at the same time is skipped.
                  </li>
                ) : null}
                {replaceable > 0 ? (
                  <li>
                    {replaceable} will be <strong className="text-foreground">replaced</strong> by the sessions below.
                  </li>
                ) : null}
              </ul>
              {replaceable > 0 ? (
                <label className="mt-2 flex cursor-pointer items-center gap-2 text-sm">
                  <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} className="size-4 accent-[var(--primary)]" />
                  I understand {replaceable} existing session{replaceable === 1 ? "" : "s"} will be replaced
                </label>
              ) : null}
            </div>
          ) : null}

          <section aria-label="Schedule settings" className="space-y-3 rounded-lg border border-border-subtle bg-surface-muted/40 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Schedule</h3>
              {plan?.settings.source ? <Badge tone="neutral">From {plan.settings.source}</Badge> : null}
            </div>
            {plan?.settings.note ? <p className="text-xs text-muted-foreground">{plan.settings.note}</p> : null}
            {settings ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Time zone" hint="Dates and times are read in this zone.">
                  {({ id }) => (
                    <TimeZoneField id={id} value={timeZone} onChange={(zone) => setTimeZone(zone)} />
                  )}
                </Field>
                <Field label="Starts on">{({ id }) => <Input id={id} type="date" value={settings.startDate} onChange={(e) => setSettings({ ...settings, startDate: e.target.value })} />}</Field>
                <Field label="Ends on">{({ id }) => <Input id={id} type="date" value={settings.endDate} onChange={(e) => setSettings({ ...settings, endDate: e.target.value })} />}</Field>
                <Field label="Number of sessions">{({ id }) => <Input id={id} type="number" min={1} max={200} value={settings.sessions} onChange={(e) => setSettings({ ...settings, sessions: e.target.value })} />}</Field>
                <Field label="Start time">{({ id }) => <Input id={id} type="time" value={settings.startTime} onChange={(e) => setSettings({ ...settings, startTime: e.target.value })} />}</Field>
                <Field label="Duration (minutes)">
                  {({ id }) => <Input id={id} type="number" min={5} max={1440} step={5} value={settings.durationMinutes || ""} onChange={(e) => setSettings({ ...settings, durationMinutes: Number(e.target.value) })} />}
                </Field>
                <div className="sm:col-span-2">
                  <span className="mb-1.5 block text-sm font-medium">Class days</span>
                  <div role="group" aria-label="Class days" className="flex flex-wrap gap-1.5">
                    {DAYS.map((label, index) => {
                      const on = settings.weekdays.includes(index);
                      return (
                        <button
                          key={label}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setSettings({ ...settings, weekdays: on ? settings.weekdays.filter((d) => d !== index) : [...settings.weekdays, index].sort() })}
                          className={cn("h-8 min-w-11 rounded-md border px-2 text-xs font-medium transition-all duration-200 ease-out", on ? "border-primary bg-primary text-primary-foreground shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.14)]" : "border-border-strong text-muted-foreground hover:border-slate-400/70 hover:bg-muted hover:text-foreground")}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex justify-center p-4">
                <InlineSpinner />
              </div>
            )}
            <div className="flex justify-end">
              <Button type="button" variant="secondary" size="sm" onClick={regenerate} loading={loading} disabled={!settings}>
                <RefreshCw /> Regenerate from these settings
              </Button>
            </div>
          </section>

          {plan && plan.warnings.length > 0 ? (
            <ul role="status" className="space-y-1 rounded-lg border border-info/40 bg-info/10 px-3 py-2 text-xs">
              {plan.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}

          <section aria-label="Proposed sessions" className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <CalendarClock className="size-4 text-muted-foreground" aria-hidden /> Proposed sessions ({rows.length})
              </h3>
              <div className="flex flex-wrap items-center gap-2">
                <div className="w-48">
                  <UserPicker role="TUTOR" value={tutorForAll} onChange={(id) => setTutorForAll(id)} placeholder="Tutor for all sessions" allowClear />
                </div>
                <Button type="button" variant="secondary" size="sm" disabled={!tutorForAll || rows.length === 0} onClick={() => { setRows((c) => c.map((r) => ({ ...r, tutorId: tutorForAll }))); setEdited(true); }}>
                  Apply
                </Button>
                <Select className="h-8 w-40" aria-label="Method for all sessions" value={(platformForAll) || null} onValueChange={(next) => { const p = (next ?? ""); setPlatformForAll(p); if (p) { setRows((c) => c.map((r) => ({ ...r, platform: p }))); setEdited(true); } }} placeholder="Method for all…" clearable options={optionsFromValues(PlatformsValues, humanise)} />
              </div>
            </div>

            {loading && rows.length === 0 ? (
              <div className="flex justify-center p-8">
                <InlineSpinner />
              </div>
            ) : rows.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border-strong p-8 text-center text-xs text-muted-foreground">No sessions proposed. Adjust the schedule above and regenerate, or add one by hand.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border-subtle">
                <table className="w-full min-w-[46rem] border-collapse text-[13px]">
                  <thead>
                    <tr className="bg-surface-muted text-left">
                      <th className="eyebrow px-2 py-1.5 text-left">#</th>
                      <th className="eyebrow px-2 py-1.5 text-left">Starts</th>
                      <th className="eyebrow px-2 py-1.5 text-left">Ends</th>
                      <th className="eyebrow px-2 py-1.5 text-left">Tutor</th>
                      <th className="eyebrow px-2 py-1.5 text-left">Method</th>
                      <th className="px-2 py-1.5" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={row.key} className="border-t border-border-subtle/70">
                        <td className="px-2 py-1 tabular-nums text-muted-foreground">{index + 1}</td>
                        <td className="px-2 py-1">
                          <Input aria-label={`Session ${index + 1} start`} type="datetime-local" className="h-8 text-[13px]" value={toLocalInputValue(row.startUtc, timeZone)} onChange={(e) => setStart(row, e.target.value)} />
                        </td>
                        <td className="px-2 py-1">
                          <Input aria-label={`Session ${index + 1} end`} type="datetime-local" className="h-8 text-[13px]" value={toLocalInputValue(row.endUtc, timeZone)} onChange={(e) => setEnd(row, e.target.value)} />
                        </td>
                        <td className="w-48 px-2 py-1">
                          <UserPicker role="TUTOR" value={row.tutorId} onChange={(id) => patchRow(row.key, { tutorId: id })} placeholder="Choose a tutor" allowClear={false} />
                        </td>
                        <td className="px-2 py-1">
                          <Select aria-label={`Session ${index + 1} method`} className="h-8" value={row.platform} onValueChange={(next) => patchRow(row.key, { platform: (next ?? "") })} options={optionsFromValues(PlatformsValues, humanise)} />
                        </td>
                        <td className="px-2 py-1 text-right">
                          <Button type="button" variant="ghost" size="icon" className="size-7" aria-label={`Remove session ${index + 1}`} onClick={() => { setRows((c) => c.filter((r) => r.key !== row.key)); setEdited(true); }}>
                            <Trash2 />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="flex items-center justify-between">
              <Button type="button" variant="ghost" size="sm" onClick={addRow}>
                <Plus /> Add a session
              </Button>
              {missingTutor ? <p className="text-xs text-danger">Every session needs a tutor.</p> : null}
            </div>
          </section>
        </div>

        <div className="border-t border-border-subtle px-5 py-3">
          <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void save()} disabled={!canSave} loading={saving}>
            Create {rows.length} session{rows.length === 1 ? "" : "s"}
          </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
