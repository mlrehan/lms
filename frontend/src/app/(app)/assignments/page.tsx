"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { api, segment } from "@/lib/api/client";
import type { AssignmentResponse, AssignmentSummary, PageAssignmentSummary, PageSessionSummary } from "@/lib/api/types";
import { SubmissionTypeValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Switch } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, Textarea } from "@/components/ui/form";
import { FormSelect } from "@/components/ui/form-controls";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative, fromLocalInputValue } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";
import { CoursePicker, FormBatchPicker, FormCoursePicker } from "@/components/domain/entity-pickers";

const createSchema = z
  .object({
    course_id: z.string().min(1, "Choose the course this belongs to."),
    // §3: who the work is for. COURSE keeps the behaviour every existing
    // assignment has, so the default changes nothing for anyone.
    scope: z.enum(["COURSE", "BATCH", "SESSION"]),
    batch_id: z.string(),
    session_id: z.string(),
    title: z.string().trim().min(2, "Give the assignment a title."),
    description: z.string().trim(),
    available_from: z.string(),
    due_date: z.string().min(1, "Set a due date."),
    max_score: z.string().min(1, "Set the maximum score."),
    passing_score: z.string(),
    submission_type: z.enum(SubmissionTypeValues),
    allow_late_submissions: z.boolean(),
    late_penalty_percent_per_day: z.string(),
    allow_resubmission: z.boolean(),
    state: z.enum(["DRAFT", "PUBLISHED"]),
  })
  // Client-side copies of two rules the API also enforces. Not a substitute
  // for the server check (§30) -- this only spares the person a round trip to
  // be told something the form already knew.
  .refine((v) => v.scope !== "BATCH" || v.batch_id, {
    path: ["batch_id"],
    message: "Choose the batch this is set for.",
  })
  .refine((v) => v.scope !== "SESSION" || v.session_id, {
    path: ["session_id"],
    message: "Choose the class this is set for.",
  })
  .refine((v) => !v.passing_score || Number(v.passing_score) <= Number(v.max_score), {
    path: ["passing_score"],
    message: "The passing mark cannot exceed the maximum.",
  })
  .refine((v) => !v.available_from || !v.due_date || v.due_date > v.available_from, {
    path: ["due_date"],
    message: "The deadline must be after the assignment opens.",
  });

type CreateValues = z.infer<typeof createSchema>;

function CreateAssignmentDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const timeZone = useDisplayTimeZone();
  const [banner, setBanner] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    setValue,
    setError,
    formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      course_id: "",
      scope: "COURSE",
      batch_id: "",
      session_id: "",
      title: "",
      description: "",
      available_from: "",
      due_date: "",
      max_score: "100",
      passing_score: "",
      submission_type: "TEXT",
      allow_late_submissions: false,
      late_penalty_percent_per_day: "",
      allow_resubmission: false,
      state: "PUBLISHED",
    },
  });

  const create = useApiMutation<AssignmentResponse, CreateValues>({
    mutationFn: (values) =>
      api.post<AssignmentResponse>(`/courses/${segment(values.course_id)}/assignments`, {
        body: {
          title: values.title,
          description: values.description || null,
          due_date: fromLocalInputValue(values.due_date, timeZone),
          max_score: Number(values.max_score),
          submission_type: values.submission_type,
          allow_late_submissions: values.allow_late_submissions,
          scope: values.scope,
          // Sent only when the scope asks for them. Passing a stale batch id
          // on a course-wide assignment is refused by the API, and rightly:
          // it is how somebody later "fixes" the scope by reading the wrong
          // field.
          batch_id: values.scope === "BATCH" ? values.batch_id : null,
          session_id: values.scope === "SESSION" ? values.session_id : null,
          state: values.state,
          available_from: values.available_from
            ? fromLocalInputValue(values.available_from, timeZone)
            : null,
          passing_score: values.passing_score ? Number(values.passing_score) : null,
          late_penalty_percent_per_day: values.late_penalty_percent_per_day
            ? Number(values.late_penalty_percent_per_day)
            : null,
          allow_resubmission: values.allow_resubmission,
        },
      }),
    success: "Assignment created.",
    invalidate: [["assignments"]],
    onSuccess: (assignment) => {
      reset();
      onOpenChange(false);
      router.push(`/assignments/${assignment.public_id}`);
    },
    onError: (error) => {
      if (!applyFieldErrors<CreateValues>(error, setError, ["title", "due_date", "max_score"])) {
        setBanner(error.message);
      }
    },
  });

  const allowLate = watch("allow_late_submissions");
  const scope = watch("scope");
  const courseId = watch("course_id");

  // Only the batches of the course that was chosen. Offering every batch on
  // the platform would let a tutor pick one from another course, which the API
  // refuses -- an error the form should never have allowed them to reach.
  const batchId = watch("batch_id");
  const sessions = useQuery({
    queryKey: ["sessions", "for-batch", batchId],
    queryFn: () =>
      api.get<PageSessionSummary>("/sessions", { query: { batch_id: batchId, limit: 200 } }),
    enabled: open && Boolean(batchId) && scope === "SESSION",
    staleTime: 60_000,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="New assignment"
          description={`The due date is entered in ${timeZone} and stored in UTC.`}
        />
        <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Course" error={errors.course_id?.message} required>
            {({ id }) => (
              <FormCoursePicker id={id} control={control} name="course_id" placeholder="Choose a course" />
            )}
          </Field>
          {/* §3's academic scope. Grouped and explained rather than left as a
              bare dropdown: "who is this for" is the decision with the widest
              consequences on this form, and the one a tutor most needs to get
              right. */}
          <fieldset className="space-y-3 rounded-lg border border-border-subtle p-3">
            <legend className="px-1 text-xs font-medium text-muted-foreground">
              Who is this for
            </legend>
            <Field label="Set for" error={errors.scope?.message}>
              {({ id }) => (
                <FormSelect
                  id={id}
                  control={control}
                  name="scope"
                  options={[
                    { value: "COURSE", label: "Everyone on the course" },
                    { value: "BATCH", label: "One batch" },
                    { value: "SESSION", label: "One class" },
                  ]}
                />
              )}
            </Field>

            {scope !== "COURSE" ? (
              <Field label="Batch" error={errors.batch_id?.message} required>
                {({ id }) => (
                  <FormBatchPicker
                    id={id}
                    control={control}
                    name="batch_id"
                    disabled={!courseId}
                    clearable
                    // A dependent picker: the placeholder states the
                    // precondition rather than offering an empty list.
                    placeholder={courseId ? "Choose a batch" : "Choose a course first"}
                  />
                )}
              </Field>
            ) : null}

            {scope === "SESSION" ? (
              <Field label="Class" error={errors.session_id?.message} required>
                {({ id }) => (
                  <FormSelect
                    id={id}
                    control={control}
                    name="session_id"
                    disabled={!batchId}
                    clearable
                    placeholder={batchId ? "Choose a class" : "Choose a batch first"}
                    options={(sessions.data?.items ?? []).map((sess) => ({
                      value: sess.public_id,
                      label: formatDateTime(sess.session_start_time, { timeZone }),
                    }))}
                  />
                )}
              </Field>
            ) : null}

            <p className="text-xs text-muted-foreground">
              {scope === "COURSE"
                ? "Every student in every active batch of this course will be set this work."
                : scope === "BATCH"
                  ? "Only students enrolled in the chosen batch."
                  : "Students of the batch this class belongs to — including anyone who missed it."}
            </p>
          </fieldset>

          <Field label="Title" error={errors.title?.message} required>
            {({ id }) => <Input id={id} {...register("title")} />}
          </Field>
          <FormGrid>
            <Field label="Due" error={errors.due_date?.message} required>
              {({ id }) => <Input id={id} type="datetime-local" {...register("due_date")} />}
            </Field>
            <Field label="Maximum score" error={errors.max_score?.message} required>
              {({ id }) => <Input id={id} type="number" min={0} step="0.01" {...register("max_score")} />}
            </Field>
            <Field label="Submission type">
              {({ id }) => (
                <FormSelect id={id}  control={control} name="submission_type" options={SubmissionTypeValues.map((value) => ({ value: value, label: humanise(value) }))} />
              )}
            </Field>
          </FormGrid>
          <Field label="Description">
            {({ id }) => <Textarea id={id} {...register("description")} />}
          </Field>
          <fieldset className="space-y-3 rounded-lg border border-border-subtle p-3">
            <legend className="px-1 text-xs font-medium text-muted-foreground">
              Rules
            </legend>
            <FormGrid>
              <Field label="Opens" error={errors.available_from?.message}>
                {({ id }) => (
                  <Input id={id} type="datetime-local" {...register("available_from")} />
                )}
              </Field>
              <Field label="Passing mark" error={errors.passing_score?.message}>
                {({ id }) => (
                  <Input id={id} type="number" min={0} step="0.01" {...register("passing_score")} />
                )}
              </Field>
            </FormGrid>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={watch("allow_resubmission")}
                onCheckedChange={(checked) => setValue("allow_resubmission", checked)}
              />
              <span>
                Allow resubmission
                <span className="block text-xs text-muted-foreground">
                  Lets you hand work back for another attempt after marking it.
                </span>
              </span>
            </label>
          </fieldset>

          <label className="flex items-center gap-3 text-sm">
            <Switch
              checked={allowLate}
              onCheckedChange={(checked) => setValue("allow_late_submissions", checked)}
            />
            <span>
              Accept late submissions
              <span className="block text-xs text-muted-foreground">
                Late work is still flagged as late; this only decides whether it is accepted at all.
              </span>
            </span>
          </label>
          {allowLate ? (
            <Field
              label="Late penalty (% of the maximum, per day)"
              error={errors.late_penalty_percent_per_day?.message}
            >
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={0}
                  max={100}
                  step="0.01"
                  placeholder="Leave empty for no penalty"
                  {...register("late_penalty_percent_per_day")}
                />
              )}
            </Field>
          ) : null}

          {/* §8's "save as Draft" / "publish immediately". A draft notifies
              nobody and accepts no submissions, which is the point of it. */}
          <Field label="On save">
            {({ id }) => (
              <FormSelect id={id}  control={control} name="state" options={[{ value: "PUBLISHED", label: "Publish now — students are notified" }, { value: "DRAFT", label: "Save as draft — nobody is notified" }]} />
            )}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create assignment
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function AssignmentsPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const { limit, offset, setPage } = useListState();
  const [courseId, setCourseId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["assignments", "list", courseId, limit, offset],
    queryFn: () =>
      api.get<PageAssignmentSummary>("/assignments", {
        query: { course_id: courseId || undefined, limit, offset },
      }),
  });

  const columns: Column<AssignmentSummary>[] = [
    {
      key: "title",
      header: "Assignment",
      cell: (row) => (
        <span className="flex flex-wrap items-center gap-2">
          <Link href={`/assignments/${row.public_id}`} className="font-medium hover:underline">
            {row.title}
          </Link>
          {/* A draft is invisible to students and accepts nothing, so a tutor
              scanning this list needs to see it at a glance -- not discover it
              when nobody submits. */}
          {row.state === "DRAFT" ? <Badge tone="warning" dot>Draft</Badge> : null}
          {row.scope !== "COURSE" ? (
            <Badge tone="neutral">{row.scope === "BATCH" ? "One batch" : "One class"}</Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "due",
      header: "Due",
      cell: (row) => (
        <span title={formatDateTime(row.due_date, { timeZone })}>
          {formatRelative(row.due_date, locale)}
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      secondary: true,
      cell: (row) => <Badge tone="neutral">{humanise(row.submission_type)}</Badge>,
    },
    {
      key: "late",
      header: "Late work",
      secondary: true,
      cell: (row) => (
        <Badge tone={row.allow_late_submissions ? "warning" : "neutral"}>
          {row.allow_late_submissions ? "Accepted" : "Refused"}
        </Badge>
      ),
    },
    {
      key: "max",
      header: "Max score",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.max_score}</span>,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Assignments"
        description="Coursework across everything you can see. Grading happens on the assignment itself."
        actions={
          permissions.has("assignment.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New assignment
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="Course" className="w-72">
            {({ id }) => (
              <CoursePicker id={id} value={(courseId) || null} disabled={!permissions.has("course.read")} onValueChange={(next) => {
                  setCourseId((next ?? ""));
                  setPage({ limit, offset: 0 });
                }} placeholder="Every course" clearable />
            )}
          </Field>
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columnsKey="assignments"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No assignments here yet."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="assignments"
            />
          </>
        )}
      </Card>

      <CreateAssignmentDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
