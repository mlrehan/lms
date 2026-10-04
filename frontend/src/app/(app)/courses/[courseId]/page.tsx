"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ExternalLink, Plus, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  BatchResponse,
  BatchSummary,
  CourseResponse,
  PageBatchSummary,
  PageTagResponse,
  PageUserSummary,
} from "@/lib/api/types";
import { CourseStatusValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { CourseForm } from "@/components/domain/course-form";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormActions, FormGrid, Input, Textarea } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { BooleanBadge, StatusBadge } from "@/components/domain/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatCalendarDate, formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function OverviewTab({ course, canEdit }: { course: CourseResponse; canEdit: boolean }) {
  // Keyed on the last update so the form re-initialises after a save (or an image change)
  // instead of showing the values it was first opened with.
  return (
    <CourseForm
      key={`${course.public_id}:${course.updated_at ?? ""}`}
      mode="edit"
      course={course}
      canEdit={canEdit}
      onSaved={() => undefined}
    />
  );
}

const batchSchema = z.object({
  batch_code: z.string().trim().min(1, "Give the batch a code."),
  capacity: z.string().trim(),
  start_date: z.string().trim(),
  end_date: z.string().trim(),
  number_of_sessions: z.string().trim(),
  notes: z.string().trim(),
});

type BatchValues = z.infer<typeof batchSchema>;

