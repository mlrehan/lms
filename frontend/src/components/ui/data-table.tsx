"use client";

import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { cn } from "@/lib/utils";

/**
 * A table over a *server*-paged list.
 *
 * Filtering, sorting and paging all happen in the API -- every list endpoint takes `limit`/`offset` and returns a
 * `total`. Pulling the whole table into the browser to sort it there works for the twelve rows a development
 * database holds and fails silently at the ten thousand a real institution has, which is exactly when nobody is
 * watching. So `sortable` columns report a sort to the caller (`onSortChange`) rather than sorting rows themselves.
 *
 * Built for dense operational use: compact rows by default, a header that stays put while the body scrolls,
 * one-line cells with the full text in a tooltip, an actions menu instead of a row of buttons, and skeleton and
 * empty states that keep the table's shape. Every option is opt-in, so an existing table only gets denser.
 */

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Right-aligned numeric columns, and the trailing actions column. */
  align?: "left" | "right" | "center";
  className?: string;
  /** Hidden below `sm`, for columns that are context rather than identity. */
  secondary?: boolean;
  /** Hidden below the given breakpoint; finer than `secondary`. */
  hideBelow?: "sm" | "md" | "lg" | "xl";
  /** Shows a sort control in the header. The value reported to `onSortChange` is `sortKey ?? key`. */
  sortable?: boolean;
  sortKey?: string;
  /** Keeps the cell on one line, cut with an ellipsis. Pair with `title` for the full text. */
  truncate?: boolean;
  /** Fixed width, e.g. `"8rem"`. */
  width?: string;
  /** The full text of a truncated cell, shown as a tooltip. */
  title?: (row: T) => string | undefined;
}

