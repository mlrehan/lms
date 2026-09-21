"use client";

import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import listPlugin from "@fullcalendar/list";
import multiMonthPlugin from "@fullcalendar/multimonth";
import interactionPlugin from "@fullcalendar/interaction";
import luxon3Plugin from "@fullcalendar/luxon3";
import type { DatesSetArg, DateSelectArg, EventClickArg, EventDropArg, EventInput } from "@fullcalendar/core";
import type { EventResizeDoneArg } from "@fullcalendar/interaction";
import { CalendarPlus, ChevronLeft, ChevronRight, RefreshCw, X } from "lucide-react";
import { toast } from "sonner";
import { api, segment } from "@/lib/api/client";
import type { BatchSummary, CalendarResponse, CalendarSession, GoogleStatusResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/states";
import { SessionDetailsDialog } from "@/components/domain/session-details-dialog";
import { SessionEditorDialog, type EditorState } from "@/components/domain/session-editor-dialog";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { batchHue } from "@/lib/calendar";
import { toLocalInputValue } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

export const CALENDAR_KEY = ["sessions", "calendar"] as const;

const VIEWS = [
  { type: "timeGridDay", label: "Day" },
  { type: "timeGridWeek", label: "Week" },
  { type: "dayGridMonth", label: "Month" },
  { type: "multiMonthYear", label: "Year" },
  { type: "listMonth", label: "Schedule" },
] as const;
type ViewType = (typeof VIEWS)[number]["type"];

const NARROW = "(max-width: 639px)";

function subscribeNarrow(notify: () => void): () => void {
  const query = window.matchMedia(NARROW);
  query.addEventListener("change", notify);
  return () => query.removeEventListener("change", notify);
}

/** The next whole hour in the display zone, as a wall-clock string for the editor. */
function nextHour(timeZone: string): { start: string; end: string } {
  const hour = 3_600_000;
  const at = Math.ceil((Date.now() + 60_000) / hour) * hour;
  return { start: toLocalInputValue(new Date(at), timeZone), end: toLocalInputValue(new Date(at + hour), timeZone) };
}

/** Local wall-clock text for an instant string with an offset, in the display zone. */
function wall(value: string, timeZone: string): string {
  return toLocalInputValue(new Date(value), timeZone);
}

/**
 * The class timetable: day, week, month, year and schedule views over the LMS's own sessions, kept in
 * step with Google Calendar.
 *
 * The server scopes what arrives (a tutor gets their batches, a student theirs, a guardian or
 * corporate manager their people), so this component never filters by role; it only decides whether
 * to offer changes, and only people who can create, update and delete sessions get them. Everyone else
 * gets a read-only calendar with the same views.
 *
 * As in Google Calendar: drag a class to move it, pull its bottom edge to change its length, drag over
 * empty time (or click a day) to add one, click a class for the details and to edit or delete it. All
 * of it goes through the ordinary session API, so clash checks and audit apply, and afterwards the batch
 * is pushed to Google when the caller may sync.
 */
export default function BatchCalendar({
  batches,
  selected,
  onClearSelection,
}: {
  batches: readonly BatchSummary[];
  selected: BatchSummary | null;
  onClearSelection: () => void;
}) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const queryClient = useQueryClient();
  const calendar = useRef<FullCalendar>(null);
  const canManage = permissions.has("session.create") && permissions.has("session.update") && permissions.has("session.delete");
  const canSync = permissions.has("google.sync");
  const narrow = useSyncExternalStore(subscribeNarrow, () => window.matchMedia(NARROW).matches, () => false);

  const [range, setRange] = useState<{ from: string; to: string; title: string; view: ViewType } | null>(null);
  const [open, setOpen] = useState<CalendarSession | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const batchId = selected?.public_id;

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: [...CALENDAR_KEY, range?.from, range?.to, batchId ?? "all"],
    queryFn: () => api.get<CalendarResponse>("/sessions/calendar", { query: { from: range?.from, to: range?.to, batch_id: batchId } }),
    enabled: range !== null,
    placeholderData: (previous) => previous, // keep what is drawn while the next window loads
  });

  const google = useQuery({
    queryKey: ["google", "status"],
    queryFn: () => api.get<GoogleStatusResponse>("/integrations/google/status"),
    enabled: canSync,
  });
  const googleConnected = canSync && google.data?.connected === true;
  const googleLink = useQuery({
    queryKey: ["google", "batch", open?.batch_id],
    queryFn: () => api.get<{ calendar_url: string | null }>(`/integrations/google/batches/${segment(open?.batch_id ?? "")}`),
    enabled: Boolean(open) && googleConnected,
  });

  const events = useMemo<EventInput[]>(
    () =>
      (data?.items ?? []).map((item) => {
        const colour = `hsl(${batchHue(item.batch_code)} 62% 40%)`;
        return {
          id: item.public_id,
          title: `${item.course_title ?? item.batch_code} (${item.batch_code})`,
          start: item.session_start_time,
          end: item.session_end_time,
          backgroundColor: colour,
          borderColor: colour,
          textColor: "#fff",
          extendedProps: { session: item },
        };
      }),
    [data],
  );

  function refresh(batch: string) {
    void queryClient.invalidateQueries({ queryKey: [...CALENDAR_KEY] });
    void queryClient.invalidateQueries({ queryKey: ["batches"] });
    // Push the batch to Google so the two calendars agree. Best effort: the LMS is the record.
    if (googleConnected) void api.post(`/integrations/google/sync?batch_id=${encodeURIComponent(batch)}`).catch(() => undefined);
  }

  const reschedule = useApiMutation<unknown, { session: CalendarSession; start: string; end: string; revert: () => void }>({
    mutationFn: ({ session, start, end }) =>
      api.patch<unknown>(`/sessions/${segment(session.public_id)}`, { body: { session_start_time: start, session_end_time: end } }),
    success: "Session moved.",
    onSuccess: (_data, { session }) => refresh(session.batch_id),
    // A refused move (a tutor clash, say) puts the class back where it was, and says why.
    onError: (err, { revert }) => {
      revert();
      toast.error(err.message);
    },
  });

  const sync = useApiMutation<unknown, string | undefined>({
    mutationFn: (id) => api.post<unknown>(`/integrations/google/sync${id ? `?batch_id=${encodeURIComponent(id)}` : ""}`),
    onSuccess: () => {
      toast.success("Sync with Google started.");
      // Google's edits are read during the run; show them once it has had time to finish.
      for (const wait of [4000, 10000]) setTimeout(() => void queryClient.invalidateQueries({ queryKey: [...CALENDAR_KEY] }), wait);
    },
  });

  function moved(info: EventDropArg | EventResizeDoneArg) {
    const session = info.event.extendedProps.session as CalendarSession;
    const startStr = info.event.startStr;
    const endStr = info.event.endStr;
    if (!startStr || !endStr) {
      info.revert();
      return;
    }
    reschedule.mutate({ session, start: new Date(startStr).toISOString(), end: new Date(endStr).toISOString(), revert: info.revert });
  }

  function selectRange(info: DateSelectArg) {
    const api_ = calendar.current?.getApi();
    api_?.unselect();
    if (info.view.type === "multiMonthYear") {
      // Nothing sensible to draw a class on in a year; take the person to that day instead.
      api_?.changeView("timeGridDay", info.startStr.slice(0, 10));
      return;
    }
    if (info.allDay) {
      const day = info.startStr.slice(0, 10);
      setEditor({ session: null, start: `${day}T18:00`, end: `${day}T19:00` });
    } else {
      setEditor({ session: null, start: wall(info.startStr, timeZone), end: wall(info.endStr, timeZone) });
    }
  }

  function changeView(type: ViewType) {
    calendar.current?.getApi().changeView(type);
  }

  const view = range?.view ?? (narrow ? "listMonth" : "dayGridMonth");

  return (
    <Card>
      <CardHeader
        title="Class schedule"
        description={
          selected
            ? `Showing ${selected.batch_code} only. Times are in ${timeZone}.`
            : `Every class you can see. Choose a batch above to filter. Times are in ${timeZone}.`
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {selected ? (
              <Badge tone="info">
                {selected.batch_code}
                <button type="button" aria-label="Show every batch" className="ml-1 rounded hover:text-foreground" onClick={onClearSelection}>
                  <X className="size-3" aria-hidden />
                </button>
              </Badge>
            ) : null}
            {canSync && googleConnected ? (
              <Button variant="ghost" size="sm" loading={sync.isPending} onClick={() => sync.mutate(batchId)} title="Read changes made in Google Calendar, and push ours">
                <RefreshCw /> Sync with Google
              </Button>
            ) : null}
            {canManage ? (
              <Button size="sm" onClick={() => setEditor({ session: null, ...nextHour(timeZone) })}>
                <CalendarPlus /> Schedule
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" aria-label="Previous" onClick={() => calendar.current?.getApi().prev()}>
            <ChevronLeft />
          </Button>
          <Button variant="ghost" size="sm" aria-label="Next" onClick={() => calendar.current?.getApi().next()}>
            <ChevronRight />
          </Button>
          <Button variant="secondary" size="sm" onClick={() => calendar.current?.getApi().today()}>
            Today
          </Button>
          <h3 className="ml-2 min-w-32 text-sm font-semibold" aria-live="polite">
            {range?.title}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {isFetching ? (
            <span className="text-xs text-muted-foreground" role="status">
              Loading…
            </span>
          ) : null}
          <div role="group" aria-label="View" className="inline-flex max-w-full overflow-x-auto rounded-lg border border-border p-0.5">
            {VIEWS.map((v) => (
              <Button key={v.type} variant={view === v.type ? "secondary" : "ghost"} size="sm" aria-pressed={view === v.type} onClick={() => changeView(v.type)}>
                {v.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {error && !data ? (
        <div className="p-4">
          <ErrorState error={error} onRetry={() => void refetch()} />
        </div>
      ) : null}

      <div className={cn("p-2 sm:p-3", canManage && "[&_.fc-event]:cursor-grab")}>
        <FullCalendar
          ref={calendar}
          plugins={[dayGridPlugin, timeGridPlugin, listPlugin, multiMonthPlugin, interactionPlugin, luxon3Plugin]}
          timeZone={timeZone}
          initialView={narrow ? "listMonth" : "dayGridMonth"}
          headerToolbar={false}
          firstDay={1}
          height={view === "timeGridDay" || view === "timeGridWeek" ? 680 : "auto"}
          events={events}
          eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
          slotDuration="00:30:00"
          snapDuration="00:15:00"
          scrollTime="08:00:00"
          nowIndicator
          navLinks
          dayMaxEvents={3}
          multiMonthMaxColumns={narrow ? 1 : 3}
          eventInteractive
          longPressDelay={350}
          eventLongPressDelay={350}
          selectLongPressDelay={350}
          allDaySlot={false}
          views={{ timeGridWeek: { dayMinWidth: narrow ? 120 : undefined } }}
          noEventsContent="No classes in this period."
          // Only people who can manage the timetable may change it; for everyone else these stay read-only.
          editable={canManage}
          eventStartEditable={canManage}
          eventDurationEditable={canManage}
          selectable={canManage}
          selectMirror
          datesSet={(arg: DatesSetArg) =>
            setRange({ from: new Date(arg.startStr).toISOString(), to: new Date(arg.endStr).toISOString(), title: arg.view.title, view: arg.view.type as ViewType })
          }
          eventClick={(info: EventClickArg) => {
            info.jsEvent.preventDefault();
            setOpen(info.event.extendedProps.session as CalendarSession);
          }}
          eventDrop={moved}
          eventResize={moved}
          select={selectRange}
        />
      </div>

      {data?.truncated ? (
        <p role="alert" className="border-t border-border px-4 py-2 text-xs text-warning">
          This period has more classes than can be drawn at once. Choose a batch to narrow it.
        </p>
      ) : null}

      <SessionDetailsDialog
        session={open}
        canManage={canManage}
        timeZone={timeZone}
        googleUrl={googleLink.data?.calendar_url ?? null}
        onClose={() => setOpen(null)}
        onEdit={(session) => {
          setOpen(null);
          setEditor({ session, start: "", end: "" });
        }}
        onDeleted={(session) => {
          setOpen(null);
          refresh(session.batch_id);
        }}
      />

      {editor ? (
        <SessionEditorDialog
          key={editor.session?.public_id ?? `new-${editor.start}`}
          state={editor}
          batches={batches}
          selected={selected}
          timeZone={timeZone}
          onClose={() => setEditor(null)}
          onSaved={(batch) => {
            setEditor(null);
            refresh(batch);
          }}
        />
      ) : null}
    </Card>
  );
}
