"use client";

/**
 * The video library: every video the caller may watch, and nothing else.
 *
 * The list is the server's answer (`GET /videos`), already narrowed to the
 * caller -- their own, those shared with them by name, and those shared with a
 * batch they study in or teach. Filters and sort are query parameters on that
 * same call, so a filter can never widen what is shown.
 */

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Film, LayoutGrid, List, Plus, Search } from "lucide-react";
import { api, apiPath } from "@/lib/api/client";
import type { PageVideoSummary, VideoSummary } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { Input } from "@/components/ui/form";
import { Select } from "@/components/ui/select";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { BatchPicker, CoursePicker } from "@/components/domain/entity-pickers";
import { AddVideoDialog } from "@/components/domain/videos/video-dialogs";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

const PROVIDERS = [
  { value: "youtube", label: "YouTube" },
  { value: "vimeo", label: "Vimeo" },
  { value: "wistia", label: "Wistia" },
  { value: "brightcove", label: "Brightcove" },
  { value: "dacast", label: "Dacast" },
  { value: "zoom", label: "Zoom" },
  { value: "google_drive", label: "Google Drive / Meet" },
  { value: "microsoft", label: "Microsoft Teams / Stream" },
  { value: "streamyard", label: "StreamYard" },
  { value: "zoho", label: "Zoho Meeting" },
  { value: "direct", label: "Video file" },
  { value: "other", label: "Other" },
];
const SHARING = [
  { value: "all", label: "All I can watch" },
  { value: "mine", label: "Added by me" },
  { value: "shared_with_me", label: "Shared with me" },
];
const SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "title", label: "Title A–Z" },
];

// The grid/list choice is a per-browser convenience, so it lives in
// localStorage -- read through useSyncExternalStore and guarded, because the
// storage may be unavailable (private windows) and the page must work anyway.
const VIEW_KEY = "lms.videos.view";
const listeners = new Set<() => void>();
function readView(): "grid" | "list" {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}
function writeView(view: "grid" | "list"): void {
  try {
    window.localStorage.setItem(VIEW_KEY, view);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
  listeners.forEach((l) => l());
}
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function Thumbnail({ video }: { video: VideoSummary }) {
  const [failed, setFailed] = useState(false);
  if (video.thumbnail_url && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- a redirect through our API, not a static asset
      <img
        src={apiPath(video.thumbnail_url)}
        alt=""
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className="size-full object-cover"
      />
    );
  }
  return (
    <div className="flex size-full flex-col items-center justify-center gap-1 bg-gradient-to-br from-slate-200 to-slate-300 text-slate-600 dark:from-slate-800 dark:to-slate-900 dark:text-slate-300">
      <Film className="size-7" aria-hidden />
      <span className="text-2xs font-medium">{video.provider_label}</span>
    </div>
  );
}

