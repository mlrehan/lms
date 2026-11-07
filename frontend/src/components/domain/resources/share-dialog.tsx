"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Search, Share2, Users, X } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import { useApiMutation } from "@/lib/api/hooks";
import { useDebounced } from "@/components/ui/combobox";
import type {
  BulkShareResponse,
  ShareCandidateResponse,
  SharedFolderResponse,
} from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/primitives";
import { EmptyState, InlineSpinner } from "@/components/ui/states";
import { cn } from "@/lib/utils";

/**
 * Handing files and folders to people.
 *
 * **The list is the server's, not a user directory with a filter on it.**
 * `GET /resources/share-audience` answers "who may *this* caller share with",
 * which for a tutor is the administrators, the students in the batches they
 * teach, and those students' guardians. Drawing the picker from `/users` and
 * narrowing it here would put the rule in the browser, where it is a
 * suggestion -- and the write already refuses anyone outside the audience, so
 * a wider picker would only produce confident 403s.
 *
 * **Every row carries the batch and the course.** Two students called Sarah is
 * the ordinary case, not a contrived one, and the consequence of picking the
 * wrong one is a file reaching a class that should not have it. For a guardian
 * the row says whose guardian they are, because their own name says nothing
 * about which class they are connected to.
 *
 * **No email address appears anywhere**, by construction rather than by
 * omission: the response has no field for one.
 *
 * Files and folders and several people in one act, through the bulk endpoint,
 * which is all-or-nothing and idempotent: something already shared at this
 * level is left alone, so the confirmation never needs to say "already shared"
 * and pressing Share twice does no harm.
 */

const PAGE = 50;

