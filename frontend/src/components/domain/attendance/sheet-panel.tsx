"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, CheckCheck, History, Loader2, MessageSquarePlus, Search, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, segment } from "@/lib/api/client";
import type { SheetHistory, SheetRow, SheetView } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatTime } from "@/lib/format/datetime";
import { cn, humanise } from "@/lib/utils";

type Status = "PRESENT" | "LATE" | "ABSENT" | "EXCUSED";
interface Mark {
  status: Status | null;
  remarks: string;
}

const STATUSES: { value: Status; label: string; key: string; on: string }[] = [
  { value: "PRESENT", label: "Present", key: "P", on: "border-success bg-success text-white" },
  { value: "LATE", label: "Late", key: "L", on: "border-warning bg-warning text-black" },
  { value: "ABSENT", label: "Absent", key: "A", on: "border-danger bg-danger text-white" },
  { value: "EXCUSED", label: "Excused", key: "E", on: "border-info bg-info text-white" },
];
const AUTOSAVE_MS = 2500;

function initialMarks(view: SheetView): Record<string, Mark> {
  const out: Record<string, Mark> = {};
  for (const row of view.roster) out[row.student.public_id] = { status: (row.status as Status | null) ?? null, remarks: row.remarks ?? "" };
  return out;
}

const STATE_TONE = { NOT_STARTED: "neutral", DRAFT: "warning", FINALIZED: "success" } as const;
const STATE_LABEL = { NOT_STARTED: "Pending", DRAFT: "Draft saved", FINALIZED: "Finalized" } as const;

/**
 * One session's register, built for speed.
 *
 * Click a status, or focus a student and press P, L, A or E (the arrow keys move between students). A draft saves
 * itself a moment after the last change and reaches nothing until it is submitted; submitting needs every student
 * marked. A submitted register stays editable, and every correction is recorded with who made it.
 *
 * Whether this person may change anything, and whether that means acting *for* the assigned tutor, comes from the
 * server (`permissions`), not from a guess about their role.
 */
