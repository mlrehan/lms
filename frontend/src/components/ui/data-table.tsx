"use client";

import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A table over a *server*-paged list.
 *
 * Filtering, sorting and paging all happen in the API -- every list endpoint
 * takes `limit`/`offset` and returns a `total`. Pulling the whole table into
 * the browser to sort it there works for the twelve rows a development
 * database holds and fails silently at the ten thousand a real institution
 * has, which is exactly when nobody is watching.
 */

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Right-aligned numeric columns, and the trailing actions column. */
  align?: "left" | "right";
  className?: string;
  /** Hidden below `sm`, for columns that are context rather than identity. */
  secondary?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  emptyMessage = "Nothing to show.",
  className,
}: {
  columns: Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyMessage?: ReactNode;
  className?: string;
}): ReactNode {
  return (
    // Wide tables scroll inside their own container; the page body must never
    // scroll horizontally.
    <div className={cn("w-full overflow-x-auto scrollbar-thin", className)}>
      <table className="w-full min-w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "whitespace-nowrap px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                  column.align === "right" && "text-right",
                  column.secondary && "hidden sm:table-cell",
                  column.className,
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-4 py-10 text-center text-sm text-muted-foreground"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={cn(
                  "border-b border-border/70 last:border-0",
                  onRowClick && "cursor-pointer transition-colors hover:bg-surface-muted",
                )}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-4 py-2.5 align-middle text-foreground",
                      column.align === "right" && "text-right",
                      column.secondary && "hidden sm:table-cell",
                      column.className,
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export interface PageState {
  limit: number;
  offset: number;
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
  label = "records",
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (next: PageState) => void;
  label?: string;
}): ReactNode {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const canPrevious = offset > 0;
  const canNext = offset + limit < total;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
      <p className="text-muted-foreground">
        {total === 0 ? (
          <>No {label}</>
        ) : (
          <>
            <span className="font-medium text-foreground">
              {first}-{last}
            </span>{" "}
            of {total.toLocaleString()} {label}
          </>
        )}
      </p>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Rows
          <select
            className="h-7 rounded-md border border-border-strong bg-surface px-1.5 text-xs"
            value={limit}
            onChange={(event) => onChange({ limit: Number(event.target.value), offset: 0 })}
          >
            {[10, 25, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="secondary"
          size="icon"
          className="size-7"
          aria-label="Previous page"
          disabled={!canPrevious}
          onClick={() => onChange({ limit, offset: Math.max(0, offset - limit) })}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="secondary"
          size="icon"
          className="size-7"
          aria-label="Next page"
          disabled={!canNext}
          onClick={() => onChange({ limit, offset: offset + limit })}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
