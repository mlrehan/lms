"use client";

import { Suspense, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ChevronRight,
  Plus,

  Download,
  FolderPlus,
  History,
  Link2,
  Share2,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { api, downloadFile, segment } from "@/lib/api/client";
import type {
  FolderResponse,
  FolderSummary,
  PageResourceSummary,
  ResourcePermissionResponse,
  ResourceResponse,
  ResourceSummary,
  ShareLinkResponse,
  SharedResourceResponse,
} from "@/lib/api/types";
import {
  ResourcePermissionLevelValues,
  ResourceScopeTypeValues,
  ResourceTypeValues,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Switch } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { FilePreview } from "@/components/domain/resources/file-preview";
import { NewFolderDialog } from "@/components/domain/resources/new-folder-dialog";
import { UploadDialog } from "@/components/domain/resources/upload-dialog";
import {
  DriveToolbar,
  DriveView,
  type DriveActions,
  useDriveLayout,
} from "@/components/domain/resources/drive-view";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

function formatBytes(size: number | null | undefined): string {
  if (size === null || size === undefined) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/* -------------------------------------------------------------------------- */
/* Upload                                                                      */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/* Resource detail                                                             */
/* -------------------------------------------------------------------------- */

function ResourceDrawer({
  resourceId,
  onClose,
}: {
  resourceId: string | null;
  onClose: () => void;
}) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const versionInput = useRef<HTMLInputElement>(null);
  const [changeNote, setChangeNote] = useState("");
  const [rename, setRename] = useState<string | null>(null);
  const [shareWith, setShareWith] = useState<string | null>(null);
  const [grant, setGrant] = useState({ scope_type: "COURSE", scope_public_id: "", level: "VIEW" });

  const resource = useQuery({
    queryKey: ["resources", "detail", resourceId],
    queryFn: () => api.get<ResourceResponse>(`/resources/${segment(resourceId!)}`),
    enabled: resourceId !== null,
  });

  const grants = useQuery({
    queryKey: ["resource-permissions", resourceId],
    queryFn: () =>
      api.get<ResourcePermissionResponse[]>("/resource-permissions", {
        query: { resource_id: resourceId! },
      }),
    enabled: resourceId !== null && permissions.has("resource.update"),
  });

  const uploadVersion = useApiMutation<ResourceResponse, File>({
    mutationFn: (file) => {
      const form = new FormData();
      form.append("file", file);
      if (changeNote) form.append("change_note", changeNote);
      return api.post<ResourceResponse>(`/resources/${segment(resourceId!)}/versions`, {
        body: form,
      });
    },
    success: "New version uploaded.",
    invalidate: [["resources"]],
    onSuccess: () => {
      setChangeNote("");
      if (versionInput.current) versionInput.current.value = "";
    },
  });

  // VIEW by default: the narrower of the two, so a share that forgets to say
  // grants the less. This used to be unreachable -- `shared_resources.level`
  // was stored and read, but nothing set it, so every share was DOWNLOAD.
  const [shareLevel, setShareLevel] = useState<"VIEW" | "DOWNLOAD">("VIEW");

  /*
   * Reset everything that belongs to *one* file when a different one is opened.
   *
   * This drawer stays mounted and only its `resourceId` changes, so without
   * this its state carries over -- and for `shareLevel` that is a permission
   * bug, not a cosmetic one: granting "Allow download" on one file left the
   * next file's share preselected to download, so the safe default above
   * applied on first mount and never again. Caught by sharing four files in a
   * row and finding all four stored DOWNLOAD when only one had been set to it.
   *
   * Done during render rather than in an effect so the drawer never paints
   * once carrying the previous file's answers.
   */
  const [openFor, setOpenFor] = useState<string | null>(resourceId);
  if (openFor !== resourceId) {
    setOpenFor(resourceId);
    setShareLevel("VIEW");
    setShareWith(null);
    setChangeNote("");
    setRename(null);
    setGrant({ scope_type: "COURSE", scope_public_id: "", level: "VIEW" });
  }

  const share = useApiMutation<SharedResourceResponse[], string>({
    mutationFn: (userId) =>
      api.post<SharedResourceResponse[]>(`/resources/${segment(resourceId!)}/share`, {
        body: { user_ids: [userId], level: shareLevel },
      }),
    success: "Shared.",
    invalidate: [["resources"]],
    onSuccess: () => setShareWith(null),
  });

  const setRestricted = useApiMutation<ResourceResponse, boolean>({
    mutationFn: (restricted) =>
      api.patch<ResourceResponse>(`/resources/${segment(resourceId!)}`, {
        body: { is_restricted: restricted },
      }),
    success: (r) =>
      r.is_restricted
        ? "Now staff-only. Any public link has been revoked."
        : "No longer staff-only.",
    invalidate: [["resources"]],
  });

  const setShareLink = useApiMutation<ShareLinkResponse, boolean>({
    mutationFn: (enabled) =>
      api.put<ShareLinkResponse>(`/resources/${segment(resourceId!)}/share-link`, {
        query: { enabled },
      }),
    success: (result) =>
      result.share_token ? "Public link enabled." : "Public link revoked.",
    invalidate: [["resources"]],
  });

  const addGrant = useApiMutation<ResourcePermissionResponse, typeof grant>({
    mutationFn: (values) =>
      api.post<ResourcePermissionResponse>("/resource-permissions", {
        query: { resource_id: resourceId! },
        body: values,
      }),
    success: "Access granted.",
    invalidate: [["resource-permissions"]],
    onSuccess: () => setGrant({ ...grant, scope_public_id: "" }),
  });

  const renameResource = useApiMutation<ResourceResponse, string>({
    mutationFn: (name) =>
      api.patch<ResourceResponse>(`/resources/${segment(resourceId!)}`, { body: { name } }),
    success: "Renamed.",
    invalidate: [["resources"]],
    onSuccess: () => setRename(null),
  });

  const removeGrant = useApiMutation<void, number>({
    mutationFn: (permissionId) =>
      api.delete<void>(`/resource-permissions/${segment(permissionId)}`),
    success: "Access removed.",
    invalidate: [["resource-permissions"]],
  });

  const data = resource.data;

  /*
   * What this caller may do with *this* file, answered by the server.
   *
   * `permissions.has("resource.update")` is a different question -- it asks
   * whether the role can edit resources *in general*, which is how a tutor ended
   * up being offered Delete on a file that had merely been shared with them. The
   * level is per-file and is what the API actually enforces, so it is what the
   * buttons follow.
   */
  const rank = { VIEW: 0, DOWNLOAD: 1, EDIT: 2, MANAGE: 3 } as const;
  const level = data?.my_level ? rank[data.my_level as keyof typeof rank] : -1;
  const canDownload = level >= rank.DOWNLOAD;
  const canEdit = level >= rank.EDIT;
  const canManage = level >= rank.MANAGE;

  return (
    <Dialog open={resourceId !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent size="xl">
        {resource.isPending ? (
          <LoadingState rows={5} />
        ) : resource.error ? (
          <ErrorState error={resource.error} onRetry={() => void resource.refetch()} />
        ) : data ? (
          <>
            <DialogHeader
              title={data.name ?? "Resource"}
              description={
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{data.resource_type}</Badge>
                  <span className="text-xs">
                    {formatBytes(data.size)} · v{data.current_version ?? 1} · uploaded by{" "}
                    {data.uploaded_by_username ?? "unknown"} ·{" "}
                    {formatDateTime(data.created_at, { timeZone })}
                  </span>
                  {data.is_deleted ? <Badge tone="danger">In the recycle bin</Badge> : null}
                </span>
              }
            />

            <div className="space-y-4">
              {/*
                The file itself, first. Preview needs only VIEW, so this renders
                for everyone who can open the dialog at all -- including the
                read-only audiences who have no Download button below.
              */}
              <FilePreview
                resourceId={data.public_id}
                name={data.name}
                mimeType={data.mime_type}
                canPreview={data.can_preview ?? false}
              />

              <div className="flex flex-wrap items-center gap-2">
                {/*
                  Gated on the server's own answer rather than on the caller's
                  global role. The server is still the authority -- this only
                  stops the console offering a button that would come back 403,
                  which is how a read-only viewer learns their level by being
                  refused rather than by being told.
                */}
                {canDownload ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      void downloadFile(
                        `/resources/${segment(data.public_id)}/download`,
                        data.name ?? "resource",
                      ).catch((caught) =>
                        toast.error(caught instanceof Error ? caught.message : "Download failed."),
                      )
                    }
                  >
                    <Download /> Download
                  </Button>
                ) : (
                  <Badge tone="neutral" dot>
                    View only — you cannot download this file
                  </Badge>
                )}
                {permissions.has("resource.update") && canManage ? (
                  <label className="flex items-center gap-2 rounded-lg border border-border-subtle px-3 py-1.5 text-sm">
                    <Switch
                      checked={data.has_share_link ?? false}
                      // A staff-only file cannot have one. Disabled rather than
                      // hidden, so the reason is visible where the control is.
                      disabled={setShareLink.isPending || data.is_restricted}
                      onCheckedChange={(checked) => setShareLink.mutate(checked)}
                    />
                    <Link2 className="size-4" aria-hidden /> Public link
                  </label>
                ) : null}
                {permissions.has("resource.view_restricted") && canManage ? (
                  <label className="flex items-center gap-2 rounded-lg border border-border-subtle px-3 py-1.5 text-sm">
                    <Switch
                      checked={data.is_restricted ?? false}
                      disabled={setRestricted.isPending}
                      onCheckedChange={(checked) => setRestricted.mutate(checked)}
                    />
                    <ShieldCheck className="size-4" aria-hidden /> Staff only
                  </label>
                ) : null}
              </div>

              {data.is_restricted ? (
                <p className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
                  Staff only. Students, guardians and corporate managers cannot open it, find
                  it in a list, or be shared it — whatever else they have been granted. It
                  cannot carry a public link.
                </p>
              ) : null}

              {data.has_share_link ? (
                <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                  A public link is active: anyone holding it can download this file without signing
                  in. The token itself is shown only when the link is created; turn the switch off to
                  revoke it.
                </p>
              ) : null}

              {canEdit ? (
                <div className="space-y-1.5">
                  <p className="text-sm font-medium">Name</p>
                  <form
                    method="post"
                    className="flex flex-wrap items-center gap-2"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const next = (rename ?? data.name ?? "").trim();
                      if (next && next !== data.name) renameResource.mutate(next);
                    }}
                  >
                    <Input
                      aria-label="File name"
                      className="min-w-56 flex-1"
                      value={rename ?? data.name ?? ""}
                      onChange={(event) => setRename(event.target.value)}
                    />
                    <Button
                      type="submit"
                      variant="secondary"
                      size="sm"
                      loading={renameResource.isPending}
                      disabled={!((rename ?? "").trim()) || rename === data.name}
                    >
                      Rename
                    </Button>
                  </form>
                </div>
              ) : null}

              {(data.versions ?? []).length > 0 ? (
                <div className="space-y-1.5">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <History className="size-4 text-muted-foreground" aria-hidden /> Versions
                  </p>
                  <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle">
                    {(data.versions ?? []).map((version) => (
                      <li
                        key={version.version_number}
                        className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                      >
                        <span className="flex items-center gap-2">
                          <Badge tone={version.version_number === data.current_version ? "success" : "neutral"}>
                            v{version.version_number}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {formatBytes(version.size)} · {version.uploaded_by_username ?? "unknown"} ·{" "}
                            {formatDateTime(version.created_at, { timeZone })}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          {version.change_note ? (
                            <span className="max-w-64 truncate text-xs text-muted-foreground">
                              {version.change_note}
                            </span>
                          ) : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              void downloadFile(
                                `/resources/${segment(data.public_id)}/download`,
                                `${data.name ?? "resource"}-v${version.version_number}`,
                                { version: version.version_number },
                              ).catch((caught) =>
                                toast.error(
                                  caught instanceof Error ? caught.message : "Download failed.",
                                ),
                              )
                            }
                          >
                            <Download />
                          </Button>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {permissions.has("resource.update") && canEdit ? (
                <div className="space-y-2 rounded-lg border border-border-subtle p-3">
                  <p className="text-sm font-medium">Upload a new version</p>
                  <input
                    ref={versionInput}
                    type="file"
                    aria-label="New version file"
                    className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1 file:text-sm"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) uploadVersion.mutate(file);
                    }}
                  />
                  <Input
                    placeholder="What changed? (optional)"
                    aria-label="Change note"
                    value={changeNote}
                    onChange={(event) => setChangeNote(event.target.value)}
                  />
                </div>
              ) : null}

              {permissions.has("resource.update") && canEdit ? (
                <div className="space-y-2 rounded-lg border border-border-subtle p-3">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Share2 className="size-4 text-muted-foreground" aria-hidden /> Share with a
                    person
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-56 flex-1">
                      <UserPicker value={shareWith} onChange={(next) => setShareWith(next)} />
                      <Select
                        aria-label="What they may do"
                        value={shareLevel}
                        onValueChange={(next) => setShareLevel((next ?? "") as "VIEW" | "DOWNLOAD")
                        }
                        // Auto width, not a fixed one: `w-40` clipped "Watch /
                        // read only" to "Watch / read o...", and a control whose
                        // label is cut off is a control nobody can be sure of.
                        className="h-9 text-sm"
                       options={[{ value: "VIEW", label: "Watch / read only" }, { value: "DOWNLOAD", label: "Allow download" }]} />
                    </div>
                    <Button
                      loading={share.isPending}
                      disabled={!shareWith}
                      onClick={() => shareWith && share.mutate(shareWith)}
                    >
                      Share
                    </Button>
                  </div>
                  <p className="text-2xs leading-relaxed text-subtle-foreground">
                    Adds one person at a time. Who already has access is not listed here yet.
                  </p>
                </div>
              ) : null}

              {permissions.has("resource.update") && canEdit ? (
                <div className="space-y-2 rounded-lg border border-border-subtle p-3">
                  <p className="text-sm font-medium">Scoped access</p>
                  <p className="text-xs text-muted-foreground">
                    Grants cascade Course &rarr; Batch &rarr; Session &rarr; Individual. Everyone in
                    the named scope gets the level chosen.
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <Select
                      className="w-36"
                      aria-label="Scope type"
                      value={grant.scope_type}
                      onValueChange={(next) => setGrant({ ...grant, scope_type: (next ?? "") })}
                     options={optionsFromValues(ResourceScopeTypeValues)} />
                    <Input
                      className="min-w-56 flex-1"
                      aria-label="Scope identifier"
                      placeholder="Course / batch / session / user id"
                      value={grant.scope_public_id}
                      onChange={(event) =>
                        setGrant({ ...grant, scope_public_id: event.target.value.trim() })
                      }
                    />
                    <Select
                      className="w-32"
                      aria-label="Level"
                      value={grant.level}
                      onValueChange={(next) => setGrant({ ...grant, level: (next ?? "") })}
                     options={optionsFromValues(ResourcePermissionLevelValues)} />
                    <Button
                      loading={addGrant.isPending}
                      disabled={!grant.scope_public_id}
                      onClick={() => addGrant.mutate(grant)}
                    >
                      Grant
                    </Button>
                  </div>

                  {(grants.data ?? []).length > 0 ? (
                    <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle">
                      {(grants.data ?? []).map((row) => (
                        <li
                          key={row.id}
                          className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                        >
                          <span>
                            <Badge tone="neutral">{row.scope_type}</Badge>{" "}
                            {row.scope_label ?? row.scope_id} &rarr;{" "}
                            <Badge tone="primary">{row.level}</Badge>
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Remove grant"
                            onClick={() => removeGrant.mutate(row.id)}
                          >
                            <Trash2 className="text-danger" />
                          </Button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Browser                                                                     */
/* -------------------------------------------------------------------------- */

function ResourcesContent() {
  const params = useSearchParams();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(25);
  const [folderId, setFolderId] = useState<string | null>(null);
  const [trail, setTrail] = useState<{ id: string | null; name: string }[]>([
    { id: null, name: "Library" },
  ]);
  const [resourceType, setResourceType] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [droppedFiles, setDroppedFiles] = useState<File[] | undefined>(undefined);
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [renaming, setRenaming] = useState<FolderSummary | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deletingFolder, setDeletingFolder] = useState<FolderSummary | null>(null);
  // Remembered per browser, the way every file manager does: a person who
  // prefers the list does not want to re-choose it on every visit.
  const [layout, setLayout] = useDriveLayout("grid");
  const [selected, setSelected] = useState<string | null>(params.get("resource"));
  const [deleting, setDeleting] = useState<ResourceSummary | null>(null);
  const [purging, setPurging] = useState<ResourceSummary | null>(null);

  const folders = useQuery({
    queryKey: ["folders", folderId],
    queryFn: () =>
      api.get<FolderSummary[]>("/folders", { query: { parent_id: folderId ?? undefined } }),
  });

  const resources = useQuery({
    queryKey: ["resources", "list", folderId, resourceType, debouncedSearch, includeDeleted, limit, offset],
    queryFn: () =>
      api.get<PageResourceSummary>("/resources", {
        query: {
          folder_id: folderId ?? undefined,
          // At the root, ask for the files that are *in* the root. Without it
          // the API returns every file in every folder, so moving a file into
          // a folder left a copy of it sitting here -- and the root read as a
          // flat dump of the whole library rather than the top of a tree.
          // Dropped while searching: a search spans the library.
          root_only: folderId === null && !debouncedSearch ? true : undefined,
          resource_type: resourceType || undefined,
          query: debouncedSearch || undefined,
          include_deleted: includeDeleted || undefined,
          limit,
          offset,
        },
      }),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/resources/${segment(id)}`),
    success: "Moved to the recycle bin.",
    invalidate: [["resources"]],
    onSuccess: () => setDeleting(null),
  });

  const purge = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/resources/${segment(id)}/purge`),
    success: "Deleted permanently.",
    invalidate: [["resources"]],
    onSuccess: () => setPurging(null),
  });

  const restore = useApiMutation<ResourceResponse, string>({
    mutationFn: (id) => api.post<ResourceResponse>(`/resources/${segment(id)}/restore`),
    success: "Restored.",
    invalidate: [["resources"]],
  });

  const move = useApiMutation<ResourceResponse, { id: string; folder: string | null }>({
    mutationFn: ({ id, folder }) =>
      api.patch<ResourceResponse>(`/resources/${segment(id)}`, { body: { folder_id: folder } }),
    success: "Moved.",
    invalidate: [["resources"], ["folders"]],
  });

  const copy = useApiMutation<ResourceResponse, string>({
    mutationFn: (id) =>
      api.post<ResourceResponse>(`/resources/${segment(id)}/copy`, {
        body: { target_folder_id: folderId },
      }),
    success: "Copied.",
    invalidate: [["resources"]],
  });

  const canWrite = permissions.has("resource.create");

  // Seed the rename field from the folder being renamed. Done during render
  // rather than in an effect so the input never shows the previous folder's
  // name for a frame first.
  const [renameSeed, setRenameSeed] = useState<FolderSummary | null>(null);
  if (renameSeed !== renaming) {
    setRenameSeed(renaming);
    setRenameValue(renaming?.name ?? "");
  }

  /**
   * Files dropped onto the surface.
   *
   * Uploaded one request each because the API takes one file per call, and
   * sequentially rather than in parallel so a dropped folder of forty files
   * cannot open forty connections at once. The type is guessed as "Document" --
   * the drop gesture has nowhere to ask, and the drawer can correct it.
   */
  const dropUpload = useApiMutation<number, File[]>({
    mutationFn: async (files) => {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        form.append("resource_type", "Document");
        form.append("name", file.name);
        if (folderId) form.append("folder_id", folderId);
        await api.post<ResourceResponse>("/resources", { body: form });
      }
      return files.length;
    },
    success: (count) => `Uploaded ${count} file(s).`,
    invalidate: [["resources"], ["folders"]],
  });

  const renameFolder = useApiMutation<FolderResponse, { id: string; name: string }>({
    mutationFn: ({ id, name }) =>
      api.patch<FolderResponse>(`/folders/${segment(id)}`, { body: { name } }),
    success: "Folder renamed.",
    invalidate: [["folders"]],
    onSuccess: () => setRenaming(null),
  });

  const deleteFolder = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/folders/${segment(id)}`),
    success: "Folder deleted.",
    invalidate: [["folders"], ["resources"]],
    onSuccess: () => setDeletingFolder(null),
  });

  function openFolder(folder: FolderSummary) {
    setFolderId(folder.public_id);
    setTrail((previous) => [...previous, { id: folder.public_id, name: folder.name }]);
    setPage({ limit, offset: 0 });
  }

  function goTo(index: number) {
    const entry = trail[index];
    if (!entry) return;
    setFolderId(entry.id);
    setTrail(trail.slice(0, index + 1));
    setPage({ limit, offset: 0 });
  }

  const driveActions: DriveActions = {
    onOpenFolder: openFolder,
    onOpenResource: (resource) => setSelected(resource.public_id),
    // Dragging a file onto a folder is the move. The old flow -- click Move,
    // navigate to the destination, confirm on a banner -- was three steps and a
    // mode, and it is gone.
    onMoveResource: (id, folder) => move.mutate({ id, folder }),
    onUploadFiles: (files) => {
      if (folderId) {
        dropUpload.mutate(files);
        return;
      }
      // At the root a file has no folder to inherit a course or batch from,
      // and the API refuses one anchored to neither. Firing the request
      // anyway would answer a drop with "the request could not be
      // completed"; staging it in the dialog asks the one question that is
      // actually missing.
      setDroppedFiles(files);
      setUploadOpen(true);
    },
    onDownload: (resource) =>
      void downloadFile(`/resources/${segment(resource.public_id)}/download`, resource.name ?? "file"),
    onCopy: (resource) => copy.mutate(resource.public_id),
    onShare: (resource) => setSelected(resource.public_id),
    onDelete: (resource) => setDeleting(resource),
    onRestore: (resource) => restore.mutate(resource.public_id),
    onRenameFolder: (folder) => setRenaming(folder),
    onDeleteFolder: (folder) => setDeletingFolder(folder),
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Resources"
        description="Files and folders, shared by course, batch, session or person."
      />

      <DriveToolbar layout={layout} onLayoutChange={setLayout}>
        <nav aria-label="Folder path" className="min-w-0">
          <ol className="flex flex-wrap items-center gap-1 text-base">
            {trail.map((entry, index) => (
              <li key={`${entry.id ?? "root"}-${index}`} className="flex items-center gap-1">
                {index > 0 ? (
                  <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
                ) : null}
                <button
                  type="button"
                  className={
                    index === trail.length - 1
                      ? "font-semibold text-foreground"
                      : "text-muted-foreground hover:underline"
                  }
                  onClick={() => goTo(index)}
                >
                  {entry.name}
                </button>
              </li>
            ))}
          </ol>
        </nav>

        {canWrite ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button size="sm">
                  <Plus /> New
                </Button>
              }
            />
            <DropdownMenuContent align="start">
              <DropdownMenuItem onClick={() => setNewFolderOpen(true)}>
                <FolderPlus /> New folder
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setUploadOpen(true)}>
                <Upload /> File upload
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </DriveToolbar>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Search" className="min-w-56 flex-1">
          {({ id }) => (
            <Input
              id={id}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search this library"
            />
          )}
        </Field>
        <Field label="Type" className="w-52">
          {({ id }) => (
            <Select
              id={id}
              value={(resourceType) || null}
              onValueChange={(next) => {
                setResourceType((next ?? ""));
                setPage({ limit, offset: 0 });
              }}
             placeholder="Any type" clearable options={optionsFromValues(ResourceTypeValues)} />
          )}
        </Field>
        <label className="flex items-center gap-2 pb-2 text-sm text-muted-foreground">
          <Switch
            checked={includeDeleted}
            onCheckedChange={(next) => {
              setIncludeDeleted(next);
              setPage({ limit, offset: 0 });
            }}
          />
          Recycle bin
        </label>
      </div>

      {resources.isPending ? (
        <LoadingState />
      ) : resources.error ? (
        <ErrorState error={resources.error} onRetry={() => void resources.refetch()} />
      ) : (
        <>
          <DriveView
            layout={layout}
            // The recycle bin has no folders of its own -- it lists deleted
            // files wherever they were, so showing the live folder tree beside
            // them would invite dragging a file into a folder it is not in.
            folders={includeDeleted ? [] : (folders.data ?? [])}
            resources={resources.data?.items ?? []}
            canWrite={canWrite}
            inBin={includeDeleted}
            emptyMessage={
              includeDeleted
                ? "The recycle bin is empty."
                : debouncedSearch || resourceType
                  ? "Nothing here matches those filters."
                  : "This folder is empty."
            }
            actions={driveActions}
            formatDate={(iso) => formatDateTime(iso, { timeZone })}
          />
          <Pagination
            total={resources.data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="files"
          />
        </>
      )}

      <UploadDialog
        open={uploadOpen}
        onOpenChange={(open) => {
          setUploadOpen(open);
          if (!open) setDroppedFiles(undefined);
        }}
        folderId={folderId}
        folderName={trail[trail.length - 1]?.name ?? "Library"}
        initialFiles={droppedFiles}
      />

      <NewFolderDialog
        open={newFolderOpen}
        onOpenChange={setNewFolderOpen}
        parentId={folderId}
        parentName={trail[trail.length - 1]?.name ?? "Library"}
      />

      <Dialog
        open={renaming !== null}
        onOpenChange={(open) => (open ? null : setRenaming(null))}
      >
        <DialogContent size="sm">
          <DialogHeader title="Rename folder" />
          <Field label="Name" required>
            {({ id }) => (
              <Input
                id={id}
                autoFocus
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && renaming && renameValue.trim()) {
                    renameFolder.mutate({ id: renaming.public_id, name: renameValue.trim() });
                  }
                }}
              />
            )}
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
            <Button
              loading={renameFolder.isPending}
              disabled={renameValue.trim() === ""}
              onClick={() => {
                if (renaming) {
                  renameFolder.mutate({ id: renaming.public_id, name: renameValue.trim() });
                }
              }}
            >
              Rename
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deletingFolder !== null}
        onOpenChange={(open) => (open ? null : setDeletingFolder(null))}
        destructive
        title={`Delete "${deletingFolder?.name ?? "this folder"}"?`}
        description="The server refuses this while the folder still holds anything, so nothing inside can be lost by accident."
        confirmLabel="Delete folder"
        pending={deleteFolder.isPending}
        onConfirm={() => {
          if (deletingFolder) deleteFolder.mutate(deletingFolder.public_id);
        }}
      />

      <ResourceDrawer resourceId={selected} onClose={() => setSelected(null)} />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (open ? null : setDeleting(null))}
        destructive
        title="Move to the recycle bin?"
        description="It stays recoverable until someone purges it."
        confirmLabel="Move to bin"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.public_id);
        }}
      />

      <ConfirmDialog
        open={purging !== null}
        onOpenChange={(open) => (open ? null : setPurging(null))}
        destructive
        title="Delete permanently?"
        description="The file and every version of it are destroyed. This cannot be undone."
        confirmPhrase={purging?.name ?? undefined}
        confirmLabel="Delete permanently"
        pending={purge.isPending}
        onConfirm={() => {
          if (purging) purge.mutate(purging.public_id);
        }}
      />
    </div>
  );
}

export default function ResourcesPage() {
  return (
    <Suspense fallback={<LoadingState rows={5} />}>
      <ResourcesContent />
    </Suspense>
  );
}
