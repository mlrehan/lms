"use client";

import {
  useRef,
  useState,
  useSyncExternalStore,
  type DragEvent,
  type ReactNode,
} from "react";
import {
  Copy,
  Download,
  File as FileIcon,
  FileSpreadsheet,
  FileText,
  Folder,
  Image as ImageIcon,
  LayoutGrid,
  List as ListIcon,
  MoreVertical,
  Music,
  Pencil,
  Presentation,
  RotateCcw,
  Share2,
  Trash2,
  Video as VideoIcon,
} from "lucide-react";
import type { FolderSummary, ResourceSummary, ResourceType } from "@/lib/api/types";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

/**
 * The Drive-style file browser.
 *
 * Folders and files live in **one** view, folders first, because that is what a
 * file manager is: the table this replaced put folders in a row of small chips
 * above an unrelated data table, so moving a file into a folder meant reading
 * two different lists and the hierarchy never felt like one.
 *
 * Three behaviours carry most of the "feels like Drive" weight, and each is a
 * real interaction rather than styling:
 *
 * * **Drag a file onto a folder to move it.** The previous flow was "click Move,
 *   navigate to the destination, click a confirm bar" — three steps and a mode.
 *   Dragging is one gesture, and the drop target highlights so it is obvious
 *   where the file will land.
 * * **Drop files from the desktop to upload.** Onto the empty space, into the
 *   current folder. The whole surface is the drop zone, not a small dashed box.
 * * **Right-click for the menu.** The same actions as the hover `⋮`, because a
 *   context menu that offers less than the visible button is worse than none.
 *
 * Selection is single-item on purpose: every action the API exposes acts on one
 * resource, so a multi-select would draw a checkbox column that no bulk endpoint
 * can serve.
 */

export type DriveLayout = "grid" | "list";

const LAYOUT_KEY = "lms.drive.layout";

/**
 * The drag payload that marks "a resource is being dragged within the app".
 *
 * A private MIME type, and a named constant because it is written in one place
 * and read in two: a folder accepts a drop only when it sees this, so a literal
 * that drifted in any one of the three would break drag-to-move *silently* --
 * the drag would simply refuse to drop, with no error anywhere. It also has to
 * be distinguishable from a desktop file drag ("Files"), which the same
 * surfaces handle completely differently.
 */
const RESOURCE_DRAG_TYPE = "application/x-resource-id";

/**
 * Grid or list, remembered in this browser and shared by every file screen.
 *
 * One preference rather than one per screen: "how I like to look at files" is a
 * single opinion, and Drive treats it that way too.
 *
 * Read through `useSyncExternalStore` rather than an effect. Reading
 * `localStorage` during render would make the first client render disagree with
 * the server's markup and React would throw the hydration away; adopting it in
 * an effect instead costs an extra render on every mount and is what the React
 * Compiler flags as a cascading render. `useSyncExternalStore` is the primitive
 * for exactly this: `getServerSnapshot` supplies the SSR value, the client
 * snapshot is read once and cached, and a change notifies every mounted view.
 *
 * `localStorage` can throw outright — a browser blocking site data, a sandboxed
 * frame — so both accesses are guarded and the view works with nothing stored,
 * matching `lib/preferences.ts`.
 */
const listeners = new Set<() => void>();

/** Cached so `getSnapshot` returns a stable value; re-reading each call would
 *  be a new string every time and React would re-render forever. */
let cached: DriveLayout | null = null;

function readLayout(): DriveLayout {
  if (cached !== null) return cached;
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(LAYOUT_KEY);
  } catch {
    stored = null;
  }
  cached = stored === "list" || stored === "grid" ? stored : "grid";
  return cached;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useDriveLayout(fallback: DriveLayout = "grid") {
  const layout = useSyncExternalStore(subscribe, readLayout, () => fallback);

  function choose(next: DriveLayout) {
    cached = next;
    try {
      window.localStorage.setItem(LAYOUT_KEY, next);
    } catch {
      // A viewer who blocks site data still gets a working browser; their
      // choice just is not remembered between visits.
    }
    for (const listener of listeners) listener();
  }

  return [layout, choose] as const;
}

