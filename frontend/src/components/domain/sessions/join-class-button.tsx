"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Loader2, Video } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { SessionJoinResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Enter a live class.
 *
 * The meeting link is **not** in the session payload for anyone who cannot edit
 * the session, so this button has nothing to open until the server hands it
 * over. That is the point: a disabled button is a suggestion, and a link sitting
 * in a network response that the page merely declines to render is no rule at
 * all. `POST /sessions/{id}/join` re-checks the window, re-checks the caller's
 * place in the batch, writes an audit row, and only then returns a URL.
 *
 * So the countdown below is cosmetic by design and says nothing the visitor
 * could not work out from the timetable. Pressing the button one second early
 * is refused by the API, not by this component.
 */

function remaining(target: Date, now: Date): string {
  const seconds = Math.max(0, Math.round((target.getTime() - now.getTime()) / 1000));
  const days = Math.floor(seconds / 86400);
  if (days >= 1) return days === 1 ? "tomorrow" : `in ${days} days`;

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours >= 1) return `in ${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes >= 1) return `in ${minutes} min`;
  return "in under a minute";
}

export function JoinClassButton({
  sessionId,
  canJoinNow,
  opensAt,
  closesAt,
  className,
  size = "sm",
}: {
  sessionId: string;
  /** The server's answer, not the component's guess. */
  canJoinNow: boolean;
  opensAt?: string | null;
  closesAt?: string | null;
  className?: string;
  size?: "xs" | "sm" | "md";
}): ReactNode {
  const [joining, setJoining] = useState(false);
  // Ticks only while a countdown is actually on screen; a class that is
  // joinable, finished, or unscheduled needs no timer at all.
  const [now, setNow] = useState(() => new Date());

  const opens = useMemo(() => (opensAt ? new Date(opensAt) : null), [opensAt]);
  const closes = useMemo(() => (closesAt ? new Date(closesAt) : null), [closesAt]);
  const counting = !canJoinNow && opens !== null && opens > now;

  useEffect(() => {
    if (!counting) return;
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, [counting]);

  if (!opens) return null; // nothing scheduled: there is no door to open

  const finished = closes !== null && closes < now && !canJoinNow;

  async function join(): Promise<void> {
    setJoining(true);
    try {
      const ticket = await api.post<SessionJoinResponse>(`/sessions/${sessionId}/join`);
      // Opened from the click handler's own task so the browser still counts
      // this as user-initiated; opening after an await is what popup blockers
      // exist to stop, so the window is opened with the URL in hand rather
      // than pre-opened and redirected.
      window.open(ticket.meeting_link, "_blank", "noopener,noreferrer");
      if (ticket.joined_outside_window) {
        toast.info("Joined outside the scheduled window", {
          description: "This was allowed by your override permission and has been recorded.",
        });
      }
    } catch (error) {
      // The server's own message: "not open to join yet", "no meeting link has
      // been added", "this class was cancelled" are three different problems
      // and only one of them is the person's to fix.
      toast.error("Could not join", { description: (error as Error).message });
    } finally {
      setJoining(false);
    }
  }

  if (finished) {
    return (
      <span className={cn("text-2xs text-subtle-foreground", className)}>Class has ended</span>
    );
  }

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Button
        type="button"
        size={size}
        onClick={join}
        disabled={!canJoinNow || joining}
        title={
          canJoinNow
            ? "Open the meeting"
            : `The class opens to join 30 minutes before it starts (${remaining(opens, now)})`
        }
      >
        {joining ? <Loader2 className="size-3.5 animate-spin" /> : <Video className="size-3.5" />}
        {joining ? "Joining…" : "Join class"}
      </Button>
      {counting ? (
        <span className="text-2xs tabular-nums text-subtle-foreground">
          Opens {remaining(opens, now)}
        </span>
      ) : null}
    </div>
  );
}
