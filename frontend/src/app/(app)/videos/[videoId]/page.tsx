"use client";

/**
 * One video: the in-platform player, what it is, and -- for whoever manages
 * it -- who it is shared with.
 *
 * Every way to the video (`player_url`, `open_url`) is a path on our API that
 * re-checks access when followed; the provider's address is shown only to the
 * person who added it (or a Super Admin), who needs to see what they entered.
 */

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Pencil, Share2, Trash2, X } from "lucide-react";
import { api, apiPath, segment } from "@/lib/api/client";
import type { VideoDetail } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button, LinkButton } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { VideoPlayer } from "@/components/domain/videos/video-player";
import { ShareVideoDialog } from "@/components/domain/videos/video-dialogs";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

function EditVideoDialog({ video, open, onOpenChange }: {
  video: VideoDetail; open: boolean; onOpenChange: (open: boolean) => void;
}) {
  const [title, setTitle] = useState(video.title);
  const [description, setDescription] = useState(video.description ?? "");
  const [url, setUrl] = useState(video.source_url ?? "");
  const save = useApiMutation<VideoDetail, void>({
    mutationFn: () =>
      api.patch<VideoDetail>(`/videos/${segment(video.public_id)}`, {
        body: {
          title,
          description,
          ...(url && url !== video.source_url ? { url } : {}),
        },
      }),
    success: "Video updated.",
    invalidate: [["videos"]],
    onSuccess: () => onOpenChange(false),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader title="Edit video" />
        <form method="post" className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Title" required>
            {({ id }) => <Input id={id} value={title} onChange={(e) => setTitle(e.target.value)} />}
          </Field>
          <Field label="Video link">
            {({ id }) => <Input id={id} value={url} onChange={(e) => setUrl(e.target.value)} />}
          </Field>
          <Field label="Description">
            {({ id }) => <Textarea id={id} rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" loading={save.isPending} disabled={title.trim().length < 2}>Save</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function VideoDetailPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const [sharing, setSharing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["videos", "detail", videoId],
    queryFn: () => api.get<VideoDetail>(`/videos/${segment(videoId)}`),
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/videos/${segment(videoId)}`),
    success: "Video deleted.",
    invalidate: [["videos"]],
    onSuccess: () => router.push("/videos"),
  });
  const unshare = useApiMutation<void, number>({
    mutationFn: (shareId) => api.delete<void>(`/videos/${segment(videoId)}/shares/${shareId}`),
    success: "Stopped sharing.",
    invalidate: [["videos"]],
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const manage = data.can_manage;
  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Video library", href: "/videos" }, { label: data.title }]}
        title={data.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={data.plays_in_lms ? "neutral" : "warning"}>{data.provider_label}</Badge>
            {data.course_title ? <Badge tone="info">{data.course_title}</Badge> : null}
            {data.batch_code ? <Badge tone="info">{data.batch_code}</Badge> : null}
            <span className="text-xs">
              {data.is_mine ? "Added by you" : data.owner_name ? `Added by ${data.owner_name}` : ""} ·{" "}
              {formatDateTime(data.created_at, { timeZone })}
            </span>
          </span>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <LinkButton variant="ghost" size="sm" href={apiPath(data.open_url)} target="_blank" rel="noopener noreferrer">
              <ExternalLink /> Open on {data.provider_label}
            </LinkButton>
            {manage && permissions.has("video.publish") ? (
              <Button size="sm" variant="secondary" onClick={() => setSharing(true)}>
                <Share2 /> Share
              </Button>
            ) : null}
            {manage && permissions.has("video.update") ? (
              <Button size="icon-sm" variant="ghost" aria-label="Edit video" onClick={() => setEditing(true)}>
                <Pencil />
              </Button>
            ) : null}
            {manage && permissions.has("video.delete") ? (
              <Button size="icon-sm" variant="ghost" aria-label="Delete video" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      <VideoPlayer video={data} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="About this video" />
          <CardBody className="space-y-3 text-sm">
            <p className="whitespace-pre-wrap">{data.description || "No description."}</p>
            <dl className="grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-[auto_1fr]">
              <dt className="font-medium">Downloads</dt><dd>{data.notes.download}</dd>
              <dt className="font-medium">Domain lock</dt><dd>{data.notes.domain_restriction}</dd>
              {data.notes.needs_provider_sign_in ? (
                <>
                  <dt className="font-medium">Sign-in</dt>
                  <dd>Viewers must be signed in to {data.provider_label} with access to it.</dd>
                </>
              ) : null}
              {data.source_url ? (
                <>
                  <dt className="font-medium">Link</dt>
                  <dd className="break-all">{data.source_url}</dd>
                </>
              ) : null}
            </dl>
          </CardBody>
        </Card>
        {manage ? (
          <Card>
            <CardHeader title="Shared with" description="Only these people and batches can watch it." />
            <CardBody>
              {data.shares && data.shares.length ? (
                <ul className="divide-y divide-border-subtle text-sm">
                  {data.shares.map((s) => (
                    <li key={s.id} className="flex items-center gap-2 py-1.5">
                      <Badge tone={s.kind === "BATCH" ? "info" : "neutral"}>{s.kind === "BATCH" ? "Batch" : "Person"}</Badge>
                      <span className="flex-1 truncate">{s.label}</span>
                      {permissions.has("video.publish") ? (
                        <Button size="icon-sm" variant="ghost" aria-label={`Stop sharing with ${s.label}`}
                                disabled={unshare.isPending} onClick={() => unshare.mutate(s.id)}>
                          <X />
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">Not shared yet — only you can watch it.</p>
              )}
            </CardBody>
          </Card>
        ) : null}
      </div>

      {manage ? <ShareVideoDialog open={sharing} onOpenChange={setSharing} video={data} /> : null}
      {manage && editing ? <EditVideoDialog video={data} open={editing} onOpenChange={setEditing} /> : null}
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title={`Delete "${data.title}"?`}
        description="It leaves the library and every share stops working immediately. The video itself stays on the provider; delete it there too if it should no longer exist."
        confirmLabel="Delete video"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