export interface RowAction {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
  /** Drawn above this action as a divider. */
  separatorBefore?: boolean;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

const HIDE: Record<NonNullable<Column<unknown>["hideBelow"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
};

function visibility<T>(column: Column<T>): string | undefined {
  if (column.hideBelow) return HIDE[column.hideBelow];
  return column.secondary ? HIDE.sm : undefined;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  rowClassName,
  emptyMessage = "Nothing to show.",
  emptyState,
  className,
  density = "compact",
  stickyHeader = false,
  maxHeight,
  sort,
  onSortChange,
  loading = false,
  skeletonRows = 8,
  rowActions,
  selectedKey,
  caption,
}: {
  columns: Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Extra classes for a row. */
  rowClassName?: (row: T) => string | undefined;
  emptyMessage?: ReactNode;
  /** A richer empty state (icon, title, next step). Wins over `emptyMessage`. */
  emptyState?: ReactNode;
  className?: string;
  density?: "compact" | "comfortable";
  /** Pins the header while the body scrolls. Give `maxHeight` too, or the page scrolls instead. */
  stickyHeader?: boolean;
  maxHeight?: string;
  sort?: SortState | null;
  onSortChange?: (next: SortState | null) => void;
  /** Draws skeleton rows in the table's own shape instead of a spinner. */
  loading?: boolean;
  skeletonRows?: number;
  /** A "..." menu at the end of each row. Return an empty array for a row with nothing to offer. */
  rowActions?: (row: T) => RowAction[];
  /** Highlights the row whose key matches. */
  selectedKey?: string | null;
  /** Read by screen readers as the table's name. */
  caption?: string;
}): ReactNode {
  const pad = density === "compact" ? "px-3 py-1.5" : "px-4 py-2.5";
  const empty = rows.length === 0 && !loading;

  function nextSort(column: Column<T>): SortState | null {
    const key = column.sortKey ?? column.key;
    if (!sort || sort.key !== key) return { key, dir: "asc" };
    return sort.dir === "asc" ? { key, dir: "desc" } : null; // a third click clears it
  }

  return (
    // Wide tables scroll inside their own container; the page body must never scroll horizontally.
    <div className={cn("w-full overflow-auto scrollbar-thin", className)} style={maxHeight ? { maxHeight } : undefined}>
      <table className={cn("w-full min-w-full border-separate border-spacing-0", density === "compact" ? "text-[13px]" : "text-sm")}>
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr className="text-left">
            {columns.map((column) => {
              const key = column.sortKey ?? column.key;
              const active = sort?.key === key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={column.sortable ? (active ? (sort?.dir === "asc" ? "ascending" : "descending") : "none") : undefined}
                  style={column.width ? { width: column.width } : undefined}
                  className={cn(
                    "group/th whitespace-nowrap border-b border-border-subtle px-3 py-2",
                    "text-2xs font-semibold uppercase tracking-caps text-subtle-foreground",
                    // Translucent + blurred rather than opaque: rows scrolling under the
                    // header stay readable as motion instead of being clipped by a solid bar.
                    stickyHeader ? "sticky top-0 z-10 bg-surface-muted/85 backdrop-blur-md" : "bg-surface-muted",
                    column.align === "right" && "text-right",
                    column.align === "center" && "text-center",
                    visibility(column),
                    column.className,
                  )}
                >
                  {column.sortable && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => onSortChange(nextSort(column))}
                      className={cn(
                        "-mx-1 inline-flex items-center gap-1 rounded-xs px-1 py-0.5 uppercase",
                        "transition-colors duration-200 ease-out hover:text-foreground",
                        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
                        active && "text-foreground",
                      )}
                    >
                      {column.header}
                      {active ? sort?.dir === "asc" ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden /> : <ArrowUpDown className="size-3 opacity-0 transition-opacity duration-200 group-hover/th:opacity-50" aria-hidden />}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
            {rowActions ? (
              <th scope="col" className={cn("w-10 border-b border-border-subtle px-2 py-2", stickyHeader ? "sticky top-0 z-10 bg-surface-muted/85 backdrop-blur-md" : "bg-surface-muted")}>
                <span className="sr-only">Actions</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: skeletonRows }).map((_, i) => (
              <tr key={`skeleton-${i}`} aria-hidden>
                {columns.map((column, c) => (
                  <td key={column.key} className={cn(pad, "border-b border-border-subtle", visibility(column))}>
                    <Skeleton className={cn("h-4", c === 0 ? "w-3/4" : "w-1/2", column.align === "right" && "ml-auto")} />
                  </td>
                ))}
                {rowActions ? <td className="border-b border-border-subtle px-2" /> : null}
              </tr>
            ))
          ) : empty ? (
            <tr>
              <td colSpan={columns.length + (rowActions ? 1 : 0)} className="px-4 py-2">
                {/*
                  The designed empty state is the default, not an opt-in. A table that
                  falls back to a line of grey text is the one place every screen looks
                  unfinished, and there are twenty of them.
                */}
                {emptyState ?? <EmptyState title={emptyMessage} />}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const key = rowKey(row);
              const selected = selectedKey != null && selectedKey === key;
              const actions = rowActions?.(row) ?? [];
              return (
                <tr
                  key={key}
                  aria-selected={selectedKey != null ? selected : undefined}
                  className={cn(
                    "group transition-colors duration-200 ease-out hover:bg-surface-muted",
                    onRowClick && "cursor-pointer",
                    selected && "bg-accent/60 hover:bg-accent/70 dark:bg-accent/40 dark:hover:bg-accent/50",
                    rowClassName?.(row),
                  )}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      title={column.title?.(row)}
                      className={cn(
                        pad,
                        "border-b border-border-subtle align-middle text-foreground",
                        selected && "first:shadow-[inset_2px_0_0_0_var(--primary)]",
                        column.align === "right" && "text-right tabular-nums",
                        column.align === "center" && "text-center",
                        column.truncate && "max-w-0 truncate", // `max-w-0` + `width` lets a truncating cell shrink to its column
                        visibility(column),
                        column.className,
                      )}
                      style={column.width ? { width: column.width } : undefined}
                    >
                      {column.cell(row)}
                    </td>
                  ))}
                  {rowActions ? (
                    <td
                      // The menu is contextual: it fades in on hover or keyboard focus, and stays
                      // put on touch, where there is no hover to reveal it with.
                      className={cn(
                        "w-10 border-b border-border-subtle px-1.5 text-right",
                        "opacity-0 transition-opacity duration-200 ease-out",
                        "group-hover:opacity-100 group-focus-within:opacity-100",
                        "has-[[data-popup-open]]:opacity-100 max-sm:opacity-100",
                        selected && "opacity-100",
                      )}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {actions.length > 0 ? <ActionMenu actions={actions} /> : null}
                    </td>
                  ) : null}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function ActionMenu({ actions }: { actions: RowAction[] }): ReactNode {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label="Row actions"
            className={cn(
              "inline-flex size-7 items-center justify-center rounded-md text-subtle-foreground",
              "transition-all duration-200 ease-out hover:bg-muted hover:text-foreground",
              "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
              "data-[popup-open]:bg-muted data-[popup-open]:text-foreground",
            )}
          />
        }
      >
        <MoreHorizontal className="size-4" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-48">
        {actions.map((action) => (
          <div key={action.label}>
            {action.separatorBefore ? <DropdownMenuSeparator /> : null}
            {/* Base UI menu items fire `onClick`; there is no `onSelect` (see components/ui/dropdown-menu.tsx). */}
            <DropdownMenuItem disabled={action.disabled} onClick={action.onSelect} className={cn("gap-2", action.destructive && "text-danger")}>
              {action.icon}
              {action.label}
            </DropdownMenuItem>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export interface PageState {
  limit: number;
  offset: number;
}

const PAGE_SIZES = [10, 25, 50, 100];

export function Pagination({
  total,
  limit,
  offset,
  onChange,
  label = "records",
  pageSizes = PAGE_SIZES,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (next: PageState) => void;
  label?: string;
  pageSizes?: number[];
}): ReactNode {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;
  const canPrevious = offset > 0;
  const canNext = offset + limit < total;
  const go = (p: number) => onChange({ limit, offset: (Math.min(Math.max(p, 1), pages) - 1) * limit });

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border-subtle bg-surface px-3 py-2 text-2xs">
      <p className="text-muted-foreground" aria-live="polite">
        {total === 0 ? (
          <>No {label}</>
        ) : (
          <>
            <span className="font-medium text-foreground tabular-nums">
              {first.toLocaleString()}–{last.toLocaleString()}
            </span>{" "}
            of <span className="tabular-nums">{total.toLocaleString()}</span> {label}
          </>
        )}
      </p>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5 text-muted-foreground">
          Rows per page
          <select
            className="h-7 cursor-pointer rounded-md border border-border-strong bg-surface px-1.5 text-2xs text-foreground transition-colors duration-200 ease-out hover:border-slate-400/70"
            value={limit}
            onChange={(event) => onChange({ limit: Number(event.target.value), offset: 0 })}
          >
            {(pageSizes.includes(limit) ? pageSizes : [...pageSizes, limit].sort((a, b) => a - b)).map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <span className="hidden text-muted-foreground tabular-nums sm:inline">
          Page {page} of {pages}
        </span>
        <div className="flex items-center gap-1">
          <Button variant="secondary" size="icon" className="hidden size-7 sm:inline-flex" aria-label="First page" disabled={!canPrevious} onClick={() => go(1)}>
            <ChevronsLeft />
          </Button>
          <Button variant="secondary" size="icon" className="size-7" aria-label="Previous page" disabled={!canPrevious} onClick={() => go(page - 1)}>
            <ChevronLeft />
          </Button>
          <Button variant="secondary" size="icon" className="size-7" aria-label="Next page" disabled={!canNext} onClick={() => go(page + 1)}>
            <ChevronRight />
          </Button>
          <Button variant="secondary" size="icon" className="hidden size-7 sm:inline-flex" aria-label="Last page" disabled={!canNext} onClick={() => go(pages)}>
            <ChevronsRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
