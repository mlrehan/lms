"use client";

import { playNotificationTone, type SoundMode } from "@/lib/notification-sound";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

/**
 * The live connection, opened once for the whole signed-in app.
 *
 * `EventSource`, not a `fetch` stream, for one reason that decides it: this
 * console deliberately never holds a token in the browser, so every call goes
 * through the same-origin BFF proxy, which attaches the bearer server-side from
 * `httpOnly` cookies. `EventSource` sends those cookies on a same-origin URL and
 * gets automatic reconnection with backoff for free. A `fetch` stream would
 * mean writing the reconnect loop by hand to gain an `Authorization` header this
 * app does not have anything to put in.
 *
 * **Events are hints, never content.** The server sends a kind and, for a
 * notification, a title it composed for this recipient. Everything else is
 * re-read through the ordinary endpoints, which is what keeps the contact-detail
 * masking in `core/privacy.py` in force -- a payload assembled at write time
 * would have been assembled for the wrong viewer.
 */

type Kind =
  | "ready"
  | "reconnect"
  | "notification.created"
  | "message.received"
  | "message.updated"
  | "data.changed";

interface Frame {
  kind: string;
  data?: { type?: string; title?: string } | null;
  /** Set on `data.changed` only: which shared vocabulary moved. */
  topic?: string | null;
}

/**
 * What a topic event invalidates.
 *
 * Keys are prefixes: TanStack matches `["dashboard"]` against
 * `["dashboard", "today"]`, and `["presence"]` against `["presence", filter]`,
 * so one entry covers every variant rather than needing a list that goes stale
 * whenever somebody adds a filter.
 */
const TOPIC_KEYS: Record<string, string[][]> = {
  directory: [["sidebar-counts"], ["dashboard"]],
  academic: [["sidebar-counts"], ["dashboard"]],
  assessment: [["sidebar-counts"], ["dashboard"]],
  announcements: [["sidebar-counts"], ["dashboard"]],
  // Only the presence list. A person arriving does not change any count, and
  // refetching the dashboard for it would make every sign-in cost every
  // administrator a query for nothing.
  presence: [["presence"]],
};

/**
 * How long one topic must wait before it may trigger a second refetch.
 *
 * **Leading edge**, so the first event of a burst refetches immediately and
 * the screen is live; the rest of the burst collapses into one trailing
 * refetch when the window closes. Without this, a sync importing three hundred
 * courses -- one transaction each -- would be three hundred refetches of the
 * sidebar and the dashboard, in every open browser, for one final answer.
 *
 * The server already coalesces within a transaction. This is the other half:
 * coalescing *across* them, which only the client can see.
 */
const REFETCH_WINDOW_MS = 1_000;

/** What each event invalidates. One place, so a badge cannot go stale because
 *  two components disagreed about which key holds the count. */
const AFFECTED: Record<string, string[][]> = {
  // `sidebar-counts` is on every one of these deliberately. Almost everything
  // that moves a badge also notifies somebody -- work set, work graded, an
  // exam scheduled, an enrolment made -- so the notification the recipient
  // already receives is the cheapest possible signal that their counts are
  // stale, and it needs no new event kind and no new publisher.
  //
  // What this does *not* cover is a change that notifies nobody, such as an
  // administrator editing an enrolment. Those correct on the next refetch
  // rather than instantly; the hook refetches on window focus for that reason.
  // `dashboard` is on these too: its KPIs count unread items and recent
  // activity, so an arrival moves them exactly as it moves a badge. It was
  // missing, which is why the dashboard was the one surface that genuinely
  // needed a page refresh.
  "notification.created": [
    ["unread"],
    ["notifications", "feed"],
    ["sidebar-counts"],
    ["dashboard"],
  ],
  "message.received": [
    ["unread"],
    ["mail", "list"],
    ["mail", "unread"],
    ["sidebar-counts"],
    ["dashboard"],
  ],
  "message.updated": [
    ["unread"],
    ["mail", "list"],
    ["mail", "unread"],
    ["sidebar-counts"],
    ["dashboard"],
  ],
};

function parse(event: MessageEvent): Frame | null {
  try {
    return { ...(JSON.parse(event.data) as Frame), kind: event.type };
  } catch {
    // A frame we cannot read is a server-side bug or a half-deployed format
    // change. Dropping it costs a delayed badge; throwing here would kill the
    // connection for everything else.
    return null;
  }
}

/* -------------------------------------------------------------------------
 * Sharing "is the stream up?" with screens that are not the topbar.
 *
 * The connection is opened in the topbar on purpose -- it is the one component
 * mounted on every signed-in screen -- so the dashboard and its panels are
 * siblings of it, not children, and cannot read its state through context
 * without moving the hook somewhere it does not belong.
 *
 * `useSyncExternalStore` over a module-level value is React's own answer to
 * this: one subscription, no provider, no re-render of the tree when the flag
 * flips. What reads it is polling intervals -- a screen asks "am I being told
 * about changes, or do I have to go and look?" -- so being a few milliseconds
 * late is of no consequence.
 * ------------------------------------------------------------------------- */

let streamLive = false;
const listeners = new Set<() => void>();

