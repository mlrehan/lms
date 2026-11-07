"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileAudio,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
  Folder,
  GraduationCap,
  Image as ImageIcon,
  Inbox,
  Search,
} from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  SharedCourseGroup,
  SharedFolderContentsResponse,
  SharedFolderEntry,
  SharedLibraryResponse,
  SharedResourceResponse,
} from "@/lib/api/types";
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
 * Files and folders shared with this person, grouped by course, beside a viewer.
 *
 * **Grouped by the course the material belongs to**, which the server works
 * out from the file or folder itself -- never from anything the sharer said --
 * and sends already grouped. A student on three courses sees three sections,
 * and whatever belongs to no course is last, under "General".
 *
 * **A shared folder opens in place.** Its subfolders and files come from
 * `/shared-with-me/folders/{id}`, one level at a time, and the trail above
 * them stops at the folder that was shared: the folders above it are
 * somebody else's and were not part of what was handed over.
 *
 * **The list is metadata; the viewer is the only thing that fetches bytes.**
 * One renderer is mounted at a time, keyed by file, so switching releases the
 * previous one. On a phone the list fills the width until a file is chosen and
 * the viewer replaces it with a Back action; the same state drives both.
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

const GENERAL = "general";

function groupKey(group: SharedCourseGroup): string {
  return group.course_id ?? GENERAL;
}

