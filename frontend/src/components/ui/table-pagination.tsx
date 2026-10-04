"use client";

import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";

/**
 * Paging controls for a server-paged list.
 *
 * Lives in its own file (it was inside `data-table.tsx`) because several
 * screens page a list that is not drawn as a table — a card grid, the drive
 * view — and importing the whole table to get its footer was the only way to
 * reuse this.
 *
 * The page-size control is the console's `Select`, not a bare `<select>`, so
 * the one control that appears under *every* table matches the rest of the
 * form system in both themes.
 */

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
  className,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (next: PageState) => void;
  label?: string;
  pageSizes?: number[];
  className?: string;
}): ReactNode {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const pages = Math.max(1, Math.ceil(total / limit));
  const page = Math.floor(offset / limit) + 1;
  const canPrevious = offset > 0;
  const canNext = offset + limit < total;
  const go = (p: number) =>
    onChange({ limit, offset: (Math.min(Math.max(p, 1), pages) - 1) * limit });

  // A size the caller is already using is kept in the list even if it is not
  // one of the offered ones, so the control can always show its own value.
  const sizes = pageSizes.includes(limit) ? pageSizes : [...pageSizes, limit].sort((a, b) => a - b);

  return (
    <div
      className={
        className ??
        "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border-subtle bg-surface px-3 py-2 text-2xs"
      }
    >
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
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <span id="rows-per-page-label">Rows per page</span>
          <Select
            aria-label="Rows per page"
            className="h-7 w-18 px-1.5 text-2xs"
            value={String(limit)}
            onValueChange={(next) =>
              onChange({ limit: Number(next ?? limit), offset: 0 })
            }
            options={sizes.map((size) => ({ value: String(size), label: String(size) }))}
          />
        </div>
        <span className="hidden text-muted-foreground tabular-nums sm:inline">
          Page {page} of {pages}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="secondary"
            size="icon"
            className="hidden size-7 sm:inline-flex"
            aria-label="First page"
            disabled={!canPrevious}
            onClick={() => go(1)}
          >
            <ChevronsLeft />
          </Button>
          <Button
            variant="secondary"
            size="icon"
            className="size-7"
            aria-label="Previous page"
            disabled={!canPrevious}
            onClick={() => go(page - 1)}
          >
            <ChevronLeft />
          </Button>
          <Button
            variant="secondary"
            size="icon"
            className="size-7"
            aria-label="Next page"
            disabled={!canNext}
            onClick={() => go(page + 1)}
          >
            <ChevronRight />
          </Button>
          <Button
            variant="secondary"
            size="icon"
            className="hidden size-7 sm:inline-flex"
            aria-label="Last page"
            disabled={!canNext}
            onClick={() => go(pages)}
          >
            <ChevronsRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
