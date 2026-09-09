"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api, type ApiError } from "@/lib/api/client";
import type { SearchHit, SearchResponse, SearchType } from "@/lib/api/types";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Badge } from "@/components/ui/primitives";
import { InlineSpinner } from "@/components/ui/states";
import { humanise } from "@/lib/utils";

/**
 * Where each search hit leads. `resource` has no detail route of its own --
 * resources live inside the folder browser -- so it deep-links to the list
 * filtered to that item rather than to a page that does not exist.
 */
const DESTINATIONS: Record<SearchType, (hit: SearchHit) => string> = {
  course: (hit) => `/courses/${hit.public_id}`,
  user: (hit) => `/users/${hit.public_id}`,
  batch: (hit) => `/batches/${hit.public_id}`,
  resource: (hit) => `/resources?resource=${hit.public_id}`,
  assignment: (hit) => `/assignments/${hit.public_id}`,
  announcement: (hit) => `/announcements?announcement=${hit.public_id}`,
  discussion: (hit) => `/discussions/${hit.public_id}`,
};

/** The backend refuses anything shorter, so there is no point asking. */
const MIN_QUERY = 2;

export function GlobalSearch(): ReactNode {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term.trim()), 220);
    return () => clearTimeout(timer);
  }, [term]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const enabled = open && debounced.length >= MIN_QUERY;
  const { data, isFetching, error } = useQuery<SearchResponse, ApiError>({
    queryKey: ["search", debounced],
    queryFn: () => api.get<SearchResponse>("/search", { query: { q: debounced, limit: 5 } }),
    enabled,
    staleTime: 15_000,
  });

  const groups = useMemo(() => (data?.groups ?? []).filter((g) => g.items.length > 0), [data]);

  function go(hit: SearchHit) {
    setOpen(false);
    setTerm("");
    router.push(DESTINATIONS[hit.type](hit));
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-9 w-full max-w-xs items-center gap-2 rounded-lg border border-border bg-surface-muted px-3 text-sm text-muted-foreground transition-colors hover:border-border-strong"
      >
        <Search className="size-4" aria-hidden />
        <span className="flex-1 text-left">Search</span>
        <kbd className="hidden rounded border border-border bg-surface px-1 font-mono text-[10px] sm:inline">
          Ctrl K
        </kbd>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="lg" className="p-0">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <Input
              autoFocus
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Search courses, people, batches, resources..."
              aria-label="Search the institution"
              className="border-0 bg-transparent px-0 focus-visible:outline-none"
            />
            {isFetching ? <InlineSpinner /> : null}
          </div>

          <div className="max-h-96 overflow-y-auto scrollbar-thin p-2">
            {debounced.length < MIN_QUERY ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                Type at least {MIN_QUERY} characters.
              </p>
            ) : error ? (
              <p className="px-3 py-6 text-center text-sm text-danger">{error.message}</p>
            ) : groups.length === 0 && !isFetching ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                No matches for &ldquo;{debounced}&rdquo;.
              </p>
            ) : (
              groups.map((group) => (
                <div key={group.type} className="mb-2 last:mb-0">
                  <p className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {humanise(group.type)}
                    {group.truncated ? ` · ${group.total} matches` : ""}
                  </p>
                  <ul>
                    {group.items.map((hit) => (
                      <li key={`${hit.type}-${hit.public_id}`}>
                        <button
                          type="button"
                          onClick={() => go(hit)}
                          className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{hit.label}</span>
                            {hit.subtitle ? (
                              <span className="block truncate text-xs text-muted-foreground">
                                {hit.subtitle}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}

            {/*
              Types the caller cannot read are reported by the API rather than
              silently omitted, so "no results" is distinguishable from "not
              allowed to look" -- two very different answers to the same query.
            */}
            {data?.skipped && data.skipped.length > 0 ? (
              <p className="flex flex-wrap items-center gap-1 border-t border-border px-3 pt-2 text-xs text-muted-foreground">
                Not searched:
                {data.skipped.map((type) => (
                  <Badge key={type} tone="neutral">
                    {humanise(type)}
                  </Badge>
                ))}
              </p>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
