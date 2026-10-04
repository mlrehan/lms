"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileCheck2, FileText, Lock } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { GenerateTranscriptsResponse, PageTranscriptResponse, TranscriptResponse } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field } from "@/components/ui/form";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { BatchPicker } from "@/components/domain/entity-pickers";

export default function TranscriptsPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [batchId, setBatchId] = useState("");
  const [studentId, setStudentId] = useState<string | null>(null);
  const [finalising, setFinalising] = useState<TranscriptResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["transcripts", "list", batchId, studentId, limit, offset],
    queryFn: () =>
      api.get<PageTranscriptResponse>("/transcripts", {
        query: {
          batch_id: batchId || undefined,
          student_id: studentId ?? undefined,
          limit,
          offset,
        },
      }),
  });

  const generate = useApiMutation<GenerateTranscriptsResponse, void>({
    mutationFn: () =>
      api.post<GenerateTranscriptsResponse>(`/batches/${segment(batchId)}/transcripts/generate`),
    success: (result) =>
      `${result.generated ?? 0} generated, ${result.updated ?? 0} updated${
        result.skipped_final ? `, ${result.skipped_final} left alone (final)` : ""
      }${result.skipped_no_grades ? `, ${result.skipped_no_grades} had no grades` : ""}.`,
    invalidate: [["transcripts"]],
  });

  const finalise = useApiMutation<TranscriptResponse, string>({
    mutationFn: (transcriptId) =>
      api.put<TranscriptResponse>(`/transcripts/${segment(transcriptId)}/finalise`, {
        body: { is_final: true },
      }),
    success: "Transcript finalised.",
    invalidate: [["transcripts"]],
    onSuccess: () => setFinalising(null),
  });

  const columns: Column<TranscriptResponse>[] = [
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
      key: "batch",
      header: "Batch",
      cell: (row) => (
        <div className="min-w-0">
          <Link href={`/batches/${row.batch_id}`} className="font-mono text-xs hover:underline">
            {row.batch_code ?? row.batch_id}
          </Link>
          {row.course_title ? (
            <p className="truncate text-xs text-muted-foreground">{row.course_title}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "gpa",
      header: "GPA",
      align: "right",
      cell: (row) => <span className="tabular-nums font-medium">{row.gpa ?? "—"}</span>,
    },
    {
      key: "grade",
      header: "Overall",
      cell: (row) =>
        row.overall_grade ? (
          <Badge tone="primary">{row.overall_grade}</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "generated",
      header: "Generated",
      secondary: true,
      cell: (row) => formatDateTime(row.generated_at, { timeZone }),
    },
    {
      key: "final",
      header: "State",
      cell: (row) =>
        row.is_final ? (
          <Badge tone="success">
            <Lock className="size-3" /> Final
          </Badge>
        ) : (
          <Badge tone="neutral">Provisional</Badge>
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <div className="flex items-center justify-end gap-2">
          {/* The official document. Open to anybody who can already see the
              row -- the backend scopes the fetch, so this link cannot reveal
              a transcript the list would not have shown. */}
          <Link href={`/transcripts/${row.public_id}`}>
            <Button variant="ghost" size="sm">
              <FileText className="size-4" aria-hidden /> View
            </Button>
          </Link>
          {permissions.has("grade.publish") && !row.is_final ? (
            <Button variant="secondary" size="sm" onClick={() => setFinalising(row)}>
              Finalise
            </Button>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Transcripts"
        description="The aggregated, publishable record of a student's standing in a batch. Regenerating leaves finalised transcripts alone."
        actions={
          permissions.has("grade.publish") ? (
            <Button
              disabled={!batchId}
              loading={generate.isPending}
              onClick={() => generate.mutate()}
            >
              <FileCheck2 /> Generate for batch
            </Button>
          ) : null
        }
      />

      <Card>
        <CardHeader title="Filters" />
        <div className="flex flex-wrap items-end gap-3 p-3">
          <Field label="Batch" className="w-80">
            {({ id }) => (
              <BatchPicker id={id} value={(batchId) || null} disabled={!permissions.has("batch.read")} onValueChange={(next) => {
                  setBatchId((next ?? ""));
                  setPage({ limit, offset: 0 });
                }} placeholder="Every batch" clearable />
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
      </Card>

      <Card>
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columnsKey="transcripts"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No transcripts yet. Generate them for a batch once its grade book is complete."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="transcripts"
            />
          </>
        )}
      </Card>

      <ConfirmDialog
        open={finalising !== null}
        onOpenChange={(open) => (open ? null : setFinalising(null))}
        title="Finalise this transcript?"
        description="A final transcript is skipped by future regenerations, so later grade changes will not be reflected in it."
        confirmLabel="Finalise"
        pending={finalise.isPending}
        onConfirm={() => {
          if (finalising) finalise.mutate(finalising.public_id);
        }}
      />
    </div>
  );
}
