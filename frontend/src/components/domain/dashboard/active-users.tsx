"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useRealtimeLive } from "@/lib/realtime";

import { api } from "@/lib/api/client";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { useDisplayTimeZone } from "@/lib/preferences";
import { cn } from "@/lib/utils";

/**
 * Who is actually using the system.
 *
 * "Online" means a browser is holding its realtime connection open right now,
 * not that a token has not expired yet — the second counts people who left an
 * hour ago, which is why the old panel's numbers could never be trusted.
 *
 * Nobody is marked offline by an event. An entry stops being refreshed and
 * falls out of the window, so a crashed browser, a closed laptop and a dropped
 * network all behave like a clean sign-out, just a minute later.
 */

interface ActiveUserRow {
  public_id: string;
  name: string;
  roles: string[];
  online: boolean;
  location: string | null;
  last_seen_at: string | null;
  last_login_at: string | null;
}

interface PresencePayload {
  online: number;
  total: number;
  window_seconds: number;
  realtime_enabled: boolean;
  users: { items: ActiveUserRow[]; total: number };
}

type Filter = "online" | "offline" | "all";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "online", label: "Online" },
  { value: "offline", label: "Offline" },
  { value: "all", label: "All" },
];

export function ActiveUsers() {
  const [filter, setFilter] = useState<Filter>("online");
  const timeZone = useDisplayTimeZone();

  const live = useRealtimeLive();
  const query = useQuery<PresencePayload>({
    queryKey: ["presence", filter],
    queryFn: () => api.get<PresencePayload>(`/presence/active?state=${filter}&limit=25`),
    // Presence has a one-minute window, so asking more often than that tells
    // you nothing new; asking less often lets the panel lie for a while.
    // Arrivals and clean departures now arrive as `presence` events, so
    // this is left to catch the one case nothing can announce: a browser
    // that was killed, whose window simply lapses with no code running.
    refetchInterval: live ? 90_000 : 30_000,
    refetchOnWindowFocus: true,
  });

  return (
    <Card>
      <CardHeader
        title="Active users"
        description={
          query.data
            ? `${query.data.online} online now · counted from live connections, not open sessions`
            : "Who is using the system now"
        }
        actions={
          <div
            role="group"
            aria-label="Filter by presence"
            className="flex rounded-md border border-border-subtle p-0.5"
          >
            {FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFilter(option.value)}
                aria-pressed={filter === option.value}
                className={cn(
                  "rounded px-2 py-0.5 text-2xs font-medium transition-colors duration-150",
                  filter === option.value
                    ? "bg-surface-muted text-foreground"
                    : "text-subtle-foreground hover:text-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      />

      {query.isPending ? (
        <LoadingState label="Loading active users" />
      ) : query.isError ? (
        <ErrorState error={query.error} />
      ) : !query.data.realtime_enabled ? (
        /* Stated rather than shown as zero: with the realtime stream switched
           off nobody *can* be reported online, and "0 online" would read as a
           claim that nobody is working. */
        <p className="px-4 py-10 text-center text-xs text-subtle-foreground">
          Live presence is switched off for this deployment, so nobody can be shown as online.
        </p>
      ) : query.data.users.items.length === 0 ? (
        <p className="px-4 py-10 text-center text-xs text-subtle-foreground">
          {filter === "online" ? "Nobody is online right now." : "Nobody to show."}
        </p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {query.data.users.items.map((user) => (
            <li
              key={user.public_id}
              className="flex items-center justify-between gap-3 px-4 py-2 transition-colors duration-200 hover:bg-surface-muted/60"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <span
                  aria-hidden
                  className={cn(
                    "size-2 shrink-0 rounded-full",
                    user.online ? "bg-emerald-500" : "bg-border-strong",
                  )}
                />
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium">{user.name}</p>
                  <p className="truncate text-2xs text-subtle-foreground">
                    {user.roles.join(", ") || "No role"}
                    {user.location ? ` · ${user.location}` : ""}
                  </p>
                </div>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-2xs font-medium text-muted-foreground">
                  {user.online ? (
                    <Badge className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                      Online
                    </Badge>
                  ) : user.last_login_at ? (
                    formatRelative(user.last_login_at)
                  ) : (
                    "Never signed in"
                  )}
                </p>
                <p className="text-2xs tabular-nums text-subtle-foreground">
                  {user.online
                    ? "active now"
                    : user.last_login_at
                      ? formatDateTime(user.last_login_at, { timeZone })
                      : ""}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
