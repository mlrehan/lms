"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { BatchResponse, CourseSummary, PageBatchSummary } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, Textarea } from "@/components/ui/form";
import { humanise } from "@/lib/utils";
import { CoursePicker } from "@/components/domain/entity-pickers";

const schema = z.object({
  course_id: z.string().min(1, "Choose the course this batch belongs to."),
  batch_code: z
    .string()
    .trim()
    .min(2, "Give the batch a code of at least two characters.")
    .regex(/^[A-Za-z0-9._-]+$/, "Use letters, numbers, dots, dashes and underscores only."),
  capacity: z.string().trim(),
  duration_hours: z.string().trim(),
  number_of_sessions: z.string().trim(),
  start_date: z.string().trim(),
  end_date: z.string().trim(),
  notes: z.string().trim(),
});
type Values = z.infer<typeof schema>;

/** The first unused `CODE-A`, `CODE-B` ... for a course, so a sensible code is offered without being imposed. */
export function suggestBatchCode(courseCode: string | null | undefined, taken: readonly string[]): string {
  const base = (courseCode ?? "").trim().replace(/[^A-Za-z0-9._-]/g, "");
  if (!base) return "";
  const used = new Set(taken.map((code) => code.toUpperCase()));
  for (let i = 0; i < 26; i += 1) {
    const candidate = `${base}-${String.fromCharCode(65 + i)}`;
    if (!used.has(candidate.toUpperCase())) return candidate;
  }
  return `${base}-${taken.length + 1}`;
}

/**
 * Create a batch from the Batches page: choose the course, and the rest is the same form the course page has.
 * It calls the endpoint the course page uses (`POST /courses/{id}/batches`), so permissions and validation are shared.
 */
export function NewBatchDialog({ onCreated }: { onCreated?: (batch: BatchResponse) => void }) {
  const [open, setOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { course_id: "", batch_code: "", capacity: "", duration_hours: "", number_of_sessions: "", start_date: "", end_date: "", notes: "" },
  });
  const courseId = watch("course_id");

  /*
   * The chosen course is held here rather than found in a fetched page.
   * `CoursePicker` searches the whole catalogue server-side and hands back the
   * row it selected, so the previous `limit: 100` fetch -- which both capped
   * the catalogue at 100 and was the only place a chosen course could be
   * resolved from -- is gone.
   */
  const [course, setCourse] = useState<CourseSummary | null>(null);

  async function chooseCourse(id: string, chosen: CourseSummary | null) {
    setValue("course_id", id, { shouldValidate: true });
    setCourse(chosen);
    if (!chosen) return;
    if (chosen.duration_hours != null) setValue("duration_hours", String(chosen.duration_hours));
    try {
      const existing = await api.get<PageBatchSummary>(`/courses/${segment(id)}/batches`, { query: { limit: 100 } });
      setValue("batch_code", suggestBatchCode(chosen.code, existing.items.map((b) => b.batch_code)), { shouldValidate: true });
    } catch {
      setValue("batch_code", suggestBatchCode(chosen.code, []));
    }
  }

  const create = useApiMutation<BatchResponse, Values>({
    mutationFn: (v) =>
      api.post<BatchResponse>(`/courses/${segment(v.course_id)}/batches`, {
        body: {
          batch_code: v.batch_code,
          capacity: v.capacity ? Number(v.capacity) : null,
          duration_hours: v.duration_hours ? Number(v.duration_hours) : null,
          number_of_sessions: v.number_of_sessions ? Number(v.number_of_sessions) : null,
          start_date: v.start_date || null,
          end_date: v.end_date || null,
          notes: v.notes || null,
        },
      }),
    success: (batch) => `Created batch ${batch.batch_code}. Schedule its sessions on the calendar below.`,
    invalidate: [["batches"], ["courses"]],
    onSuccess: (batch) => {
      reset();
      setBanner(null);
      setOpen(false);
      onCreated?.(batch);
    },
    onError: (error) => {
      if (!applyFieldErrors<Values>(error, setError, ["batch_code", "start_date", "end_date", "capacity"])) setBanner(error.message);
    },
  });

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <Plus /> New batch
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="md">
          <DialogHeader title="New batch" description="A cohort of one course, with its own schedule, capacity and register." />
          <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
            {banner ? (
              <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                {banner}
              </div>
            ) : null}
            <Field label="Course" error={errors.course_id?.message} required>
              {({ id }) => (
                <CoursePicker
                  id={id}
                  value={courseId || null}
                  placeholder="Search courses"
                  onValueChange={(next, chosen) => void chooseCourse(next ?? "", chosen)}
                />
              )}
            </Field>
            {course && course.status !== "PUBLISHED" && course.status !== "RUNNING" ? (
              <p className="text-xs text-warning">
                This course is {humanise(course.status).toLowerCase()}, so students cannot be enrolled in the batch until it is published.
              </p>
            ) : null}
            <Field label="Batch code" error={errors.batch_code?.message} required hint="Unique across the institution. Suggested from the course code.">
              {({ id }) => <Input id={id} placeholder="MATH101-A" {...register("batch_code")} />}
            </Field>
            <FormGrid>
              <Field label="Capacity" hint="Leave blank for unlimited." error={errors.capacity?.message}>
                {({ id }) => <Input id={id} type="number" min={1} {...register("capacity")} />}
              </Field>
              <Field label="Duration (hours)">{({ id }) => <Input id={id} type="number" min={0} {...register("duration_hours")} />}</Field>
              <Field label="Planned sessions">{({ id }) => <Input id={id} type="number" min={0} {...register("number_of_sessions")} />}</Field>
              <span aria-hidden className="hidden sm:block" />
              <Field label="Start date" error={errors.start_date?.message}>
                {({ id }) => <Input id={id} type="date" {...register("start_date")} />}
              </Field>
              <Field label="End date" error={errors.end_date?.message}>
                {({ id }) => <Input id={id} type="date" {...register("end_date")} />}
              </Field>
            </FormGrid>
            <Field label="Notes">{({ id }) => <Textarea id={id} rows={2} {...register("notes")} />}</Field>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" loading={create.isPending}>
                Create batch
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
