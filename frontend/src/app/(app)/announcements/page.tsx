"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Megaphone, Pin, Plus, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  AnnouncementResponse,
  PageAnnouncementResponse,
  PageBatchSummary,
  PageCourseSummary,
} from "@/lib/api/types";
import { RolesValues } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader, Switch } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "@/lib/format/datetime";

interface Draft {
  title: string;
  content: string;
  course_id: string;
  batch_id: string;
  role_scope: string;
  start_at: string;
  end_at: string;
  pinned: boolean;
}

const EMPTY: Draft = {
  title: "",
  content: "",
  course_id: "",
  batch_id: "",
  role_scope: "",
  start_at: "",
  end_at: "",
  pinned: false,
};

function AnnouncementDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: AnnouncementResponse | null;
}) {
  const timeZone = useDisplayTimeZone();
  const { permissions } = useSession();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [initialised, setInitialised] = useState<string | null>(null);

  // Seeded from the record being edited on first open, then left to the user.
  if (open && initialised !== (editing?.public_id ?? "new")) {
    setInitialised(editing?.public_id ?? "new");
    setDraft(
      editing
        ? {
            title: editing.title,
            content: editing.content,
            course_id: editing.course_id ?? "",
            batch_id: editing.batch_id ?? "",
            role_scope: editing.role_scope ?? "",
            start_at: toLocalInputValue(editing.start_at, timeZone),
            end_at: toLocalInputValue(editing.end_at, timeZone),
            pinned: editing.pinned ?? false,
          }
        : EMPTY,
    );
  }

  const courses = useQuery({
    queryKey: ["courses", "picker"],
    queryFn: () => api.get<PageCourseSummary>("/courses", { query: { limit: 200 } }),
    enabled: open && permissions.has("course.read"),
    staleTime: 60_000,
  });

  const batches = useQuery({
    queryKey: ["batches", "picker"],
    queryFn: () => api.get<PageBatchSummary>("/batches", { query: { limit: 200 } }),
    enabled: open && permissions.has("batch.read"),
    staleTime: 60_000,
  });

  const save = useApiMutation<AnnouncementResponse, Draft>({
    mutationFn: (values) => {
      const payload = {
        title: values.title,
        content: values.content,
        role_scope: values.role_scope || null,
        start_at: values.start_at ? fromLocalInputValue(values.start_at, timeZone) : null,
        end_at: values.end_at ? fromLocalInputValue(values.end_at, timeZone) : null,
        pinned: values.pinned,
      };
      if (editing) {
        return api.patch<AnnouncementResponse>(`/announcements/${segment(editing.public_id)}`, {
          body: payload,
        });
      }
      return api.post<AnnouncementResponse>("/announcements", {
        body: {
          ...payload,
          course_id: values.course_id || null,
          batch_id: values.batch_id || null,
        },
      });
    },
    success: editing ? "Announcement updated." : "Announcement posted.",
    invalidate: [["announcements"], ["dashboard"]],
    onSuccess: () => {
      setInitialised(null);
      onOpenChange(false);
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setInitialised(null);
        onOpenChange(next);
      }}
    >
      <DialogContent size="lg">
        <DialogHeader
          title={editing ? "Edit announcement" : "New announcement"}
          description={
            editing
              ? "The audience cannot be changed after posting -- the API takes course and batch only at creation."
              : `Leave the window blank to publish now and never expire. Times are entered in ${timeZone}.`
          }
        />
        <div className="space-y-4">
          <Field label="Title" required>
            {({ id }) => (
              <Input
                id={id}
                value={draft.title}
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              />
            )}
          </Field>
          <Field label="Message" required>
            {({ id }) => (
              <Textarea
                id={id}
                rows={6}
                value={draft.content}
                onChange={(event) => setDraft({ ...draft, content: event.target.value })}
              />
            )}
          </Field>

          {!editing ? (
            <FormGrid>
              <Field label="Course" hint="Optional: narrow to one course.">
                {({ id }) => (
                  <NativeSelect
                    id={id}
                    value={draft.course_id}
                    onChange={(event) => setDraft({ ...draft, course_id: event.target.value })}
                  >
                    <option value="">Everyone</option>
                    {(courses.data?.items ?? []).map((course) => (
                      <option key={course.public_id} value={course.public_id}>
                        {course.title}
                      </option>
                    ))}
                  </NativeSelect>
                )}
              </Field>
              <Field label="Batch" hint="Optional: narrow to one cohort.">
                {({ id }) => (
                  <NativeSelect
                    id={id}
                    value={draft.batch_id}
                    onChange={(event) => setDraft({ ...draft, batch_id: event.target.value })}
                  >
                    <option value="">Everyone</option>
                    {(batches.data?.items ?? []).map((batch) => (
                      <option key={batch.public_id} value={batch.public_id}>
                        {batch.batch_code}
                      </option>
                    ))}
                  </NativeSelect>
                )}
              </Field>
            </FormGrid>
          ) : null}

          <FormGrid columns={3}>
            <Field label="Role" hint="Optional: only this role sees it.">
              {({ id }) => (
                <NativeSelect
                  id={id}
                  value={draft.role_scope}
                  onChange={(event) => setDraft({ ...draft, role_scope: event.target.value })}
                >
                  <option value="">Every role</option>
                  {RolesValues.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Show from">
              {({ id }) => (
                <Input
                  id={id}
                  type="datetime-local"
                  value={draft.start_at}
                  onChange={(event) => setDraft({ ...draft, start_at: event.target.value })}
                />
              )}
            </Field>
            <Field label="Show until" hint="Blank means it never expires.">
              {({ id }) => (
                <Input
                  id={id}
                  type="datetime-local"
                  value={draft.end_at}
                  onChange={(event) => setDraft({ ...draft, end_at: event.target.value })}
                />
              )}
            </Field>
          </FormGrid>

          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={draft.pinned}
              onCheckedChange={(checked) => setDraft({ ...draft, pinned: checked })}
            />
            Pin to the top of the feed
          </label>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            disabled={draft.title.trim() === "" || draft.content.trim() === ""}
            onClick={() => save.mutate(draft)}
          >
            {editing ? "Save changes" : "Post announcement"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AnnouncementsPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(20);
  const [mineOnly, setMineOnly] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AnnouncementResponse | null>(null);
  const [deleting, setDeleting] = useState<AnnouncementResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["announcements", "list", mineOnly, limit, offset],
    queryFn: () =>
      api.get<PageAnnouncementResponse>("/announcements", {
        query: { mine: mineOnly || undefined, limit, offset },
      }),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/announcements/${segment(id)}`),
    success: "Announcement deleted.",
    invalidate: [["announcements"], ["dashboard"]],
    onSuccess: () => setDeleting(null),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Announcements"
        description="Notices with a display window. An announcement outside its window is stored but not shown."
        actions={
          permissions.has("announcement.create") ? (
            <Button
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus /> New announcement
            </Button>
          ) : null
        }
      />

      <Card>
        <CardHeader
          title="Feed"
          actions={
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={mineOnly}
                onCheckedChange={(checked) => {
                  setMineOnly(checked);
                  setPage({ limit, offset: 0 });
                }}
              />
              Only mine
            </label>
          }
        />
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <EmptyState icon={<Megaphone className="size-5" />} title="Nothing announced" />
        ) : (
          <>
            <ul className="divide-y divide-border">
              {(data?.items ?? []).map((announcement) => (
                <li key={announcement.public_id} className="space-y-1.5 px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {announcement.pinned ? (
                          <Pin className="size-3.5 text-primary" aria-label="Pinned" />
                        ) : null}
                        {announcement.title}
                        {announcement.is_live === false ? (
                          <Badge tone="neutral">Not live</Badge>
                        ) : (
                          <Badge tone="success">Live</Badge>
                        )}
                      </p>
                      <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {announcement.author ? (
                          <span>{announcement.author.full_name || announcement.author.username}</span>
                        ) : null}
                        {announcement.course_title ? (
                          <Badge tone="info">{announcement.course_title}</Badge>
                        ) : null}
                        {announcement.batch_code ? (
                          <Badge tone="info">{announcement.batch_code}</Badge>
                        ) : null}
                        {announcement.role_scope ? (
                          <Badge tone="neutral">{announcement.role_scope} only</Badge>
                        ) : null}
                        <span>
                          {formatDateTime(announcement.start_at, { timeZone })}
                          {announcement.end_at
                            ? ` – ${formatDateTime(announcement.end_at, { timeZone })}`
                            : " – no end"}
                        </span>
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {permissions.has("announcement.update") ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditing(announcement);
                            setDialogOpen(true);
                          }}
                        >
                          Edit
                        </Button>
                      ) : null}
                      {permissions.has("announcement.delete") ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Delete announcement"
                          onClick={() => setDeleting(announcement)}
                        >
                          <Trash2 className="text-danger" />
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {/* Author-written text, rendered as text. */}
                  <p className="whitespace-pre-wrap break-words text-sm">{announcement.content}</p>
                </li>
              ))}
            </ul>
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="announcements"
            />
          </>
        )}
      </Card>

      <AnnouncementDialog open={dialogOpen} onOpenChange={setDialogOpen} editing={editing} />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (open ? null : setDeleting(null))}
        destructive
        title="Delete this announcement?"
        description="It disappears from everyone's feed."
        confirmLabel="Delete"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.public_id);
        }}
      />
    </div>
  );
}