function Placements({ candidate }: { candidate: ShareCandidateResponse }): ReactNode {
  const places = candidate.placements ?? [];
  if (places.length === 0 && !candidate.relation) return null;
  return (
    <div className="mt-0.5 space-y-0.5">
      {candidate.relation ? (
        <p className="text-2xs text-muted-foreground">{candidate.relation}</p>
      ) : null}
      {places.map((place, index) => (
        <p key={index} className="text-2xs text-subtle-foreground">
          {[place.batch_code, place.course_title].filter(Boolean).join(" · ")}
        </p>
      ))}
      {(candidate.more_placements ?? 0) > 0 ? (
        <p className="text-2xs text-subtle-foreground">
          +{candidate.more_placements} more
        </p>
      ) : null}
    </div>
  );
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "this file", "3 files", "a folder", "2 files and 1 folder" -- for the title. */
export function describeSelection(files: number, folders: number): string {
  if (files === 1 && folders === 0) return "this file";
  if (files === 0 && folders === 1) return "this folder";
  const parts = [
    files > 0 ? plural(files, "file", "files") : null,
    folders > 0 ? plural(folders, "folder", "folders") : null,
  ].filter(Boolean);
  return parts.join(" and ");
}

/** Who already holds one folder, with a way to take it back. */
function FolderAccess({ folderId }: { folderId: string }): ReactNode {
  const queryClient = useQueryClient();
  const shares = useQuery({
    queryKey: ["folder-shares", folderId],
    queryFn: () => api.get<SharedFolderResponse[]>(`/folders/${segment(folderId)}/shares`),
  });
  const revoke = useApiMutation<void, string>({
    mutationFn: (userId) =>
      api.delete<void>(`/folders/${segment(folderId)}/share/${segment(userId)}`),
    success: "Access removed.",
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["folder-shares", folderId] });
    },
  });

  const rows = shares.data ?? [];
  if (shares.isPending || rows.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">People with access</p>
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle">
        {rows.map((row) => (
          <li key={row.shared_with_user_id} className="flex items-center gap-2 px-3 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate">{row.shared_with_name}</span>
            <Badge tone="neutral" className="text-2xs">
              {row.level === "DOWNLOAD" ? "View and download" : "View only"}
            </Badge>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove ${row.shared_with_name ?? "this person"}`}
              loading={revoke.isPending && revoke.variables === row.shared_with_user_id}
              onClick={() => row.shared_with_user_id && revoke.mutate(row.shared_with_user_id)}
            >
              <X className="size-4" />
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ShareDialog({
  open,
  onOpenChange,
  resourceIds,
  resourceNames,
  folderIds = [],
  folderNames = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** One file, or everything currently ticked in the library. */
  resourceIds: string[];
  resourceNames: string[];
  /** Folders to hand over whole; everything beneath them is covered. */
  folderIds?: string[];
  folderNames?: string[];
}): ReactNode {
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const debounced = useDebounced(term, 300);
  const [chosen, setChosen] = useState<ShareCandidateResponse[]>([]);
  const [level, setLevel] = useState<"VIEW" | "DOWNLOAD">("VIEW");

  // The dialog is mounted once and reused, so the previous share's recipients
  // and -- more importantly -- its level would carry into the next one. The
  // level is a permission; defaulting it to whatever was last chosen is how a
  // file meant to be watched in place ends up downloadable.
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setTerm("");
      setChosen([]);
      setLevel("VIEW");
    }
  }

  const audience = useQuery({
    queryKey: ["resources", "share-audience", debounced],
    queryFn: () =>
      api.get<ShareCandidateResponse[]>("/resources/share-audience", {
        query: { query: debounced || undefined, limit: PAGE },
      }),
    enabled: open,
    staleTime: 30_000,
  });

  const chosenIds = useMemo(() => new Set(chosen.map((c) => c.public_id)), [chosen]);
  const itemCount = resourceIds.length + folderIds.length;
  const names = [...folderNames, ...resourceNames];

  const share = useApiMutation<BulkShareResponse, void>({
    mutationFn: () =>
      api.post<BulkShareResponse>("/resources/share", {
        body: {
          resource_ids: resourceIds,
          folder_ids: folderIds,
          user_ids: chosen.map((c) => c.public_id),
          level,
        },
      }),
    // Deliberately the same message whether every row was new or some were
    // already shared: the server skipped the duplicates, nothing went wrong,
    // and telling the sharer "3 were already shared" interrupts them with a
    // fact they cannot act on.
    success: () => `Shared with ${plural(chosen.length, "person", "people")}.`,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["resources"] });
      void queryClient.invalidateQueries({ queryKey: ["shared-with-me"] });
      for (const id of folderIds) {
        void queryClient.invalidateQueries({ queryKey: ["folder-shares", id] });
      }
      onOpenChange(false);
    },
  });

  function toggle(candidate: ShareCandidateResponse): void {
    setChosen((current) =>
      current.some((c) => c.public_id === candidate.public_id)
        ? current.filter((c) => c.public_id !== candidate.public_id)
        : [...current, candidate],
    );
  }

  const results = audience.data ?? [];
  const what = describeSelection(resourceIds.length, folderIds.length);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader
          title={`Share ${what}`}
          description={
            names.length === 1
              ? names[0]
              : `${names.slice(0, 3).join(", ")}${
                  names.length > 3 ? ` +${names.length - 3} more` : ""
                }`
          }
        />

        <div className="space-y-3">
          {folderIds.length > 0 ? (
            <p className="rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
              Sharing a folder shares everything inside it, including subfolders and files added
              later. Staff-only files inside it stay hidden from students, guardians and managers.
            </p>
          ) : null}

          {open && folderIds.length === 1 && folderIds[0] && resourceIds.length === 0 ? (
            <FolderAccess folderId={folderIds[0]} />
          ) : null}

          <Field label="Find people">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={term}
                onChange={(event) => setTerm(event.target.value)}
                placeholder="Search by name"
                className="pl-8"
                autoComplete="off"
              />
            </div>
          </Field>

          {chosen.length > 0 ? (
            <div className="flex flex-wrap gap-1.5" aria-label="Chosen recipients">
              {chosen.map((candidate) => (
                <button
                  key={candidate.public_id}
                  type="button"
                  onClick={() => toggle(candidate)}
                  className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-surface-muted px-2 py-0.5 text-xs hover:border-border-strong"
                >
                  {candidate.name}
                  <X className="size-3 text-muted-foreground" aria-hidden />
                  <span className="sr-only">Remove {candidate.name}</span>
                </button>
              ))}
            </div>
          ) : null}

          <div className="max-h-72 overflow-y-auto rounded-lg border border-border-subtle">
            {audience.isPending ? (
              <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                <InlineSpinner /> Finding people you can share with…
              </div>
            ) : results.length === 0 ? (
              <EmptyState
                icon={<Users />}
                title="Nobody to show"
                description={
                  term
                    ? "No one in your classes matches that name."
                    : "You can share with your administrators, the students you teach and their guardians."
                }
              />
            ) : (
              <ul className="divide-y divide-border-subtle">
                {results.map((candidate) => {
                  const picked = chosenIds.has(candidate.public_id);
                  return (
                    <li key={candidate.public_id}>
                      <button
                        type="button"
                        aria-pressed={picked}
                        onClick={() => toggle(candidate)}
                        className={cn(
                          "flex w-full items-start gap-2 px-3 py-2 text-left transition-colors",
                          picked ? "bg-accent/60" : "hover:bg-muted/50",
                        )}
                      >
                        <span
                          className={cn(
                            "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-xs border",
                            picked
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border-strong bg-surface",
                          )}
                          aria-hidden
                        >
                          {picked ? <Check className="size-3" strokeWidth={3} /> : null}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate text-sm font-medium">{candidate.name}</span>
                            <Badge tone="neutral" className="text-2xs">
                              {candidate.role}
                            </Badge>
                          </span>
                          <Placements candidate={candidate} />
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <Field
            label="What they may do"
            hint="View lets them read or watch it in place. Download hands over the file."
          >
            <Select
              value={level}
              onValueChange={(next) => setLevel((next ?? "VIEW") as "VIEW" | "DOWNLOAD")}
              options={[
                { value: "VIEW", label: "View only" },
                { value: "DOWNLOAD", label: "View and download" },
              ]}
            />
          </Field>
        </div>

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            loading={share.isPending}
            disabled={chosen.length === 0 || itemCount === 0 || share.isPending}
            onClick={() => share.mutate()}
          >
            <Share2 className="size-4" aria-hidden />
            {chosen.length > 0 ? `Share with ${chosen.length}` : "Share"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