function groupTitle(group: SharedCourseGroup): string {
  return group.course_title ?? "General";
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function toViewer(file: SharedResourceResponse): ViewerFile {
  return {
    resource_id: file.resource_id,
    resource_name: file.resource_name,
    mime_type: file.mime_type,
    level: file.level,
    size: file.size,
    shared_by_name: file.shared_by_name,
  };
}

function FileButton({
  file,
  chosen,
  timeZone,
  onOpen,
}: {
  file: SharedResourceResponse;
  chosen: boolean;
  timeZone: string;
  onOpen: () => void;
}): ReactNode {
  return (
    <button
      type="button"
      aria-current={chosen ? "true" : undefined}
      onClick={onOpen}
      className={cn(
        "flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors",
        chosen ? "bg-accent/70 ring-1 ring-inset ring-primary/40" : "hover:bg-muted/50",
      )}
    >
      <span className="mt-0.5 shrink-0">{ICONS[viewerKind(file)]}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{file.resource_name ?? "Untitled"}</span>
        <span className="block truncate text-2xs text-muted-foreground">
          {[
            // `typeLabel`, not the MIME type's second half: a `.docx` would
            // otherwise read "VND.OPENXMLFORMATS-OFFICEDOCUMENT.WORDPROCES…".
            typeLabel(file),
            file.size ? formatBytes(file.size) : null,
            formatDate(file.created_at, { timeZone }),
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </span>
    </button>
  );
}

function FolderButton({ name, detail, onOpen }: { name: string; detail?: string; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-muted/50"
    >
      <Folder className="size-4 shrink-0 text-warning" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{name}</span>
        {detail ? (
          <span className="block truncate text-2xs text-muted-foreground">{detail}</span>
        ) : null}
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
    </button>
  );
}

export default function SharedWithMePage() {
  const timeZone = useDisplayTimeZone();
  const [term, setTerm] = useState("");
  const [filter, setFilter] = useState<TypeFilter>("all");
  const [openFile, setOpenFile] = useState<SharedResourceResponse | null>(null);
  const [folderId, setFolderId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const library = useQuery({
    queryKey: ["shared-with-me", "library"],
    queryFn: () => api.get<SharedLibraryResponse>("/shared-with-me/library"),
  });

  const folder = useQuery({
    queryKey: ["shared-with-me", "folder", folderId],
    queryFn: () =>
      api.get<SharedFolderContentsResponse>(`/shared-with-me/folders/${segment(folderId!)}`),
    enabled: folderId !== null,
  });

  const groups = useMemo(() => library.data?.groups ?? [], [library.data]);

  // The files the search and the type filter work over: every file in view --
  // all groups at the top level, the open folder's files inside one.
  const filesInView = useMemo<SharedResourceResponse[]>(
    () =>
      folderId !== null
        ? (folder.data?.files ?? [])
        : groups.flatMap((group) => group.files ?? []),
    [folderId, folder.data, groups],
  );
  const filters = useMemo(() => availableFilters(filesInView), [filesInView]);

  const needle = term.trim().toLowerCase();
  const fileMatches = (file: SharedResourceResponse) =>
    matchesFilter(file, filter) &&
    (!needle || (file.resource_name ?? "").toLowerCase().includes(needle));
  const folderMatches = (name: string) =>
    filter === "all" && (!needle || name.toLowerCase().includes(needle));

  function toggle(key: string): void {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function openFolder(id: string): void {
    setFolderId(id);
    setTerm("");
    setFilter("all");
  }

  const total = (library.data?.total_files ?? 0) + (library.data?.total_folders ?? 0);

  function topLevel(): ReactNode {
    const shown = groups
      .map((group) => ({
        group,
        folders: (group.folders ?? []).filter((f) => folderMatches(f.folder_name)),
        files: (group.files ?? []).filter(fileMatches),
      }))
      .filter((entry) => entry.folders.length + entry.files.length > 0);

    if (shown.length === 0) {
      return <p className="p-6 text-center text-sm text-muted-foreground">Nothing here matches that.</p>;
    }
    return shown.map(({ group, folders, files }) => {
      const key = groupKey(group);
      const isOpen = !collapsed.has(key) || Boolean(needle);
      const counts = [
        folders.length > 0 ? plural(folders.length, "folder", "folders") : null,
        files.length > 0 ? plural(files.length, "file", "files") : null,
      ]
        .filter(Boolean)
        .join(" · ");
      return (
        <section key={key} className="border-b border-border-subtle last:border-b-0">
          <button
            type="button"
            aria-expanded={isOpen}
            onClick={() => toggle(key)}
            className="flex w-full items-center gap-2 bg-surface-muted/60 px-3 py-2 text-left hover:bg-muted/60"
          >
            {isOpen ? (
              <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            ) : (
              <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            )}
            <GraduationCap className="size-4 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-sm font-semibold">{groupTitle(group)}</span>
            <span className="shrink-0 text-2xs text-muted-foreground">{counts}</span>
          </button>
          {isOpen ? (
            <ul className="divide-y divide-border-subtle">
              {folders.map((f) => (
                <li key={`folder-${f.folder_id}`}>
                  <FolderButton
                    name={f.folder_name}
                    detail={f.shared_by_name ? `Shared by ${f.shared_by_name}` : undefined}
                    onOpen={() => openFolder(f.folder_id)}
                  />
                </li>
              ))}
              {files.map((file) => (
                <li key={`file-${file.resource_id}`}>
                  <FileButton
                    file={file}
                    chosen={openFile?.resource_id === file.resource_id}
                    timeZone={timeZone}
                    onOpen={() => setOpenFile(file)}
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      );
    });
  }

  function insideFolder(): ReactNode {
    if (folder.error) {
      return <ErrorState error={folder.error} onRetry={() => void folder.refetch()} />;
    }
    if (folder.isPending || !folder.data) return <LoadingState label="Opening folder" />;
    const data = folder.data;
    const folders = (data.folders ?? []).filter((f) => folderMatches(f.name));
    const files = (data.files ?? []).filter(fileMatches);
    if (folders.length + files.length === 0) {
      return (
        <p className="p-6 text-center text-sm text-muted-foreground">
          {(data.folders ?? []).length + (data.files ?? []).length === 0
            ? "This folder is empty."
            : "Nothing here matches that."}
        </p>
      );
    }
    return (
      <ul className="divide-y divide-border-subtle">
        {folders.map((f: SharedFolderEntry) => (
          <li key={`folder-${f.folder_id}`}>
            <FolderButton name={f.name} onOpen={() => openFolder(f.folder_id)} />
          </li>
        ))}
        {files.map((file) => (
          <li key={`file-${file.resource_id}`}>
            <FileButton
              file={file}
              chosen={openFile?.resource_id === file.resource_id}
              timeZone={timeZone}
              onOpen={() => setOpenFile(file)}
            />
          </li>
        ))}
      </ul>
    );
  }

  const path = folder.data?.path ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <PageHeader
        title="Shared resources"
        description="Files and folders your tutors and administrators have shared with you, by course."
      />

      {library.error ? (
        <ErrorState error={library.error} onRetry={() => void library.refetch()} />
      ) : library.isPending ? (
        <LoadingState label="Loading your files" />
      ) : total === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title="Nothing shared with you yet"
          description="When a tutor or administrator shares a file or a folder with you, it appears here."
        />
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          {/* The list. Hidden on a phone once a file is open, where the viewer
              takes the whole width instead of being squeezed beside it. */}
          <section
            className={cn(
              "flex min-h-0 flex-col rounded-xl border border-border-subtle bg-surface",
              openFile ? "hidden lg:flex" : "flex",
            )}
          >
            <div className="space-y-2 border-b border-border-subtle p-3">
              {folderId !== null ? (
                <nav aria-label="Folder" className="flex flex-wrap items-center gap-1 text-xs">
                  <button
                    type="button"
                    onClick={() => setFolderId(null)}
                    className="inline-flex items-center gap-1 rounded px-1 py-0.5 font-medium text-primary hover:bg-muted"
                  >
                    <ChevronLeft className="size-3.5" aria-hidden /> Shared with me
                  </button>
                  {folder.data?.course_title ? (
                    <span className="text-muted-foreground">/ {folder.data.course_title}</span>
                  ) : null}
                  {path.map((entry, index) => (
                    <span key={entry.folder_id} className="inline-flex items-center gap-1">
                      <span className="text-muted-foreground">/</span>
                      {index === path.length - 1 ? (
                        <span className="font-medium">{entry.name}</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => openFolder(entry.folder_id)}
                          className="rounded px-1 py-0.5 hover:bg-muted"
                        >
                          {entry.name}
                        </button>
                      )}
                    </span>
                  ))}
                </nav>
              ) : null}
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  value={term}
                  onChange={(event) => setTerm(event.target.value)}
                  placeholder={folderId !== null ? "Search this folder…" : "Search resources…"}
                  aria-label="Search resources"
                  className="pl-8"
                />
              </div>
              {filters.length > 1 ? (
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
                      {FILTER_LABELS[option]} ({countFor(filesInView, option)})
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {folderId !== null ? insideFolder() : topLevel()}
            </div>
          </section>

          <section
            className={cn(
              "min-h-0 overflow-hidden rounded-xl border border-border-subtle bg-surface",
              openFile ? "block" : "hidden lg:block",
            )}
          >
            <UniversalViewer
              key={openFile?.resource_id ?? "none"}
              file={openFile ? toViewer(openFile) : null}
              onBack={() => setOpenFile(null)}
            />
          </section>
        </div>
      )}
    </div>
  );
}
