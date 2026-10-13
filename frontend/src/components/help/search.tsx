"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Search, X } from "lucide-react";
import type { Guide } from "@/content/help/types";
import { searchText } from "@/content/help/types";
import { cn } from "@/lib/utils";

/**
 * Search across one guide.
 *
 * The index is built in the browser from the guide the page already has, so
 * there is no search service, no API call and nothing to keep in step with
 * the content. A guide is a few dozen articles; scoring them on each
 * keystroke is far below the cost of a round trip.
 *
 * Scoring is deliberately simple and explainable: a hit in the title beats a
 * hit in the summary, which beats a hit in the body, and every word typed
 * must appear somewhere. That makes "grade book" find the grade book article
 * rather than every article that mentions grades.
 */
type Entry = {
  id: string;
  title: string;
  summary: string;
  section: string;
  haystack: string;
  titleLower: string;
};

export function HelpSearch({ guide, compact = false }: { guide: Guide; compact?: boolean }) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const entries = useMemo<Entry[]>(
    () =>
      guide.sections.flatMap((section) =>
        section.articles.map((article) => ({
          id: article.id,
          title: article.title,
          summary: article.summary,
          section: section.title,
          haystack: searchText(article).toLowerCase(),
          titleLower: article.title.toLowerCase(),
        })),
      ),
    [guide],
  );

  const results = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return entries
      .map((entry) => {
        let score = 0;
        for (const word of words) {
          if (!entry.haystack.includes(word)) return null; // every word must appear
          if (entry.titleLower.includes(word)) score += 10;
          if (entry.summary.toLowerCase().includes(word)) score += 4;
          score += 1;
        }
        return { entry, score };
      })
      .filter((hit): hit is { entry: Entry; score: number } => hit !== null)
      .sort((a, b) => b.score - a.score)
      .slice(0, 8)
      .map((hit) => hit.entry);
  }, [entries, query]);

  // Clicking away closes the result list; Escape clears it.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setFocused(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const showResults = focused && query.trim().length > 0;

  return (
    <div ref={containerRef} className="relative print:hidden">
      <label className="sr-only" htmlFor={`help-search-${guide.slug}`}>
        Search the {guide.title}
      </label>
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          id={`help-search-${guide.slug}`}
          type="search"
          value={query}
          placeholder={compact ? "Search the guide" : "Search this guide"}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setFocused(true)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setQuery("");
          }}
          className={cn(
            "w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-7 text-sm",
            "placeholder:text-subtle-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary",
          )}
          autoComplete="off"
        />
        {query ? (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear search"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        ) : null}
      </div>

      {showResults ? (
        <div
          className="absolute left-0 right-0 top-full z-40 mt-1 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
          role="listbox"
          aria-label="Search results"
        >
          {results.length === 0 ? (
            <p className="px-3 py-3 text-xs text-muted-foreground">
              Nothing found for “{query}”. Try a word that appears on the screen you are looking
              for, such as “batch” or “attendance”.
            </p>
          ) : (
            <ul className="max-h-80 overflow-y-auto py-1">
              {results.map((entry) => (
                <li key={entry.id}>
                  <Link
                    href={`/help/${guide.slug}/${entry.id}`}
                    onClick={() => {
                      setQuery("");
                      setFocused(false);
                    }}
                    className="block px-3 py-2 hover:bg-muted"
                  >
                    <span className="block text-sm font-medium text-foreground">{entry.title}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {entry.section} · {entry.summary}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
