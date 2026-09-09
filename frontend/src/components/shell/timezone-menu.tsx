"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Globe } from "lucide-react";
import { api } from "@/lib/api/client";
import type { TimeZoneResponse } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Badge } from "@/components/ui/primitives";
import { InlineSpinner } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { usePreferences, useDisplayTimeZone } from "@/lib/preferences";
import { browserTimeZone, describeTimeZone, formatDateTime } from "@/lib/format/datetime";

interface LocaleHint {
  ip: string | null;
  timezone: string | null;
  country_name: string | null;
  source: string;
}

/**
 * The timezone switcher (spec section 53).
 *
 * Everything the API returns is UTC; this only changes how it is rendered.
 * The candidate list comes from `GET /geo/timezones`, the institution's own
 * table -- not a hard-coded list that would drift from the values the profile
 * form is allowed to store.
 */
export function TimeZoneMenu(): ReactNode {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const { user } = useSession();
  const active = useDisplayTimeZone();
  const { timeZoneOverride, setTimeZoneOverride } = usePreferences();

  const { data: zones, isFetching } = useQuery({
    queryKey: ["geo", "timezones"],
    queryFn: () => api.get<TimeZoneResponse[]>("/geo/timezones"),
    enabled: open,
    // The IANA table does not change while someone has the console open.
    staleTime: 24 * 60 * 60 * 1000,
  });

  // Only asked for when the person opens the picker: an IP lookup on every
  // page load would send an address to two third parties to answer a question
  // the browser has already answered locally.
  const { data: hint } = useQuery({
    queryKey: ["locale-hint"],
    queryFn: async (): Promise<LocaleHint> => {
      const response = await fetch("/api/locale", { credentials: "same-origin" });
      return (await response.json()) as LocaleHint;
    },
    enabled: open,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    // Rendered only after mount: a clock in server-rendered HTML is wrong by
    // the time it reaches the browser and causes a hydration mismatch.
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const options = useMemo(() => {
    const names = new Set<string>();
    for (const zone of zones ?? []) if (zone.code) names.add(zone.code);
    // The browser's own zone is always offered, even when the institution's
    // table does not list it -- otherwise the most accurate answer available
    // is the one option the person cannot pick.
    names.add(browserTimeZone());
    if (user?.timezone) names.add(user.timezone);
    if (hint?.timezone) names.add(hint.timezone);
    const term = filter.trim().toLowerCase();
    return [...names]
      .filter((name) => !term || name.toLowerCase().includes(term))
      .sort()
      .slice(0, 400);
  }, [zones, filter, user?.timezone, hint?.timezone]);

  return (
    <>
      <Button variant="ghost" size="icon" aria-label="Display timezone" onClick={() => setOpen(true)}>
        <Globe />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Display timezone"
            description="Times are stored in UTC and shown in the timezone you choose here. This is a display setting for this browser only; it does not change your profile."
          />

          <div className="space-y-3">
            <div className="rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm">
              <p className="font-medium">{describeTimeZone(active, now ?? undefined)}</p>
              <p className="text-xs text-muted-foreground">
                {now ? formatDateTime(now, { timeZone: active }) : " "}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {timeZoneOverride ? (
                  <Badge tone="primary">Chosen here</Badge>
                ) : user?.timezone ? (
                  <Badge tone="info">From your profile</Badge>
                ) : (
                  <Badge tone="neutral">From this browser</Badge>
                )}
                {hint?.timezone && hint.timezone !== active ? (
                  <Badge tone="warning">Your network suggests {hint.timezone}</Badge>
                ) : null}
              </div>
            </div>

            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter timezones"
              aria-label="Filter timezones"
            />

            <div className="max-h-72 overflow-y-auto scrollbar-thin rounded-lg border border-border">
              {isFetching && options.length === 0 ? (
                <div className="flex justify-center p-6">
                  <InlineSpinner />
                </div>
              ) : (
                <ul>
                  {options.map((name) => (
                    <li key={name}>
                      <button
                        type="button"
                        onClick={() => {
                          setTimeZoneOverride(name);
                          setOpen(false);
                        }}
                        className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-muted"
                      >
                        <span className="truncate">{describeTimeZone(name, now ?? undefined)}</span>
                        {name === active ? <Check className="size-4 shrink-0 text-primary" /> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => {
                setTimeZoneOverride(null);
                setOpen(false);
              }}
            >
              Use my profile / browser
            </Button>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
