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
import type { PageCourseSummary, PageQuizSummary, QuizResponse, QuizSummary } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { FormSelect } from "@/components/ui/form-controls";
import { Badge, Card, Switch } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";

const createSchema = z.object({
  course_id: z.string().min(1, "Choose the course this belongs to."),
  title: z.string().trim().min(2, "Give the quiz a title."),
  instructions: z.string().trim(),
  duration_minutes: z.string().trim(),
  attempts_allowed: z.string().trim(),
  passing_score: z.string().min(1, "Set a passing score."),
  shuffle_questions: z.boolean(),
  is_auto_graded: z.boolean(),
});

type CreateValues = z.infer<typeof createSchema>;

function CreateQuizDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const router = useRouter();
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
      title: "",
      instructions: "",
      duration_minutes: "",
      attempts_allowed: "1",
      passing_score: "50",
      shuffle_questions: false,
      is_auto_graded: true,
    },
  });

  const create = useApiMutation<QuizResponse, CreateValues>({
    mutationFn: (values) =>
      api.post<QuizResponse>(`/courses/${segment(values.course_id)}/quizzes`, {
        body: {
          title: values.title,
          instructions: values.instructions || null,
          duration_minutes: values.duration_minutes ? Number(values.duration_minutes) : null,
          attempts_allowed: values.attempts_allowed ? Number(values.attempts_allowed) : 1,
          passing_score: Number(values.passing_score),
          shuffle_questions: values.shuffle_questions,
          is_auto_graded: values.is_auto_graded,
        },
      }),
    success: "Quiz created. Add questions before publishing it.",
    invalidate: [["quizzes"]],
    onSuccess: (quiz) => {
      reset();
      onOpenChange(false);
      router.push(`/quizzes/${quiz.public_id}`);
    },
    onError: (error) => {
      if (!applyFieldErrors<CreateValues>(error, setError, ["title", "passing_score"])) {
        setBanner(error.message);
      }
    },
  });

  const shuffle = watch("shuffle_questions");
  const autoGrade = watch("is_auto_graded");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="New quiz"
          description="A quiz starts unpublished. Students cannot see or attempt it until you publish it."
        />
        <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Course" error={errors.course_id?.message} required>
            {({ id }) => (
              <FormSelect id={id}  control={control} name="course_id" placeholder="Choose a course" clearable options={(courses.data?.items ?? []).map((course) => ({ value: course.public_id, label: course.title }))} />
            )}
          </Field>
          <Field label="Title" error={errors.title?.message} required>
            {({ id }) => <Input id={id} {...register("title")} />}
          </Field>
          <FormGrid columns={3}>
            <Field label="Duration (minutes)" hint="Blank means untimed.">
              {({ id }) => <Input id={id} type="number" min={1} {...register("duration_minutes")} />}
            </Field>
            <Field label="Attempts allowed">
              {({ id }) => <Input id={id} type="number" min={1} {...register("attempts_allowed")} />}
            </Field>
            <Field label="Passing score" error={errors.passing_score?.message} required>
              {({ id }) => <Input id={id} type="number" min={0} step="0.01" {...register("passing_score")} />}
            </Field>
          </FormGrid>
          <Field label="Instructions">
            {({ id }) => <Textarea id={id} rows={3} {...register("instructions")} />}
          </Field>
          <div className="space-y-2">
            <label className="flex items-center gap-3 text-sm">
              <Switch checked={shuffle} onCheckedChange={(v) => setValue("shuffle_questions", v)} />
              Shuffle question order for each attempt
            </label>
            <label className="flex items-center gap-3 text-sm">
              <Switch checked={autoGrade} onCheckedChange={(v) => setValue("is_auto_graded", v)} />
              <span>
                Grade automatically where possible
                <span className="block text-xs text-muted-foreground">
                  Short-answer and essay questions always need a person; this decides the rest.
                </span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create quiz
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function QuizzesPage() {
  const { permissions } = useSession();
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
    queryKey: ["quizzes", "list", courseId, limit, offset],
    queryFn: () =>
      api.get<PageQuizSummary>("/quizzes", {
        query: { course_id: courseId || undefined, limit, offset },
      }),
  });

  const columns: Column<QuizSummary>[] = [
    {
      key: "title",
      header: "Quiz",
      cell: (row) => (
        <Link href={`/quizzes/${row.public_id}`} className="font-medium hover:underline">
          {row.title}
        </Link>
      ),
    },
    {
      key: "published",
      header: "State",
      cell: (row) => (
        <Badge tone={row.is_published ? "success" : "neutral"}>
          {row.is_published ? "Published" : "Draft"}
        </Badge>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      secondary: true,
      cell: (row) => (row.duration_minutes ? `${row.duration_minutes} min` : "Untimed"),
    },
    {
      key: "attempts",
      header: "Attempts",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.attempts_allowed}</span>,
    },
    {
      key: "pass",
      header: "Pass mark",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.passing_score}</span>,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Quizzes"
        description="Auto-graded question banks. Examinations, which are scheduled and invigilated, live under Examinations."
        actions={
          permissions.has("quiz.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New quiz
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="Course" className="w-72">
            {({ id }) => (
              <Select
                id={id}
                value={(courseId) || null}
                disabled={!permissions.has("course.read")}
                onValueChange={(next) => {
                  setCourseId((next ?? ""));
                  setPage({ limit, offset: 0 });
                }}
               placeholder="Every course" clearable options={(courses.data?.items ?? []).map((course) => ({ value: course.public_id, label: course.title }))} />
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
              emptyMessage="No quizzes here yet."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="quizzes"
            />
          </>
        )}
      </Card>

      <CreateQuizDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
