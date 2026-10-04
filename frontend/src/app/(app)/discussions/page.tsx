"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock, MessagesSquare, Pin, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import type { DiscussionResponse, PageDiscussionResponse } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale } from "@/lib/preferences";
import { formatRelative } from "@/lib/format/datetime";
import { CoursePicker } from "@/components/domain/entity-pickers";

function NewDiscussionDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [courseId, setCourseId] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  const create = useApiMutation<DiscussionResponse, void>({
    mutationFn: () =>
      api.post<DiscussionResponse>("/discussions", {
        body: { course_id: courseId, title, body },
      }),
    success: "Discussion started.",
    invalidate: [["discussions"]],
    onSuccess: () => {
      setTitle("");
      setBody("");
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader
          title="Start a discussion"
          description="Discussions belong to a course; everyone who can see the course can read them."
        />
        <div className="space-y-4">
          <Field label="Course" required>
            {({ id }) => (
              <CoursePicker id={id} value={(courseId) || null} onValueChange={(next) => setCourseId((next ?? ""))} placeholder="Choose a course" clearable />
            )}
          </Field>
          <Field label="Title" required>
            {({ id }) => (
              <Input id={id} value={title} onChange={(event) => setTitle(event.target.value)} />
            )}
          </Field>
          <Field label="Opening post" required>
            {({ id }) => (
              <Textarea id={id} rows={6} value={body} onChange={(event) => setBody(event.target.value)} />
            )}
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            loading={create.isPending}
            disabled={!courseId || title.trim() === "" || body.trim() === ""}
            onClick={() => create.mutate()}
          >
            Start discussion
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function DiscussionsPage() {
  const { permissions } = useSession();
  const locale = useDisplayLocale();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(20);
  const [courseId, setCourseId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["discussions", "list", courseId, debouncedSearch, limit, offset],
    queryFn: () =>
      api.get<PageDiscussionResponse>("/discussions", {
        query: { course_id: courseId || undefined, q: debouncedSearch || undefined, limit, offset },
      }),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Discussions"
        description="Course-scoped threads. A locked thread stays readable but takes no new replies."
        actions={
          permissions.has("discussion.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> Start a discussion
            </Button>
          ) : null
        }
      />

      <Card>
        <CardHeader
          title="Threads"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Input
                className="w-56"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search discussions"
                aria-label="Search discussions"
              />
              <CoursePicker className="w-56" ariaLabel="Filter by course" value={(courseId) || null} disabled={!permissions.has("course.read")} onValueChange={(next) => {
                  setCourseId((next ?? ""));
                  setPage({ limit, offset: 0 });
                }} placeholder="Every course" clearable />
            </div>
          }
        />
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={<MessagesSquare className="size-5" />} title="No discussions yet" />
        ) : (
          <>
            <ul className="divide-y divide-border-subtle">
              {(data?.items ?? []).map((discussion) => (
                <li key={discussion.public_id} className="px-4 py-3">
                  <Link
                    href={`/discussions/${discussion.public_id}`}
                    className="flex flex-wrap items-center gap-2 font-medium hover:underline"
                  >
                    {discussion.is_pinned ? (
                      <Pin className="size-3.5 text-primary" aria-label="Pinned" />
                    ) : null}
                    {discussion.is_locked ? (
                      <Lock className="size-3.5 text-muted-foreground" aria-label="Locked" />
                    ) : null}
                    {discussion.title}
                  </Link>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {discussion.course_title ? (
                      <Badge tone="info">{discussion.course_title}</Badge>
                    ) : null}
                    {discussion.author ? (
                      <span>{discussion.author.full_name || discussion.author.username}</span>
                    ) : null}
                    <span>{formatRelative(discussion.created_at, locale)}</span>
                    <span>
                      {discussion.reply_count ?? 0}{" "}
                      {discussion.reply_count === 1 ? "reply" : "replies"}
                    </span>
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{discussion.body}</p>
                </li>
              ))}
            </ul>
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="discussions"
            />
          </>
        )}
      </Card>

      <NewDiscussionDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
