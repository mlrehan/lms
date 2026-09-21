"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PageUserSummary, UserSummary } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { InlineSpinner } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

/**
 * Pick a person by name instead of pasting a UUID.
 *
 * `GET /users` supports a server-side `query` and a `role` filter, so this
 * searches the institution rather than filtering a page of results that were
 * already fetched -- the difference between finding someone in a roster of
 * 10,000 and finding them only if they happened to be in the first 25.
 *
 * A caller without `user.read` cannot search at all. Rather than showing an
 * empty picker that looks broken, it degrades to a plain identifier field,
 * which still works for someone who was given an id to enter.
 */
export function UserPicker({
  value,
  onChange,
  role,
  placeholder = "Select a person",
  disabled,
  allowClear = true,
  id,
}: {
  value: string | null;
  onChange: (userId: string | null, user: UserSummary | null) => void;
  /** Restrict to holders of a role, e.g. `TUTOR` for a session's tutor. */
  role?: string;
  placeholder?: string;
  disabled?: boolean;
  allowClear?: boolean;
  id?: string;
}): ReactNode {
  const { permissions } = useSession();
  const canSearch = permissions.has("user.read");
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [selected, setSelected] = useState<UserSummary | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), 250);
    return () => clearTimeout(timer);
  }, [term]);

  // Forget the remembered label when the caller clears the field from
  // outside. Done during render rather than in an effect so the stale name is
  // never painted after the value has already gone.
  const [lastValue, setLastValue] = useState(value);
  if (lastValue !== value) {
    setLastValue(value);
    if (!value) setSelected(null);
  }

  const { data, isFetching } = useQuery({
    queryKey: ["users", "picker", debounced, role ?? null],
    queryFn: () =>
      api.get<PageUserSummary>("/users", {
        query: { query: debounced || undefined, role, limit: 20, status: "ACTIVE" },
      }),
    enabled: open && canSearch,
    staleTime: 20_000,
  });

  // A value that arrived from outside (a default tutor, an existing session) has no remembered name, so it is
  // looked up. Showing the raw id there would put a UUID where a person's name belongs.
  const needsLookup = canSearch && !!value && (!selected || selected.public_id !== value);
  const known = useQuery({
    queryKey: ["users", "label", value],
    queryFn: () => api.get<UserSummary>(`/users/${value}`),
    enabled: needsLookup,
    staleTime: 5 * 60_000,
  });

  // The selected person's name may not be in the current result page, so it
  // is remembered from the moment of selection rather than looked up again.
  const label = useMemo(() => {
    if (selected && selected.public_id === value) return selected.full_name || selected.username;
    if (value) return known.data ? known.data.full_name || known.data.username : "Loading…";
    return null;
  }, [selected, value, known.data]);

  if (!canSearch) {
    return (
      <Input
        id={id}
        value={value ?? ""}
        disabled={disabled}
        placeholder="User identifier"
        onChange={(event) => onChange(event.target.value || null, null)}
        aria-describedby={id ? `${id}-no-search` : undefined}
      />
    );
  }

  return (
    <>
      <div className="flex items-center gap-1">
        <button
          type="button"
          id={id}
          disabled={disabled}
          onClick={() => setOpen(true)}
          className={cn(
            "flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-border-strong bg-surface px-3 text-left text-sm",
            "disabled:cursor-not-allowed disabled:opacity-60",
            !label && "text-muted-foreground",
          )}
        >
          <span className="truncate">{label ?? placeholder}</span>
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        </button>
        {allowClear && value ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Clear selection"
            onClick={() => {
              setSelected(null);
              onChange(null, null);
            }}
          >
            <X />
          </Button>
        ) : null}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Select a person"
            description={role ? `Only accounts holding the ${role} role are listed.` : undefined}
          />
          <Input
            autoFocus
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search by name, username or email"
            aria-label="Search people"
          />
          <div className="mt-3 max-h-80 overflow-y-auto scrollbar-thin rounded-lg border border-border">
            {isFetching && !data ? (
              <div className="flex justify-center p-6">
                <InlineSpinner />
              </div>
            ) : (data?.items.length ?? 0) === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">No matching accounts.</p>
            ) : (
              <ul>
                {data?.items.map((person) => (
                  <li key={person.public_id}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelected(person);
                        onChange(person.public_id, person);
                        setOpen(false);
                      }}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {person.full_name || person.username}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {person.username}
                          {person.email ? ` · ${person.email}` : ""}
                        </span>
                      </span>
                      {person.public_id === value ? (
                        <Check className="size-4 shrink-0 text-primary" />
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
