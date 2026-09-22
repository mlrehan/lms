"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Save, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  ExamResponse,
  ExamResultResponse,
  PageEnrollmentResponse,
  PageExamResultResponse,
  PageUserSummary,
} from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { FormActions, Input } from "@/components/ui/form";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

interface MarkRow {
  studentId: string;
  username: string;
  marks: string;
  grade: string;
  remarks: string;
}

function MarkSheet({ exam }: { exam: ExamResponse }) {
  const { permissions } = useSession();
  const canRecord = permissions.has("exam.update");

  const results = useQuery({
    queryKey: ["exam-results", exam.public_id],
    queryFn: () =>
      api.get<PageExamResultResponse>("/exam-results", {
        query: { exam_id: exam.public_id, limit: 500 },
      }),
  });

  // Candidates come from the batch when the exam is scoped to one. Without a
  // batch there is no roster to derive, so only students who already have a
  // result appear -- stated in the UI rather than silently showing nobody.
  const roster = useQuery({
    queryKey: ["enrollments", exam.batch_id, "confirmed"],
    queryFn: () =>
      api.get<PageEnrollmentResponse>("/enrollments", {
        query: { batch_id: exam.batch_id!, status: "CONFIRMED", limit: 500 },
      }),
    enabled: Boolean(exam.batch_id),
  });

  const resultItems = results.data?.items;
  const rosterItems = roster.data?.items;

  const initial = useMemo<MarkRow[]>(() => {
    const byStudent = new Map<string, ExamResultResponse>();
    for (const result of resultItems ?? []) byStudent.set(result.student_id, result);

    const rows: MarkRow[] = [];
    const seen = new Set<string>();

    for (const enrollment of rosterItems ?? []) {
      const existing = byStudent.get(enrollment.student_id);
      seen.add(enrollment.student_id);
      rows.push({
        studentId: enrollment.student_id,
        username: enrollment.student_username ?? enrollment.student_id,
        marks: existing?.marks_obtained ?? "",
        grade: existing?.grade ?? "",
        remarks: existing?.remarks ?? "",
      });
    }
    for (const result of resultItems ?? []) {
      if (seen.has(result.student_id)) continue;
      rows.push({
        studentId: result.student_id,
        username: result.student_username ?? result.student_id,
        marks: result.marks_obtained ?? "",
        grade: result.grade ?? "",
        remarks: result.remarks ?? "",
      });
    }
    return rows;
  }, [resultItems, rosterItems]);

  const [rows, setRows] = useState<MarkRow[] | null>(null);
  // Adjust during render rather than in an effect; see the register on the
  // session screen for why.
  const [seed, setSeed] = useState(initial);
  if (seed !== initial) {
    setSeed(initial);
    setRows(null);
  }
  const current = rows ?? initial;

  const record = useApiMutation<ExamResultResponse[], MarkRow[]>({
    mutationFn: (entries) =>
      api.put<ExamResultResponse[]>(`/exams/${segment(exam.public_id)}/results`, {
        body: {
          entries: entries
            // A blank mark means "not sat yet", not zero. Sending it as 0
            // would record a fail for someone who has not been marked.
            .filter((row) => row.marks.trim() !== "")
            .map((row) => ({
              student_id: row.studentId,
              marks_obtained: Number(row.marks),
              grade: row.grade || null,
              remarks: row.remarks || null,
            })),
        },
      }),
    success: (saved) => `Recorded ${saved.length} result(s).`,
    invalidate: [["exam-results"], ["exams"]],
    onSuccess: () => setRows(null),
  });

  if (results.isPending || (exam.batch_id && roster.isPending)) return <LoadingState rows={5} />;
  if (results.error) return <ErrorState error={results.error} onRetry={() => void results.refetch()} />;

  if (current.length === 0) {
    return (
      <CardBody>
        <p className="text-sm text-muted-foreground">
          {exam.batch_id
            ? "Nobody is confirmed on this exam's batch, so there is no mark sheet to fill in."
            : "This examination is not scoped to a batch, so the console cannot derive a candidate list. Results recorded through the API will appear here."}
        </p>
      </CardBody>
    );
  }

  function update(studentId: string, patch: Partial<MarkRow>) {
    setRows((previous) =>
      (previous ?? initial).map((row) => (row.studentId === studentId ? { ...row, ...patch } : row)),
    );
  }

  return (
    <>
      <CardBody>
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left">
                <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Candidate
                </th>
                <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Marks / {exam.total_marks}
                </th>
                <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Grade
                </th>
                <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Remarks
                </th>
              </tr>
            </thead>
            <tbody>
              {current.map((row) => {
                const numeric = row.marks === "" ? null : Number(row.marks);
                const passed =
                  numeric === null ? null : numeric >= Number(exam.passing_marks);
                return (
                  <tr key={row.studentId} className="border-b border-border-subtle/70 last:border-0">
                    <td className="px-3 py-2">
                      <Link href={`/users/${row.studentId}`} className="hover:underline">
                        {row.username}
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <Input
                          className="w-24"
                          type="number"
                          min={0}
                          step="0.01"
                          aria-label={`Marks for ${row.username}`}
                          disabled={!canRecord}
                          value={row.marks}
                          onChange={(event) => update(row.studentId, { marks: event.target.value })}
                        />
                        {passed === null ? null : passed ? (
                          <Badge tone="success">Pass</Badge>
                        ) : (
                          <Badge tone="danger">Fail</Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <Input
                        className="w-20"
                        aria-label={`Grade for ${row.username}`}
                        disabled={!canRecord}
                        value={row.grade}
                        onChange={(event) => update(row.studentId, { grade: event.target.value })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Input
                        aria-label={`Remarks for ${row.username}`}
                        disabled={!canRecord}
                        value={row.remarks}
                        onChange={(event) => update(row.studentId, { remarks: event.target.value })}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardBody>
      {canRecord ? (
        <div className="border-t border-border-subtle px-4 py-3">
          <FormActions>
            <Button variant="ghost" disabled={rows === null} onClick={() => setRows(null)}>
              Reset
            </Button>
            <Button loading={record.isPending} onClick={() => record.mutate(current)}>
              <Save /> Save marks
            </Button>
          </FormActions>
        </div>
      ) : null}
    </>
  );
}

function InvigilatorsTab({ exam }: { exam: ExamResponse }) {
  const { permissions } = useSession();
  const canEdit = permissions.has("exam.update");
  const canListUsers = permissions.has("user.read");

  const tutors = useQuery({
    queryKey: ["users", "tutors"],
    queryFn: () =>
      api.get<PageUserSummary>("/users", { query: { role: "TUTOR", limit: 200, status: "ACTIVE" } }),
    enabled: canListUsers,
    staleTime: 5 * 60_000,
  });

  const idByUsername = useMemo(() => {
    const map = new Map<string, string>();
    for (const person of tutors.data?.items ?? []) map.set(person.username, person.public_id);
    return map;
  }, [tutors.data]);

  const currentIds = (exam.invigilators ?? [])
    .map((username) => idByUsername.get(username))
    .filter((value): value is string => Boolean(value));

  const [selected, setSelected] = useState<string[] | null>(null);
  const selection = selected ?? currentIds;

  const save = useApiMutation<ExamResponse, string[]>({
    mutationFn: (invigilators) =>
      api.put<ExamResponse>(`/exams/${segment(exam.public_id)}/invigilators`, {
        body: { invigilators },
      }),
    success: "Invigilators updated.",
    invalidate: [["exams"]],
    onSuccess: () => setSelected(null),
  });

  return (
    <Card>
      <CardHeader title="Invigilators" description="Tutors responsible for supervising this examination." />
      <CardBody className="space-y-3">
        {!canListUsers ? (
          <p className="text-sm text-muted-foreground">
            Assigned: {(exam.invigilators ?? []).join(", ") || "nobody"}. Changing this needs{" "}
            <code className="font-mono text-xs">user.read</code>, because the API returns usernames
            but accepts identifiers.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {(tutors.data?.items ?? []).map((tutor) => {
                const checked = selection.includes(tutor.public_id);
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
                        setSelected(
                          event.target.checked
                            ? [...selection, tutor.public_id]
                            : selection.filter((id) => id !== tutor.public_id),
                        )
                      }
                    />
                    {tutor.full_name || tutor.username}
                  </label>
                );
              })}
            </div>
            {canEdit ? (
              <FormActions>
                <Button variant="ghost" disabled={selected === null} onClick={() => setSelected(null)}>
                  Reset
                </Button>
                <Button
                  loading={save.isPending}
                  disabled={selected === null}
                  onClick={() => save.mutate(selection)}
                >
                  Save invigilators
                </Button>
              </FormActions>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}

export default function ExamDetailPage({ params }: { params: Promise<{ examId: string }> }) {
  const { examId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["exams", "detail", examId],
    queryFn: () => api.get<ExamResponse>(`/exams/${segment(examId)}`),
  });

  const publishSchedule = useApiMutation<ExamResponse, boolean>({
    mutationFn: (isPublished) =>
      api.put<ExamResponse>(`/exams/${segment(examId)}/publish`, { body: { is_published: isPublished } }),
    success: "Schedule visibility updated.",
    invalidate: [["exams"]],
  });

  const publishResults = useApiMutation<Record<string, unknown>, boolean>({
    mutationFn: (isPublished) =>
      api.put<Record<string, unknown>>(`/exams/${segment(examId)}/results/publish`, {
        body: { is_published: isPublished },
      }),
    success: "Result visibility updated.",
    invalidate: [["exams"], ["exam-results"]],
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/exams/${segment(examId)}`),
    success: "Examination deleted.",
    invalidate: [["exams"]],
    onSuccess: () => router.push("/exams"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const allPublished =
    (data.result_count ?? 0) > 0 && data.published_result_count === data.result_count;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Examinations", href: "/exams" }, { label: data.title }]}
        title={data.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{humanise(data.exam_type)}</Badge>
            <Badge tone={data.is_published ? "success" : "neutral"}>
              {data.is_published ? "Schedule published" : "Schedule draft"}
            </Badge>
            <span className="text-xs">
              {formatDateTime(data.scheduled_at, { timeZone })}
              {data.duration_minutes ? ` · ${data.duration_minutes} min` : ""}
              {data.venue_or_link ? ` · ${data.venue_or_link}` : ""}
            </span>
            {data.course_title ? <Badge tone="info">{data.course_title}</Badge> : null}
            {data.batch_code ? <Badge tone="info">{data.batch_code}</Badge> : null}
          </span>
        }
        actions={
          permissions.has("exam.delete") ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label="Delete examination"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="text-danger" />
            </Button>
          ) : null
        }
      />

      <StatGrid>
        <Stat label="Total marks" value={data.total_marks} />
        <Stat label="Passing marks" value={data.passing_marks} />
        <Stat label="Results recorded" value={data.result_count} />
        <Stat
          label="Results published"
          value={data.published_result_count}
          tone={allPublished ? "success" : "default"}
        />
      </StatGrid>

      {permissions.has("exam.publish") ? (
        <Card>
          <CardHeader
            title="Visibility"
            description="Two independent switches: candidates can see when and where an exam is long before they can see what they scored."
          />
          <CardBody className="space-y-3">
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={data.is_published}
                disabled={publishSchedule.isPending}
                onCheckedChange={(checked) => publishSchedule.mutate(checked)}
              />
              Publish the schedule
            </label>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={allPublished}
                disabled={publishResults.isPending || (data.result_count ?? 0) === 0}
                onCheckedChange={(checked) => publishResults.mutate(checked)}
              />
              <span>
                Publish every recorded result
                <span className="block text-xs text-muted-foreground">
                  {(data.result_count ?? 0) === 0
                    ? "There are no results to publish yet."
                    : "Applies to all results for this examination at once."}
                </span>
              </span>
            </label>
          </CardBody>
        </Card>
      ) : null}

      {data.instructions ? (
        <Card>
          <CardHeader title="Instructions" />
          <CardBody>
            <p className="whitespace-pre-wrap break-words text-sm">{data.instructions}</p>
          </CardBody>
        </Card>
      ) : null}

      <Tabs defaultValue="results">
        <TabsList>
          <TabsTab value="results">Mark sheet</TabsTab>
          <TabsTab value="invigilators">Invigilators</TabsTab>
        </TabsList>
        <TabsPanel value="results">
          <Card>
            <CardHeader
              title="Mark sheet"
              description="Entered for the whole cohort in one save, like a register. A blank mark means 'not marked', not zero."
            />
            <MarkSheet exam={data} />
          </Card>
        </TabsPanel>
        <TabsPanel value="invigilators">
          <InvigilatorsTab exam={data} />
        </TabsPanel>
      </Tabs>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this examination?"
        description="Its results go with it."
        confirmPhrase={data.title}
        confirmLabel="Delete examination"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
