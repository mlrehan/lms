"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Lock, Pin, Send, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  DiscussionReplyResponse,
  DiscussionResponse,
  PageDiscussionReplyResponse,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Switch } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";

export default function DiscussionDetailPage({
  params,
}: {
  params: Promise<{ discussionId: string }>;
}) {
  const { discussionId } = use(params);
  const router = useRouter();
  const { permissions, user } = useSession();
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const { limit, offset, setPage } = useListState(25);
  const [reply, setReply] = useState("");
  const [editingReply, setEditingReply] = useState<DiscussionReplyResponse | null>(null);
  const [editBody, setEditBody] = useState("");
  const [deletingReply, setDeletingReply] = useState<DiscussionReplyResponse | null>(null);
  const [deletingThread, setDeletingThread] = useState(false);

  const discussion = useQuery({
    queryKey: ["discussions", "detail", discussionId],
    queryFn: () => api.get<DiscussionResponse>(`/discussions/${segment(discussionId)}`),
  });

  const replies = useQuery({
    queryKey: ["discussions", discussionId, "replies", limit, offset],
    queryFn: () =>
      api.get<PageDiscussionReplyResponse>(`/discussions/${segment(discussionId)}/replies`, {
        query: { limit, offset },
      }),
  });

  const post = useApiMutation<DiscussionReplyResponse, string>({
    mutationFn: (body) =>
      api.post<DiscussionReplyResponse>(`/discussions/${segment(discussionId)}/replies`, {
        body: { body },
      }),
    success: "Reply posted.",
    invalidate: [["discussions"]],
    onSuccess: () => setReply(""),
  });

  const editReply = useApiMutation<DiscussionReplyResponse, { id: string; body: string }>({
    mutationFn: ({ id, body }) =>
      api.patch<DiscussionReplyResponse>(`/discussion-replies/${segment(id)}`, { body: { body } }),
    success: "Reply updated.",
    invalidate: [["discussions"]],
    onSuccess: () => setEditingReply(null),
  });

  const removeReply = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/discussion-replies/${segment(id)}`),
    success: "Reply deleted.",
    invalidate: [["discussions"]],
    onSuccess: () => setDeletingReply(null),
  });

  const updateThread = useApiMutation<DiscussionResponse, { is_pinned?: boolean; is_locked?: boolean }>({
    mutationFn: (patch) =>
      api.patch<DiscussionResponse>(`/discussions/${segment(discussionId)}`, { body: patch }),
    success: "Discussion updated.",
    invalidate: [["discussions"]],
  });

  const removeThread = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/discussions/${segment(discussionId)}`),
    success: "Discussion deleted.",
    invalidate: [["discussions"]],
    onSuccess: () => router.push("/discussions"),
  });

  if (discussion.isPending) return <LoadingState rows={6} />;
  if (discussion.error) {
    return <ErrorState error={discussion.error} onRetry={() => void discussion.refetch()} />;
  }
  const data = discussion.data;
  if (!data) return null;

  const canModerate = permissions.has("discussion.update");
  const canReply = permissions.has("discussion.create") && !data.is_locked;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Discussions", href: "/discussions" }, { label: data.title }]}
        title={data.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {data.is_pinned ? <Badge tone="primary">Pinned</Badge> : null}
            {data.is_locked ? (
              <Badge tone="warning">
                <Lock className="size-3" /> Locked
              </Badge>
            ) : null}
            {data.course_title ? (
              <Link href={`/courses/${data.course_id}`} className="text-xs hover:underline">
                {data.course_title}
              </Link>
            ) : null}
            <span className="text-xs">
              Started by {data.author?.full_name || data.author?.username || "someone"} ·{" "}
              {formatDateTime(data.created_at, { timeZone })}
            </span>
          </span>
        }
        actions={
          <div className="flex flex-wrap items-center gap-3">
            {canModerate ? (
              <>
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={data.is_pinned ?? false}
                    disabled={updateThread.isPending}
                    onCheckedChange={(checked) => updateThread.mutate({ is_pinned: checked })}
                  />
                  <Pin className="size-4" aria-hidden /> Pin
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={data.is_locked ?? false}
                    disabled={updateThread.isPending}
                    onCheckedChange={(checked) => updateThread.mutate({ is_locked: checked })}
                  />
                  <Lock className="size-4" aria-hidden /> Lock
                </label>
              </>
            ) : null}
            {permissions.has("discussion.delete") ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete discussion"
                onClick={() => setDeletingThread(true)}
              >
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      <Card>
        <CardBody>
          {/* Author-written text, rendered as text. */}
          <p className="whitespace-pre-wrap break-words text-sm">{data.body}</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={`${data.reply_count ?? 0} replies`} />
        {replies.isPending ? (
          <LoadingState />
        ) : replies.error ? (
          <ErrorState error={replies.error} onRetry={() => void replies.refetch()} />
        ) : (replies.data?.items.length ?? 0) === 0 ? (
          <CardBody>
            <p className="text-sm text-muted-foreground">No replies yet.</p>
          </CardBody>
        ) : (
          <>
            <ul className="divide-y divide-border-subtle">
              {(replies.data?.items ?? []).map((item) => {
                const mine = item.author?.public_id === user?.public_id;
                return (
                  <li key={item.public_id} className="space-y-1.5 px-4 py-3">
                    <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {item.author?.full_name || item.author?.username || "Someone"}
                      </span>
                      <span>{formatRelative(item.created_at, locale)}</span>
                      {mine || canModerate ? (
                        <>
                          <button
                            type="button"
                            className="hover:underline"
                            onClick={() => {
                              setEditingReply(item);
                              setEditBody(item.body);
                            }}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="text-danger hover:underline"
                            onClick={() => setDeletingReply(item)}
                          >
                            Delete
                          </button>
                        </>
                      ) : null}
                    </p>
                    {editingReply?.public_id === item.public_id ? (
                      <div className="space-y-2">
                        <Textarea
                          rows={4}
                          aria-label="Edit reply"
                          value={editBody}
                          onChange={(event) => setEditBody(event.target.value)}
                        />
                        <FormActions>
                          <Button variant="ghost" size="sm" onClick={() => setEditingReply(null)}>
                            Cancel
                          </Button>
                          <Button
                            size="sm"
                            loading={editReply.isPending}
                            onClick={() => editReply.mutate({ id: item.public_id, body: editBody })}
                          >
                            Save
                          </Button>
                        </FormActions>
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap break-words text-sm">{item.body}</p>
                    )}
                  </li>
                );
              })}
            </ul>
            <Pagination
              total={replies.data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="replies"
            />
          </>
        )}

        {canReply ? (
          <CardBody className="border-t border-border-subtle">
            <Field label="Your reply">
              {({ id }) => (
                <Textarea
                  id={id}
                  rows={4}
                  value={reply}
                  onChange={(event) => setReply(event.target.value)}
                />
              )}
            </Field>
            <FormActions>
              <Button
                loading={post.isPending}
                disabled={reply.trim() === ""}
                onClick={() => post.mutate(reply)}
              >
                <Send /> Post reply
              </Button>
            </FormActions>
          </CardBody>
        ) : data.is_locked ? (
          <CardBody className="border-t border-border-subtle">
            <p className="text-sm text-muted-foreground">
              This discussion is locked. It stays readable, but takes no new replies.
            </p>
          </CardBody>
        ) : null}
      </Card>

      <ConfirmDialog
        open={deletingReply !== null}
        onOpenChange={(open) => (open ? null : setDeletingReply(null))}
        destructive
        title="Delete this reply?"
        confirmLabel="Delete reply"
        pending={removeReply.isPending}
        onConfirm={() => {
          if (deletingReply) removeReply.mutate(deletingReply.public_id);
        }}
      />

      <ConfirmDialog
        open={deletingThread}
        onOpenChange={setDeletingThread}
        destructive
        title="Delete this discussion?"
        description="Every reply goes with it."
        confirmPhrase={data.title}
        confirmLabel="Delete discussion"
        pending={removeThread.isPending}
        onConfirm={() => removeThread.mutate()}
      />
    </div>
  );
}
