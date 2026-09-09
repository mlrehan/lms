"use client";

import { Suspense, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ChevronRight,
  Copy,
  Download,
  Folder,
  FolderPlus,
  History,
  Link2,
  RotateCcw,
  Share2,
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
import { Badge, Card, CardBody, CardHeader, Switch } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect } from "@/components/ui/form";
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

function UploadDialog({
  open,
  onOpenChange,
  folderId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folderId: string | null;
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [resourceType, setResourceType] = useState<string>("Document");

  const upload = useApiMutation<ResourceResponse, void>({
    mutationFn: () => {
      const form = new FormData();
      // The file is appended as-is. The BFF proxy forwards the request body as
      // bytes, never as decoded text -- decoding multipart as UTF-8 leaves the
      // boundaries intact and silently destroys the file's contents.
      form.append("file", file!);
      form.append("resource_type", resourceType);
      if (name) form.append("name", name);
      if (folderId) form.append("folder_id", folderId);
      return api.post<ResourceResponse>("/resources", { body: form });
    },
    success: "Uploaded.",
    invalidate: [["resources"]],
    onSuccess: () => {
      setFile(null);
      setName("");
      if (inputRef.current) inputRef.current.value = "";
      void queryClient.invalidateQueries({ queryKey: ["folders"] });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader
          title="Upload a resource"
          description={folderId ? "Into the current folder." : "Into the root of your library."}
        />
        <div className="space-y-4">
          <Field label="File" required>
            {({ id }) => (
              <input
                id={id}
                ref={inputRef}
                type="file"
                className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1 file:text-sm"
                onChange={(event) => {
                  const chosen = event.target.files?.[0] ?? null;
                  setFile(chosen);
                  if (chosen && !name) setName(chosen.name);
                }}
              />
            )}
          </Field>
          <FormGrid>
            <Field label="Display name">
              {({ id }) => (
                <Input id={id} value={name} onChange={(event) => setName(event.target.value)} />
              )}
            </Field>
            <Field label="Type">
              {({ id }) => (
                <NativeSelect
                  id={id}
                  value={resourceType}
                  onChange={(event) => setResourceType(event.target.value)}
                >
                  {ResourceTypeValues.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
          {file ? (
            <p className="text-xs text-muted-foreground">
              {file.name} · {formatBytes(file.size)}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={upload.isPending} disabled={!file} onClick={() => upload.mutate()}>
            <Upload /> Upload
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

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
  const [shareWith, setShareWith] = useState<string | null>(null);
  const [grant, setGrant] = useState({ scope_type: "COURSE", scope_public_id: "", level: "VIEW" });

  const resource = useQuery({
    queryKey: ["resources", "detail", resourceId],
    queryFn: () => api.get<ResourceResponse>(`/resources/${segment(resourceId!)}`),
    enabled: resourceId !== null,
  });

  const shares = useQuery({
    queryKey: ["resources", resourceId, "shares"],
    queryFn: () =>
      api.post<SharedResourceResponse[]>(`/resources/${segment(resourceId!)}/share`, {
        body: { user_ids: [] },
      }),
    // Deliberately not fetched: the API has no GET for a resource's share
    // list, and POSTing an empty share to read it would be a write pretending
    // to be a read. See docs/BACKEND-GAPS.md.
    enabled: false,
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

  const share = useApiMutation<SharedResourceResponse[], string>({
    mutationFn: (userId) =>
      api.post<SharedResourceResponse[]>(`/resources/${segment(resourceId!)}/share`, {
        body: { user_ids: [userId] },
      }),
    success: "Shared.",
    invalidate: [["resources"]],
    onSuccess: () => setShareWith(null),
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

  const removeGrant = useApiMutation<void, number>({
    mutationFn: (permissionId) =>
      api.delete<void>(`/resource-permissions/${segment(permissionId)}`),
    success: "Access removed.",
    invalidate: [["resource-permissions"]],
  });

  const data = resource.data;

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
              <div className="flex flex-wrap gap-2">
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
                {permissions.has("resource.update") ? (
                  <label className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm">
                    <Switch
                      checked={data.has_share_link ?? false}
                      disabled={setShareLink.isPending}
                      onCheckedChange={(checked) => setShareLink.mutate(checked)}
                    />
                    <Link2 className="size-4" aria-hidden /> Public link
                  </label>
                ) : null}
              </div>

              {data.has_share_link ? (
                <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning-foreground dark:text-warning">
                  A public link is active: anyone holding it can download this file without signing
                  in. The token itself is shown only when the link is created; turn the switch off to
                  revoke it.
                </p>
              ) : null}

              {(data.versions ?? []).length > 0 ? (
                <div className="space-y-1.5">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <History className="size-4 text-muted-foreground" aria-hidden /> Versions
                  </p>
                  <ul className="divide-y divide-border rounded-lg border border-border">
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

              {permissions.has("resource.update") ? (
                <div className="space-y-2 rounded-lg border border-border p-3">
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

              {permissions.has("resource.update") ? (
                <div className="space-y-2 rounded-lg border border-border p-3">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Share2 className="size-4 text-muted-foreground" aria-hidden /> Share with a
                    person
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="min-w-56 flex-1">
                      <UserPicker value={shareWith} onChange={(next) => setShareWith(next)} />
                    </div>
                    <Button
                      loading={share.isPending}
                      disabled={!shareWith}
                      onClick={() => shareWith && share.mutate(shareWith)}
                    >
                      Share
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    The API has no endpoint that lists who a resource is already shared with, so this
                    panel can add a share but not show existing ones.
                  </p>
                </div>
              ) : null}

              {permissions.has("resource.update") ? (
                <div className="space-y-2 rounded-lg border border-border p-3">
                  <p className="text-sm font-medium">Scoped access</p>
                  <p className="text-xs text-muted-foreground">
                    Grants cascade Course &rarr; Batch &rarr; Session &rarr; Individual. Everyone in
                    the named scope gets the level chosen.
                  </p>
                  <div className="flex flex-wrap items-end gap-2">
                    <NativeSelect
                      className="w-36"
                      aria-label="Scope type"
                      value={grant.scope_type}
                      onChange={(event) => setGrant({ ...grant, scope_type: event.target.value })}
                    >
                      {ResourceScopeTypeValues.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </NativeSelect>
                    <Input
                      className="min-w-56 flex-1"
                      aria-label="Scope identifier"
                      placeholder="Course / batch / session / user id"
                      value={grant.scope_public_id}
                      onChange={(event) =>
                        setGrant({ ...grant, scope_public_id: event.target.value.trim() })
                      }
                    />
                    <NativeSelect
                      className="w-32"
                      aria-label="Level"
                      value={grant.level}
                      onChange={(event) => setGrant({ ...grant, level: event.target.value })}
                    >
                      {ResourcePermissionLevelValues.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </NativeSelect>
                    <Button
                      loading={addGrant.isPending}
                      disabled={!grant.scope_public_id}
                      onClick={() => addGrant.mutate(grant)}
                    >
                      Grant
                    </Button>
                  </div>

                  {(grants.data ?? []).length > 0 ? (
                    <ul className="divide-y divide-border rounded-lg border border-border">
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
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
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
          resource_type: resourceType || undefined,
          query: debouncedSearch || undefined,
          include_deleted: includeDeleted || undefined,
          limit,
          offset,
        },
      }),
  });

  const createFolder = useApiMutation<FolderResponse, string>({
    mutationFn: (name) =>
      api.post<FolderResponse>("/folders", { body: { name, parent_id: folderId } }),
    success: "Folder created.",
    invalidate: [["folders"]],
    onSuccess: () => {
      setNewFolderName("");
      setNewFolderOpen(false);
    },
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

  const copy = useApiMutation<ResourceResponse, string>({
    mutationFn: (id) =>
      api.post<ResourceResponse>(`/resources/${segment(id)}/copy`, {
        body: { target_folder_id: folderId },
      }),
    success: "Copied.",
    invalidate: [["resources"]],
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

  const columns: Column<ResourceSummary>[] = [
    {
      key: "name",
      header: "Name",
      cell: (row) => (
        <button
          type="button"
          className="text-left font-medium hover:underline"
          onClick={() => setSelected(row.public_id)}
        >
          {row.name ?? "Untitled"}
        </button>
      ),
    },
    {
      key: "type",
      header: "Type",
      cell: (row) => <Badge tone="neutral">{row.resource_type}</Badge>,
    },
    {
      key: "size",
      header: "Size",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{formatBytes(row.size)}</span>,
    },
    {
      key: "created",
      header: "Added",
      secondary: true,
      cell: (row) => formatDateTime(row.created_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <div className="flex items-center justify-end gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Download ${row.name ?? "resource"}`}
            onClick={() =>
              void downloadFile(
                `/resources/${segment(row.public_id)}/download`,
                row.name ?? "resource",
              ).catch((caught) =>
                toast.error(caught instanceof Error ? caught.message : "Download failed."),
              )
            }
          >
            <Download />
          </Button>
          {permissions.has("resource.create") ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Copy ${row.name ?? "resource"}`}
              onClick={() => copy.mutate(row.public_id)}
            >
              <Copy />
            </Button>
          ) : null}
          {permissions.has("resource.delete") ? (
            includeDeleted ? (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Restore ${row.name ?? "resource"}`}
                  onClick={() => restore.mutate(row.public_id)}
                >
                  <RotateCcw />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Purge ${row.name ?? "resource"}`}
                  onClick={() => setPurging(row)}
                >
                  <Trash2 className="text-danger" />
                </Button>
              </>
            ) : (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${row.name ?? "resource"}`}
                onClick={() => setDeleting(row)}
              >
                <Trash2 className="text-danger" />
              </Button>
            )
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Resources"
        description="Files, organised in folders, with versions and scoped access."
        actions={
          <div className="flex items-center gap-2">
            {permissions.has("resource.create") ? (
              <>
                <Button variant="secondary" onClick={() => setNewFolderOpen(true)}>
                  <FolderPlus /> New folder
                </Button>
                <Button onClick={() => setUploadOpen(true)}>
                  <Upload /> Upload
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      <nav aria-label="Folder path">
        <ol className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
          {trail.map((entry, index) => (
            <li key={`${entry.id ?? "root"}-${index}`} className="flex items-center gap-1">
              {index > 0 ? <ChevronRight className="size-3.5" aria-hidden /> : null}
              <button
                type="button"
                className={index === trail.length - 1 ? "font-medium text-foreground" : "hover:underline"}
                onClick={() => goTo(index)}
              >
                {entry.name}
              </button>
            </li>
          ))}
        </ol>
      </nav>

      {folders.isPending ? null : (folders.data ?? []).length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {(folders.data ?? []).map((folder) => (
            <button
              key={folder.public_id}
              type="button"
              onClick={() => openFolder(folder)}
              className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2.5 text-left text-sm transition-colors hover:border-border-strong"
            >
              <Folder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate font-medium">{folder.name}</span>
            </button>
          ))}
        </div>
      ) : null}

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border p-3">
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
              <NativeSelect
                id={id}
                value={resourceType}
                onChange={(event) => {
                  setResourceType(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any type</option>
                {ResourceTypeValues.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </NativeSelect>
            )}
          </Field>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <Switch
              checked={includeDeleted}
              onCheckedChange={(checked) => {
                setIncludeDeleted(checked);
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
            <DataTable
              columns={columns}
              rows={resources.data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage={includeDeleted ? "The recycle bin is empty." : "No files here."}
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
      </Card>

      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} folderId={folderId} />

      <Dialog open={newFolderOpen} onOpenChange={setNewFolderOpen}>
        <DialogContent size="sm">
          <DialogHeader
            title="New folder"
            description={`Inside ${trail[trail.length - 1]?.name ?? "the library"}.`}
          />
          <Field label="Name" required>
            {({ id }) => (
              <Input
                id={id}
                autoFocus
                value={newFolderName}
                onChange={(event) => setNewFolderName(event.target.value)}
              />
            )}
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setNewFolderOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={createFolder.isPending}
              disabled={newFolderName.trim() === ""}
              onClick={() => createFolder.mutate(newFolderName.trim())}
            >
              Create folder
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