function BatchesTab({ course }: { course: CourseResponse }) {
  const { permissions } = useSession();
  const { limit, offset, setPage } = useListState(10);
  const [createOpen, setCreateOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["courses", course.public_id, "batches", limit, offset],
    queryFn: () =>
      api.get<PageBatchSummary>(`/courses/${segment(course.public_id)}/batches`, {
        query: { limit, offset },
      }),
  });

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<BatchValues>({ resolver: zodResolver(batchSchema) });

  const create = useApiMutation<BatchResponse, BatchValues>({
    mutationFn: (values) =>
      api.post<BatchResponse>(`/courses/${segment(course.public_id)}/batches`, {
        body: {
          batch_code: values.batch_code,
          capacity: values.capacity ? Number(values.capacity) : null,
          number_of_sessions: values.number_of_sessions ? Number(values.number_of_sessions) : null,
          start_date: values.start_date || null,
          end_date: values.end_date || null,
          notes: values.notes || null,
        },
      }),
    success: (batch) => `Created batch ${batch.batch_code}.`,
    invalidate: [["courses", course.public_id, "batches"], ["batches"]],
    onSuccess: () => {
      reset();
      setBanner(null);
      setCreateOpen(false);
    },
    onError: (error) => {
      if (!applyFieldErrors<BatchValues>(error, setError, ["batch_code", "start_date", "end_date"])) {
        setBanner(error.message);
      }
    },
  });

  const columns: Column<BatchSummary>[] = [
    {
      key: "code",
      header: "Batch",
      cell: (batch) => (
        <Link href={`/batches/${batch.public_id}`} className="font-mono text-sm font-medium hover:underline">
          {batch.batch_code}
        </Link>
      ),
    },
    {
      key: "active",
      header: "Active",
      cell: (batch) => <BooleanBadge value={batch.is_active} trueLabel="Active" falseLabel="Closed" />,
    },
    {
      key: "dates",
      header: "Runs",
      secondary: true,
      cell: (batch) =>
        `${formatCalendarDate(batch.start_date)} - ${formatCalendarDate(batch.end_date)}`,
    },
    {
      key: "capacity",
      header: "Capacity",
      align: "right",
      cell: (batch) => <span className="tabular-nums">{batch.capacity ?? "Unlimited"}</span>,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Batches"
        description="A batch is one cohort running this course: its own schedule, capacity and register."
        actions={
          permissions.has("batch.create") ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus /> New batch
            </Button>
          ) : null
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(batch) => batch.public_id}
            emptyMessage="No batches yet. Create one to schedule sessions and enroll students."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="batches"
          />
        </>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="md">
          <DialogHeader title="New batch" description={`A new cohort for ${course.title}.`} />
          <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
            {banner ? (
              <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                {banner}
              </div>
            ) : null}
            <Field label="Batch code" error={errors.batch_code?.message} required hint="Unique across the institution.">
              {({ id }) => <Input id={id} placeholder="MATH101-A" {...register("batch_code")} />}
            </Field>
            <FormGrid>
              <Field label="Capacity" hint="Leave blank for unlimited.">
                {({ id }) => <Input id={id} type="number" min={1} {...register("capacity")} />}
              </Field>
              <Field label="Planned sessions">
                {({ id }) => <Input id={id} type="number" min={1} {...register("number_of_sessions")} />}
              </Field>
              <Field label="Start date" error={errors.start_date?.message}>
                {({ id }) => <Input id={id} type="date" {...register("start_date")} />}
              </Field>
              <Field label="End date" error={errors.end_date?.message}>
                {({ id }) => <Input id={id} type="date" {...register("end_date")} />}
              </Field>
            </FormGrid>
            <Field label="Notes">
              {({ id }) => <Textarea id={id} rows={2} {...register("notes")} />}
            </Field>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending}>
                Create batch
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function TeachingTab({ course }: { course: CourseResponse }) {
  const { permissions } = useSession();
  const canEdit = permissions.has("course.update");
  const canListUsers = permissions.has("user.read");
  const canReadAcademic = permissions.has("academic.read");

  const tutorDirectory = useQuery({
    queryKey: ["users", "tutors"],
    queryFn: () =>
      api.get<PageUserSummary>("/users", { query: { role: "TUTOR", limit: 200, status: "ACTIVE" } }),
    enabled: canListUsers,
    staleTime: 5 * 60_000,
  });

  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: () => api.get<PageTagResponse>("/tags", { query: { limit: 200 } }),
    enabled: canReadAcademic,
    staleTime: 5 * 60_000,
  });

  /**
   * The API returns tutors as *usernames* but accepts *public ids*, so the
   * two have to be matched up through the user directory. Without
   * `user.read` there is no directory to match against, which is why the
   * editor below is disabled rather than shown broken.
   */
  const idByUsername = useMemo(() => {
    const map = new Map<string, string>();
    for (const person of tutorDirectory.data?.items ?? []) map.set(person.username, person.public_id);
    return map;
  }, [tutorDirectory.data]);

  const [selectedTutors, setSelectedTutors] = useState<string[] | null>(null);
  const currentTutorIds = (course.tutors ?? [])
    .map((username) => idByUsername.get(username))
    .filter((value): value is string => Boolean(value));
  const tutorSelection = selectedTutors ?? currentTutorIds;

  const saveTutors = useApiMutation<CourseResponse, string[]>({
    mutationFn: (tutors) =>
      api.put<CourseResponse>(`/courses/${segment(course.public_id)}/tutors`, { body: { tutors } }),
    success: "Tutors updated.",
    invalidate: [["courses"]],
    onSuccess: () => setSelectedTutors(null),
  });

  const [selectedTags, setSelectedTags] = useState<string[] | null>(null);
  const currentTagIds = useMemo(() => {
    const byName = new Map((tags.data?.items ?? []).map((tag) => [tag.name, tag.public_id]));
    return (course.tags ?? [])
      .map((name) => byName.get(name))
      .filter((value): value is string => Boolean(value));
  }, [tags.data, course.tags]);
  const tagSelection = selectedTags ?? currentTagIds;

  const saveTags = useApiMutation<CourseResponse, string[]>({
    mutationFn: (tagIds) =>
      api.put<CourseResponse>(`/courses/${segment(course.public_id)}/tags`, { body: { tags: tagIds } }),
    success: "Tags updated.",
    invalidate: [["courses"]],
    onSuccess: () => setSelectedTags(null),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Tutors"
          description="Assigning a tutor to a course gives them access to its batches and the students in them."
        />
        <CardBody className="space-y-3">
          {!canListUsers ? (
            <p className="text-sm text-muted-foreground">
              Currently assigned: {(course.tutors ?? []).join(", ") || "nobody"}. Changing this needs
              the <code className="font-mono text-xs">user.read</code> permission, because the API
              identifies tutors by id and returns them by username.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {(tutorDirectory.data?.items ?? []).map((tutor) => {
                  const checked = tutorSelection.includes(tutor.public_id);
                  return (
                    <label
                      key={tutor.public_id}
                      className={`cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                        checked
                          ? "border-primary bg-accent text-accent-foreground"
                          : "border-border-subtle text-muted-foreground hover:border-border-strong"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        disabled={!canEdit}
                        onChange={(event) =>
                          setSelectedTutors(
                            event.target.checked
                              ? [...tutorSelection, tutor.public_id]
                              : tutorSelection.filter((id) => id !== tutor.public_id),
                          )
                        }
                      />
                      {tutor.full_name || tutor.username}
                    </label>
                  );
                })}
                {(tutorDirectory.data?.items ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No active accounts hold the TUTOR role yet.
                  </p>
                ) : null}
              </div>
              {canEdit ? (
                <FormActions>
                  <Button
                    variant="ghost"
                    disabled={selectedTutors === null}
                    onClick={() => setSelectedTutors(null)}
                  >
                    Reset
                  </Button>
                  <Button
                    loading={saveTutors.isPending}
                    disabled={selectedTutors === null}
                    onClick={() => saveTutors.mutate(tutorSelection)}
                  >
                    Save tutors
                  </Button>
                </FormActions>
              ) : null}
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Tags" description="Free-form grouping, independent of category and department." />
        <CardBody className="space-y-3">
          {!canReadAcademic ? (
            <p className="text-sm text-muted-foreground">
              Tagged: {(course.tags ?? []).join(", ") || "none"}. Editing tags needs{" "}
              <code className="font-mono text-xs">academic.read</code> to list the tag catalog.
            </p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {(tags.data?.items ?? []).map((tag) => {
                  const checked = tagSelection.includes(tag.public_id);
                  return (
                    <label
                      key={tag.public_id}
                      className={`cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                        checked
                          ? "border-primary bg-accent text-accent-foreground"
                          : "border-border-subtle text-muted-foreground hover:border-border-strong"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        disabled={!canEdit}
                        onChange={(event) =>
                          setSelectedTags(
                            event.target.checked
                              ? [...tagSelection, tag.public_id]
                              : tagSelection.filter((id) => id !== tag.public_id),
                          )
                        }
                      />
                      {tag.name}
                    </label>
                  );
                })}
                {(tags.data?.items ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No tags exist yet. Create them under Academic setup.
                  </p>
                ) : null}
              </div>
              {canEdit ? (
                <FormActions>
                  <Button
                    variant="ghost"
                    disabled={selectedTags === null}
                    onClick={() => setSelectedTags(null)}
                  >
                    Reset
                  </Button>
                  <Button
                    loading={saveTags.isPending}
                    disabled={selectedTags === null}
                    onClick={() => saveTags.mutate(tagSelection)}
                  >
                    Save tags
                  </Button>
                </FormActions>
              ) : null}
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

export default function CourseDetailPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["courses", "detail", courseId],
    queryFn: () => api.get<CourseResponse>(`/courses/${segment(courseId)}`),
  });

  const setStatus = useApiMutation<CourseResponse, string>({
    mutationFn: (status) =>
      api.put<CourseResponse>(`/courses/${segment(courseId)}/status`, { body: { status } }),
    success: "Status updated.",
    invalidate: [["courses"]],
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/courses/${segment(courseId)}`),
    success: "Course deleted.",
    invalidate: [["courses"]],
    onSuccess: () => router.push("/courses"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const canEdit = permissions.has("course.update");
  const canPublish = permissions.has("course.publish");

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Courses", href: "/courses" }, { label: data.title }]}
        title={data.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge value={data.status} kind="course" />
            <Badge tone="neutral">{humanise(data.level)}</Badge>
            {data.code ? <Badge tone="neutral">{data.code}</Badge> : null}
            {data.category_name ? <Badge tone="info">{data.category_name}</Badge> : null}
            {data.department_name ? <Badge tone="info">{data.department_name}</Badge> : null}
            <span className="text-xs">
              {data.batch_count ?? 0} batches · updated{" "}
              {formatDateTime(data.updated_at ?? data.created_at, { timeZone })}
            </span>
          </span>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {data.course_link ? (
              <a
                href={data.course_link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
              >
                Course link <ExternalLink className="size-3.5" />
              </a>
            ) : null}
            {canPublish ? (
              <Select
                aria-label="Course status"
                className="w-auto"
                value={data.status}
                disabled={setStatus.isPending}
                onValueChange={(next) => setStatus.mutate((next ?? ""))}
               options={optionsFromValues(CourseStatusValues, humanise)} />
            ) : null}
            {permissions.has("course.delete") ? (
              <Button variant="ghost" size="icon" aria-label="Delete course" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTab value="overview">Overview</TabsTab>
          <TabsTab value="batches">Batches</TabsTab>
          <TabsTab value="teaching">Tutors &amp; tags</TabsTab>
        </TabsList>
        <TabsPanel value="overview">
          <OverviewTab course={data} canEdit={canEdit} />
        </TabsPanel>
        <TabsPanel value="batches">
          <BatchesTab course={data} />
        </TabsPanel>
        <TabsPanel value="teaching">
          <TeachingTab course={data} />
        </TabsPanel>
      </Tabs>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this course?"
        description="Its batches, enrollments and assessments go with it. Archiving keeps the record instead."
        confirmPhrase={data.code || data.title}
        confirmLabel="Delete course"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
