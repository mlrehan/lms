"use client";

import { Fragment, useEffect, useMemo, useRef, type ReactNode } from "react";
import {
  useTable,
  coreCellsFeature,
  coreColumnsFeature,
  coreHeadersFeature,
  coreRowModelsFeature,
  coreRowsFeature,
  coreTablesFeature,
  createCoreRowModel,
  columnPinningFeature,
  columnResizingFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  rowExpandingFeature,
  rowSelectionFeature,
  createExpandedRowModel,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/primitives";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TableColumnHeader, type SortState } from "@/components/ui/table-column-header";
import { TableViewOptions, type ColumnToggle } from "@/components/ui/table-view-options";
import { cn } from "@/lib/utils";

export type { SortState } from "@/components/ui/table-column-header";
export { Pagination, type PageState } from "@/components/ui/table-pagination";

/**
 * A table over a *server*-paged list, with TanStack Table as its state engine.
 *
 * **Server-side by default, and that is a decision, not an omission.** Every
 * list endpoint in this API takes `limit`/`offset` and returns a `total`.
 * Pulling a whole table into the browser to sort it there works for the twelve
 * rows a development database holds and fails silently at the ten thousand a
 * real institution has — exactly when nobody is watching. So `sortable`
 * columns still *report* a sort (`onSortChange`) rather than reordering rows
 * locally, and paging stays the caller's business.
 *
 * What TanStack brings is the state machine for everything that is genuinely
 * client-side: row selection, column visibility, expansion, sizing and
 * pinning. Each is **opt-in** — a table that passes none of those options
 * registers none of those features, and renders exactly what it rendered
 * before.
 *
 * The `Column<T>` API is unchanged, because twenty-seven screens use it and a
 * migration that rewrote them all would risk far more than it gained. Columns
 * are converted to TanStack `ColumnDef`s internally; a caller who wants the
 * full TanStack surface can reach it through `renderTable`.
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
  /** Shows a sort control in the header. The value reported is `sortKey ?? key`. */
  sortable?: boolean;
  sortKey?: string;
  /** Keeps the cell on one line, cut with an ellipsis. Pair with `title`. */
  truncate?: boolean;
  /** Fixed width, e.g. `"8rem"`. */
  width?: string;
  /** The full text of a truncated cell, shown as a tooltip. */
  title?: (row: T) => string | undefined;
  /** Excluded from the column-visibility menu; the table is unreadable without it. */
  alwaysVisible?: boolean;
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

/** Row selection, as a controlled set of row keys. */
export interface SelectionOptions {
  selected: readonly string[];
  onChange: (selected: string[]) => void;
  /** Rows that cannot be selected, e.g. ones the caller may not act on. */
  isSelectable?: (key: string) => boolean;
  /** Shown in a bar above the table while anything is selected. */
  bulkActions?: ReactNode;
}

export interface ExpansionOptions<T> {
  /** The panel drawn beneath an expanded row. Return null for a row with nothing to add. */
  render: (row: T) => ReactNode;
  canExpand?: (row: T) => boolean;
  expanded: readonly string[];
  onChange: (expanded: string[]) => void;
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

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
  emptyMessage?: ReactNode;
  emptyState?: ReactNode;
  className?: string;
  density?: "compact" | "comfortable";
  stickyHeader?: boolean;
  maxHeight?: string;
  sort?: SortState | null;
  onSortChange?: (next: SortState | null) => void;
  loading?: boolean;
  skeletonRows?: number;
  rowActions?: (row: T) => RowAction[];
  selectedKey?: string | null;
  caption?: string;
  /** Replaces the table body with a retryable error. */
  error?: unknown;
  onRetry?: () => void;
  /** Opt in to row selection, select-all and a bulk-action bar. */
  selection?: SelectionOptions;
  /** Opt in to a "Columns" menu. Controlled by the caller so it can be persisted. */
  columnVisibility?: {
    hidden: readonly string[];
    onChange: (hidden: string[]) => void;
  };
  /** Opt in to expandable rows. */
  expansion?: ExpansionOptions<T>;
  /** Opt in to drag-to-resize column widths. */
  resizable?: boolean;
  /** Column keys frozen to the left while the table scrolls sideways. */
  pinnedColumns?: readonly string[];
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
  error,
  onRetry,
  selection,
  columnVisibility,
  expansion,
  resizable = false,
  pinnedColumns,
}: DataTableProps<T>): ReactNode {
  const pad = density === "compact" ? "px-3 py-1.5" : "px-4 py-2.5";

  /*
   * Only the features the caller actually asked for are registered. This is
   * the whole point of v9's explicit feature list: an unused feature is not
   * merely idle, it adds state slices and per-row work to every table in the
   * console, of which there are twenty-seven.
   */
  const wantsSelection = !!selection;
  const wantsVisibility = !!columnVisibility;
  const wantsExpansion = !!expansion;
  const wantsPinning = !!pinnedColumns;

  const features = useMemo(
    () => ({
      coreCellsFeature,
      coreColumnsFeature,
      coreHeadersFeature,
      coreRowModelsFeature,
      coreRowsFeature,
      coreTablesFeature,
      coreRowModel: createCoreRowModel(),
      ...(selection ? { rowSelectionFeature } : {}),
      ...(columnVisibility ? { columnVisibilityFeature } : {}),
      ...(expansion ? { rowExpandingFeature, expandedRowModel: createExpandedRowModel() } : {}),
      ...(resizable ? { columnResizingFeature, columnSizingFeature } : {}),
      ...(pinnedColumns ? { columnPinningFeature, columnSizingFeature } : {}),
    }),
    [wantsSelection, wantsVisibility, wantsExpansion, resizable, wantsPinning],
  );

  /*
   * TanStack's `TData` is constrained to `Record<string, any> | any[]`, which
   * an interface does not satisfy — and every row type in this console is an
   * interface generated from the API. The constraint is a typing detail, not a
   * runtime one, so it is crossed exactly once, here, rather than forcing
   * twenty-seven call sites to restate their row types as index signatures.
   */
  type Loose = Record<string, unknown>;

  const columnDefs = useMemo(
    () =>
      columns.map((column) => ({
        id: column.key,
        header: () => column.header,
        cell: (context: { row: { original: Loose } }) =>
          column.cell(context.row.original as T),
        enableHiding: !column.alwaysVisible,
      })) as unknown as ColumnDef<typeof features, Loose, unknown>[],
    [columns, features],
  );

  const hidden = columnVisibility?.hidden ?? [];
  const visibleColumns = useMemo(
    () => columns.filter((column) => column.alwaysVisible || !hidden.includes(column.key)),
    [columns, hidden],
  );

  /*
   * The instance owns the row model: `modelRows` below is what the body
   * renders, so this is load-bearing rather than decorative. With no
   * client-side feature registered it is the identity of `rows`, which is what
   * keeps a server-paged table byte-identical to its previous output; register
   * expansion and it is the expanded model instead.
   */
  const table = useTable({
    features,
    columns: columnDefs,
    data: rows as unknown as Loose[],
    getRowId: (row) => rowKey(row as unknown as T),
  });

  const modelRows = table.getRowModel().rows;

  const selectable = useMemo(() => {
    if (!selection) return [] as string[];
    return rows.map(rowKey).filter((key) => selection.isSelectable?.(key) ?? true);
  }, [rows, rowKey, selection]);

  const selectedSet = useMemo(() => new Set(selection?.selected ?? []), [selection?.selected]);
  const allSelected = selectable.length > 0 && selectable.every((key) => selectedSet.has(key));
  const someSelected = selectable.some((key) => selectedSet.has(key)) && !allSelected;

  function toggleAll() {
    if (!selection) return;
    // Only rows currently on the page are affected. A "select all" that
    // silently included rows the person has never seen — on a server-paged
    // list, every other page — would make a bulk delete unanswerable.
    const others = selection.selected.filter((key) => !selectable.includes(key));
    selection.onChange(allSelected ? others : [...others, ...selectable]);
  }

  function toggleRow(key: string) {
    if (!selection) return;
    selection.onChange(
      selectedSet.has(key)
        ? selection.selected.filter((k) => k !== key)
        : [...selection.selected, key],
    );
  }

  const expandedSet = useMemo(() => new Set(expansion?.expanded ?? []), [expansion?.expanded]);
  function toggleExpanded(key: string) {
    if (!expansion) return;
    expansion.onChange(
      expandedSet.has(key)
        ? expansion.expanded.filter((k) => k !== key)
        : [...expansion.expanded, key],
    );
  }

  const leadingCols = (selection ? 1 : 0) + (expansion ? 1 : 0);
  const totalCols = visibleColumns.length + leadingCols + (rowActions ? 1 : 0);
  const empty = rows.length === 0 && !loading && !error;

  const headCell = cn(
    "whitespace-nowrap border-b border-border-subtle px-3 py-2",
    "text-2xs font-semibold uppercase tracking-caps text-subtle-foreground",
    stickyHeader ? "sticky top-0 z-10 bg-surface-muted/85 backdrop-blur-md" : "bg-surface-muted",
  );

  function pinClass(key: string): string | undefined {
    return pinnedColumns?.includes(key)
      ? "sticky left-0 z-20 bg-surface shadow-[1px_0_0_0_var(--border-subtle)]"
      : undefined;
  }

  return (
    <div className="w-full">
      {selection && selection.selected.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle bg-accent/50 px-3 py-2 text-2xs">
          <span className="font-medium text-accent-foreground tabular-nums">
            {selection.selected.length} selected
          </span>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground hover:underline"
            onClick={() => selection.onChange([])}
          >
            Clear
          </button>
          {selection.bulkActions ? (
            <div className="ml-auto flex flex-wrap items-center gap-2">{selection.bulkActions}</div>
          ) : null}
        </div>
      ) : null}

      <div
        className={cn("w-full overflow-auto scrollbar-thin", className)}
        style={maxHeight ? { maxHeight } : undefined}
      >
        <table
          className={cn(
            "w-full min-w-full border-separate border-spacing-0",
            density === "compact" ? "text-[13px]" : "text-sm",
          )}
        >
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <thead>
            <tr className="text-left">
              {expansion ? (
                <th scope="col" className={cn(headCell, "w-8 px-1")}>
                  <span className="sr-only">Expand</span>
                </th>
              ) : null}
              {selection ? (
                <th scope="col" className={cn(headCell, "w-9")}>
                  <TriStateCheckbox
                    label={allSelected ? "Clear selection" : "Select all on this page"}
                    checked={allSelected}
                    indeterminate={someSelected}
                    disabled={selectable.length === 0}
                    onChange={toggleAll}
                  />
                </th>
              ) : null}
              {visibleColumns.map((column) => {
                const key = column.sortKey ?? column.key;
                const active = sort?.key === key;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={
                      column.sortable
                        ? active
                          ? sort?.dir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                        : undefined
                    }
                    style={column.width ? { width: column.width } : undefined}
                    className={cn(
                      "group/th",
                      headCell,
                      column.align === "right" && "text-right",
                      column.align === "center" && "text-center",
                      visibility(column),
                      pinClass(column.key),
                      resizable && "relative",
                      column.className,
                    )}
                  >
                    {column.sortable && onSortChange ? (
                      <TableColumnHeader sortKey={key} sort={sort} onSortChange={onSortChange}>
                        {column.header}
                      </TableColumnHeader>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
              {rowActions ? (
                <th scope="col" className={cn(headCell, "w-10 px-2")}>
                  <span className="sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr>
                <td colSpan={totalCols} className="px-4 py-2">
                  <ErrorState error={error} onRetry={onRetry} />
                </td>
              </tr>
            ) : loading ? (
              Array.from({ length: skeletonRows }).map((_, i) => (
                <tr key={`skeleton-${i}`} aria-hidden>
                  {expansion ? <td className="border-b border-border-subtle px-1" /> : null}
                  {selection ? <td className="border-b border-border-subtle px-3" /> : null}
                  {visibleColumns.map((column, c) => (
                    <td
                      key={column.key}
                      className={cn(pad, "border-b border-border-subtle", visibility(column))}
                    >
                      <Skeleton
                        className={cn(
                          "h-4",
                          c === 0 ? "w-3/4" : "w-1/2",
                          column.align === "right" && "ml-auto",
                        )}
                      />
                    </td>
                  ))}
                  {rowActions ? <td className="border-b border-border-subtle px-2" /> : null}
                </tr>
              ))
            ) : empty ? (
              <tr>
                <td colSpan={totalCols} className="px-4 py-2">
                  {emptyState ?? <EmptyState title={emptyMessage} />}
                </td>
              </tr>
            ) : (
              modelRows.map((modelRow) => {
                const row = modelRow.original as unknown as T;
                const key = modelRow.id;
                const selected = selectedKey != null && selectedKey === key;
                const checked = selectedSet.has(key);
                const actions = rowActions?.(row) ?? [];
                const canExpand = expansion ? (expansion.canExpand?.(row) ?? true) : false;
                const isExpanded = expandedSet.has(key);
                return (
                  // `Fragment` with an explicit key, not `<>`: the key must sit
                  // on the outermost element the map returns. With it on the
                  // inner <tr>, React warned on every table and — worse —
                  // reconciled rows by position, so an expanded row could keep
                  // another row's DOM state when the list reordered.
                  <Fragment key={key}>
                    <tr
                      aria-selected={selectedKey != null ? selected : undefined}
                      className={cn(
                        "group transition-colors duration-200 ease-out hover:bg-surface-muted",
                        onRowClick && "cursor-pointer",
                        (selected || checked) &&
                          "bg-accent/60 hover:bg-accent/70 dark:bg-accent/40 dark:hover:bg-accent/50",
                        rowClassName?.(row),
                      )}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}
                    >
                      {expansion ? (
                        <td
                          className={cn("w-8 border-b border-border-subtle px-1")}
                          onClick={(event) => event.stopPropagation()}
                        >
                          {canExpand ? (
                            <button
                              type="button"
                              aria-label={isExpanded ? "Collapse row" : "Expand row"}
                              aria-expanded={isExpanded}
                              onClick={() => toggleExpanded(key)}
                              className="rounded-xs p-0.5 text-subtle-foreground transition-colors hover:text-foreground"
                            >
                              {isExpanded ? (
                                <ChevronDown className="size-4" aria-hidden />
                              ) : (
                                <ChevronRight className="size-4" aria-hidden />
                              )}
                            </button>
                          ) : null}
                        </td>
                      ) : null}
                      {selection ? (
                        <td
                          className="w-9 border-b border-border-subtle px-3"
                          // Stops a row-click handler firing when the intent
                          // was only to tick the box.
                          onClick={(event) => event.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            aria-label={`Select row ${key}`}
                            checked={checked}
                            disabled={!(selection.isSelectable?.(key) ?? true)}
                            onChange={() => toggleRow(key)}
                            className="size-3.5 cursor-pointer accent-primary"
                          />
                        </td>
                      ) : null}
                      {visibleColumns.map((column) => (
                        <td
                          key={column.key}
                          title={column.title?.(row)}
                          className={cn(
                            pad,
                            "border-b border-border-subtle align-middle text-foreground",
                            selected && "first:shadow-[inset_2px_0_0_0_var(--primary)]",
                            column.align === "right" && "text-right tabular-nums",
                            column.align === "center" && "text-center",
                            column.truncate && "max-w-0 truncate",
                            visibility(column),
                            pinClass(column.key),
                            column.className,
                          )}
                          style={column.width ? { width: column.width } : undefined}
                        >
                          {column.cell(row)}
                        </td>
                      ))}
                      {rowActions ? (
                        <td
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
                    {expansion && isExpanded ? (
                      <tr className="bg-surface-muted/40">
                        <td colSpan={totalCols} className="border-b border-border-subtle px-4 py-3">
                          {expansion.render(row)}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The "Columns" menu for a table, built from its own column list. */
export function columnToggles<T>(
  columns: Column<T>[],
  hidden: readonly string[],
): ColumnToggle[] {
  return columns.map((column) => ({
    id: column.key,
    label: typeof column.header === "string" ? column.header : column.key,
    visible: column.alwaysVisible || !hidden.includes(column.key),
    locked: column.alwaysVisible,
  }));
}

export { TableViewOptions };


/**
 * A checkbox that can show "some, but not all".
 *
 * `indeterminate` is a DOM property with no HTML attribute, so it has to be
 * assigned to the node. Doing that from a callback ref runs *during* render,
 * which React may discard or replay — so it is set in an effect instead, which
 * is the only point the node is guaranteed to exist and the render is
 * guaranteed to have been committed.
 */
function TriStateCheckbox({
  label,
  checked,
  indeterminate,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  indeterminate: boolean;
  disabled?: boolean;
  onChange: () => void;
}): ReactNode {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      className="size-3.5 cursor-pointer accent-primary"
    />
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
            {/* Base UI menu items fire `onClick`; there is no `onSelect`. */}
            <DropdownMenuItem
              disabled={action.disabled}
              onClick={action.onSelect}
              className={cn("gap-2", action.destructive && "text-danger")}
            >
              {action.icon}
              {action.label}
            </DropdownMenuItem>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export { Button as _TableButton };
