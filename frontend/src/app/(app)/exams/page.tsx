"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import type { ExamResponse, ExamSummary, PageBatchSummary, PageCourseSummary, PageExamSummary } from "@/lib/api/types";
import { ExamTypeValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, fromLocalInputValue } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

const createSchema = z.object({
  title: z.string().trim().min(2, "Give the examination a title."),
  exam_type: z.enum(ExamTypeValues),
  scheduled_at: z.string().min(1, "Set the date and time."),
  duration_minutes: z.string().trim(),
  total_marks: z.string().min(1, "Set the total marks."),
  passing_marks: z.string().min(1, "Set the passing marks."),
  venue_or_link: z.string().trim(),
  instructions: z.string().trim(),
  course_id: z.string().trim(),
  batch_id: z.string().trim(),
});

type CreateValues = z.infer<typeof createSchema>;

function CreateExamDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const router = useRouter();
  const timeZone = useDisplayTimeZone();
  const { permissions } = useSession();
  const [banner, setBanner] = useState<string | null>(null);

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

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      title: "",
      exam_type: "MIDTERM",
      scheduled_at: "",
      duration_minutes: "",
      total_marks: "100",
      passing_marks: "40",
      venue_or_link: "",
      instructions: "",
      course_id: "",
      batch_id: "",
    },
  });

  const create = useApiMutation<ExamResponse, CreateValues>({
    mutationFn: (values) =>
      api.post<ExamResponse>("/exams", {
        body: {
          title: values.title,
          exam_type: values.exam_type,
          scheduled_at: fromLocalInputValue(values.scheduled_at, timeZone),
          duration_minutes: values.duration_minutes ? Number(values.duration_minutes) : null,
          total_marks: Number(values.total_marks),
          passing_marks: Number(values.passing_marks),
          venue_or_link: values.venue_or_link || null,
          instructions: values.instructions || null,
          course_id: values.course_id || null,
          batch_id: values.batch_id || null,
        },
      }),
    success: "Examination scheduled.",
    invalidate: [["exams"]],
    onSuccess: (exam) => {
      reset();
      onOpenChange(false);
      router.push(`/exams/${exam.public_id}`);
    },
    onError: (error) => {
      if (
        !applyFieldErrors<CreateValues>(error, setError, [
          "title",
          "scheduled_at",
          "total_marks",
          "passing_marks",
        ])
      ) {
        setBanner(error.message);
      }
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="Schedule an examination"
          description={`Times are entered in ${timeZone} and stored in UTC. The schedule can be published before any results exist.`}
        />
        <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Title" error={errors.title?.message} required>
            {({ id }) => <Input id={id} {...register("title")} />}
          </Field>
          <FormGrid columns={3}>
            <Field label="Type">
              {({ id }) => (
                <NativeSelect id={id} {...register("exam_type")}>
                  {ExamTypeValues.map((value) => (
                    <option key={value} value={value}>
                      {humanise(value)}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Scheduled" error={errors.scheduled_at?.message} required>
              {({ id }) => <Input id={id} type="datetime-local" {...register("scheduled_at")} />}
            </Field>
            <Field label="Duration (minutes)">
              {({ id }) => <Input id={id} type="number" min={1} {...register("duration_minutes")} />}
            </Field>
            <Field label="Total marks" error={errors.total_marks?.message} required>
              {({ id }) => <Input id={id} type="number" min={1} step="0.01" {...register("total_marks")} />}
            </Field>
            <Field label="Passing marks" error={errors.passing_marks?.message} required>
              {({ id }) => <Input id={id} type="number" min={0} step="0.01" {...register("passing_marks")} />}
            </Field>
            <Field label="Venue or link">
              {({ id }) => <Input id={id} {...register("venue_or_link")} />}
            </Field>
            <Field label="Course" hint="Optional: scope the exam to one course.">
              {({ id }) => (
                <NativeSelect id={id} {...register("course_id")}>
                  <option value="">Not scoped</option>
                  {(courses.data?.items ?? []).map((course) => (
                    <option key={course.public_id} value={course.public_id}>
                      {course.title}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Batch" hint="Optional: scope to one cohort.">
              {({ id }) => (
                <NativeSelect id={id} {...register("batch_id")}>
                  <option value="">Not scoped</option>
                  {(batches.data?.items ?? []).map((batch) => (
                    <option key={batch.public_id} value={batch.public_id}>
                      {batch.batch_code}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
          <Field label="Instructions">
            {({ id }) => <Textarea id={id} rows={3} {...register("instructions")} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Schedule
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function ExamsPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["exams", "list", limit, offset],
    queryFn: () => api.get<PageExamSummary>("/exams", { query: { limit, offset } }),
  });

  const columns: Column<ExamSummary>[] = [
    {
      key: "title",
      header: "Examination",
      cell: (row) => (
        <Link href={`/exams/${row.public_id}`} className="font-medium hover:underline">
          {row.title}
        </Link>
      ),
    },
    {
      key: "type",
      header: "Type",
      cell: (row) => <Badge tone="neutral">{humanise(row.exam_type)}</Badge>,
    },
    {
      key: "when",
      header: "Scheduled",
      cell: (row) => formatDateTime(row.scheduled_at, { timeZone }),
    },
    {
      key: "marks",
      header: "Marks",
      align: "right",
      secondary: true,
      cell: (row) => (
        <span className="tabular-nums">
          {row.passing_marks} / {row.total_marks}
        </span>
      ),
    },
    {
      key: "published",
      header: "Schedule",
      cell: (row) => (
        <Badge tone={row.is_published ? "success" : "neutral"}>
          {row.is_published ? "Published" : "Draft"}
        </Badge>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Examinations"
        description="Scheduled, invigilated assessments. Publishing the schedule and publishing the results are separate switches."
        actions={
          permissions.has("exam.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> Schedule examination
            </Button>
          ) : null
        }
      />

      <Card>
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
              emptyMessage="No examinations scheduled."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="examinations"
            />
          </>
        )}
      </Card>

      <CreateExamDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
