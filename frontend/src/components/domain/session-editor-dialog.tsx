"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, segment } from "@/lib/api/client";
import type { BatchSummary, CalendarSession } from "@/lib/api/types";
import { PlatformsValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input } from "@/components/ui/form";
import { FormSelect } from "@/components/ui/form-controls";
import { UserPicker } from "@/components/domain/user-picker";
import { fromLocalInputValue, toLocalInputValue } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

const formSchema = z.object({
  batch_id: z.string().min(1, "Choose the batch."),
  tutor_id: z.string().min(1, "Choose the tutor taking this session."),
  start: z.string().min(1, "Set a start time."),
  end: z.string(),
  platform: z.enum(PlatformsValues),
  classroom: z.string().trim(),
  meeting_link: z.string().trim(),
});
type FormValues = z.infer<typeof formSchema>;

/** What the editor opens with: an existing session to edit, or a blank one at a chosen time. */
export interface EditorState {
  session: CalendarSession | null;
  /** `YYYY-MM-DDTHH:mm` wall-clock in the display time zone. */
  start: string;
  end: string;
}

export function SessionEditorDialog({
  state,
  batches,
  selected,
  timeZone,
  onClose,
  onSaved,
}: {
  state: EditorState;
  batches: readonly BatchSummary[];
  selected: BatchSummary | null;
  timeZone: string;
  onClose: () => void;
  onSaved: (batchId: string) => void;
}) {
  const editing = state.session;
  const [banner, setBanner] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    control,
    setValue,
    setError,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: editing
      ? {
          batch_id: editing.batch_id,
          tutor_id: editing.tutor_id,
          start: toLocalInputValue(editing.session_start_time, timeZone),
          end: toLocalInputValue(editing.session_end_time, timeZone),
          platform: editing.platform,
          classroom: editing.classroom ?? "",
          meeting_link: editing.meeting_link ?? "",
        }
      : {
          batch_id: selected?.public_id ?? "",
          tutor_id: "",
          start: state.start,
          end: state.end,
          platform: "Zoom",
          classroom: "",
          meeting_link: "",
        },
  });
  const tutorId = watch("tutor_id");

  const save = useApiMutation<unknown, FormValues>({
    mutationFn: (v) => {
      const body = {
        tutor_id: v.tutor_id,
        session_start_time: fromLocalInputValue(v.start, timeZone),
        session_end_time: v.end ? fromLocalInputValue(v.end, timeZone) : null,
        platform: v.platform,
        classroom: v.classroom || null,
        meeting_link: v.meeting_link || null,
      };
      return editing
        ? api.patch<unknown>(`/sessions/${segment(editing.public_id)}`, { body })
        : api.post<unknown>(`/batches/${segment(v.batch_id)}/sessions`, { body: { ...body, duration_minutes: v.end ? undefined : 60 } });
    },
    success: editing ? "Session updated." : "Session scheduled.",
    onSuccess: (_data, v) => onSaved(v.batch_id),
    onError: (error) => {
      if (!applyFieldErrors<FormValues>(error, setError, [])) setBanner(error.message);
    },
  });

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent size="md">
        <DialogHeader
          title={editing ? "Edit session" : "Schedule a session"}
          description={`Times are entered in ${timeZone} and stored in UTC. Google Calendar is updated afterwards.`}
        />
        <form method="post" onSubmit={handleSubmit((values) => save.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Batch" error={errors.batch_id?.message} required>
            {({ id }) => (
              <FormSelect
                id={id}
                control={control}
                name="batch_id"
                disabled={Boolean(editing)}
                placeholder="Choose a batch"
                clearable
                /*
                 * The current batch is appended when the loaded page does not
                 * contain it, so an existing session can always name its own
                 * batch rather than showing a blank field.
                 */
                options={[
                  ...batches.map((b) => ({ value: b.public_id, label: b.batch_code })),
                  ...(!editing && selected && !batches.some((b) => b.public_id === selected.public_id)
                    ? [{ value: selected.public_id, label: selected.batch_code }]
                    : []),
                  ...(editing && !batches.some((b) => b.public_id === editing.batch_id)
                    ? [{ value: editing.batch_id, label: editing.batch_code }]
                    : []),
                ]}
              />
            )}
          </Field>
          <Field label="Tutor" error={errors.tutor_id?.message} required>
            {({ id }) => (
              <UserPicker id={id} role="TUTOR" value={tutorId || null} onChange={(next) => setValue("tutor_id", next ?? "", { shouldValidate: true })} />
            )}
          </Field>
          <FormGrid>
            <Field label="Starts" error={errors.start?.message} required>
              {({ id }) => <Input id={id} type="datetime-local" {...register("start")} />}
            </Field>
            <Field label="Ends" error={errors.end?.message}>
              {({ id }) => <Input id={id} type="datetime-local" {...register("end")} />}
            </Field>
            <Field label="Platform">
              {({ id }) => (
                <FormSelect id={id}  control={control} name="platform" options={PlatformsValues.map((p) => ({ value: p, label: humanise(p) }))} />
              )}
            </Field>
            <Field label="Classroom">{({ id }) => <Input id={id} {...register("classroom")} />}</Field>
          </FormGrid>
          <Field label="Meeting link" error={errors.meeting_link?.message}>
            {({ id }) => <Input id={id} {...register("meeting_link")} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              {editing ? "Save changes" : "Schedule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
