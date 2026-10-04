"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";
import type { Column } from "@/components/ui/data-table";
import type { ColumnToggle } from "@/components/ui/table-view-options";

/**
 * Hold a table's hidden columns, remembered per person per table.
 *
 * `DataTable` takes column visibility as a controlled prop so the caller
 * decides where it is stored -- but that meant four lines of state, a
 * `ColumnToggle[]` to assemble and a `localStorage` read in every page, which
 * is why the capability shipped and no screen used it. This is that
 * boilerplate, once.
 *
 * **`useSyncExternalStore`, not state seeded in an effect.** `localStorage`
 * does not exist while the page renders on the server, so the stored value
 * cannot be read during the first render without the markup disagreeing with
 * the server's. Reading it in an effect and calling `setState` fixes the
 * mismatch but renders twice on every mount, which is what the React Compiler
 * rules reject. `useSyncExternalStore` is the supported answer: React renders
 * `getServerSnapshot` on the server and during hydration, then reconciles
 * against the real store -- so there is one re-render only when something was
 * actually stored.
 *
 * A key that cannot be read or written is ignored. A private window with site
 * data blocked must not take a table down, and forgetting a column choice is a
 * far smaller harm than a blank screen.
 */

const EMPTY: readonly string[] = [];

/*
 * `getSnapshot` must return the *same* reference while the stored value is
 * unchanged, or React re-renders forever. Parsing produces a fresh array each
 * time, so the parse is cached against the raw string it came from.
 */
const parsed = new Map<string, { raw: string | null; value: readonly string[] }>();
const listeners = new Map<string, Set<() => void>>();

function subscribe(key: string | null, onChange: () => void): () => void {
  if (key === null) return () => {};
  let set = listeners.get(key);
  if (!set) {
    set = new Set();
    listeners.set(key, set);
  }
  set.add(onChange);
  // Another tab changing the same preference should be reflected here too.
  const onStorage = (event: StorageEvent) => {
    if (event.key === key) onChange();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    set!.delete(onChange);
    window.removeEventListener("storage", onStorage);
  };
}

function notify(key: string): void {
  for (const listener of listeners.get(key) ?? []) listener();
}

function snapshot(key: string | null, fallback: readonly string[]): readonly string[] {
  if (key === null) return fallback;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return fallback;
  }
  const cached = parsed.get(key);
  if (cached && cached.raw === raw) return cached.value;

  let value = fallback;
  if (raw !== null) {
    try {
      const candidate: unknown = JSON.parse(raw);
      if (Array.isArray(candidate) && candidate.every((item) => typeof item === "string")) {
        value = candidate as string[];
      }
    } catch {
      /* Corrupt or hand-edited: fall back to showing everything. */
    }
  }
  parsed.set(key, { raw, value });
  return value;
}

export interface TableView {
  /** Pass straight to `DataTable`'s `columnVisibility`. */
  state: { hidden: readonly string[]; onChange: (hidden: string[]) => void };
  /** Spread onto `TableViewOptions`. */
  options: {
    columns: ColumnToggle[];
    onToggle: (id: string, visible: boolean) => void;
    onReset: () => void;
  };
}

export function useTableView<T>(
  /**
   * Unique per table, namespaced on write so it cannot collide. `undefined`
   * disables the whole thing without touching storage, which is what lets
   * `DataTable` call this unconditionally for tables that did not ask for it.
   */
  storageKey: string | undefined,
  columns: Column<T>[],
  {
    locked = EMPTY,
    initiallyHidden = EMPTY,
  }: {
    /** Columns the table is unreadable without -- usually the identity column. */
    locked?: readonly string[];
    /** Hidden until someone turns them on, for a wide table's optional detail. */
    initiallyHidden?: readonly string[];
  } = {},
): TableView {
  const key = storageKey === undefined ? null : `lms.table.${storageKey}.hidden`;

  // A caller writing `initiallyHidden={["email"]}` inline passes a new array
  // every render, and `getServerSnapshot` must be stable, so the identity is
  // rebuilt from the contents rather than taken from the prop.
  const fallbackKey = initiallyHidden.join("\u0000");
  const fallback = useMemo(
    () => (fallbackKey ? fallbackKey.split("\u0000") : EMPTY),
    [fallbackKey],
  );

  const hidden = useSyncExternalStore(
    useCallback((onChange: () => void) => subscribe(key, onChange), [key]),
    useCallback(() => snapshot(key, fallback), [key, fallback]),
    useCallback(() => fallback, [fallback]),
  );

  const persist = useCallback(
    (next: readonly string[]) => {
      if (key === null) return;
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* The choice cannot be remembered; nothing else is affected. */
      }
      notify(key);
    },
    [key],
  );

  const onToggle = useCallback(
    (id: string, visible: boolean) =>
      persist(visible ? hidden.filter((h) => h !== id) : [...hidden, id]),
    [hidden, persist],
  );

  const toggles = useMemo<ColumnToggle[]>(
    () =>
      columns
        // A column with no header has nothing to name it in the menu -- a
        // row-actions or avatar column -- so it is not offered.
        .filter((column) => column.header)
        .map((column) => ({
          id: column.key,
          label: column.header,
          visible: !hidden.includes(column.key),
          locked: locked.includes(column.key),
        })),
    [columns, hidden, locked],
  );

  return {
    state: { hidden, onChange: persist },
    options: { columns: toggles, onToggle, onReset: useCallback(() => persist(EMPTY), [persist]) },
  };
}
