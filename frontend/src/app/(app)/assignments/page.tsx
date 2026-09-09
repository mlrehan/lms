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
import type {
  AssignmentResponse,
  AssignmentSummary,
  PageAssignmentSummary,
  PageCourseSummary,
} from "@/lib/api/types";
import { SubmissionTypeValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Switch } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative, fromLocalInputValue } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

const createSchema = z.object({
  course_id: z.string().min(1, "Choose the course this belongs to."),
  title: z.string().trim().min(2, "Give the assignment a title."),
  description: z.string().trim(),
  due_date: z.string().min(1, "Set a due date."),
  max_score: z.string().min(1, "Set the maximum score."),
  submission_type: z.enum(SubmissionTypeValues),
  allow_late_submissions: z.boolean(),
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

  const courses = useQuery({
    queryKey: ["courses", "picker"],
    queryFn: () => api.get<PageCourseSummary>("/courses", { query: { limit: 200 } }),
    enabled: open,
    staleTime: 60_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    setError,
    formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      course_id: "",
      title: "",
      description: "",
      due_date: "",
      max_score: "100",
      submission_type: "TEXT",
      allow_late_submissions: false,
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="New assignment"
          description={`The due date is entered in ${timeZone} and stored in UTC.`}
        />
        <form onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Course" error={errors.course_id?.message} required>
            {({ id }) => (
              <NativeSelect id={id} {...register("course_id")}>
                <option value="">Choose a course</option>
                {(courses.data?.items ?? []).map((course) => (
                  <option key={course.public_id} value={course.public_id}>
                    {course.title}
                  </option>
                ))}
              </NativeSelect>
            )}
          </Field>
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
                <NativeSelect id={id} {...register("submission_type")}>
                  {SubmissionTypeValues.map((value) => (
                    <option key={value} value={value}>
                      {humanise(value)}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
          <Field label="Description">
            {({ id }) => <Textarea id={id} {...register("description")} />}
          </Field>
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

  const courses = useQuery({
    queryKey: ["courses", "picker"],
    queryFn: () => api.get<PageCourseSummary>("/courses", { query: { limit: 200 } }),
    enabled: permissions.has("course.read"),
    staleTime: 60_000,
  });

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
        <Link href={`/assignments/${row.public_id}`} className="font-medium hover:underline">
          {row.title}
        </Link>
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
        <div className="flex flex-wrap items-end gap-3 border-b border-border p-3">
          <Field label="Course" className="w-72">
            {({ id }) => (
              <NativeSelect
                id={id}
                value={courseId}
                disabled={!permissions.has("course.read")}
                onChange={(event) => {
                  setCourseId(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Every course</option>
                {(courses.data?.items ?? []).map((course) => (
                  <option key={course.public_id} value={course.public_id}>
                    {course.title}
                  </option>
                ))}
              </NativeSelect>
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
