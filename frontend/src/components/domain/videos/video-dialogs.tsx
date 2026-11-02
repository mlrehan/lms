"use client";

/**
 * Adding a video, and sharing one.
 *
 * Neither dialog decides who may receive a video. People come from
 * `GET /resources/share-audience` -- the server's answer to "who may this
 * caller share with" (a Super Admin: anybody; a tutor: colleagues, the
 * students they teach and those students' guardians) -- and batches from the
 * batch picker, which lists only batches the caller can reach. The server
 * checks both again on the write and refuses the whole request if one
 * recipient is out of bounds.
 */

import { useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Search, Users, X } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import { useApiMutation } from "@/lib/api/hooks";
import { useDebounced } from "@/components/ui/combobox";
import type {
  ShareCandidateResponse,
  VideoDetail,
  VideoInspectResponse,
  VideoShareResult,
} from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Badge } from "@/components/ui/primitives";
import { EmptyState, InlineSpinner } from "@/components/ui/states";
import { BatchPicker, CoursePicker } from "@/components/domain/entity-pickers";
import { cn } from "@/lib/utils";

export function AddVideoDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (video: VideoDetail) => void;
}): ReactNode {
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [courseId, setCourseId] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const debouncedUrl = useDebounced(url.trim(), 400);

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setTitle("");
      setUrl("");
      setDescription("");
      setCourseId(null);
      setBatchId(null);
    }
  }

  // What the LMS recognises in the link, before anything is saved -- parsed
  // on the server, never fetched (fetching a pasted address is an SSRF).
  const inspect = useQuery({
    queryKey: ["videos", "inspect", debouncedUrl],
    queryFn: () => api.post<VideoInspectResponse>("/videos/inspect", { body: { url: debouncedUrl } }),
    enabled: open && debouncedUrl.length > 6,
    retry: false,
  });

  const create = useApiMutation<VideoDetail, void>({
    mutationFn: () =>
      api.post<VideoDetail>("/videos", {
        body: {
          title,
          url,
          description: description || null,
          course_id: courseId,
          batch_id: batchId,
        },
      }),
    success: "Video added. Share it to let others watch.",
    invalidate: [["videos"]],
    onSuccess: (video) => {
      onOpenChange(false);
      onCreated(video);
    },
  });

  const notes = inspect.data?.notes;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader
          title="Add a video"
          description="Paste a link from YouTube, Vimeo, Wistia, Brightcove, Dacast, Zoom, Google Drive or Meet, Microsoft Teams/Stream, StreamYard or Zoho."
        />
        <form
          method="post"
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Video link" required>
            {({ id }) => (
              <Input id={id} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" autoComplete="off" />
            )}
          </Field>
          {inspect.error ? (
            <p className="text-xs text-danger">{inspect.error.message}</p>
          ) : notes ? (
            <div className="space-y-1 rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs">
              <p className="flex items-center gap-2 font-medium">
                <Badge tone={notes.plays_in_lms ? "success" : "warning"}>{inspect.data?.provider_label}</Badge>
                {notes.plays_in_lms ? "Plays inside the LMS" : "Opens on the provider's site"}
              </p>
              <p className="text-muted-foreground">Downloads: {notes.download}</p>
              <p className="text-muted-foreground">Domain lock: {notes.domain_restriction}</p>
            </div>
          ) : null}
          <Field label="Title" required>
            {({ id }) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} />}
          </Field>
          <Field label="Description">
            {({ id }) => (
              <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
            )}
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Course" hint="Optional — a course you teach.">
              {({ id }) => <CoursePicker id={id} value={courseId} onValueChange={(v) => setCourseId(v)} />}
            </Field>
            <Field label="Batch" hint="Optional — a batch you teach.">
              {({ id }) => <BatchPicker id={id} value={batchId} onValueChange={(v) => setBatchId(v)} />}
            </Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending} disabled={title.trim().length < 2 || !url.trim()}>
              Add video
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ShareVideoDialog({
  open,
  onOpenChange,
  video,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  video: VideoDetail;
}): ReactNode {
  const queryClient = useQueryClient();
  const [term, setTerm] = useState("");
  const debounced = useDebounced(term, 300);
  const [chosen, setChosen] = useState<ShareCandidateResponse[]>([]);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchLabel, setBatchLabel] = useState<string | null>(null);

  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setTerm("");
      setChosen([]);
      setBatchId(null);
      setBatchLabel(null);
    }
  }

  const audience = useQuery({
    queryKey: ["resources", "share-audience", debounced],
    queryFn: () =>
      api.get<ShareCandidateResponse[]>("/resources/share-audience", {
        query: { query: debounced || undefined, limit: 30 },
      }),
    enabled: open,
    staleTime: 30_000,
  });
  const chosenIds = useMemo(() => new Set(chosen.map((c) => c.public_id)), [chosen]);

  const share = useApiMutation<VideoShareResult, void>({
    mutationFn: () =>
      api.post<VideoShareResult>(`/videos/${segment(video.public_id)}/shares`, {
        body: { user_ids: chosen.map((c) => c.public_id), batch_ids: batchId ? [batchId] : [] },
      }),
    success: (r) =>
      `Shared with ${r.people_added} ${r.people_added === 1 ? "person" : "people"}${
        r.batches_added ? ` and ${r.batches_added} batch` : ""
      }.`,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["videos"] });
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader title="Share this video" description={video.title} />
        <div className="space-y-3">
          <Field label="A whole batch" hint="Everyone enrolled, and the tutors who teach it.">
            {({ id }) => (
              <BatchPicker
                id={id}
                value={batchId}
                onValueChange={(v, b) => {
                  setBatchId(v);
                  setBatchLabel(b?.batch_code ?? null);
                }}
              />
            )}
          </Field>
          <Field label="People">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder="Search by name"
                className="pl-8"
                autoComplete="off"
              />
            </div>
          </Field>
          {chosen.length || batchLabel ? (
            <div className="flex flex-wrap gap-1.5" aria-label="Chosen recipients">
              {batchLabel ? <Badge tone="info">Batch {batchLabel}</Badge> : null}
              {chosen.map((c) => (
                <button
                  key={c.public_id}
                  type="button"
                  onClick={() => toggle(c)}
                  className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-surface-muted px-2 py-0.5 text-xs hover:border-border-strong"
                >
                  {c.name}
                  <X className="size-3 text-muted-foreground" aria-hidden />
                  <span className="sr-only">Remove {c.name}</span>
                </button>
              ))}
            </div>
          ) : null}
          <div className="max-h-64 overflow-y-auto rounded-lg border border-border-subtle">
            {audience.isPending ? (
              <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                <InlineSpinner /> Finding people you can share with…
              </div>
            ) : results.length === 0 ? (
              <EmptyState
                icon={<Users />}
                title="Nobody to show"
                description={term ? "No one you may share with matches that name." : "You can share with your colleagues, the students you teach and their guardians."}
              />
            ) : (
              <ul className="divide-y divide-border-subtle">
                {results.map((c) => {
                  const picked = chosenIds.has(c.public_id);
                  return (
                    <li key={c.public_id}>
                      <button
                        type="button"
                        aria-pressed={picked}
                        onClick={() => toggle(c)}
                        className={cn(
                          "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors",
                          picked ? "bg-accent/60" : "hover:bg-muted/50",
                        )}
                      >
                        <span
                          className={cn(
                            "flex size-4 shrink-0 items-center justify-center rounded-xs border",
                            picked ? "border-primary bg-primary text-primary-foreground" : "border-border-strong bg-surface",
                          )}
                          aria-hidden
                        >
                          {picked ? <Check className="size-3" strokeWidth={3} /> : null}
                        </span>
                        <span className="truncate text-sm font-medium">{c.name}</span>
                        <Badge tone="neutral" className="text-2xs">{c.role}</Badge>
                        {c.relation ? <span className="truncate text-xs text-muted-foreground">{c.relation}</span> : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={share.isPending} disabled={!chosen.length && !batchId} onClick={() => share.mutate()}>
            Share
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
