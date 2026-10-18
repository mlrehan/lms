"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  ChevronRight,
  Plus,
  Download,
  FolderPlus,
  History,
  Link2,
  Share2,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import { api, downloadFile, segment } from "@/lib/api/client";
import type {
  BulkDeleteResponse,
  BulkPurgeResponse,
  BulkRestoreResponse,
  DeletionImpactResponse,
  FolderResponse,
  FolderSummary,
  PageResourceSummary,
  PurgeAllResourcesResponse,
  ResourcePermissionResponse,
  ResourceResponse,
  ResourceSummary,
  ShareLinkResponse,
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
import { ShareDialog } from "@/components/domain/resources/share-dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { UserPicker } from "@/components/domain/user-picker";
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
/* Resource detail & Sharing Visibility                                       */
/* -------------------------------------------------------------------------- */

function ResourceDrawer({
  resourceId,
  onClose,
  onPurge,
}: {
  resourceId: string | null;
  onClose: () => void;
  onPurge?: (resource: ResourceSummary) => void;
}) {
  const { permissions, roles } = useSession();
  const isSuperAdmin = roles.some((r) => r.toUpperCase() === "SUPER_ADMIN");
  const timeZone = useDisplayTimeZone();
  const versionInput = useRef<HTMLInputElement>(null);
  const [changeNote, setChangeNote] = useState("");
  const [rename, setRename] = useState<string | null>(null);
  const [sharing, setSharing] = useState<string[] | null>(null);
  const [grant, setGrant] = useState({ scope_type: "COURSE", scope_public_id: "", level: "VIEW" });

  const resource = useQuery({
    queryKey: ["resources", "detail", resourceId],
    queryFn: () => api.get<ResourceResponse>(`/resources/${segment(resourceId!)}`),
    enabled: resourceId !== null,
  });

  const impact = useQuery({
    queryKey: ["resources", "impact", resourceId],
    queryFn: () =>
      api.post<DeletionImpactResponse>("/resources/deletion-impact", {
        body: { resource_ids: [resourceId!] },
      }),
    enabled: resourceId !== null && (permissions.has("resource.read") || isSuperAdmin),
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

  const [openFor, setOpenFor] = useState<string | null>(resourceId);
  if (openFor !== resourceId) {
    setOpenFor(resourceId);
    setSharing(null);
    setChangeNote("");
    setRename(null);
    setGrant({ scope_type: "COURSE", scope_public_id: "", level: "VIEW" });
  }

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
    invalidate: [["resource-permissions"], ["resources", "impact", resourceId]],
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
    invalidate: [["resource-permissions"], ["resources", "impact", resourceId]],
  });

  const data = resource.data;

  const rank = { VIEW: 0, DOWNLOAD: 1, EDIT: 2, MANAGE: 3 } as const;
  const level = data?.my_level ? rank[data.my_level as keyof typeof rank] : -1;
  const canDownload = level >= rank.DOWNLOAD;
  const canEdit = level >= rank.EDIT;
  const canManage = level >= rank.MANAGE;

  const directShares = impact.data?.resources[0]?.direct_shares ?? [];

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
                    <strong>{data.uploaded_by_username ?? "unknown"}</strong> ·{" "}
                    {formatDateTime(data.created_at, { timeZone })}
                  </span>
                  {data.is_deleted ? <Badge tone="danger">In the recycle bin</Badge> : null}
                </span>
              }
            />

            <div className="space-y-4">
              <FilePreview
                resourceId={data.public_id}
                name={data.name}
                mimeType={data.mime_type}
                canPreview={data.can_preview ?? false}
              />

              <div className="flex flex-wrap items-center justify-between gap-3 border-y border-border-subtle py-3">
                <div className="flex flex-wrap items-center gap-2">
                  {canDownload ? (
                    <Button
                      variant="secondary"
                      onClick={() =>
                        void downloadFile(
                          `/resources/${segment(data.public_id)}/download`,
                          data.name ?? "file"
                        )
                      }
                    >
                      <Download className="size-4" /> Download
                    </Button>
                  ) : null}

                  {permissions.has("resource.update") && canEdit ? (
                    <Button variant="secondary" onClick={() => setSharing([data.public_id])}>
                      <Share2 className="size-4" /> Share
                    </Button>
                  ) : null}

                  {permissions.has("resource.delete") && canManage && onPurge && (
                    <Button
                      variant="danger"
                      onClick={() => {
                        onClose();
                        onPurge(data);
                      }}
                    >
                      <Trash2 className="size-4" /> {isSuperAdmin ? "Delete permanently" : "Purge"}
                    </Button>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                  {permissions.has("resource.update") && canEdit ? (
                    <label className="flex items-center gap-2 cursor-pointer">
                      <Switch
                        checked={data.has_share_link}
                        disabled={setShareLink.isPending || data.is_restricted}
                        onCheckedChange={(checked) => setShareLink.mutate(checked)}
                      />
                      <span>Public link</span>
                    </label>
                  ) : null}

                  {permissions.has("resource.view_restricted") && canEdit ? (
                    <label className="flex items-center gap-2 cursor-pointer">
                      <Switch
                        checked={data.is_restricted}
                        disabled={setRestricted.isPending}
                        onCheckedChange={(checked) => setRestricted.mutate(checked)}
                      />
                      <span>Staff-only</span>
                    </label>
                  ) : null}
                </div>
              </div>

              {/* Usage and Sharing Visibility */}
              <div className="space-y-2 rounded-lg border border-border-subtle p-3">
                <div className="flex items-center justify-between">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <Users className="size-4 text-muted-foreground" aria-hidden /> Access &amp; Sharing Visibility
                  </p>
                  <Badge tone={directShares.length > 0 ? "primary" : "neutral"}>
                    {directShares.length} direct recipient(s)
                  </Badge>
                </div>
                {directShares.length > 0 ? (
                  <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle text-xs">
                    {directShares.map((s) => (
                      <li key={s.user_id} className="flex flex-wrap items-center justify-between gap-2 p-2">
                        <span className="truncate">
                          <span className="font-semibold text-foreground">{s.name}</span>
                          {s.role ? <span className="ml-1 text-muted-foreground">({s.role})</span> : null}
                          {s.email_or_username ? (
                            <span className="ml-1 text-muted-foreground">· {s.email_or_username}</span>
                          ) : null}
                        </span>
                        <span className="flex items-center gap-2">
                          <Badge tone="primary">{s.level}</Badge>
                          {s.shared_by_name ? (
                            <span className="text-2xs text-muted-foreground">Shared by {s.shared_by_name}</span>
                          ) : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No direct individual shares. Access is derived from course/batch membership or public link.
                  </p>
                )}
              </div>

              {permissions.has("resource.update") && canEdit ? (
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
                                { version: version.version_number }
                              ).catch((caught) =>
                                toast.error(
                                  caught instanceof Error ? caught.message : "Download failed."
                                )
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
                      onValueChange={(next) => setGrant({ ...grant, scope_type: next ?? "" })}
                      options={optionsFromValues(ResourceScopeTypeValues)}
                    />
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
                      onValueChange={(next) => setGrant({ ...grant, level: next ?? "" })}
                      options={optionsFromValues(ResourcePermissionLevelValues)}
                    />
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
      <ShareDialog
        open={sharing !== null}
        onOpenChange={(next) => !next && setSharing(null)}
        resourceIds={sharing ?? []}
        resourceNames={[resource.data?.name ?? "Untitled"]}
      />
    </Dialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Deletion Impact Warning Dialog                                             */
/* -------------------------------------------------------------------------- */

function DeletionImpactDialog({
  resourceIds,
  open,
  onClose,
  onConfirm,
  isPending,
  isSuperAdmin,
}: {
  resourceIds: string[];
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isPending: boolean;
  isSuperAdmin: boolean;
}) {
  const [confirmedAcknowledged, setConfirmedAcknowledged] = useState(false);

  const impact = useQuery({
    queryKey: ["resources", "deletion-impact", resourceIds],
    queryFn: () =>
      api.post<DeletionImpactResponse>("/resources/deletion-impact", {
        body: { resource_ids: resourceIds },
      }),
    enabled: open && resourceIds.length > 0,
  });

  useEffect(() => {
    if (open) setConfirmedAcknowledged(false);
  }, [open]);

  const data = impact.data;
  const hasActiveShares = (data?.total_direct_shares ?? 0) > 0 || (data?.total_grants ?? 0) > 0;

  return (
    <Dialog open={open} onOpenChange={(next) => (!next && !isPending ? onClose() : null)}>
      <DialogContent size="lg">
        <DialogHeader
          title={
            <span className="flex items-center gap-2 text-danger">
              <ShieldAlert className="size-5 shrink-0" /> Permanent Deletion Impact Warning
            </span>
          }
          description="Irreversible action: The selected resource(s), all their stored versions, and associated permissions will be permanently destroyed."
        />

        {impact.isPending ? (
          <LoadingState />
        ) : impact.error ? (
          <ErrorState error={impact.error} onRetry={() => void impact.refetch()} />
        ) : data ? (
          <div className="space-y-4">
            {hasActiveShares ? (
              <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
                <div className="flex items-center gap-2 font-semibold">
                  <AlertTriangle className="size-4 shrink-0" />
                  Active Access &amp; Usage Detected:
                </div>
                <p className="mt-1">
                  This permanent deletion will immediately revoke access for{" "}
                  <strong>{data.total_affected_users} user(s)</strong> with direct shares and delete{" "}
                  <strong>{data.total_grants} scope grant(s)</strong>.
                </p>
                {isSuperAdmin ? (
                  <p className="mt-1.5 font-medium">
                    As SuperAdmin, you have full administrative authority to permanently purge these files regardless of active shares or dependencies.
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                No active external user shares found for the selected {data.total_resources} resource(s).
              </p>
            )}

            <div className="max-h-64 space-y-3 overflow-y-auto rounded-lg border border-border-subtle p-3">
              {data.resources.map((item) => (
                <div
                  key={item.resource_id}
                  className="space-y-1.5 border-b border-border-subtle pb-2.5 last:border-0 last:pb-0 text-xs"
                >
                  <div className="flex items-center justify-between font-medium">
                    <span className="truncate font-semibold text-foreground">{item.name}</span>
                    <span className="text-muted-foreground">
                      {item.course_title ?? item.batch_code ?? "Library Root"}
                    </span>
                  </div>
                  {item.uploaded_by_username ? (
                    <p className="text-2xs text-muted-foreground">Uploaded by: {item.uploaded_by_username}</p>
                  ) : null}

                  {item.direct_shares.length > 0 ? (
                    <div className="mt-1 space-y-1">
                      <p className="text-2xs font-semibold text-foreground">Directly shared with:</p>
                      <ul className="divide-y divide-border-subtle/60 rounded border border-border-subtle/60 bg-muted/20">
                        {item.direct_shares.map((share) => (
                          <li
                            key={share.user_id}
                            className="flex items-center justify-between px-2 py-1 text-2xs"
                          >
                            <span className="truncate">
                              <strong>{share.name}</strong>{" "}
                              {share.role ? <span className="text-muted-foreground">({share.role})</span> : ""} ·{" "}
                              {share.email_or_username ?? ""}
                            </span>
                            <Badge tone="primary" className="text-[10px]">
                              {share.level}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {item.grants.length > 0 ? (
                    <div className="mt-1 space-y-1">
                      <p className="text-2xs font-semibold text-foreground">Scope Grants:</p>
                      <ul className="rounded border border-border-subtle/60 bg-muted/20 px-2 py-1 text-2xs">
                        {item.grants.map((grant, idx) => (
                          <li key={idx} className="flex justify-between py-0.5">
                            <span>{grant.scope_label ?? grant.scope_type}</span>
                            <Badge tone="neutral" className="text-[10px]">
                              {grant.level}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>

            <label className="flex items-start gap-2 text-xs font-medium text-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={confirmedAcknowledged}
                onChange={(e) => setConfirmedAcknowledged(e.target.checked)}
                className="mt-0.5 rounded border-border-strong text-danger"
              />
              <span>
                I understand that permanently deleting these {data.total_resources} file(s) will destroy all stored versions and revoke all user shares immediately.
              </span>
            </label>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" disabled={isPending} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            loading={isPending}
            disabled={!confirmedAcknowledged}
            onClick={onConfirm}
          >
            Permanently Delete ({resourceIds.length})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Main Resources Console                                                     */
/* -------------------------------------------------------------------------- */

function ResourcesContent() {
  const params = useSearchParams();
  const { permissions, roles } = useSession();
  const isSuperAdmin = roles.some((r) => r.toUpperCase() === "SUPER_ADMIN");
  const timeZone = useDisplayTimeZone();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(25);

  const [folderId, setFolderId] = useState<string | null>(null);
  const [trail, setTrail] = useState<{ id: string | null; name: string }[]>([
    { id: null, name: "Library" },
  ]);
  const [resourceType, setResourceType] = useState("");
  const [fileStatus, setFileStatus] = useState<"active" | "deleted" | "all">("active");
  const [ownership, setOwnership] = useState<"all" | "mine">("all");
  const [uploaderId, setUploaderId] = useState<string | null>(null);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [droppedFiles, setDroppedFiles] = useState<File[] | undefined>(undefined);
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [renaming, setRenaming] = useState<FolderSummary | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deletingFolder, setDeletingFolder] = useState<FolderSummary | null>(null);

  const [layout, setLayout] = useDriveLayout("grid");
  const [selected, setSelected] = useState<string | null>(params.get("resource"));

  const [sharingMany, setSharingMany] = useState<string[]>([]);
  const [deleting, setDeleting] = useState<ResourceSummary | null>(null);
  const [deletingMany, setDeletingMany] = useState<string[]>([]);
  const [purgingTarget, setPurgingTarget] = useState<string[] | null>(null);

  const [confirmingEmptyBin, setConfirmingEmptyBin] = useState(false);
  const [confirmingPurgeAll, setConfirmingPurgeAll] = useState(false);

  const folders = useQuery({
    queryKey: ["folders", folderId],
    queryFn: () =>
      api.get<FolderSummary[]>("/folders", { query: { parent_id: folderId ?? undefined } }),
  });

  const inBin = fileStatus === "deleted";

  const resources = useQuery({
    queryKey: [
      "resources",
      "list",
      folderId,
      resourceType,
      debouncedSearch,
      fileStatus,
      ownership,
      uploaderId,
      limit,
      offset,
    ],
    queryFn: () =>
      api.get<PageResourceSummary>("/resources", {
        query: {
          folder_id: folderId ?? undefined,
          root_only: folderId === null && !debouncedSearch ? true : undefined,
          resource_type: resourceType || undefined,
          query: debouncedSearch || undefined,
          file_status: fileStatus,
          include_deleted: fileStatus === "deleted" || fileStatus === "all" ? true : undefined,
          only_mine: ownership === "mine" ? true : undefined,
          uploader_id: uploaderId || undefined,
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

  const removeMany = useApiMutation<BulkDeleteResponse, string[]>({
    mutationFn: (resource_ids) =>
      api.post<BulkDeleteResponse>("/resources/delete-many", { body: { resource_ids } }),
    success: (res) => `Moved ${res.deleted_count} file(s) to the recycle bin.`,
    invalidate: [["resources"]],
    onSuccess: () => setDeletingMany([]),
  });

  const purgeMany = useApiMutation<BulkPurgeResponse, { resource_ids: string[]; force?: boolean }>({
    mutationFn: (body) => api.post<BulkPurgeResponse>("/resources/purge-many", { body }),
    success: (res) => `Permanently deleted ${res.purged_count} file(s).`,
    invalidate: [["resources"]],
    onSuccess: () => setPurgingTarget(null),
  });

  const restore = useApiMutation<ResourceResponse, string>({
    mutationFn: (id) => api.post<ResourceResponse>(`/resources/${segment(id)}/restore`),
    success: "Restored.",
    invalidate: [["resources"]],
  });

  const restoreMany = useApiMutation<BulkRestoreResponse, string[]>({
    mutationFn: (resource_ids) =>
      api.post<BulkRestoreResponse>("/resources/restore-many", { body: { resource_ids } }),
    success: (res) => `Restored ${res.restored_count} file(s).`,
    invalidate: [["resources"]],
  });

  const emptyBin = useApiMutation<PurgeAllResourcesResponse, void>({
    mutationFn: () => api.delete<PurgeAllResourcesResponse>("/resources/bin"),
    success: (res) => `Emptied recycle bin (${res.purged_count} file(s) permanently destroyed).`,
    invalidate: [["resources"]],
    onSuccess: () => setConfirmingEmptyBin(false),
  });

  const purgeAll = useApiMutation<PurgeAllResourcesResponse, void>({
    mutationFn: () =>
      api.delete<PurgeAllResourcesResponse>("/resources/purge-all", { query: { in_bin_only: false } }),
    success: (res) => `Permanently deleted all ${res.purged_count} file(s).`,
    invalidate: [["resources"]],
    onSuccess: () => setConfirmingPurgeAll(false),
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

  const [renameSeed, setRenameSeed] = useState<FolderSummary | null>(null);
  if (renameSeed !== renaming) {
    setRenameSeed(renaming);
    setRenameValue(renaming?.name ?? "");
  }

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
    onShareMany: (resourceIds) => setSharingMany(resourceIds),
    onMoveResource: (id, folder) => move.mutate({ id, folder }),
    onUploadFiles: (files) => {
      setDroppedFiles(files);
      setUploadOpen(true);
    },
    onDownload: (resource) =>
      void downloadFile(`/resources/${segment(resource.public_id)}/download`, resource.name ?? "file"),
    onCopy: (resource) => copy.mutate(resource.public_id),
    onShare: (resource) => setSharingMany([resource.public_id]),
    onDelete: (resource) => setDeleting(resource),
    onDeleteMany: (resourceIds) => setDeletingMany(resourceIds),
    onRestore: (resource) => restore.mutate(resource.public_id),
    onRestoreMany: (resourceIds) => restoreMany.mutate(resourceIds),
    onPurge: (resource) => setPurgingTarget([resource.public_id]),
    onPurgeMany: (resourceIds) => setPurgingTarget(resourceIds),
    onRenameFolder: (folder) => setRenaming(folder),
    onDeleteFolder: (folder) => setDeletingFolder(folder),
  };

  const statusOptions = [
    { value: "active", label: "Active files" },
    { value: "deleted", label: "Recycle bin" },
    ...(isSuperAdmin ? [{ value: "all", label: "All files (Active & Bin)" }] : []),
  ];

  const ownershipOptions = [
    { value: "all", label: "All files" },
    { value: "mine", label: "My uploads only" },
  ];

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

        {inBin && (resources.data?.total ?? 0) > 0 && (canWrite || isSuperAdmin) ? (
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={() => setConfirmingEmptyBin(true)}
          >
            <Trash2 className="size-4" aria-hidden /> Empty recycle bin
          </Button>
        ) : null}

        {canWrite || isSuperAdmin ? (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button size="sm">
                  <Plus /> New
                </Button>
              }
            />
            <DropdownMenuContent align="start">
              {canWrite ? (
                <>
                  <DropdownMenuItem onClick={() => setNewFolderOpen(true)}>
                    <FolderPlus /> New folder
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setUploadOpen(true)}>
                    <Upload /> File upload
                  </DropdownMenuItem>
                </>
              ) : null}
              {isSuperAdmin ? (
                <DropdownMenuItem
                  destructive
                  onClick={() => setConfirmingPurgeAll(true)}
                >
                  <Trash2 /> Purge all resources (Permanent)
                </DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </DriveToolbar>

      {/* Filter and Management Bar */}
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Search" className="min-w-48 flex-1">
          {({ id }) => (
            <Input
              id={id}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search library files"
            />
          )}
        </Field>

        <Field label="Type" className="w-44">
          {({ id }) => (
            <Select
              id={id}
              value={resourceType || null}
              onValueChange={(next) => {
                setResourceType(next ?? "");
                setPage({ limit, offset: 0 });
              }}
              placeholder="Any type"
              clearable
              options={optionsFromValues(ResourceTypeValues)}
            />
          )}
        </Field>

        <Field label="Status" className="w-40">
          {({ id }) => (
            <Select
              id={id}
              value={fileStatus}
              onValueChange={(next) => {
                setFileStatus((next as "active" | "deleted" | "all") ?? "active");
                setPage({ limit, offset: 0 });
              }}
              options={statusOptions}
            />
          )}
        </Field>

        <Field label="Ownership" className="w-36">
          {({ id }) => (
            <Select
              id={id}
              value={ownership}
              onValueChange={(next) => {
                setOwnership((next as "all" | "mine") ?? "all");
                setPage({ limit, offset: 0 });
              }}
              options={ownershipOptions}
            />
          )}
        </Field>

        {(isSuperAdmin || permissions.has("user.read")) && (
          <Field label="Uploader" className="w-48">
            <UserPicker
              value={uploaderId}
              onChange={(id) => {
                setUploaderId(id);
                setPage({ limit, offset: 0 });
              }}
              placeholder="Any uploader"
              allowClear
            />
          </Field>
        )}
      </div>

      {resources.isPending ? (
        <LoadingState />
      ) : resources.error ? (
        <ErrorState error={resources.error} onRetry={() => void resources.refetch()} />
      ) : (
        <>
          <DriveView
            layout={layout}
            folders={inBin ? [] : folders.data ?? []}
            resources={resources.data?.items ?? []}
            canWrite={canWrite}
            isSuperAdmin={isSuperAdmin}
            inBin={inBin}
            emptyMessage={
              inBin
                ? "The recycle bin is empty."
                : debouncedSearch || resourceType || uploaderId || ownership === "mine"
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

      {/* Upload Dialog with real-time percentage progress and duplicate checks */}
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

      <ResourceDrawer
        resourceId={selected}
        onClose={() => setSelected(null)}
        onPurge={(r) => setPurgingTarget([r.public_id])}
      />

      <ShareDialog
        open={sharingMany.length > 0}
        onOpenChange={(open) => (open ? null : setSharingMany([]))}
        resourceIds={sharingMany}
        resourceNames={sharingMany.map(
          (id) =>
            resources.data?.items.find((item) => item.public_id === id)?.name ?? "Untitled"
        )}
      />

      {/* Single Move to Bin */}
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

      {/* Bulk Move to Bin */}
      <ConfirmDialog
        open={deletingMany.length > 0}
        onOpenChange={(open) => (open ? null : setDeletingMany([]))}
        destructive
        title={`Move ${deletingMany.length} file(s) to the recycle bin?`}
        description="The selected files will be moved to the recycle bin and remain recoverable until permanently purged."
        confirmLabel="Move to bin"
        pending={removeMany.isPending}
        onConfirm={() => {
          removeMany.mutate(deletingMany);
        }}
      />

      {/* Permanent Deletion Impact Warning Dialog for Single or Bulk Purge */}
      <DeletionImpactDialog
        open={purgingTarget !== null && purgingTarget.length > 0}
        onClose={() => setPurgingTarget(null)}
        resourceIds={purgingTarget ?? []}
        isPending={purgeMany.isPending}
        isSuperAdmin={isSuperAdmin}
        onConfirm={() => {
          if (purgingTarget) {
            purgeMany.mutate({ resource_ids: purgingTarget, force: isSuperAdmin });
          }
        }}
      />

      <ConfirmDialog
        open={confirmingEmptyBin}
        onOpenChange={setConfirmingEmptyBin}
        destructive
        title="Empty the recycle bin?"
        description="All files in the recycle bin and every stored version will be permanently destroyed. This cannot be undone."
        confirmLabel="Empty recycle bin"
        pending={emptyBin.isPending}
        onConfirm={() => emptyBin.mutate()}
      />

      <ConfirmDialog
        open={confirmingPurgeAll}
        onOpenChange={setConfirmingPurgeAll}
        destructive
        title="Purge ALL resources permanently?"
        description="CRITICAL ACTION: This will permanently delete EVERY resource and file version across the entire LMS library. This cannot be undone."
        confirmPhrase="DELETE ALL RESOURCES"
        confirmLabel="Purge all resources"
        pending={purgeAll.isPending}
        onConfirm={() => purgeAll.mutate()}
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