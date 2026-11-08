"use client";

/**
 * Choosing who an assessment is for beyond "a course, a batch, a class":
 * named students, and reusing one assessment for other batches or students.
 *
 * The student list comes from `/assessments/nameable-students`, which applies
 * the rule the write applies -- an active seat on the course, in a class the
 * caller teaches. So the list never offers somebody the server would refuse.
 */

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, segment } from "@/lib/api/client";
import type {
  AssessmentCopyRequest,
  AssessmentCopyResponse,
  CopyTargetInput,
  NameableStudent,
  RecipientsResponse,
  RevisionResponse,
} from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge, Checkbox, Switch } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { BatchPicker } from "@/components/domain/entity-pickers";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { fromLocalInputValue, formatDateTime } from "@/lib/format/datetime";
import { useDisplayTimeZone } from "@/lib/preferences";

export type AssessmentKind = "assignments" | "quizzes" | "exams";

export function useNameableStudents(courseId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["assessments", "nameable-students", courseId],
    queryFn: () =>
      api.get<NameableStudent[]>("/assessments/nameable-students", { query: { course_id: courseId! } }),
    enabled: enabled && Boolean(courseId),
    staleTime: 60_000,
  });
}

/** A searchable checklist of the students the caller may name on a course. */
export function StudentChecklist({
  courseId,
  value,
  onChange,
}: {
  courseId: string | null | undefined;
  value: string[];
  onChange: (ids: string[]) => void;
}): ReactNode {
  const [query, setQuery] = useState("");
  const students = useNameableStudents(courseId);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = students.data ?? [];
    return q
      ? all.filter((s) => s.name.toLowerCase().includes(q) || s.batch_codes.some((c) => c.toLowerCase().includes(q)))
      : all;
  }, [students.data, query]);

  if (!courseId) return <p className="text-xs text-muted-foreground">Choose a course first.</p>;
  if (students.isLoading) return <LoadingState label="Loading students" />;
  if (students.error) return <ErrorState error={students.error} />;
  if (!students.data?.length) {
    return (
      <p className="text-xs text-muted-foreground">
        No students on this course are in a class you teach.
      </p>
    );
  }

  const picked = new Set(value);
  const toggle = (id: string, on: boolean) =>
    onChange(on ? [...value, id] : value.filter((v) => v !== id));

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Input
          aria-label="Search students"
          placeholder="Search by name or batch"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Badge tone={value.length ? "info" : "neutral"}>{value.length} chosen</Badge>
      </div>
      <ul className="max-h-56 divide-y divide-border-subtle overflow-y-auto rounded-lg border border-border-subtle">
        {shown.map((s) => (
          <li key={s.public_id}>
            <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-surface-raised">
              <Checkbox
                checked={picked.has(s.public_id)}
                onCheckedChange={(on) => toggle(s.public_id, Boolean(on))}
                aria-label={s.name}
              />
              <span className="flex-1">{s.name}</span>
              <span className="text-xs text-muted-foreground">{s.batch_codes.join(", ")}</span>
            </label>
          </li>
        ))}
        {shown.length === 0 ? (
          <li className="px-3 py-2 text-sm text-muted-foreground">Nobody matches “{query}”.</li>
        ) : null}
      </ul>
    </div>
  );
}

const KIND_NOUN: Record<AssessmentKind, string> = {
  assignments: "assignment",
  quizzes: "quiz",
  exams: "examination",
};