/**
 * The icon for a file, returned as an **element** rather than a component type.
 *
 * The obvious shape — `const Icon = iconFor(...)` then `<Icon />` — is what the
 * React Compiler flags as "creating a component during render": `Icon` is a new
 * binding each render, so React treats it as a different component type and
 * remounts it. Returning finished elements of fixed types avoids that entirely.
 */
function ResourceIcon({
  type,
  mime,
  className,
}: {
  type: ResourceType;
  mime?: string | null;
  className?: string;
}) {
  if (type === "Video" || type === "Recordings" || mime?.startsWith("video/")) {
    return <VideoIcon className={className} aria-hidden />;
  }
  if (type === "Audio" || mime?.startsWith("audio/")) {
    return <Music className={className} aria-hidden />;
  }
  if (type === "Presentation") {
    return <Presentation className={className} aria-hidden />;
  }
  if (mime?.startsWith("image/")) {
    return <ImageIcon className={className} aria-hidden />;
  }
  if (mime?.includes("spreadsheet") || mime?.includes("excel") || mime === "text/csv") {
    return <FileSpreadsheet className={className} aria-hidden />;
  }
  if (
    type === "Lecture Sheet" ||
    type === "Document" ||
    type === "Policy Document" ||
    mime?.startsWith("text/") ||
    mime === "application/pdf"
  ) {
    return <FileText className={className} aria-hidden />;
  }
  return <FileIcon className={className} aria-hidden />;
}

