"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  GradeBandResponse,
  GradeBookEntryResponse,
  GradeBookSummaryResponse,
  PageBatchSummary,
  PageGradeBookEntryResponse,
  SyncResultResponse,
} from "@/lib/api/types";
import { GradeComponentTypeValues } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
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
import { Field, FormActions, FormGrid, Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { Stat, StatGrid } from "@/components/ui/stat";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function GradeBands() {
  const { permissions } = useSession();
  const canEdit = permissions.has("grade.update");
  const [draft, setDraft] = useState({ min_score: "", max_score: "", letter_grade: "", gpa_points: "" });
  const [removing, setRemoving] = useState<GradeBandResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["grade-bands"],
    queryFn: () => api.get<GradeBandResponse[]>("/grade-bands"),
  });

  const create = useApiMutation<GradeBandResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<GradeBandResponse>("/grade-bands", {
        body: {
          min_score: Number(values.min_score),
          max_score: Number(values.max_score),
          letter_grade: values.letter_grade,
          gpa_points: Number(values.gpa_points),
        },
      }),
    success: "Band added.",
    invalidate: [["grade-bands"]],
    onSuccess: () => setDraft({ min_score: "", max_score: "", letter_grade: "", gpa_points: "" }),
  });

  const remove = useApiMutation<void, number>({
    mutationFn: (bandId) => api.delete<void>(`/grade-bands/${segment(bandId)}`),
    success: "Band removed.",
    invalidate: [["grade-bands"]],
    onSuccess: () => setRemoving(null),
  });

  return (
    <Card>
      <CardHeader
        title="Grading scale"
        description="The institution-wide bands that turn a percentage into a letter and GPA points. Transcripts are computed against these."
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={[
              {
                key: "range",
                header: "Range",
                cell: (band: GradeBandResponse) => (
                  <span className="tabular-nums">
                    {band.min_score} – {band.max_score}
                  </span>
                ),
              },
              {
                key: "letter",
                header: "Grade",
                cell: (band: GradeBandResponse) => <Badge tone="primary">{band.letter_grade}</Badge>,
              },
              {
                key: "gpa",
                header: "GPA points",
                align: "right",
                cell: (band: GradeBandResponse) => (
                  <span className="tabular-nums">{band.gpa_points}</span>
                ),
              },
              {
                key: "actions",
                header: <span className="sr-only">Actions</span>,
                align: "right",
                cell: (band: GradeBandResponse) =>
                  canEdit ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove band ${band.letter_grade}`}
                      onClick={() => setRemoving(band)}
                    >
                      <Trash2 className="text-danger" />
                    </Button>
                  ) : null,
              },
            ]}
            rows={data ?? []}
            rowKey={(band) => String(band.id)}
            emptyMessage="No bands defined. Without them a transcript has no letter grade or GPA to report."
          />

          {canEdit ? (
            <CardBody className="border-t border-border-subtle">
              <FormGrid columns={3}>
                <Field label="Minimum score">
                  {({ id }) => (
                    <Input
                      id={id}
                      type="number"
                      step="0.01"
                      value={draft.min_score}
                      onChange={(event) => setDraft({ ...draft, min_score: event.target.value })}
                    />
                  )}
                </Field>
                <Field label="Maximum score">
                  {({ id }) => (
                    <Input
                      id={id}
                      type="number"
                      step="0.01"
                      value={draft.max_score}
                      onChange={(event) => setDraft({ ...draft, max_score: event.target.value })}
                    />
                  )}
                </Field>
                <Field label="Letter">
                  {({ id }) => (
                    <Input
                      id={id}
                      value={draft.letter_grade}
                      onChange={(event) => setDraft({ ...draft, letter_grade: event.target.value })}
                    />
                  )}
                </Field>
                <Field label="GPA points">
                  {({ id }) => (
                    <Input
                      id={id}
                      type="number"
                      step="0.01"
                      value={draft.gpa_points}
                      onChange={(event) => setDraft({ ...draft, gpa_points: event.target.value })}
                    />
                  )}
                </Field>
              </FormGrid>
              <FormActions>
                <Button
                  loading={create.isPending}
                  disabled={
                    draft.min_score === "" ||
                    draft.max_score === "" ||
                    draft.letter_grade === "" ||
                    draft.gpa_points === ""
                  }
                  onClick={() => create.mutate(draft)}
                >
                  <Plus /> Add band
                </Button>
              </FormActions>
            </CardBody>
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Remove band ${removing?.letter_grade ?? ""}?`}
        description="Transcripts generated afterwards will use the remaining bands."
        confirmLabel="Remove band"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
        }}
      />
    </Card>
  );
}

