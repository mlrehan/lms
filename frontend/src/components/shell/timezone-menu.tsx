"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Popover } from "@base-ui/react/popover";
import { Check, ChevronDown, Globe, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import type { TimeZoneResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { InlineSpinner } from "@/components/ui/states";
import { CURRENT_USER_KEY, useSession } from "@/lib/auth/session";
import { usePreferences, useDisplayTimeZone } from "@/lib/preferences";
import { browserTimeZone, describeTimeZone, formatDateTime, isValidTimeZone } from "@/lib/format/datetime";
import { useNow } from "@/lib/format/use-now";
import { cn } from "@/lib/utils";

/** `GMT+6`, `GMT+5:30`, `GMT` for a zone right now. */
function shortOffset(timeZone: string, at: Date): string {
  try {
    return new Intl.DateTimeFormat("en-GB", { timeZone, timeZoneName: "shortOffset" }).formatToParts(at).find((p) => p.type === "timeZoneName")?.value ?? "";
  } catch {
    return "";
  }
}

/** Every IANA zone the browser knows, so a zone is never missing just because a table does not list it. */
function allBrowserZones(): string[] {
  try {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
    return supported ? supported("timeZone") : [];
  } catch {
    return [];
  }
}

/**
 * The display time zone, in the top bar: always visible, searchable, and already set to the zone in force.
 *
 * Everything the API returns is UTC and this only changes how it is rendered, so choosing a zone re-draws
 * every time in the console at once (the calendar, lists, dialogs all read `useDisplayTimeZone`). The
 * choice applies to this browser immediately; "Save as my default" writes it to the profile so it also
 * follows the account to other devices. Precedence, unchanged: this choice, then the profile, then the browser.
 */
export function TimeZoneMenu(): ReactNode {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const { user } = useSession();
  const queryClient = useQueryClient();
  const active = useDisplayTimeZone();
  const { timeZoneOverride, setTimeZoneOverride } = usePreferences();
  const listRef = useRef<HTMLUListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const { data: zones, isFetching } = useQuery({
    queryKey: ["geo", "timezones"],
    queryFn: () => api.get<TimeZoneResponse[]>("/geo/timezones"),
    enabled: open,
    staleTime: 24 * 60 * 60 * 1000,
  });

  // A clock in server-rendered HTML is wrong by the time it reaches the browser, so null until hydration.
  const now = useNow();

  const zoneCodes = zones;
  const accountTimeZone = user?.timezone && isValidTimeZone(user.timezone) ? user.timezone : null;
  const browserZone = browserTimeZone();
  // Where the sign-in address says they are: worked out by the server at sign-in (services/locale_service.py).
  const suggestedTimeZone = user?.detected_timezone ?? null;

  const options = useMemo(() => {
    const names = new Set<string>(allBrowserZones());
    for (const zone of zoneCodes ?? []) if (zone.code && isValidTimeZone(zone.code)) names.add(zone.code);
    names.add(browserZone);
    names.add(active);
    if (accountTimeZone) names.add(accountTimeZone);
    const at = now ?? new Date();
    const term = filter.trim().toLowerCase();
    return [...names]
      .map((name) => ({ name, label: describeTimeZone(name, at) }))
      // Matches the name, the region and the offset, so "dhaka", "asia" and "+6" all find Asia/Dhaka.
      .filter(({ name, label }) => !term || name.toLowerCase().includes(term) || label.toLowerCase().includes(term) || label.replace(/\s/g, "").toLowerCase().includes(term.replace(/\s/g, "")))
      .sort((a, b) => (a.name === active ? -1 : b.name === active ? 1 : a.name.localeCompare(b.name)))
      .slice(0, 300);
  }, [zoneCodes, filter, accountTimeZone, browserZone, active, now]);

  const saveDefault = useApiMutation<unknown, string>({
    mutationFn: (timeZone) => api.patch<unknown>("/auth/me", { body: { timezone: timeZone } }),
    success: "Saved as your default time zone.",
    invalidate: [[...CURRENT_USER_KEY]],
    onSuccess: () => setTimeZoneOverride(null), // the profile now says it, so no local override is needed
  });

  useEffect(() => {
    if (open) {
      // Start each visit fresh, with the cursor in the search box.
      const id = requestAnimationFrame(() => searchRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
    return undefined;
  }, [open]);

  function choose(name: string) {
    // Picking the profile's own zone is "follow the profile", not a second, competing setting.
    setTimeZoneOverride(name === accountTimeZone ? null : name);
    void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    toast.success(`Showing times in ${name.replace(/_/g, " ")}.`);
    setOpen(false);
    setFilter("");
  }

  function onSearchKey(event: KeyboardEvent<HTMLInputElement>) {
    const buttons = () => Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      buttons()[0]?.focus();
    } else if (event.key === "Enter" && options[0]) {
      event.preventDefault();
      choose(options[0].name);
    }
  }

  function onListKey(event: KeyboardEvent<HTMLUListElement>) {
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      buttons[Math.min(at + 1, buttons.length - 1)]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (at <= 0) searchRef.current?.focus();
      else buttons[at - 1]?.focus();
    }
  }

  const offset = shortOffset(active, now ?? new Date());
  const source = timeZoneOverride ? "Chosen here" : accountTimeZone ? "From your profile" : "From this browser";
  const differsFromProfile = accountTimeZone !== active;

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        render={
          <button
            type="button"
            aria-label={`Display time zone: ${active}. Change`}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border bg-surface px-2 text-sm transition-colors hover:bg-muted"
          />
        }
      >
        <Globe className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="hidden max-w-40 truncate font-medium md:inline">{active.replace(/_/g, " ")}</span>
        <span className="text-xs tabular-nums text-muted-foreground">{offset}</span>
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Positioner align="end" sideOffset={6} className="z-50 outline-none">
          <Popover.Popup
            className={cn(
              "w-[min(22rem,calc(100vw-1.5rem))] origin-(--transform-origin) rounded-lg border border-border bg-surface shadow-lg outline-none",
              "data-[open]:animate-[lms-fade-in_120ms_ease-out] data-[closed]:animate-[lms-fade-out_100ms_ease-in]",
            )}
          >
            <div className="space-y-1 border-b border-border px-3 py-2.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Display time zone</p>
              <p className="text-sm font-medium">{describeTimeZone(active, now ?? undefined)}</p>
              <p className="text-xs text-muted-foreground tabular-nums">{now ? formatDateTime(now, { timeZone: active }) : " "}</p>
              <div className="flex flex-wrap gap-1 pt-0.5">
                <Badge tone={timeZoneOverride ? "primary" : accountTimeZone ? "info" : "neutral"}>{source}</Badge>
                {suggestedTimeZone && suggestedTimeZone !== active && suggestedTimeZone !== browserZone ? <Badge tone="warning">Network suggests {suggestedTimeZone}</Badge> : null}
              </div>
              {browserZone !== active ? (
                <button type="button" className="text-xs text-primary hover:underline" onClick={() => choose(browserZone)}>
                  Your browser is in {browserZone.replace(/_/g, " ")} — use that
                </button>
              ) : null}
            </div>

            <div className="relative border-b border-border p-2">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <input
                ref={searchRef}
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                onKeyDown={onSearchKey}
                placeholder="Search city, region or offset (e.g. Dhaka, +6)"
                aria-label="Search time zones"
                className="h-9 w-full rounded-md border border-border bg-surface pl-8 pr-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              />
            </div>

            <ul ref={listRef} onKeyDown={onListKey} role="listbox" aria-label="Time zones" className="max-h-64 overflow-y-auto scrollbar-thin py-1">
              {isFetching && options.length === 0 ? (
                <li className="flex justify-center p-6">
                  <InlineSpinner />
                </li>
              ) : options.length === 0 ? (
                <li className="px-3 py-6 text-center text-sm text-muted-foreground">No time zone matches “{filter}”.</li>
              ) : (
                options.map(({ name, label }) => (
                  <li key={name} role="option" aria-selected={name === active}>
                    <button
                      type="button"
                      onClick={() => choose(name)}
                      className={cn("flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none", name === active && "bg-primary/5 font-medium")}
                    >
                      <span className="truncate">{label}</span>
                      {name === active ? <Check className="size-4 shrink-0 text-primary" aria-hidden /> : null}
                    </button>
                  </li>
                ))
              )}
            </ul>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
              {timeZoneOverride ? (
                <Button variant="ghost" size="sm" onClick={() => { setTimeZoneOverride(null); setOpen(false); }}>
                  Back to {accountTimeZone ? "my profile" : "browser"}
                </Button>
              ) : (
                <span className="text-xs text-muted-foreground">Times are stored in UTC.</span>
              )}
              {differsFromProfile ? (
                <Button size="sm" variant="secondary" loading={saveDefault.isPending} onClick={() => saveDefault.mutate(active)}>
                  Save as my default
                </Button>
              ) : null}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