function formatBytes(size: number | null | undefined): string {
  if (size === null || size === undefined) return "—";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

export interface DriveActions {
  onOpenFolder: (folder: FolderSummary) => void;
  onOpenResource: (resource: ResourceSummary) => void;
  onMoveResource: (resourceId: string, folderId: string | null) => void;
  onUploadFiles: (files: File[]) => void;
  onDownload: (resource: ResourceSummary) => void;
  onCopy: (resource: ResourceSummary) => void;
  onShare: (resource: ResourceSummary) => void;
  onDelete: (resource: ResourceSummary) => void;
  onRestore: (resource: ResourceSummary) => void;
  onRenameFolder: (folder: FolderSummary) => void;
  onDeleteFolder: (folder: FolderSummary) => void;
}

interface MenuState {
  x: number;
  y: number;
  resource?: ResourceSummary;
  folder?: FolderSummary;
}

export function DriveToolbar({
  layout,
  onLayoutChange,
  children,
}: {
  layout: DriveLayout;
  onLayoutChange: (layout: DriveLayout) => void;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {children}
      <div className="ml-auto flex items-center rounded-full border border-border-subtle p-0.5">
        <button
          type="button"
          aria-label="Grid view"
          aria-pressed={layout === "grid"}
          onClick={() => onLayoutChange("grid")}
          className={cn(
            "rounded-full p-1.5 transition-colors",
            layout === "grid" ? "bg-muted text-foreground" : "text-muted-foreground",
          )}
        >
          <LayoutGrid className="size-4" aria-hidden />
        </button>
        <button
          type="button"
          aria-label="List view"
          aria-pressed={layout === "list"}
          onClick={() => onLayoutChange("list")}
          className={cn(
            "rounded-full p-1.5 transition-colors",
            layout === "list" ? "bg-muted text-foreground" : "text-muted-foreground",
          )}
        >
          <ListIcon className="size-4" aria-hidden />
        </button>
      </div>
    </div>
  );
}

export function DriveView({
  folders,
  resources,
  layout,
  canWrite,
  inBin,
  emptyMessage,
  actions,
  formatDate,
}: {
  folders: FolderSummary[];
  resources: ResourceSummary[];
  layout: DriveLayout;
  canWrite: boolean;
  inBin: boolean;
  emptyMessage: string;
  actions: DriveActions;
  formatDate: (iso: string) => string;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [dragOverFolder, setDragOverFolder] = useState<string | null>(null);
  const [fileDragDepth, setFileDragDepth] = useState(0);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  /** A desktop file drag, as opposed to a resource being dragged within the app. */
  function isFileDrag(event: DragEvent): boolean {
    return Array.from(event.dataTransfer.types).includes("Files");
  }

  function onSurfaceDragEnter(event: DragEvent) {
    if (!canWrite || inBin || !isFileDrag(event)) return;
    event.preventDefault();
    setFileDragDepth((depth) => depth + 1);
  }

  function onSurfaceDragLeave(event: DragEvent) {
    if (!canWrite || inBin || !isFileDrag(event)) return;
    event.preventDefault();
    // Counted rather than toggled: dragging across a child element fires
    // `dragleave` on the parent, so a boolean flickers the overlay off while
    // the pointer is still inside.
    setFileDragDepth((depth) => Math.max(0, depth - 1));
  }

  function onSurfaceDrop(event: DragEvent) {
    if (!canWrite || inBin || !isFileDrag(event)) return;
    event.preventDefault();
    setFileDragDepth(0);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) actions.onUploadFiles(files);
  }

  function openMenu(event: React.MouseEvent, item: MenuState) {
    event.preventDefault();
    setMenu(item);
  }

  const empty = folders.length === 0 && resources.length === 0;

  return (
    <div
      ref={surfaceRef}
      className="relative"
      onDragEnter={onSurfaceDragEnter}
      onDragOver={(event) => {
        if (canWrite && !inBin && isFileDrag(event)) event.preventDefault();
      }}
      onDragLeave={onSurfaceDragLeave}
      onDrop={onSurfaceDrop}
      onClick={() => setSelected(null)}
    >
      {fileDragDepth > 0 ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-accent/80">
          <p className="text-sm font-medium text-accent-foreground">Drop files to upload here</p>
        </div>
      ) : null}

      {empty ? (
        <div className="rounded-xl border border-border-subtle py-16 text-center">
          <Folder className="mx-auto size-8 text-muted-foreground" aria-hidden />
          <p className="mt-3 text-sm text-muted-foreground">{emptyMessage}</p>
          {canWrite && !inBin ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Drag files here to upload them.
            </p>
          ) : null}
        </div>
      ) : layout === "grid" ? (
        <div className="space-y-5">
          {folders.length > 0 ? (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Folders
              </h3>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {folders.map((folder) => (
                  <FolderTile
                    key={folder.public_id}
                    folder={folder}
                    selected={selected === folder.public_id}
                    dragOver={dragOverFolder === folder.public_id}
                    canWrite={canWrite}
                    onSelect={() => setSelected(folder.public_id)}
                    onOpen={() => actions.onOpenFolder(folder)}
                    onContextMenu={(event) =>
                      openMenu(event, { x: event.clientX, y: event.clientY, folder })
                    }
                    onDragStateChange={(over) =>
                      setDragOverFolder(over ? folder.public_id : null)
                    }
                    onDropResource={(resourceId) => {
                      setDragOverFolder(null);
                      actions.onMoveResource(resourceId, folder.public_id);
                    }}
                    onRename={() => actions.onRenameFolder(folder)}
                    onDelete={() => actions.onDeleteFolder(folder)}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {resources.length > 0 ? (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Files
              </h3>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {resources.map((resource) => (
                  <FileTile
                    key={resource.public_id}
                    resource={resource}
                    selected={selected === resource.public_id}
                    canWrite={canWrite}
                    inBin={inBin}
                    formatDate={formatDate}
                    actions={actions}
                    onSelect={() => setSelected(resource.public_id)}
                    onContextMenu={(event) =>
                      openMenu(event, { x: event.clientX, y: event.clientY, resource })
                    }
                  />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border-subtle">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">Name</th>
                <th className="hidden px-3 py-2 text-left font-medium sm:table-cell">Type</th>
                <th className="hidden px-3 py-2 text-left font-medium md:table-cell">Added</th>
                <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Size</th>
                <th className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {folders.map((folder) => (
                <FolderRow
                  key={folder.public_id}
                  folder={folder}
                  selected={selected === folder.public_id}
                  dragOver={dragOverFolder === folder.public_id}
                  canWrite={canWrite}
                  formatDate={formatDate}
                  onSelect={() => setSelected(folder.public_id)}
                  onOpen={() => actions.onOpenFolder(folder)}
                  onContextMenu={(event) =>
                    openMenu(event, { x: event.clientX, y: event.clientY, folder })
                  }
                  onDragStateChange={(over) =>
                    setDragOverFolder(over ? folder.public_id : null)
                  }
                  onDropResource={(resourceId) => {
                    setDragOverFolder(null);
                    actions.onMoveResource(resourceId, folder.public_id);
                  }}
                  onRename={() => actions.onRenameFolder(folder)}
                  onDelete={() => actions.onDeleteFolder(folder)}
                />
              ))}
              {resources.map((resource) => (
                <FileRow
                  key={resource.public_id}
                  resource={resource}
                  selected={selected === resource.public_id}
                  canWrite={canWrite}
                  inBin={inBin}
                  formatDate={formatDate}
                  actions={actions}
                  onSelect={() => setSelected(resource.public_id)}
                  onContextMenu={(event) =>
                    openMenu(event, { x: event.clientX, y: event.clientY, resource })
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {menu ? (
        <ContextMenu
          state={menu}
          canWrite={canWrite}
          inBin={inBin}
          actions={actions}
          onClose={() => setMenu(null)}
        />
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Folders                                                                     */
/* -------------------------------------------------------------------------- */

interface FolderTargetProps {
  folder: FolderSummary;
  selected: boolean;
  dragOver: boolean;
  canWrite: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onContextMenu: (event: React.MouseEvent) => void;
  onDragStateChange: (over: boolean) => void;
  onDropResource: (resourceId: string) => void;
  onRename: () => void;
  onDelete: () => void;
}

/** Shared drop handling: a folder accepts a resource id dragged from a tile or row. */
function useFolderDropTarget({
  canWrite,
  onDragStateChange,
  onDropResource,
}: Pick<FolderTargetProps, "canWrite" | "onDragStateChange" | "onDropResource">) {
  return {
    onDragOver: (event: DragEvent) => {
      if (!canWrite) return;
      if (!event.dataTransfer.types.includes(RESOURCE_DRAG_TYPE)) return;
      // Preventing default is what makes this a valid drop target at all; the
      // browser rejects the drop otherwise and the drag snaps back.
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      onDragStateChange(true);
    },
    onDragLeave: () => onDragStateChange(false),
    onDrop: (event: DragEvent) => {
      if (!canWrite) return;
      const id = event.dataTransfer.getData(RESOURCE_DRAG_TYPE);
      if (!id) return;
      event.preventDefault();
      event.stopPropagation();
      onDropResource(id);
    },
  };
}

function FolderTile(props: FolderTargetProps) {
  const drop = useFolderDropTarget(props);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={props.folder.name}
      onClick={(event) => {
        event.stopPropagation();
        props.onSelect();
      }}
      onDoubleClick={props.onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          props.onOpen();
        }
      }}
      onContextMenu={props.onContextMenu}
      {...drop}
      className={cn(
        "group flex cursor-default items-center gap-2.5 rounded-xl border px-3 py-3 text-sm transition-colors",
        props.dragOver
          ? "border-primary bg-accent"
          : props.selected
            ? "border-primary/40 bg-accent/60"
            : "border-border-subtle bg-surface hover:bg-muted/60",
      )}
    >
      <Folder className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 truncate font-medium">{props.folder.name}</span>
      {props.canWrite ? (
        <FolderMenu onRename={props.onRename} onDelete={props.onDelete} onOpen={props.onOpen} />
      ) : null}
    </div>
  );
}

function FolderRow(props: FolderTargetProps & { formatDate: (iso: string) => string }) {
  const drop = useFolderDropTarget(props);
  return (
    <tr
      onClick={(event) => {
        event.stopPropagation();
        props.onSelect();
      }}
      onDoubleClick={props.onOpen}
      onContextMenu={props.onContextMenu}
      {...drop}
      className={cn(
        "border-b border-border-subtle last:border-0",
        props.dragOver
          ? "bg-accent"
          : props.selected
            ? "bg-accent/60"
            : "hover:bg-muted/50",
      )}
    >
      <td className="px-3 py-2">
        <button
          type="button"
          className="flex items-center gap-2 text-left font-medium"
          onClick={props.onOpen}
        >
          <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">{props.folder.name}</span>
        </button>
      </td>
      <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">Folder</td>
      <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">
        {props.formatDate(props.folder.created_at)}
      </td>
      <td className="hidden px-3 py-2 text-right text-muted-foreground sm:table-cell">—</td>
      <td className="px-3 py-2 text-right">
        {props.canWrite ? (
          <FolderMenu onRename={props.onRename} onDelete={props.onDelete} onOpen={props.onOpen} />
        ) : null}
      </td>
    </tr>
  );
}

function FolderMenu({
  onOpen,
  onRename,
  onDelete,
}: {
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label="Folder actions"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted"
            onClick={(event) => event.stopPropagation()}
          >
            <MoreVertical className="size-4" aria-hidden />
          </button>
        }
      />
      <DropdownMenuContent align="end">
        {/* Base UI's Menu.Item fires onClick, not onSelect -- onSelect is a real
            DOM handler on a div, so TypeScript accepts it and it never runs. */}
        <DropdownMenuItem onClick={onOpen}>
          <Folder /> Open
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onRename}>
          <Pencil /> Rename
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onClick={onDelete}>
          <Trash2 /> Delete folder
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/* -------------------------------------------------------------------------- */
/* Files                                                                       */
/* -------------------------------------------------------------------------- */

interface FileProps {
  resource: ResourceSummary;
  selected: boolean;
  canWrite: boolean;
  inBin: boolean;
  formatDate: (iso: string) => string;
  actions: DriveActions;
  onSelect: () => void;
  onContextMenu: (event: React.MouseEvent) => void;
}

function dragProps(resource: ResourceSummary, canWrite: boolean) {
  if (!canWrite) return {};
  return {
    draggable: true,
    onDragStart: (event: DragEvent) => {
      // A private type, so a folder can tell a resource drag from a desktop
      // file drag and accept only the one it can act on.
      event.dataTransfer.setData(RESOURCE_DRAG_TYPE, resource.public_id);
      event.dataTransfer.effectAllowed = "move";
    },
  };
}

function FileTile(props: FileProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={props.resource.name ?? "Untitled"}
      onClick={(event) => {
        event.stopPropagation();
        props.onSelect();
      }}
      onDoubleClick={() => props.actions.onOpenResource(props.resource)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          props.actions.onOpenResource(props.resource);
        }
      }}
      onContextMenu={props.onContextMenu}
      {...dragProps(props.resource, props.canWrite && !props.inBin)}
      className={cn(
        "flex cursor-default flex-col gap-2 rounded-xl border p-3 transition-colors",
        props.selected
          ? "border-primary/40 bg-accent/60"
          : "border-border-subtle bg-surface hover:bg-muted/60",
      )}
    >
      <div className="flex items-start gap-2">
        <ResourceIcon
          type={props.resource.resource_type}
          mime={props.resource.mime_type}
          className="size-5 shrink-0 text-muted-foreground"
        />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {props.resource.name ?? "Untitled"}
        </span>
        <FileMenu {...props} />
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="truncate">{props.resource.resource_type}</span>
        <span>{formatBytes(props.resource.size)}</span>
      </div>
      {props.resource.is_restricted ? (
        <span className="w-fit rounded-full border border-border-subtle px-2 py-0.5 text-[10px] text-muted-foreground">
          Staff only
        </span>
      ) : null}
    </div>
  );
}

function FileRow(props: FileProps) {
  return (
    <tr
      onClick={(event) => {
        event.stopPropagation();
        props.onSelect();
      }}
      onDoubleClick={() => props.actions.onOpenResource(props.resource)}
      onContextMenu={props.onContextMenu}
      {...dragProps(props.resource, props.canWrite && !props.inBin)}
      className={cn(
        "border-b border-border-subtle last:border-0",
        props.selected ? "bg-accent/60" : "hover:bg-muted/50",
      )}
    >
      <td className="px-3 py-2">
        <button
          type="button"
          className="flex items-center gap-2 text-left font-medium"
          onClick={() => props.actions.onOpenResource(props.resource)}
        >
          <ResourceIcon
            type={props.resource.resource_type}
            mime={props.resource.mime_type}
            className="size-4 shrink-0 text-muted-foreground"
          />
          <span className="truncate">{props.resource.name ?? "Untitled"}</span>
          {props.resource.is_restricted ? (
            <span className="shrink-0 rounded-full border border-border-subtle px-2 py-0.5 text-[10px] text-muted-foreground">
              Staff only
            </span>
          ) : null}
        </button>
      </td>
      <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">
        {props.resource.resource_type}
      </td>
      <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">
        {props.formatDate(props.resource.created_at)}
      </td>
      <td className="hidden px-3 py-2 text-right tabular-nums text-muted-foreground sm:table-cell">
        {formatBytes(props.resource.size)}
      </td>
      <td className="px-3 py-2 text-right">
        <FileMenu {...props} />
      </td>
    </tr>
  );
}

function FileMenu({ resource, canWrite, inBin, actions }: FileProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label={`Actions for ${resource.name ?? "file"}`}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted"
            onClick={(event) => event.stopPropagation()}
          >
            <MoreVertical className="size-4" aria-hidden />
          </button>
        }
      />
      <DropdownMenuContent align="end">
        {inBin ? (
          <DropdownMenuItem onClick={() => actions.onRestore(resource)}>
            <RotateCcw /> Restore
          </DropdownMenuItem>
        ) : (
          <>
            <DropdownMenuItem onClick={() => actions.onOpenResource(resource)}>
              <FileText /> Open details
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => actions.onDownload(resource)}>
              <Download /> Download
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => actions.onShare(resource)}>
              <Share2 /> Share
            </DropdownMenuItem>
            {canWrite ? (
              <>
                <DropdownMenuItem onClick={() => actions.onCopy(resource)}>
                  <Copy /> Make a copy
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem destructive onClick={() => actions.onDelete(resource)}>
                  <Trash2 /> Move to bin
                </DropdownMenuItem>
              </>
            ) : null}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/* -------------------------------------------------------------------------- */
/* Right-click menu                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Positioned at the pointer, closed by the next click anywhere.
 *
 * Deliberately not the Base UI menu: that one anchors to a trigger element, and
 * there is no trigger here — the anchor is wherever the pointer was.
 */
function ContextMenu({
  state,
  canWrite,
  inBin,
  actions,
  onClose,
}: {
  state: MenuState;
  canWrite: boolean;
  inBin: boolean;
  actions: DriveActions;
  onClose: () => void;
}) {
  const item =
    "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-4";

  function run(action: () => void) {
    action();
    onClose();
  }

  return (
    <>
      {/* Catches the dismissing click before anything underneath reacts to it. */}
      <div
        className="fixed inset-0 z-40"
        onClick={onClose}
        onContextMenu={(event) => {
          event.preventDefault();
          onClose();
        }}
      />
      <div
        role="menu"
        className="fixed z-50 min-w-48 rounded-lg border border-border-subtle bg-surface p-1 shadow-lg"
        style={{ left: state.x, top: state.y }}
      >
        {state.folder ? (
          <>
            <button type="button" className={item} onClick={() => run(() => actions.onOpenFolder(state.folder!))}>
              <Folder /> Open
            </button>
            {canWrite ? (
              <>
                <button type="button" className={item} onClick={() => run(() => actions.onRenameFolder(state.folder!))}>
                  <Pencil /> Rename
                </button>
                <button
                  type="button"
                  className={cn(item, "text-danger hover:bg-danger/10 hover:text-danger")}
                  onClick={() => run(() => actions.onDeleteFolder(state.folder!))}
                >
                  <Trash2 /> Delete folder
                </button>
              </>
            ) : null}
          </>
        ) : state.resource ? (
          inBin ? (
            <button type="button" className={item} onClick={() => run(() => actions.onRestore(state.resource!))}>
              <RotateCcw /> Restore
            </button>
          ) : (
            <>
              <button type="button" className={item} onClick={() => run(() => actions.onOpenResource(state.resource!))}>
                <FileText /> Open details
              </button>
              <button type="button" className={item} onClick={() => run(() => actions.onDownload(state.resource!))}>
                <Download /> Download
              </button>
              <button type="button" className={item} onClick={() => run(() => actions.onShare(state.resource!))}>
                <Share2 /> Share
              </button>
              {canWrite ? (
                <>
                  <button type="button" className={item} onClick={() => run(() => actions.onCopy(state.resource!))}>
                    <Copy /> Make a copy
                  </button>
                  <button
                    type="button"
                    className={cn(item, "text-danger hover:bg-danger/10 hover:text-danger")}
                    onClick={() => run(() => actions.onDelete(state.resource!))}
                  >
                    <Trash2 /> Move to bin
                  </button>
                </>
              ) : null}
            </>
          )
        ) : null}
      </div>
    </>
  );
}

export { formatBytes };
