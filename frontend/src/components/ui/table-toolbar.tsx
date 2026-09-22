"use client";

import type { ReactNode } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The strip above a table: a search box, any filters, and actions on the right.
 *
 * The search is *controlled* and only reports what was typed; the caller debounces it and sends it to the API
 * (see `useListState`), so it searches the whole list rather than the page that happens to be loaded.
 */
export function TableToolbar({
  search,
  onSearch,
  searchPlaceholder = "Search",
  filters,
  actions,
  summary,
  className,
}: {
  search?: string;
  onSearch?: (value: string) => void;
  searchPlaceholder?: string;
  /** Selects and toggles that narrow the list. */
  filters?: ReactNode;
  actions?: ReactNode;
  /** e.g. "47 batches". Shown after the filters. */
  summary?: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <div className={cn("flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface px-3 py-2.5", className)}>
      {onSearch ? (
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground transition-colors duration-200 peer-focus-visible:text-primary" aria-hidden />
          <input
            type="search"
            value={search ?? ""}
            onChange={(event) => onSearch(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className={cn(
              "peer h-8 w-full rounded-md border border-border-strong bg-surface pl-8 pr-7 text-[13px] shadow-xs",
              "outline-none placeholder:text-subtle-foreground",
              "transition-all duration-200 ease-out hover:border-slate-400/70 dark:hover:border-slate-500/70",
              "focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-primary/18",
              "[&::-webkit-search-cancel-button]:hidden",
            )}
          />
          {search ? (
            <button type="button" aria-label="Clear search" className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-xs p-0.5 text-subtle-foreground transition-colors duration-200 ease-out hover:text-foreground" onClick={() => onSearch("")}>
              <X className="size-3.5" aria-hidden />
            </button>
          ) : null}
        </div>
      ) : null}
      {filters ? <div className="flex flex-wrap items-center gap-2">{filters}</div> : null}
      {summary ? <div className="text-2xs text-subtle-foreground">{summary}</div> : null}
      {actions ? <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