function EntriesTab({ batchId }: { batchId: string }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(25);
  const [componentType, setComponentType] = useState("");
  const [studentId, setStudentId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<GradeBookEntryResponse | null>(null);
  const [draft, setDraft] = useState({
    student_id: "",
    component_type: "ASSIGNMENT",
    score: "",
    max_score: "100",
    weight: "1",
  });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["gradebook", "entries", batchId, componentType, studentId, limit, offset],
    queryFn: () =>
      api.get<PageGradeBookEntryResponse>("/gradebook", {
        query: {
          batch_id: batchId || undefined,
          component_type: componentType || undefined,
          student_id: studentId || undefined,
          limit,
          offset,
        },
      }),
  });

  const create = useApiMutation<GradeBookEntryResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<GradeBookEntryResponse>(`/batches/${segment(batchId)}/gradebook/entries`, {
        body: {
          student_id: values.student_id,
          component_type: values.component_type,
          score: Number(values.score),
          max_score: Number(values.max_score),
          weight: Number(values.weight),
        },
      }),
    success: "Entry recorded.",
    invalidate: [["gradebook"]],
    onSuccess: () => {
      setDraft({ ...draft, student_id: "", score: "" });
      setAddOpen(false);
    },
  });

  const sync = useApiMutation<SyncResultResponse, void>({
    mutationFn: () => api.post<SyncResultResponse>(`/batches/${segment(batchId)}/gradebook/sync`),
    success: (result) =>
      `Synced: ${result.created ?? 0} created, ${result.updated ?? 0} updated, ${
        result.unchanged ?? 0
      } unchanged${result.skipped_ungraded ? `, ${result.skipped_ungraded} still unmarked` : ""}.`,
    invalidate: [["gradebook"]],
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (entryId) => api.delete<void>(`/gradebook/${segment(entryId)}`),
    success: "Entry removed.",
    invalidate: [["gradebook"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<GradeBookEntryResponse>[] = [
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <Link href={`/users/${row.student_id}`} className="font-medium hover:underline">
          {row.student_username ?? row.student_id}
        </Link>
      ),
    },
    {
      key: "component",
      header: "Component",
      cell: (row) => <Badge tone="neutral">{humanise(row.component_type)}</Badge>,
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      cell: (row) => (
        <span className="tabular-nums">
          {row.score} / {row.max_score}
          {row.percentage ? (
            <span className="ml-2 text-xs text-muted-foreground">{row.percentage}%</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "weight",
      header: "Weight",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.weight}</span>,
    },
    {
      key: "recorded",
      header: "Recorded",
      secondary: true,
      cell: (row) => formatDateTime(row.recorded_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("grade.update") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Remove entry"
            onClick={() => setRemoving(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Entries"
        description="One row per contribution: assignment, quiz, attendance, practical, final exam."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {permissions.has("grade.update") && batchId ? (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={sync.isPending}
                  onClick={() => sync.mutate()}
                >
                  <RefreshCw /> Sync from marks
                </Button>
                <Button size="sm" onClick={() => setAddOpen(true)}>
                  <Plus /> Add entry
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
        <Field label="Component" className="w-52">
          {({ id }) => (
            <Select
              id={id}
              value={(componentType) || null}
              onValueChange={(next) => {
                setComponentType((next ?? ""));
                setPage({ limit, offset: 0 });
              }}
             placeholder="Every component" clearable options={optionsFromValues(GradeComponentTypeValues, humanise)} />
          )}
        </Field>
        <Field label="Student" className="w-72">
          {({ id }) => (
            <UserPicker
              id={id}
              role="STUDENT"
              value={studentId}
              onChange={(next) => {
                setStudentId(next);
                setPage({ limit, offset: 0 });
              }}
            />
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
            emptyMessage={
              batchId
                ? "Nothing recorded for this batch yet. 'Sync from marks' pulls in graded submissions and attempts."
                : "Choose a batch to see its grade book."
            }
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="entries"
          />
        </>
      )}

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Add a grade book entry"
            description="For marks that do not come from a submission or an attempt -- a practical, a participation score."
          />
          <div className="space-y-4">
            <Field label="Student" required>
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="STUDENT"
                  value={draft.student_id || null}
                  onChange={(next) => setDraft({ ...draft, student_id: next ?? "" })}
                />
              )}
            </Field>
            <FormGrid>
              <Field label="Component">
                {({ id }) => (
                  <Select
                    id={id}
                    value={draft.component_type}
                    onValueChange={(next) => setDraft({ ...draft, component_type: (next ?? "") })}
                   options={optionsFromValues(GradeComponentTypeValues, humanise)} />
                )}
              </Field>
              <Field label="Weight" hint="Relative weight in the batch average.">
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    step="0.01"
                    min={0}
                    value={draft.weight}
                    onChange={(event) => setDraft({ ...draft, weight: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Score" required>
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    step="0.01"
                    value={draft.score}
                    onChange={(event) => setDraft({ ...draft, score: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Out of" required>
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    step="0.01"
                    value={draft.max_score}
                    onChange={(event) => setDraft({ ...draft, max_score: event.target.value })}
                  />
                )}
              </Field>
            </FormGrid>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={create.isPending}
              disabled={!draft.student_id || draft.score === ""}
              onClick={() => create.mutate(draft)}
            >
              Record entry
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title="Remove this entry?"
        description="The student's weighted average is recomputed without it."
        confirmLabel="Remove entry"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

function SummaryTab({ batchId }: { batchId: string }) {
  const [studentId, setStudentId] = useState<string | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["gradebook", "summary", batchId, studentId],
    queryFn: () =>
      api.get<GradeBookSummaryResponse>("/gradebook/summary", {
        query: { batch_id: batchId, student_id: studentId ?? undefined },
      }),
    enabled: Boolean(batchId && studentId),
  });

  return (
    <Card>
      <CardHeader
        title="Standing in this batch"
        description="Computed from the entries, weighted by each component's weight."
      />
      <CardBody className="space-y-4">
        <Field label="Student" className="max-w-md">
          {({ id }) => (
            <UserPicker id={id} role="STUDENT" value={studentId} onChange={(next) => setStudentId(next)} />
          )}
        </Field>

        {!batchId ? (
          <p className="text-sm text-muted-foreground">Choose a batch above.</p>
        ) : !studentId ? (
          <p className="text-sm text-muted-foreground">Choose a student to see their standing.</p>
        ) : isPending ? (
          <LoadingState rows={3} />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : data ? (
          <>
            <StatGrid>
              <Stat
                label="Weighted average"
                value={data.weighted_percentage ?? null}
                suffix="%"
                hint="Null until something is recorded."
              />
              <Stat label="Letter grade" value={data.letter_grade ?? null} />
              <Stat label="GPA points" value={data.gpa_points ?? null} />
              <Stat label="Components" value={data.components?.length ?? 0} />
            </StatGrid>

            <DataTable
              columns={[
                {
                  key: "component",
                  header: "Component",
                  cell: (row: NonNullable<GradeBookSummaryResponse["components"]>[number]) => (
                    <Badge tone="neutral">{humanise(row.component_type)}</Badge>
                  ),
                },
                {
                  key: "entries",
                  header: "Entries",
                  align: "right",
                  cell: (row) => <span className="tabular-nums">{row.entries}</span>,
                },
                {
                  key: "score",
                  header: "Earned",
                  align: "right",
                  cell: (row) => (
                    <span className="tabular-nums">
                      {row.earned} / {row.available}
                    </span>
                  ),
                },
                {
                  key: "percentage",
                  header: "Percentage",
                  align: "right",
                  cell: (row) => <span className="tabular-nums">{row.percentage ?? "—"}</span>,
                },
                {
                  key: "weight",
                  header: "Weight",
                  align: "right",
                  cell: (row) => <span className="tabular-nums">{row.weight}</span>,
                },
              ]}
              rows={data.components ?? []}
              rowKey={(row) => row.component_type}
              emptyMessage="Nothing recorded for this student in this batch."
            />
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

function GradebookContent() {
  const params = useSearchParams();
  const { permissions } = useSession();
  const [batchId, setBatchId] = useState(params.get("batch") ?? "");

  const batches = useQuery({
    queryKey: ["batches", "picker"],
    queryFn: () => api.get<PageBatchSummary>("/batches", { query: { limit: 200 } }),
    enabled: permissions.has("batch.read"),
    staleTime: 60_000,
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Grade book"
        description="Every contribution to a student's standing in a batch, and the scale that turns it into a grade."
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 p-3">
          <Field label="Batch" className="w-80">
            {({ id }) => (
              <Select
                id={id}
                value={(batchId) || null}
                disabled={!permissions.has("batch.read")}
                onValueChange={(next) => setBatchId((next ?? ""))}
               placeholder="Every batch" clearable options={(batches.data?.items ?? []).map((batch) => ({ value: batch.public_id, label: batch.batch_code }))} />
            )}
          </Field>
        </div>
      </Card>

      <Tabs defaultValue="entries">
        <TabsList>
          <TabsTab value="entries">Entries</TabsTab>
          <TabsTab value="summary">Student standing</TabsTab>
          <TabsTab value="bands">Grading scale</TabsTab>
        </TabsList>
        <TabsPanel value="entries">
          <EntriesTab batchId={batchId} />
        </TabsPanel>
        <TabsPanel value="summary">
          <SummaryTab batchId={batchId} />
        </TabsPanel>
        <TabsPanel value="bands">
          <GradeBands />
        </TabsPanel>
      </Tabs>
    </div>
  );
}

export default function GradebookPage() {
  // `useSearchParams` needs a Suspense boundary in the App Router.
  return (
    <Suspense fallback={<LoadingState rows={5} />}>
      <GradebookContent />
    </Suspense>
  );
}