export default function VideoLibraryPage() {
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, search, debouncedSearch, setSearch, setPage, resetPage } = useListState(24);
  const view = useSyncExternalStore(subscribe, readView, () => "grid" as const);
  const [provider, setProvider] = useState<string | null>(null);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [sharing, setSharing] = useState("all");
  const [sort, setSort] = useState("newest");
  const [adding, setAdding] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["videos", { limit, offset, debouncedSearch, provider, courseId, batchId, sharing, sort }],
    queryFn: () =>
      api.get<PageVideoSummary>("/videos", {
        query: {
          limit, offset, sort, sharing,
          q: debouncedSearch || undefined,
          provider: provider || undefined,
          course_id: courseId || undefined,
          batch_id: batchId || undefined,
        },
      }),
  });

  const columns: Column<VideoSummary>[] = [
    {
      key: "title",
      header: "Video",
      cell: (v) => (
        <span className="flex items-center gap-3">
          <span className="block aspect-video w-24 shrink-0 overflow-hidden rounded-md">
            <Thumbnail video={v} />
          </span>
          <span className="min-w-0">
            <Link href={`/videos/${v.public_id}`} className="font-medium hover:underline">
              {v.title}
            </Link>
            {v.description ? (
              <span className="block truncate text-xs text-muted-foreground">{v.description}</span>
            ) : null}
          </span>
        </span>
      ),
    },
    {
      key: "provider",
      header: "Provider",
      cell: (v) => (
        <Badge tone={v.plays_in_lms ? "neutral" : "warning"}>{v.provider_label}</Badge>
      ),
    },
    {
      key: "where",
      header: "Course / batch",
      secondary: true,
      cell: (v) => [v.course_title, v.batch_code].filter(Boolean).join(" · ") || "—",
    },
    {
      key: "owner",
      header: "Added by",
      hideBelow: "md",
      cell: (v) => (v.is_mine ? "You" : v.owner_name ?? "—"),
    },
    {
      key: "created",
      header: "Added",
      hideBelow: "lg",
      cell: (v) => formatDateTime(v.created_at, { timeZone }),
    },
  ];

  const rows = data?.items ?? [];
  return (
    <div className="space-y-5">
      <PageHeader
        title="Video library"
        description="Recordings and videos shared with you, played inside the LMS."
        actions={
          permissions.has("video.create") ? (
            <Button onClick={() => setAdding(true)}>
              <Plus /> Add video
            </Button>
          ) : null
        }
      />

      <Card className="space-y-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search titles and descriptions"
              aria-label="Search videos"
              className="pl-8"
            />
          </div>
          <Select aria-label="Sort" className="w-40" value={sort} options={SORTS}
                  onValueChange={(v) => { setSort(v ?? "newest"); resetPage(); }} />
          <div className="flex rounded-md border border-border-subtle" role="group" aria-label="Layout">
            <Button size="icon-sm" variant={view === "grid" ? "secondary" : "ghost"} aria-pressed={view === "grid"}
                    aria-label="Grid view" onClick={() => writeView("grid")}>
              <LayoutGrid />
            </Button>
            <Button size="icon-sm" variant={view === "list" ? "secondary" : "ghost"} aria-pressed={view === "list"}
                    aria-label="List view" onClick={() => writeView("list")}>
              <List />
            </Button>
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Select aria-label="Provider" value={provider} clearable placeholder="Any provider" options={PROVIDERS}
                  onValueChange={(v) => { setProvider(v); resetPage(); }} />
          <CoursePicker value={courseId} placeholder="Any course" ariaLabel="Filter by course"
                        onValueChange={(v) => { setCourseId(v); resetPage(); }} />
          <BatchPicker value={batchId} placeholder="Any batch" ariaLabel="Filter by batch"
                       onValueChange={(v) => { setBatchId(v); resetPage(); }} />
          <Select aria-label="Sharing" value={sharing} options={SHARING}
                  onValueChange={(v) => { setSharing(v ?? "all"); resetPage(); }} />
        </div>
      </Card>

      {isPending ? (
        <LoadingState rows={6} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Film />}
          title="No videos here"
          description={
            debouncedSearch || provider || courseId || batchId || sharing !== "all"
              ? "Nothing matches these filters."
              : "Videos shared with you, or with a batch you are in, appear here."
          }
        />
      ) : view === "grid" ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {rows.map((v) => (
            <li key={v.public_id}>
              <Link
                href={`/videos/${v.public_id}`}
                className="group block overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-xs transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/40"
              >
                <div className="relative aspect-video overflow-hidden">
                  <Thumbnail video={v} />
                  <Badge tone={v.plays_in_lms ? "neutral" : "warning"} className="absolute left-2 top-2">
                    {v.provider_label}
                  </Badge>
                </div>
                <div className="space-y-1 p-3">
                  <p className="line-clamp-2 text-sm font-medium group-hover:underline">{v.title}</p>
                  {v.description ? (
                    <p className="line-clamp-2 text-xs text-muted-foreground">{v.description}</p>
                  ) : null}
                  <p className="text-2xs text-subtle-foreground">
                    {[v.course_title, v.batch_code].filter(Boolean).join(" · ") || "No course"}
                    {" · "}
                    {v.is_mine ? "Added by you" : v.owner_name ? `Added by ${v.owner_name}` : ""}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(v) => v.public_id}
                   onRowClick={(v) => router.push(`/videos/${v.public_id}`)} />
      )}

      {data && data.total > limit ? (
        <Pagination total={data.total} limit={limit} offset={offset} onChange={setPage} label="videos" />
      ) : null}

      <AddVideoDialog open={adding} onOpenChange={setAdding} onCreated={(v) => router.push(`/videos/${v.public_id}`)} />
    </div>
  );
}
