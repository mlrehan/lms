"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { PageUserSummary, UserSummary } from "@/lib/api/types";
import { Combobox, useDebounced } from "@/components/ui/combobox";
import { Input } from "@/components/ui/form";
import type { SelectOption } from "@/components/ui/select";
import { useSession } from "@/lib/auth/session";

/**
 * Pick a person by name instead of pasting a UUID.
 *
 * `GET /users` supports a server-side `query` and a `role` filter, so this
 * searches the institution rather than filtering a page of results that were
 * already fetched — the difference between finding someone in a roster of
 * 10,000 and finding them only if they happened to be in the first 25.
 *
 * **Now the console's `Combobox` rather than a bespoke dialog.** The dialog
 * worked, but it was a second selection idiom: it opened a modal to choose a
 * value, which is not what any other field in the console does, and it carried
 * its own debounce, its own loading state and its own "remember the chosen
 * label" logic. All three now live in one place, so the async-search behaviour
 * is identical here, in the tenant picker and in anything added later.
 *
 * A caller without `user.read` cannot search at all. Rather than showing an
 * empty picker that looks broken, it degrades to a plain identifier field,
 * which still works for someone who was given an id to enter.
 */
export function UserPicker({
  value,
  onChange,
  role,
  placeholder = "Search by name, username or email",
  disabled,
  id,
}: {
  value: string | null;
  onChange: (userId: string | null, user: UserSummary | null) => void;
  /** Restrict to holders of a role, e.g. `TUTOR` for a session's tutor. */
  role?: string;
  placeholder?: string;
  disabled?: boolean;
  /** Kept for callers that still pass it; clearing is always offered. */
  allowClear?: boolean;
  id?: string;
}): ReactNode {
  const { permissions } = useSession();
  const canSearch = permissions.has("user.read");

  const [term, setTerm] = useState("");
  const debounced = useDebounced(term, 300);

  const search = useQuery({
    queryKey: ["users", "picker", debounced, role ?? null],
    queryFn: () =>
      api.get<PageUserSummary>("/users", {
        query: { query: debounced || undefined, role, limit: 20, status: "ACTIVE" },
      }),
    enabled: canSearch,
    staleTime: 20_000,
  });

  /*
   * A value that arrived from outside — a default tutor, an existing session —
   * has no label yet, so it is looked up once. Without this the field shows a
   * UUID where a person's name belongs, which is the whole reason this control
   * exists.
   */
  const known = useQuery({
    queryKey: ["users", "label", value],
    queryFn: () => api.get<UserSummary>(`/users/${value}`),
    enabled: canSearch && !!value,
    staleTime: 5 * 60_000,
  });

  // Built inside the memo, not mutated after it: a render may be discarded or
  // replayed, so accumulating into a memoised object during render is exactly
  // the unsoundness the React Compiler rejects.
  const byId = useMemo(() => {
    const map = new Map<string, UserSummary>();
    for (const person of search.data?.items ?? []) map.set(person.public_id, person);
    if (known.data) map.set(known.data.public_id, known.data);
    return map;
  }, [search.data, known.data]);

  const options = useMemo<SelectOption[]>(() => {
    const items = search.data?.items ?? [];
    const list = items.map((person) => ({
      value: person.public_id,
      label: person.full_name || person.username,
      description: person.email ? `${person.username} · ${person.email}` : person.username,
    }));
    // The selected person is kept in the list even when the current search
    // does not return them, so the combobox can always name its own value.
    if (known.data && !items.some((person) => person.public_id === known.data!.public_id)) {
      list.unshift({
        value: known.data.public_id,
        label: known.data.full_name || known.data.username,
        description: known.data.email
          ? `${known.data.username} · ${known.data.email}`
          : known.data.username,
      });
    }
    return list;
  }, [search.data, known.data]);

  if (!canSearch) {
    return (
      <Input
        id={id}
        value={value ?? ""}
        disabled={disabled}
        placeholder="User identifier"
        onChange={(event) => onChange(event.target.value || null, null)}
      />
    );
  }

  return (
    <Combobox
      id={id}
      value={value}
      disabled={disabled}
      placeholder={placeholder}
      aria-label={role ? `Search ${role.toLowerCase()} accounts` : "Search people"}
      emptyMessage="No matching accounts."
      options={options}
      loading={search.isFetching}
      error={search.error ? "Could not search accounts." : null}
      onRetry={() => void search.refetch()}
      onSearch={setTerm}
      onValueChange={(next) => onChange(next, next ? (byId.get(next) ?? null) : null)}
    />
  );
}