function setStreamLive(value: boolean): void {
  if (streamLive === value) return;
  streamLive = value;
  for (const listener of listeners) listener();
}

/**
 * Whether the live stream is currently connected.
 *
 * Screens use it to choose a polling interval: a long backstop while events
 * are arriving, a short one when they are not. It is deliberately not used to
 * decide whether to *show* anything -- a page that renders differently
 * depending on a transport detail is a page that flickers on every reconnect.
 */
export function useRealtimeLive(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => streamLive,
    // The server render has no connection, and claiming otherwise would
    // hydrate with the wrong interval.
    () => false,
  );
}

export function useRealtime(
  enabled: boolean,
  /**
   * How loudly to announce an arrival, from the signed-in person's own
   * preference. Read through a ref below so changing it does not restart
   * the connection -- restarting it *is* the connection flipping, and a
   * reconnect costs a `ready` round trip for a setting that changes once.
   */
  sound: SoundMode = "subtle",
): { connected: boolean } {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  // Held in a ref so the effect below does not restart every time the
  // connection flips -- restarting it *is* the connection flipping.
  const seen = useRef(0);
  const soundRef = useRef(sound);
  // Synced in an effect, not during render: writing a ref while rendering
  // is a React rule violation and is unsafe under concurrent rendering,
  // where a render may be thrown away after the write.
  useEffect(() => {
    soundRef.current = sound;
  }, [sound]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;

    const source = new EventSource("/api/backend/realtime/stream");

    /** When each topic last caused a refetch, and its pending trailing timer. */
    const lastRun = new Map<string, number>();
    const timers = new Map<string, ReturnType<typeof setTimeout>>();

    const invalidate = (keys: string[][]) => {
      for (const key of keys) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    };

    /** Leading-edge throttle per topic. See `REFETCH_WINDOW_MS`. */
    const throttled = (topic: string, keys: string[][]) => {
      const now = Date.now();
      const previous = lastRun.get(topic) ?? 0;
      const elapsed = now - previous;

      if (elapsed >= REFETCH_WINDOW_MS) {
        lastRun.set(topic, now);
        invalidate(keys);
        return;
      }
      // Inside the window. One trailing refetch is enough however many events
      // arrive, so an existing timer is left to fire rather than reset -- a
      // reset on every event is how a throttle turns into "never runs" under
      // a continuous stream.
      if (timers.has(topic)) return;
      timers.set(
        topic,
        setTimeout(() => {
          timers.delete(topic);
          lastRun.set(topic, Date.now());
          invalidate(keys);
        }, REFETCH_WINDOW_MS - elapsed),
      );
    };

    const refresh = (frame: Frame) => {
      if (frame.kind === "data.changed") {
        const topic = frame.topic;
        // An unknown topic is a newer server talking to an older console.
        // Ignoring it costs a late badge; guessing would invalidate
        // everything on every event.
        if (!topic) return;
        const keys = TOPIC_KEYS[topic];
        if (keys) throttled(topic, keys);
        return;
      }
      // Personal events are never throttled: there is one recipient, they are
      // rare, and a chime that arrives before its badge looks broken.
      invalidate(AFFECTED[frame.kind] ?? []);
    };

    const handle = (kind: Kind) => (event: MessageEvent) => {
      const frame = parse(event);
      if (!frame) return;
      refresh({ ...frame, kind });
      seen.current += 1;

      if (kind === "notification.created" && frame.data?.title) {
        // The title was composed by the server for this recipient, so it
        // carries nothing this person is not already entitled to read.
        toast(frame.data.title);
        // Only when this tab is visible -- `playNotificationTone` checks. If
        // it is not, the push notification announces this with the operating
        // system's own sound, and doing both is what makes people switch
        // notifications off altogether.
        playNotificationTone(soundRef.current);
      }
      if (kind === "message.received") {
        // No sender name: the server does not send one, because who you are
        // allowed to see the name of is decided per reader. The list refetch
        // above fills it in through the endpoint that knows.
        toast("New message");
      }
    };

    source.addEventListener("ready", () => {
      setConnected(true);
      setStreamLive(true);
    });
    source.addEventListener("notification.created", handle("notification.created"));
    source.addEventListener("message.received", handle("message.received"));
    source.addEventListener("message.updated", handle("message.updated"));
    source.addEventListener("data.changed", handle("data.changed"));

    // The server ends a stream deliberately after its maximum lifetime so that
    // connections drain onto new workers during a rolling deploy. EventSource
    // reopens on its own; this only stops the UI claiming to be live in the gap.
    source.addEventListener("reconnect", () => {
      setConnected(false);
      setStreamLive(false);
    });

    source.onerror = () => {
      // Fires on every reconnect attempt too, so it is not an error state --
      // it is "not currently connected". The polling fallback covers the gap.
      setConnected(false);
      setStreamLive(false);
    };

    return () => {
      source.close();
      // A pending trailing refetch would otherwise fire against a QueryClient
      // this component no longer belongs to.
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
      setConnected(false);
      setStreamLive(false);
    };
  }, [enabled, queryClient]);

  return { connected };
}
