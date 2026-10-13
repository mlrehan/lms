"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FileAudio,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
  Image as ImageIcon,
  Inbox,
  Search,
} from "lucide-react";
import { api } from "@/lib/api/client";
import type { SharedResourceResponse } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Input } from "@/components/ui/form";
import { ErrorState, EmptyState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDate } from "@/lib/format/datetime";
import { formatBytes } from "@/components/domain/resources/drive-view";
import { UniversalViewer, type ViewerFile } from "@/components/domain/resources/viewer/universal-viewer";
import {
  FILTER_LABELS,
  availableFilters,
  countFor,
  matchesFilter,
  typeLabel,
  viewerKind,
  type TypeFilter,
} from "@/components/domain/resources/viewer/kinds";
import { cn } from "@/lib/utils";

/**
 * Files shared with this person, side by side with a viewer.
 *
 * **The list is metadata; the viewer is the only thing that fetches bytes.**
 * `/shared-with-me` returns name, type, size and level per row, which is enough
 * to draw an icon, run the search and work the type filter -- so a student with
 * forty shared files downloads none of them until they choose one. One renderer
 * is mounted at a time, keyed by file, so switching releases the previous one.
 *
 * **One component, two layouts.** On a desktop the list and viewer sit beside
 * each other; on a phone the list fills the width until a file is chosen, and
 * the viewer replaces it with a Back action. The same state drives both, so
 * search and filter survive opening a file, rotating the device, and coming
 * back -- there is no navigation involved and nothing to restore.
 */

const ICONS: Record<ReturnType<typeof viewerKind>, ReactNode> = {
  pdf: <FileType className="size-4 text-danger" />,
  image: <ImageIcon className="size-4 text-info" />,
  video: <FileVideo className="size-4 text-primary" />,
  audio: <FileAudio className="size-4 text-warning" />,
  sheet: <FileSpreadsheet className="size-4 text-success" />,
  document: <FileText className="size-4 text-info" />,
  markdown: <FileText className="size-4 text-muted-foreground" />,
  text: <FileText className="size-4 text-muted-foreground" />,
  other: <FileText className="size-4 text-muted-foreground" />,
};

function key(share: SharedResourceResponse): string {
  return `${share.resource_id}`;
}

export default function SharedWithMePage() {
  const timeZone = useDisplayTimeZone();
  const [term, setTerm] = useState("");
  const [filter, setFilter] = useState<TypeFilter>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["shared-with-me"],
    queryFn: () => api.get<SharedResourceResponse[]>("/shared-with-me"),
  });

  const shares = useMemo(() => data ?? [], [data]);

  const filters = useMemo(() => availableFilters(shares), [shares]);

  const shown = useMemo(() => {
    const needle = term.trim().toLowerCase();
    return shares.filter((share) => {
      if (!matchesFilter(share, filter)) return false;
      if (!needle) return true;
      // Title and filename are the same string here, so one test covers the
      // brief's two: the share endpoint reports the resource's name, which is
      // what was uploaded.
      return (share.resource_name ?? "").toLowerCase().includes(needle);
    });
  }, [shares, term, filter]);

  // Resolved against the whole list, not the filtered one: narrowing the
  // filter while a file is open should not blank the viewer.
  const open = useMemo(
    () => shares.find((share) => key(share) === openId) ?? null,
    [shares, openId],
  );

  const file: ViewerFile | null = open
    ? {
        resource_id: open.resource_id,
        resource_name: open.resource_name,
        mime_type: open.mime_type,
        level: open.level,
        size: open.size,
        shared_by_name: open.shared_by_name,
      }
    : null;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <PageHeader
        title="Shared resources"
        description="Files your tutors and administrators have shared with you."
      />

      {error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <LoadingState label="Loading your files" />
      ) : shares.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title="Nothing shared with you yet"
          description="When a tutor or administrator shares a file with you, it appears here."
        />
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          {/* The list. Hidden on a phone once a file is open, where the viewer
              takes the whole width instead of being squeezed beside it. */}
          <section
            className={cn(
              "flex min-h-0 flex-col rounded-xl border border-border-subtle bg-surface",
              openId ? "hidden lg:flex" : "flex",
            )}
          >
            <div className="space-y-2 border-b border-border-subtle p-3">
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  value={term}
                  onChange={(event) => setTerm(event.target.value)}
                  placeholder="Search resources…"
                  aria-label="Search resources"
                  className="pl-8"
                />
              </div>
              <div className="flex flex-wrap gap-1">
                {filters.map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={filter === option}
                    onClick={() => setFilter(option)}
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                      filter === option
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border-subtle text-muted-foreground hover:bg-muted/60",
                    )}
                  >
                    {FILTER_LABELS[option]} ({countFor(shares, option)})
                  </button>
                ))}
              </div>
            </div>

            <ul className="min-h-0 flex-1 divide-y divide-border-subtle overflow-y-auto">
              {shown.length === 0 ? (
                <li className="p-6 text-center text-sm text-muted-foreground">
                  Nothing here matches that.
                </li>
              ) : (
                shown.map((share) => {
                  const id = key(share);
                  const chosen = id === openId;
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        aria-current={chosen ? "true" : undefined}
                        onClick={() => setOpenId(id)}
                        className={cn(
                          "flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors",
                          chosen
                            ? "bg-accent/70 ring-1 ring-inset ring-primary/40"
                            : "hover:bg-muted/50",
                        )}
                      >
                        <span className="mt-0.5 shrink-0">{ICONS[viewerKind(share)]}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {share.resource_name ?? "Untitled"}
                          </span>
                          <span className="block truncate text-2xs text-muted-foreground">
                            {[
                              // `typeLabel`, not the MIME type's second half:
                              // a `.docx` would otherwise read
                              // "VND.OPENXMLFORMATS-OFFICEDOCUMENT.WORDPROCES…",
                              // which tells a student nothing and pushes the
                              // size and date off the row.
                              typeLabel(share),
                              share.size ? formatBytes(share.size) : null,
                              formatDate(share.created_at, { timeZone }),
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          </section>

          <section
            className={cn(
              "min-h-0 overflow-hidden rounded-xl border border-border-subtle bg-surface",
              openId ? "block" : "hidden lg:block",
            )}
          >
            <UniversalViewer file={file} onBack={() => setOpenId(null)} />
          </section>
        </div>
      )}
    </div>
  );
}