/** "Reuse for other batches or students": separate copies, drafts by default. */
export function ReuseAssessmentDialog({
  kind,
  assessmentId,
  courseId,
  title,
  open,
  onOpenChange,
}: {
  kind: AssessmentKind;
  assessmentId: string;
  courseId: string | null | undefined;
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}): ReactNode {
  const timeZone = useDisplayTimeZone();
  const [batches, setBatches] = useState<{ id: string; code: string }[]>([]);
  const [students, setStudents] = useState<string[]>([]);
  const [when, setWhen] = useState("");
  const [publish, setPublish] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const noun = KIND_NOUN[kind];

  const copy = useApiMutation<AssessmentCopyResponse, AssessmentCopyRequest>({
    mutationFn: (body) =>
      api.post<AssessmentCopyResponse>(`/assessments/${kind}/${segment(assessmentId)}/copies`, { body }),
    success: (data) => `Made ${data.copies.length} ${data.copies.length === 1 ? "copy" : "copies"}.`,
    invalidate: [[kind]],
    onSuccess: () => {
      setBatches([]);
      setStudents([]);
      setWhen("");
      setPublish(false);
      setBanner(null);
      onOpenChange(false);
    },
    onError: (error) => setBanner(error.message),
  });

  const targets: CopyTargetInput[] = [
    ...batches.map((b) => ({ scope: "BATCH" as const, batch_id: b.id })),
    ...(students.length ? [{ scope: "STUDENTS" as const, student_ids: students }] : []),
  ];

  const submit = () => {
    if (!targets.length) {
      setBanner("Choose at least one batch or student.");
      return;
    }
    const iso = when ? fromLocalInputValue(when, timeZone) : null;
    copy.mutate({
      targets,
      publish,
      ...(kind === "assignments" ? { due_date: iso } : {}),
      ...(kind === "exams" ? { scheduled_at: iso } : {}),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title={`Reuse this ${noun}`}
          description={`Each batch, and the group of students, gets its own copy of “${title}” with its own deadline, submissions and marks. The original is not changed.`}
        />
        <form
          method="post"
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Add a batch">
            {({ id }) => (
              <BatchPicker
                id={id}
                value={null}
                placeholder="Search your batches"
                onValueChange={(batchId, batch) => {
                  if (batchId && !batches.some((b) => b.id === batchId)) {
                    setBatches([...batches, { id: batchId, code: batch?.batch_code ?? batchId }]);
                  }
                }}
              />
            )}
          </Field>
          {batches.length ? (
            <div className="flex flex-wrap gap-2">
              {batches.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  className="rounded-full border border-border-subtle px-2 py-0.5 text-xs hover:border-danger hover:text-danger"
                  onClick={() => setBatches(batches.filter((x) => x.id !== b.id))}
                  aria-label={`Remove ${b.code}`}
                >
                  {b.code} ×
                </button>
              ))}
            </div>
          ) : null}
          <Field label="And/or chosen students (one shared copy)">
            {() => <StudentChecklist courseId={courseId} value={students} onChange={setStudents} />}
          </Field>
          {kind !== "quizzes" ? (
            <Field label={kind === "assignments" ? "New deadline (optional)" : "New date and time (optional)"}>
              {({ id }) => (
                <Input id={id} type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
              )}
            </Field>
          ) : null}
          <label className="flex items-center gap-3 text-sm">
            <Switch checked={publish} onCheckedChange={setPublish} aria-label="Publish the copies" />
            {publish
              ? "Publish now — each copy's students are notified."
              : "Save as drafts — nobody is notified until you publish."}
          </label>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={copy.isPending || !targets.length}>
              {copy.isPending ? "Copying…" : `Make ${targets.length || ""} ${targets.length === 1 ? "copy" : "copies"}`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The named students of a STUDENTS-scoped assessment, editable by its author. */
export function RecipientsPanel({
  kind,
  assessmentId,
  courseId,
  canManage,
}: {
  kind: AssessmentKind;
  assessmentId: string;
  courseId: string | null | undefined;
  canManage: boolean;
}): ReactNode {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const key = ["assessments", kind, assessmentId, "recipients"];
  const recipients = useQuery({
    queryKey: key,
    queryFn: () => api.get<RecipientsResponse>(`/assessments/${kind}/${segment(assessmentId)}/recipients`),
  });
  const save = useApiMutation<RecipientsResponse, string[]>({
    mutationFn: (ids) =>
      api.put<RecipientsResponse>(`/assessments/${kind}/${segment(assessmentId)}/recipients`, {
        body: { student_ids: ids },
      }),
    success: "Students updated. Anyone newly added has been told.",
    invalidate: [key, ["assessments", kind, assessmentId, "revisions"]],
    onSuccess: () => setEditing(false),
  });

  if (recipients.isLoading) return <LoadingState label="Loading students" />;
  if (recipients.error) return <ErrorState error={recipients.error} />;
  const list = recipients.data?.recipients ?? [];

  if (editing) {
    return (
      <div className="space-y-3">
        <StudentChecklist courseId={courseId} value={draft} onChange={setDraft} />
        <div className="flex gap-2">
          <Button size="sm" disabled={!draft.length || save.isPending} onClick={() => save.mutate(draft)}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Removing someone keeps anything they already handed in.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {list.map((r) => (
          <Badge key={r.public_id} tone="neutral">
            {r.name}
          </Badge>
        ))}
      </div>
      {canManage ? (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setDraft(list.map((r) => r.public_id));
            setEditing(true);
          }}
        >
          Change students
        </Button>
      ) : null}
    </div>
  );
}

const FIELD_LABEL: Record<string, string> = {
  due_date: "Deadline",
  scheduled_at: "Date and time",
  max_score: "Marks",
  total_marks: "Marks",
  description: "Brief",
  instructions: "Instructions",
  recipients: "Students",
};

/** What changed after publication, newest first. */
export function RevisionHistory({ kind, assessmentId }: { kind: AssessmentKind; assessmentId: string }): ReactNode {
  const timeZone = useDisplayTimeZone();
  const revisions = useQuery({
    queryKey: ["assessments", kind, assessmentId, "revisions"],
    queryFn: () => api.get<RevisionResponse[]>(`/assessments/${kind}/${segment(assessmentId)}/revisions`),
  });
  if (revisions.isLoading) return <LoadingState label="Loading history" />;
  if (revisions.error) return <ErrorState error={revisions.error} />;
  const rows = revisions.data ?? [];
  if (!rows.length) {
    return <p className="text-sm text-muted-foreground">No changes since it was published.</p>;
  }
  const show = (v: unknown): string => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return formatDateTime(v, { timeZone });
    const text = typeof v === "string" ? v.replace(/<[^>]+>/g, " ") : JSON.stringify(v);
    return text.length > 80 ? `${text.slice(0, 77)}…` : text;
  };
  return (
    <ol className="space-y-3">
      {rows.map((r) => (
        <li key={r.revision_no} className="rounded-lg border border-border-subtle p-3 text-sm">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="font-medium">Revision {r.revision_no}</span>
            <span className="text-muted-foreground">
              {formatDateTime(r.changed_at, { timeZone })}
              {r.changed_by ? ` · ${r.changed_by}` : ""}
            </span>
            {r.material ? <Badge tone="warning">Students told ({r.notified})</Badge> : null}
          </div>
          <ul className="space-y-0.5">
            {Object.entries(r.changes).map(([field, change]) => (
              <li key={field}>
                <span className="text-muted-foreground">{FIELD_LABEL[field] ?? field.replace(/_/g, " ")}: </span>
                {field === "recipients"
                  ? `${String(change.from)} → ${String(change.to)} students`
                  : `${show(change.from)} → ${show(change.to)}`}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}
