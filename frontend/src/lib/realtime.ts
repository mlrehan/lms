"use client";

import { useEffect, useRef, useState } from "react";
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

type Kind = "ready" | "reconnect" | "notification.created" | "message.received" | "message.updated";

interface Frame {
  kind: string;
  data?: { type?: string; title?: string } | null;
}

/** What each event invalidates. One place, so a badge cannot go stale because
 *  two components disagreed about which key holds the count. */
const AFFECTED: Record<string, string[][]> = {
  "notification.created": [["unread"], ["notifications", "feed"]],
  "message.received": [["unread"], ["mail", "list"], ["mail", "unread"]],
  "message.updated": [["unread"], ["mail", "list"], ["mail", "unread"]],
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

export function useRealtime(enabled: boolean): { connected: boolean } {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  // Held in a ref so the effect below does not restart every time the
  // connection flips -- restarting it *is* the connection flipping.
  const seen = useRef(0);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;

    const source = new EventSource("/api/backend/realtime/stream");

    const refresh = (frame: Frame) => {
      for (const key of AFFECTED[frame.kind] ?? []) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
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
      }
      if (kind === "message.received") {
        // No sender name: the server does not send one, because who you are
        // allowed to see the name of is decided per reader. The list refetch
        // above fills it in through the endpoint that knows.
        toast("New message");
      }
    };

    source.addEventListener("ready", () => setConnected(true));
    source.addEventListener("notification.created", handle("notification.created"));
    source.addEventListener("message.received", handle("message.received"));
    source.addEventListener("message.updated", handle("message.updated"));

    // The server ends a stream deliberately after its maximum lifetime so that
    // connections drain onto new workers during a rolling deploy. EventSource
    // reopens on its own; this only stops the UI claiming to be live in the gap.
    source.addEventListener("reconnect", () => setConnected(false));

    source.onerror = () => {
      // Fires on every reconnect attempt too, so it is not an error state --
      // it is "not currently connected". The polling fallback covers the gap.
      setConnected(false);
    };

    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled, queryClient]);

  return { connected };
}
