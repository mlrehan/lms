"use client";

import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A sortable column heading.
 *
 * Three states, cycled by clicking: ascending, descending, unsorted. The third
 * click clearing the sort matters on a server-paged list, because "no sort" is
 * the API's own default ordering and there is otherwise no way back to it.
 *
 * The indicator is always rendered — invisible rather than absent when the
 * column is unsorted — so the heading does not change width when it is
 * clicked, which makes a wide table jump sideways under the pointer.
 */

export type SortDirection = "asc" | "desc";

export interface SortState {
  key: string;
  dir: SortDirection;
}

export function nextSortState(current: SortState | null | undefined, key: string): SortState | null {
  if (!current || current.key !== key) return { key, dir: "asc" };
  return current.dir === "asc" ? { key, dir: "desc" } : null;
}

export function TableColumnHeader({
  children,
  sortKey,
  sort,
  onSortChange,
  className,
}: {
  children: ReactNode;
  sortKey: string;
  sort?: SortState | null;
  onSortChange?: (next: SortState | null) => void;
  className?: string;
}): ReactNode {
  if (!onSortChange) return <>{children}</>;

  const active = sort?.key === sortKey;

  return (
    <button
      type="button"
      onClick={() => onSortChange(nextSortState(sort, sortKey))}
      className={cn(
        "-mx-1 inline-flex items-center gap-1 rounded-xs px-1 py-0.5 uppercase",
        "transition-colors duration-200 ease-out hover:text-foreground",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
        active && "text-foreground",
        className,
      )}
    >
      {children}
      {active ? (
        sort?.dir === "asc" ? (
          <ArrowUp className="size-3" aria-hidden />
        ) : (
          <ArrowDown className="size-3" aria-hidden />
        )
      ) : (
        <ArrowUpDown
          className="size-3 opacity-0 transition-opacity duration-200 group-hover/th:opacity-50"
          aria-hidden
        />
      )}
    </button>
  );
}
