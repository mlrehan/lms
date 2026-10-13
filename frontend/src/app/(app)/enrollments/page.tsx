"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { EnrollmentResponse, PageEnrollmentResponse } from "@/lib/api/types";
import { EnrollmentStatusValues } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { BatchPicker } from "@/components/domain/entity-pickers";
import { UserPicker } from "@/components/domain/user-picker";
import { StatusBadge } from "@/components/domain/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { formatCalendarDate } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

/**
 * Transfer moves a student to another batch and links the two enrollments,
 * so the history is a chain rather than an overwrite. The target batch is
 * entered by id because there is no batch search endpoint -- `GET /batches`
 * pages but does not take a query.
 */
function TransferDialog({
  enrollment,
  onClose,
}: {
  enrollment: EnrollmentResponse | null;
  onClose: () => void;
}) {
  const [targetBatchId, setTargetBatchId] = useState("");

  const transfer = useApiMutation<EnrollmentResponse, string>({
    mutationFn: (batchId) =>
      api.post<EnrollmentResponse>(`/enrollments/${segment(enrollment!.public_id)}/transfer`, {
        body: { target_batch_id: batchId },
      }),
    success: "Student transferred.",
    invalidate: [["enrollments"], ["batches"]],
    onSuccess: () => {
      setTargetBatchId("");
      onClose();
    },
  });

  return (
    <Dialog open={enrollment !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent size="md">
        <DialogHeader
          title="Transfer to another batch"
          description={`${enrollment?.student_username ?? "This student"} moves out of ${
            enrollment?.batch_code ?? "their batch"
          }.`}
        />
        <div className="space-y-4">
          <Field
            label="Target batch id"
            required
            hint="Copy it from the target batch's URL. There is no batch search endpoint to pick from."
          >
            {({ id }) => (
              <Input
                id={id}
                value={targetBatchId}
                onChange={(event) => setTargetBatchId(event.target.value.trim())}
                placeholder="00000000-0000-0000-0000-000000000000"
              />
            )}
          </Field>
          <p className="text-xs text-muted-foreground">
            The old enrollment is always kept and linked to the new one; the API takes no option to
            discard it, so nothing here offers to.
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={transfer.isPending}
            disabled={!targetBatchId}
            onClick={() => transfer.mutate(targetBatchId)}
          >
            Transfer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function EnrollmentsPage() {
  const { permissions } = useSession();
  const { limit, offset, setPage } = useListState();
  const [status, setStatus] = useState("");
  const [batchId, setBatchId] = useState<string | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [tutorId, setTutorId] = useState<string | null>(null);
  const [transferring, setTransferring] = useState<EnrollmentResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["enrollments", "list", status, batchId, studentId, tutorId, limit, offset],
    queryFn: () =>
      api.get<PageEnrollmentResponse>("/enrollments", {
        query: {
          status: status || undefined,
          batch_id: batchId || undefined,
          student_id: studentId || undefined,
          tutor_id: tutorId || undefined,
          limit,
          offset,
        },
      }),
  });

  const setEnrollmentStatus = useApiMutation<
    EnrollmentResponse,
    { enrollmentId: string; status: string }
  >({
    mutationFn: ({ enrollmentId, status: next }) =>
      api.put<EnrollmentResponse>(`/enrollments/${segment(enrollmentId)}/status`, {
        body: { status: next },
      }),
    success: "Enrollment updated.",
    invalidate: [["enrollments"]],
  });

  const columns: Column<EnrollmentResponse>[] = [
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
      key: "status",
      header: "Status",
      cell: (row) => (
        <span className="flex items-center gap-1.5">
          <StatusBadge value={row.status} kind="enrollment" />
          {row.is_transfer ? <Badge tone="info">Transfer</Badge> : null}
          {row.organization_id ? <Badge tone="neutral">Sponsored</Badge> : null}
        </span>
      ),
    },
    {
      key: "date",
      header: "Enrolled",
      secondary: true,
      cell: (row) => formatCalendarDate(row.enrollment_date),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <div className="flex items-center justify-end gap-1">
          {permissions.has("enrollment.update") ? (
            <>
              <Select
                className="w-auto"
                aria-label={`Status for ${row.student_username ?? "student"}`}
                value={row.status}
                disabled={setEnrollmentStatus.isPending}
                onValueChange={(next) => {
                  if (next) {
                    setEnrollmentStatus.mutate({
                      enrollmentId: row.public_id,
                      status: next,
                    });
                  }
                }}
                options={optionsFromValues(EnrollmentStatusValues, humanise)}
              />
              <Button
                variant="ghost"
                size="sm"
                aria-label="Transfer to another batch"
                onClick={() => setTransferring(row)}
              >
                <ArrowLeftRight />
              </Button>
            </>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Enrollments"
        description="Who is on which batch, and in what state. A transfer links the old enrollment to the new one rather than replacing it."
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="Status" className="w-44">
            {({ id }) => (
              <Select
                id={id}
                value={status || null}
                placeholder="Any status"
                clearable
                onValueChange={(next) => {
                  // `null` is the cleared state and means "any status", which
                  // is the empty string the query already sends.
                  setStatus(next ?? "");
                  setPage({ limit, offset: 0 });
                }}
                options={optionsFromValues(EnrollmentStatusValues, humanise)}
              />
            )}
          </Field>
          {/*
            * Pickers, not id boxes.
            *
            * These two were `<Input>`s expecting a raw uuid typed by hand.
            * Nobody has one, and anything short of a well-formed uuid made the
            * API refuse the entire request with a 422 -- so the filter looked
            * broken rather than empty, which is what was reported.
            */}
          <Field label="Batch" className="w-64">
            {({ id }) => (
              <BatchPicker
                id={id}
                value={batchId}
                placeholder="Any batch"
                onValueChange={(next) => {
                  setBatchId(next);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          <Field label="Student" className="w-64">
            {({ id }) => (
              <UserPicker
                id={id}
                role="STUDENT"
                value={studentId}
                placeholder="Any student"
                onChange={(next) => {
                  setStudentId(next);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          {permissions.has("institution.view_all") ? (
            <Field label="Tutor" className="w-64">
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="TUTOR"
                  value={tutorId}
                  placeholder="Any tutor"
                  onChange={(next) => {
                    setTutorId(next);
                    setPage({ limit, offset: 0 });
                  }}
                />
              )}
            </Field>
          ) : null}
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columnsKey="enrollments"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No enrollments match these filters."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="enrollments"
            />
          </>
        )}
      </Card>

      <TransferDialog enrollment={transferring} onClose={() => setTransferring(null)} />
    </div>
  );
}
