"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Send, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  AssignmentResponse,
  PageSubmissionResponse,
  SubmissionResponse,
} from "@/lib/api/types";
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
import { Field, FormActions, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function GradeDialog({
  submission,
  maxScore,
  onClose,
}: {
  submission: SubmissionResponse | null;
  maxScore: string;
  onClose: () => void;
}) {
  const [grade, setGrade] = useState("");
  const [feedback, setFeedback] = useState("");

  const save = useApiMutation<SubmissionResponse, { grade: string; feedback: string }>({
    mutationFn: (values) =>
      api.put<SubmissionResponse>(`/submissions/${segment(submission!.public_id)}/grade`, {
        body: { grade: Number(values.grade), feedback: values.feedback || null },
      }),
    success: "Grade recorded.",
    invalidate: [["submissions"], ["assignments"], ["gradebook"], ["dashboard"]],
    onSuccess: () => {
      setGrade("");
      setFeedback("");
      onClose();
    },
  });

  return (
    <Dialog
      open={submission !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="md">
        <DialogHeader
          title={`Grade ${submission?.student_username ?? "submission"}`}
          description={`Out of ${maxScore}.`}
        />
        {submission?.content ? (
          <div className="mb-3 space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Submitted work</p>
            {/*
              Student-authored text, rendered as text. Nothing in this console
              turns a submission into markup.
            */}
            <p className="max-h-56 overflow-y-auto scrollbar-thin whitespace-pre-wrap break-words rounded-lg border border-border-subtle bg-surface-muted p-3 text-sm">
              {submission.content}
            </p>
          </div>
        ) : null}
        <div className="space-y-4">
          <Field label="Score" required>
            {({ id }) => (
              <Input
                id={id}
                type="number"
                min={0}
                step="0.01"
                value={grade}
                onChange={(event) => setGrade(event.target.value)}
              />
            )}
          </Field>
          <Field label="Feedback">
            {({ id }) => (
              <Textarea id={id} value={feedback} onChange={(event) => setFeedback(event.target.value)} />
            )}
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} disabled={grade === ""} onClick={() => save.mutate({ grade, feedback })}>
            Record grade
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SubmitPanel({ assignment }: { assignment: AssignmentResponse }) {
  const [content, setContent] = useState("");

  const submit = useApiMutation<SubmissionResponse, string>({
    mutationFn: (text) =>
      api.put<SubmissionResponse>(`/assignments/${segment(assignment.public_id)}/submission`, {
        body: { content: text },
      }),
    success: "Submitted.",
    invalidate: [["assignments"], ["submissions"], ["dashboard"]],
  });

  return (
    <Card>
      <CardHeader
        title={assignment.my_submission_id ? "Replace your submission" : "Submit your work"}
        description={
          assignment.submission_type === "FILE_UPLOAD"
            ? "This assignment expects a file. The API's submission endpoint takes text and file metadata but has no upload of its own -- upload the file under Resources and paste its link here."
            : "Re-submitting before the deadline replaces what you sent; it does not create a second submission."
        }
      />
      <CardBody className="space-y-3">
        <Field
          label={assignment.submission_type === "LINK" ? "Link to your work" : "Your answer"}
          required
        >
          {({ id }) => (
            <Textarea
              id={id}
              rows={6}
              value={content}
              onChange={(event) => setContent(event.target.value)}
            />
          )}
        </Field>
        <FormActions>
          <Button
            loading={submit.isPending}
            disabled={content.trim() === ""}
            onClick={() => submit.mutate(content)}
          >
            <Send /> {assignment.my_submission_id ? "Replace submission" : "Submit"}
          </Button>
        </FormActions>
      </CardBody>
    </Card>
  );
}

function SubmissionsTab({ assignment }: { assignment: AssignmentResponse }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(25);
  const [graded, setGraded] = useState("");
  const [grading, setGrading] = useState<SubmissionResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["submissions", assignment.public_id, graded, limit, offset],
    queryFn: () =>
      api.get<PageSubmissionResponse>("/submissions", {
        query: {
          assignment_id: assignment.public_id,
          graded: graded === "" ? undefined : graded === "true",
          limit,
          offset,
        },
      }),
  });

  const columns: Column<SubmissionResponse>[] = [
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
      key: "submitted",
      header: "Submitted",
      cell: (row) => (
        <span className="flex items-center gap-2">
          {formatDateTime(row.submitted_at, { timeZone })}
          {row.is_late ? <Badge tone="warning">Late</Badge> : null}
        </span>
      ),
    },
    {
      key: "grade",
      header: "Grade",
      align: "right",
      cell: (row) =>
        row.grade === null || row.grade === undefined ? (
          <Badge tone="warning">Not graded</Badge>
        ) : (
          <span className="tabular-nums font-medium">
            {row.grade} / {assignment.max_score}
          </span>
        ),
    },
    {
      key: "gradedBy",
      header: "Graded by",
      secondary: true,
      cell: (row) => (
        <span className="text-xs text-muted-foreground">
          {row.graded_by_username ?? "—"}
          {row.graded_at ? ` · ${formatDateTime(row.graded_at, { timeZone })}` : ""}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("assignment.grade") ? (
          <Button variant="secondary" size="sm" onClick={() => setGrading(row)}>
            {row.grade === null || row.grade === undefined ? "Grade" : "Re-grade"}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Submissions"
        description={`${assignment.submission_count ?? 0} received.`}
        actions={
          <NativeSelect
            className="w-auto"
            aria-label="Filter by grading state"
            value={graded}
            onChange={(event) => {
              setGraded(event.target.value);
              setPage({ limit, offset: 0 });
            }}
          >
            <option value="">All submissions</option>
            <option value="false">Awaiting grading</option>
            <option value="true">Graded</option>
          </NativeSelect>
        }
      />
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
            emptyMessage="Nothing submitted yet."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="submissions"
          />
        </>
      )}

      <GradeDialog
        submission={grading}
        maxScore={assignment.max_score}
        onClose={() => setGrading(null)}
      />
    </Card>
  );
}

export default function AssignmentDetailPage({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  const { assignmentId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["assignments", "detail", assignmentId],
    queryFn: () => api.get<AssignmentResponse>(`/assignments/${segment(assignmentId)}`),
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/assignments/${segment(assignmentId)}`),
    success: "Assignment deleted.",
    invalidate: [["assignments"]],
    onSuccess: () => router.push("/assignments"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const canSubmit = permissions.has("assignment.submit");
  const canSeeSubmissions = permissions.has("assignment.read");

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[
          { label: "Assignments", href: "/assignments" },
          ...(data.course_title
            ? [{ label: data.course_title, href: `/courses/${data.course_id}` }]
            : []),
          { label: data.title },
        ]}
        title={data.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{humanise(data.submission_type)}</Badge>
            <Badge tone={data.allow_late_submissions ? "warning" : "neutral"}>
              {data.allow_late_submissions ? "Late work accepted" : "No late work"}
            </Badge>
            <span className="text-xs">
              Due {formatDateTime(data.due_date, { timeZone })} ({formatRelative(data.due_date, locale)})
              · out of {data.max_score}
            </span>
          </span>
        }
        actions={
          permissions.has("assignment.delete") ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label="Delete assignment"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="text-danger" />
            </Button>
          ) : null
        }
      />

      {data.description ? (
        <Card>
          <CardHeader title="Brief" />
          <CardBody>
            <p className="whitespace-pre-wrap break-words text-sm">{data.description}</p>
          </CardBody>
        </Card>
      ) : null}

      {canSubmit && canSeeSubmissions ? (
        <Tabs defaultValue="submissions">
          <TabsList>
            <TabsTab value="submissions">Submissions</TabsTab>
            <TabsTab value="mine">My submission</TabsTab>
          </TabsList>
          <TabsPanel value="submissions">
            <SubmissionsTab assignment={data} />
          </TabsPanel>
          <TabsPanel value="mine">
            <SubmitPanel assignment={data} />
          </TabsPanel>
        </Tabs>
      ) : canSubmit ? (
        <SubmitPanel assignment={data} />
      ) : (
        <SubmissionsTab assignment={data} />
      )}

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this assignment?"
        description="Every submission and grade attached to it goes too."
        confirmPhrase={data.title}
        confirmLabel="Delete assignment"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