export function AttendanceSheetPanel({ sessionId, onBack }: { sessionId: string; onBack?: () => void }) {
  const queryClient = useQueryClient();
  const timeZone = useDisplayTimeZone();

  const sheet = useQuery({
    queryKey: ["attendance", "sheet", sessionId],
    queryFn: () => api.get<SheetView>(`/attendance/sessions/${segment(sessionId)}/sheet`),
    refetchOnWindowFocus: false, // never replace marks somebody is in the middle of making
  });

  const [marks, setMarks] = useState<Record<string, Mark> | null>(null);
  const [notes, setNotes] = useState("");
  const [seeded, setSeeded] = useState<SheetView | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState<"idle" | "draft" | "submit">("idle");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [filter, setFilter] = useState<Status | "UNMARKED" | null>(null);
  const [openNote, setOpenNote] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);

  // Seed the local marks from the server's sheet once per session (adjusting state while rendering, no effect).
  if (sheet.data && (seeded === null || seeded.session.public_id !== sessionId) && sheet.data.session.public_id === sessionId) {
    setSeeded(sheet.data);
    setMarks(initialMarks(sheet.data));
    setNotes(sheet.data.notes ?? "");
    setDirty(false);
  }

  const view = sheet.data;
  const canEdit = view?.permissions.can_edit ?? false;
  const state = view?.meta.state ?? "NOT_STARTED";
  const finalized = state === "FINALIZED";

  const entries = useCallback(
    (forSubmit: boolean) =>
      Object.entries(marks ?? {})
        .filter(([, m]) => !forSubmit || m.status !== null)
        .map(([student_id, m]) => ({ student_id, status: m.status, remarks: m.remarks.trim() || null })),
    [marks],
  );

  const counts = useMemo(() => {
    const c = { PRESENT: 0, LATE: 0, ABSENT: 0, EXCUSED: 0, UNMARKED: 0 };
    for (const row of view?.roster ?? []) {
      const s = marks?.[row.student.public_id]?.status ?? null;
      if (s) c[s] += 1;
      else c.UNMARKED += 1;
    }
    const counted = c.PRESENT + c.LATE + c.ABSENT;
    const rate = counted === 0 ? null : Math.round(((c.PRESENT + c.LATE) / counted) * 1000) / 10;
    return { ...c, rate, total: view?.roster.length ?? 0 };
  }, [view, marks]);

  function change(studentId: string, patch: Partial<Mark>) {
    setMarks((current) => ({ ...(current ?? {}), [studentId]: { status: null, remarks: "", ...(current?.[studentId] ?? {}), ...patch } }));
    setDirty(true);
    setError(null);
  }

  // A draft saves itself. A submitted register does not: correcting one is a deliberate act with its own button.
  useEffect(() => {
    if (!dirty || finalized || !canEdit || saving !== "idle" || marks === null) return undefined;
    const timer = window.setTimeout(async () => {
      setSaving("draft");
      try {
        const saved = await api.put<SheetView>(`/attendance/sessions/${segment(sessionId)}/sheet`, { body: { entries: entries(false), notes: notes || null, submit: false } });
        queryClient.setQueryData(["attendance", "sheet", sessionId], saved);
        setDirty(false);
        setSavedAt(new Date().toISOString());
        void queryClient.invalidateQueries({ queryKey: ["attendance", "queue"] });
      } catch {
        // A failed autosave is not worth an interruption; the buttons report real errors.
      } finally {
        setSaving("idle");
      }
    }, AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [dirty, finalized, canEdit, saving, marks, notes, entries, sessionId, queryClient]);

  async function submit() {
    setSaving("submit");
    setError(null);
    try {
      const saved = await api.put<SheetView>(`/attendance/sessions/${segment(sessionId)}/sheet`, { body: { entries: entries(true), notes: notes || null, submit: true } });
      queryClient.setQueryData(["attendance", "sheet", sessionId], saved);
      setMarks(initialMarks(saved));
      setNotes(saved.notes ?? "");
      setDirty(false);
      setSavedAt(new Date().toISOString());
      toast.success(finalized ? "Changes saved." : "Attendance submitted.");
      for (const key of [["attendance"], ["batches"]]) void queryClient.invalidateQueries({ queryKey: key });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The attendance could not be saved.");
    } finally {
      setSaving("idle");
    }
  }

  async function saveDraftNow() {
    setSaving("draft");
    setError(null);
    try {
      const saved = await api.put<SheetView>(`/attendance/sessions/${segment(sessionId)}/sheet`, { body: { entries: entries(false), notes: notes || null, submit: false } });
      queryClient.setQueryData(["attendance", "sheet", sessionId], saved);
      setDirty(false);
      setSavedAt(new Date().toISOString());
      toast.success("Draft saved.");
      void queryClient.invalidateQueries({ queryKey: ["attendance", "queue"] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The draft could not be saved.");
    } finally {
      setSaving("idle");
    }
  }

  const visibleRows: SheetRow[] = useMemo(() => {
    const needle = term.trim().toLowerCase();
    return (view?.roster ?? []).filter((row) => {
      if (needle && !row.student.name.toLowerCase().includes(needle)) return false;
      const s = marks?.[row.student.public_id]?.status ?? null;
      if (filter === "UNMARKED") return s === null;
      return !filter || s === filter;
    });
  }, [view, marks, term, filter]);

  function markAll(status: Status) {
    setMarks((current) => {
      const next = { ...(current ?? {}) };
      for (const row of visibleRows) next[row.student.public_id] = { status, remarks: next[row.student.public_id]?.remarks ?? "" };
      return next;
    });
    setDirty(true);
  }

  function onRowKey(event: React.KeyboardEvent<HTMLLIElement>, studentId: string) {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
    const hit = STATUSES.find((s) => s.key === event.key.toUpperCase());
    if (hit && canEdit && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      change(studentId, { status: hit.value });
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const rows = Array.from(listRef.current?.querySelectorAll<HTMLElement>("[data-student-row]") ?? []);
      const at = rows.indexOf(event.currentTarget);
      rows[at + (event.key === "ArrowDown" ? 1 : -1)]?.focus();
    }
  }

  if (sheet.isPending) return <LoadingState />;
  if (sheet.error) return <ErrorState error={sheet.error} onRetry={() => void sheet.refetch()} />;
  if (!view) return null;

  const when = view.session.start_time ? `${formatDateTime(view.session.start_time, { timeZone })}${view.session.end_time ? ` – ${formatTime(view.session.end_time, { timeZone })}` : ""}` : "";
  const onBehalf = view.permissions.would_be_on_behalf;
  const submitLabel = finalized ? "Save changes" : onBehalf ? `Submit on behalf of ${view.meta.assigned_tutor.name}` : "Submit attendance";
  const canSubmit = canEdit && saving === "idle" && (finalized ? dirty : counts.UNMARKED === 0 && counts.total > 0);

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex items-start gap-2">
        {onBack ? (
          <Button variant="ghost" size="icon" aria-label="Back to the sessions" className="lg:hidden" onClick={onBack}>
            <ArrowLeft />
          </Button>
        ) : null}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold leading-tight">{view.batch.course_title ?? view.batch.batch_code}</h2>
          <p className="truncate text-xs text-muted-foreground">
            <span className="font-mono">{view.batch.batch_code}</span> · {when} · {humanise(view.session.platform ?? "")}
            {view.session.classroom ? ` · ${view.session.classroom}` : ""}
          </p>
          <p className="text-xs text-muted-foreground">
            Tutor <strong className="font-medium text-foreground">{view.meta.assigned_tutor.name}</strong> · {view.batch.enrolled} enrolled
          </p>
        </div>
        <Badge tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Badge>
      </div>

      {onBehalf && !finalized ? (
        <div role="status" className="flex items-start gap-2 rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-xs">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p>
            You are taking this register <strong>on behalf of {view.meta.assigned_tutor.name}</strong>. It is recorded that you submitted it, and that {view.meta.assigned_tutor.name} was the assigned tutor.
          </p>
        </div>
      ) : null}
      {!canEdit ? (
        <p role="status" className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
          You can see this register but not change it: only {view.meta.assigned_tutor.name}, or a Super Admin acting for them, can.
        </p>
      ) : null}
      {view.meta.legacy ? <p className="text-xs text-muted-foreground">Marked before registers were tracked: there is no record of who took it. Changes you save are recorded.</p> : null}

      {/* Summary: also the filter. */}
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by status">
          {STATUSES.map((s) => (
            <button
              key={s.value}
              type="button"
              aria-pressed={filter === s.value}
              onClick={() => setFilter(filter === s.value ? null : s.value)}
              className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors", filter === s.value ? s.on : "border-border-subtle hover:bg-muted")}
            >
              {s.label}
              <span className="font-semibold tabular-nums">{counts[s.value]}</span>
            </button>
          ))}
          <button
            type="button"
            aria-pressed={filter === "UNMARKED"}
            onClick={() => setFilter(filter === "UNMARKED" ? null : "UNMARKED")}
            className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors", filter === "UNMARKED" ? "border-foreground bg-foreground text-surface" : "border-dashed border-border-subtle hover:bg-muted")}
          >
            Unmarked <span className="font-semibold tabular-nums">{counts.UNMARKED}</span>
          </button>
          <span className="ml-auto text-sm font-semibold tabular-nums" title="(present + late) / (present + late + absent); excused students are left out">
            {counts.rate === null ? "—" : `${counts.rate}%`} <span className="text-xs font-normal text-muted-foreground">attendance</span>
          </span>
        </div>
        <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
          {counts.total > 0
            ? STATUSES.map((s) => <span key={s.value} className={cn("h-full", s.value === "PRESENT" && "bg-success", s.value === "LATE" && "bg-warning", s.value === "ABSENT" && "bg-danger", s.value === "EXCUSED" && "bg-info")} style={{ width: `${(counts[s.value] / counts.total) * 100}%` }} />)
            : null}
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-40 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search students"
            aria-label="Search students"
            className="h-8 w-full rounded-md border border-border-strong bg-surface pl-8 pr-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-primary"
          />
        </div>
        {canEdit ? (
          <>
            <Button variant="secondary" size="sm" onClick={() => markAll("PRESENT")} disabled={visibleRows.length === 0}>
              <CheckCheck /> Mark all present
            </Button>
            {filter !== null || term ? <span className="text-xs text-muted-foreground">applies to the {visibleRows.length} shown</span> : null}
          </>
        ) : null}
      </div>

      {error ? (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </div>
      ) : null}

      <Card className="overflow-hidden">
        {visibleRows.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">{view.roster.length === 0 ? "Nobody is enrolled in this batch." : "No students match."}</p>
        ) : (
          <ul ref={listRef} className="divide-y divide-border-subtle" aria-label="Students">
            {visibleRows.map((row) => {
              const id = row.student.public_id;
              const mark = marks?.[id] ?? { status: null, remarks: "" };
              return (
                <li
                  key={id}
                  data-student-row
                  tabIndex={0}
                  onKeyDown={(event) => onRowKey(event, id)}
                  className={cn("px-3 py-1.5 outline-none focus-visible:bg-primary/[0.06] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary", mark.status === null && "bg-warning/[0.04]")}
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="min-w-0 flex-1 basis-40 truncate text-sm font-medium" title={row.student.name}>
                      {row.student.name}
                    </span>
                    <div role="radiogroup" aria-label={`Attendance for ${row.student.name}`} className="flex gap-1">
                      {STATUSES.map((s) => {
                        const on = mark.status === s.value;
                        return (
                          <button
                            key={s.value}
                            type="button"
                            role="radio"
                            aria-checked={on}
                            disabled={!canEdit}
                            title={`${s.label} (${s.key})`}
                            tabIndex={-1}
                            onClick={() => change(id, { status: on && !finalized ? null : s.value })}
                            className={cn(
                              "h-7 min-w-8 rounded-md border px-2 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 sm:min-w-16",
                              on ? s.on : "border-border-strong hover:bg-muted",
                            )}
                          >
                            <span className="sm:hidden">{s.key}</span>
                            <span className="hidden sm:inline">{s.label}</span>
                          </button>
                        );
                      })}
                    </div>
                    <button
                      type="button"
                      tabIndex={-1}
                      aria-label={`Note for ${row.student.name}`}
                      aria-expanded={openNote === id}
                      title="Add a note"
                      onClick={() => setOpenNote(openNote === id ? null : id)}
                      className={cn("rounded p-1 hover:bg-muted", mark.remarks ? "text-primary" : "text-muted-foreground")}
                    >
                      <MessageSquarePlus className="size-4" aria-hidden />
                    </button>
                  </div>
                  {openNote === id || mark.remarks ? (
                    <input
                      value={mark.remarks}
                      disabled={!canEdit}
                      maxLength={1000}
                      placeholder="Note (e.g. reason for absence)"
                      aria-label={`Note for ${row.student.name}`}
                      onChange={(event) => change(id, { remarks: event.target.value })}
                      className="mt-1 h-7 w-full rounded-md border border-border-subtle bg-surface px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-70"
                    />
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <label className="block space-y-1">
        <span className="text-xs font-medium text-muted-foreground">Session note</span>
        <textarea
          value={notes}
          disabled={!canEdit}
          maxLength={2000}
          rows={2}
          onChange={(event) => {
            setNotes(event.target.value);
            setDirty(true);
          }}
          placeholder="Anything worth recording about this class"
          className="w-full rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-70"
        />
      </label>

      {canEdit ? (
        <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 border-t border-border-subtle bg-surface/95 px-1 py-2.5 backdrop-blur">
          <Button onClick={() => void submit()} disabled={!canSubmit} loading={saving === "submit"}>
            <Check /> {submitLabel}
          </Button>
          {!finalized ? (
            <Button variant="secondary" onClick={() => void saveDraftNow()} disabled={!dirty || saving !== "idle"} loading={saving === "draft"}>
              Save draft
            </Button>
          ) : null}
          <span className="text-xs text-muted-foreground" role="status">
            {saving === "draft" ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="size-3 animate-spin" aria-hidden /> Saving…
              </span>
            ) : dirty ? (
              finalized ? "Unsaved changes" : "Saving shortly…"
            ) : savedAt ? (
              `Saved ${formatTime(savedAt, { timeZone })}`
            ) : !finalized && counts.UNMARKED > 0 ? (
              `${counts.UNMARKED} still to mark`
            ) : null}
          </span>
          <span className="ml-auto hidden text-[11px] text-muted-foreground lg:inline">Tip: focus a student, press P / L / A / E, use ↑ ↓ to move.</span>
        </div>
      ) : null}

      <div className="rounded-lg border border-border-subtle">
        <button type="button" onClick={() => setShowHistory((v) => !v)} aria-expanded={showHistory} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium hover:bg-muted">
          <History className="size-4 text-muted-foreground" aria-hidden /> Record & audit trail
          <span className="ml-auto text-xs font-normal text-muted-foreground">{view.meta.finalized_at ? `Submitted ${formatDateTime(view.meta.finalized_at, { timeZone })}` : view.meta.started_at ? `Started ${formatDateTime(view.meta.started_at, { timeZone })}` : "Nothing recorded yet"}</span>
        </button>
        {showHistory ? <AuditTrail sessionId={sessionId} view={view} timeZone={timeZone} /> : null}
      </div>
    </div>
  );
}

function AuditTrail({ sessionId, view, timeZone }: { sessionId: string; view: SheetView; timeZone: string }) {
  const history = useQuery({
    queryKey: ["attendance", "history", sessionId, view.meta.last_saved_at, view.meta.state],
    queryFn: () => api.get<SheetHistory>(`/attendance/sessions/${segment(sessionId)}/sheet/history`),
  });
  const m = view.meta;
  return (
    <div className="space-y-3 border-t border-border-subtle px-3 py-3 text-xs">
      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground">Assigned tutor</dt>
        <dd>{m.assigned_tutor.name}</dd>
        {m.started_by ? (
          <>
            <dt className="text-muted-foreground">Started by</dt>
            <dd>
              {m.started_by.name}
              {m.started_at ? `, ${formatDateTime(m.started_at, { timeZone })}` : ""}
            </dd>
          </>
        ) : null}
        {m.finalized_by ? (
          <>
            <dt className="text-muted-foreground">Submitted by</dt>
            <dd>
              {m.finalized_by.name}
              {m.finalized_at ? `, ${formatDateTime(m.finalized_at, { timeZone })}` : ""}
              {m.submitted_on_behalf ? <Badge tone="warning" className="ml-2">on behalf of {m.assigned_tutor.name}</Badge> : null}
            </dd>
          </>
        ) : null}
        {m.last_saved_by && m.last_saved_at ? (
          <>
            <dt className="text-muted-foreground">Last changed</dt>
            <dd>
              {m.last_saved_by.name}, {formatDateTime(m.last_saved_at, { timeZone })}
            </dd>
          </>
        ) : null}
      </dl>
      {history.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : (history.data?.events ?? []).length === 0 ? (
        <p className="text-muted-foreground">No events yet.</p>
      ) : (
        <ol className="space-y-2 border-l border-border-subtle pl-3">
          {history.data?.events.map((e, i) => (
            <li key={`${e.at}-${i}`}>
              <p>
                <strong className="font-medium">{e.action === "STARTED" ? "Started" : e.action === "FINALIZED" ? "Submitted" : "Edited"}</strong> by {e.actor.name}
                {e.on_behalf ? <span className="text-warning"> on behalf of {e.assigned_tutor.name}</span> : null}
                <span className="text-muted-foreground"> · {formatDateTime(e.at, { timeZone })}</span>
              </p>
              {e.action === "FINALIZED" && e.counts ? (
                <p className="text-muted-foreground">
                  {e.counts.PRESENT ?? 0} present · {e.counts.LATE ?? 0} late · {e.counts.ABSENT ?? 0} absent · {e.counts.EXCUSED ?? 0} excused
                </p>
              ) : null}
              {(e.changes ?? []).map((c) => (
                <p key={c.student} className="text-muted-foreground">
                  {c.student}: {c.was ? humanise(c.was) : "not marked"} → <span className="text-foreground">{c.now ? humanise(c.now) : "cleared"}</span>
                  {c.remarks_changed ? " (note changed)" : ""}
                </p>
              ))}
              {e.notes_changed ? <p className="text-muted-foreground">Session note changed</p> : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
