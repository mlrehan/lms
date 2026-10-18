"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { useRealtimeLive } from "@/lib/realtime";
import { Clock, MapPin, Users, Video } from "lucide-react";

import { api } from "@/lib/api/client";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { JoinClassButton } from "@/components/domain/sessions/join-class-button";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

/**
 * Today's classes.
 *
 * Cards rather than a table because the useful unit here is one class, read at
 * a glance, and because this panel is the one thing on the dashboard somebody
 * acts on in the next few minutes.
 *
 * The meeting link is deliberately absent from the payload: the row says
 * whether a door exists and whether it is open, and `JoinClassButton` asks the
 * API to open it. So a card cannot leak a link that outlives the join window,
 * and the window is enforced where it can be enforced.
 */

export interface TodayClass {
  public_id: string;
  course_title: string;
  batch_code: string;
  session_number: number | null;
  tutor_name: string | null;
  enrolled: number;
  starts_at: string | null;
  ends_at: string | null;
  duration_minutes: number | null;
  platform: string | null;
  classroom: string | null;
  status: "upcoming" | "live" | "ended" | "cancelled";
  has_meeting_link: boolean;
  join_opens_at: string | null;
  join_closes_at: string | null;
  can_join_now: boolean;
}

interface TodayPayload {
  timezone: string;
  date: string;
  classes: TodayClass[];
}

const STATUS: Record<TodayClass["status"], { label: string; tone: string }> = {
  live: { label: "In progress", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" },
  upcoming: { label: "Upcoming", tone: "bg-primary/10 text-primary" },
  ended: { label: "Ended", tone: "bg-surface-muted text-subtle-foreground" },
  cancelled: { label: "Cancelled", tone: "bg-destructive/10 text-destructive" },
};

export function TodayClasses() {
  const timeZone = useDisplayTimeZone();
  const live = useRealtimeLive();
  const query = useQuery<TodayPayload>({
    queryKey: ["dashboard", "today"],
    queryFn: () => api.get<TodayPayload>("/dashboard/today"),
    // A class starting, or a link appearing, matters within a minute or two.
    // The `academic` topic covers a session being added, moved or
    // cancelled; this only has to catch a clock crossing into the next
    // class, which no write announces.
    refetchInterval: live ? 300_000 : 60_000,
    refetchOnWindowFocus: true,
  });

  return (
    <Card>
      <CardHeader
        title="Today's classes"
        description={
          query.data
            ? `${query.data.classes.length === 0 ? "Nothing" : query.data.classes.length} scheduled · times in ${query.data.timezone}`
            : "Scheduled for today"
        }
      />
      {query.isPending ? (
        <LoadingState label="Loading today's classes" />
      ) : query.isError ? (
        <ErrorState error={query.error} />
      ) : query.data.classes.length === 0 ? (
        <p className="px-4 py-10 text-center text-xs text-subtle-foreground">
          No classes scheduled today.
        </p>
      ) : (
        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {query.data.classes.map((item) => (
            <article
              key={item.public_id}
              className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface p-3.5 transition-shadow duration-200 hover:shadow-xs"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link
                    href={`/sessions/${item.public_id}`}
                    className="block truncate text-[13px] font-medium decoration-border-strong underline-offset-2 hover:underline"
                  >
                    {item.course_title || "Untitled course"}
                  </Link>
                  <p className="mt-0.5 truncate text-2xs text-subtle-foreground">
                    Batch {item.batch_code}
                    {item.session_number ? ` · Session ${item.session_number}` : ""}
                  </p>
                </div>
                <Badge className={cn("shrink-0", STATUS[item.status].tone)}>
                  {STATUS[item.status].label}
                </Badge>
              </div>

              <dl className="space-y-1 text-2xs text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <Clock className="size-3 shrink-0 text-subtle-foreground" aria-hidden />
                  <dd className="tabular-nums">
                    {formatDateTime(item.starts_at, { timeZone })}
                    {item.duration_minutes ? ` · ${item.duration_minutes} min` : ""}
                  </dd>
                </div>
                {item.tutor_name ? (
                  <div className="flex items-center gap-1.5">
                    <Users className="size-3 shrink-0 text-subtle-foreground" aria-hidden />
                    <dd className="truncate">
                      {item.tutor_name} · {item.enrolled} enrolled
                    </dd>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <Users className="size-3 shrink-0 text-subtle-foreground" aria-hidden />
                    <dd>{item.enrolled} enrolled</dd>
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  {item.has_meeting_link ? (
                    <Video className="size-3 shrink-0 text-subtle-foreground" aria-hidden />
                  ) : (
                    <MapPin className="size-3 shrink-0 text-subtle-foreground" aria-hidden />
                  )}
                  <dd className="truncate">
                    {item.classroom || item.platform || "No location set"}
                  </dd>
                </div>
              </dl>

              <div className="mt-auto flex items-center justify-between gap-2 pt-1">
                {item.has_meeting_link ? (
                  <JoinClassButton
                    sessionId={item.public_id}
                    canJoinNow={item.can_join_now}
                    opensAt={item.join_opens_at}
                    closesAt={item.join_closes_at}
                    size="xs"
                  />
                ) : (
                  /* Said plainly rather than shown as a dead button: there is
                     no link on this class, which is a different thing from a
                     link that has not opened yet. */
                  <span className="text-2xs text-subtle-foreground">No meeting link</span>
                )}
                <Link
                  href={`/sessions/${item.public_id}`}
                  className="shrink-0 rounded-md border border-border-subtle px-2 py-1 text-2xs font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground"
                >
                  Details
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </Card>
  );
}
