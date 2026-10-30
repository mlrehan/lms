"use client";

import Link from "next/link";
import { use, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, Paperclip, Send, Trash2 } from "lucide-react";
import { api, apiPath, segment } from "@/lib/api/client";
import type {
  AssignmentResponse,
  PageSubmissionResponse,
  SubmissionFileResponse,
  SubmissionResponse,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
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
import { InlineSpinner } from "@/components/ui/states";
import { formatBytes } from "@/components/domain/resources/drive-view";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormActions, Input, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { RichText } from "@/components/domain/rich-text";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

/** Every state §7 defines, with the tone it deserves. */
const STATE_LABELS: Record<string, { label: string; tone: "neutral" | "success" | "warning" | "danger" }> = {
  NOT_STARTED: { label: "Not started", tone: "neutral" },
  PENDING: { label: "Pending", tone: "neutral" },
  SUBMITTED: { label: "Submitted", tone: "neutral" },
  LATE: { label: "Late", tone: "warning" },
  UNDER_REVIEW: { label: "Under review", tone: "neutral" },
  GRADED: { label: "Graded, not released", tone: "warning" },
  // "Published" read to tutors as "the assignment is published", not "the
  // student can now see this mark". Say what it means.
  PUBLISHED: { label: "Released to student", tone: "success" },
  ABSENT: { label: "Absent", tone: "danger" },
  EXEMPTED: { label: "Exempted", tone: "neutral" },
  RESUBMISSION_REQUIRED: { label: "Resubmission asked", tone: "warning" },
  REASSESSED: { label: "Reassessed", tone: "success" },
};

function SubmissionStateBadge({ state }: { state?: string | null }) {
  const found = STATE_LABELS[state ?? ""] ?? { label: state ?? "—", tone: "neutral" as const };
  return <Badge tone={found.tone}>{found.label}</Badge>;
}

function GradeDialog({
  submission,
  assignmentId,
  maxScore,
  canRelease,
  onClose,
}: {
  submission: SubmissionResponse | null;
  assignmentId: string;
  maxScore: string;
  canRelease: boolean;
  onClose: () => void;
}) {
  // Re-grading starts from the mark and feedback already given -- a tutor
  // correcting one number should not have to retype the paragraph beside it.
  // The dialog is keyed by submission, so this initialiser runs per student.
  const [grade, setGrade] = useState(submission?.grade != null ? String(Number(submission.grade)) : "");
  const [feedback, setFeedback] = useState(submission?.feedback ?? "");
  const [reason, setReason] = useState("");

  // Changing a mark that has already been given needs a reason (§24). The API
  // refuses without one; asking here means the tutor is not told off after
  // typing everything else.
  const isChange = submission?.grade !== null && submission?.grade !== undefined;
  const wasReleased = submission?.state === "PUBLISHED";

  // Marking and releasing stay two server calls -- two permissions, two audit
  // rows -- but for the one student in front of the tutor they can be one
  // click. The release names this student only, so nobody else's mark goes
  // out with it.
  const save = useApiMutation<
    { released: boolean },
    { grade: string; feedback: string; release: boolean }
  >({
    mutationFn: async (values) => {
      await api.put<SubmissionResponse>(`/submissions/${segment(submission!.public_id)}/grade`, {
        body: {
          grade: Number(values.grade),
          feedback: values.feedback || null,
          override_reason: isChange ? reason : null,
        },
      });
      if (!values.release) return { released: false };
      await api.post<{ published: number }>(
        `/assignments/${segment(assignmentId)}/publish-results`,
        { body: { student_ids: [submission!.student_id] } },
      );
      return { released: true };
    },
    success: (result) =>
      result.released
        ? "Grade recorded and released. The student and their guardians have been notified."
        : "Grade recorded. It is not visible to the student until you release it.",
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
        {/* The marker has to be able to open what was handed in; before this
            there was nothing to open. */}
        <div className="mb-3">
          <AttachedFiles files={submission?.files ?? []} label="Submitted files" preview />
        </div>
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
          {isChange ? (
            <Field label="Reason for the change" required>
              {({ id }) => (
                <Textarea
                  id={id}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Recorded against the mark, and visible to administrators."
                />
              )}
            </Field>
          ) : null}
          <p className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
            {wasReleased
              ? "This mark has already been released. Changing it hides it from the student again until it is released."
              : "Record grade keeps the mark private. Record and release shows it to the student and notifies them and their guardians."}
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={canRelease ? "secondary" : "primary"}
            loading={save.isPending && !save.variables?.release}
            disabled={save.isPending || grade === "" || (isChange && reason.trim().length < 3)}
            onClick={() => save.mutate({ grade, feedback, release: false })}
          >
            Record grade
          </Button>
          {canRelease ? (
            <Button
              loading={save.isPending && save.variables?.release === true}
              disabled={save.isPending || grade === "" || (isChange && reason.trim().length < 3)}
              onClick={() => save.mutate({ grade, feedback, release: true })}
            >
              <Send aria-hidden />
              Record and release
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The files attached to one submission, with a link to each.
 *
 * `download_url` is a path on this API that re-authorises per request -- the
 * student who attached it, or whoever may mark it. There is no storage key in
 * the payload to render, which is the point of the table that replaced the
 * old JSON column.
 */
function AttachedFiles({
  files,
  label = "Attached files",
  preview = false,
}: {
  files: SubmissionFileResponse[];
  label?: string;
  /** Show images in place. Work is often handed in as nine screenshots, and
   *  marking it should not mean downloading nine files first. */
  preview?: boolean;
}) {
  const [zoomed, setZoomed] = useState<string | null>(null);
  if (files.length === 0) return null;
  // An <img> renders bytes and runs nothing, and ignores the download
  // disposition, so the same re-authorising URL serves the preview.
  const images = preview ? files.filter((f) => (f.mime_type ?? "").startsWith("image/")) : [];
  const open = images.find((f) => f.public_id === zoomed);
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      {open ? (
        <figure className="space-y-1">
          <button
            type="button"
            className="block w-full overflow-hidden rounded-lg border border-border-subtle bg-surface-muted"
            onClick={() => setZoomed(null)}
            aria-label={`Close ${open.filename}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- an authenticated API stream, not a static asset */}
            <img src={apiPath(open.download_url)} alt={open.filename} className="mx-auto max-h-[60svh] w-auto" />
          </button>
          <figcaption className="truncate text-2xs text-muted-foreground">
            {open.filename} &middot; click to close
          </figcaption>
        </figure>
      ) : null}
      {images.length > 0 ? (
        <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
          {images.map((file, index) => (
            <button
              key={file.public_id}
              type="button"
              onClick={() => setZoomed(file.public_id === zoomed ? null : file.public_id)}
              className={`overflow-hidden rounded-md border ${file.public_id === zoomed ? "border-accent" : "border-border-subtle"} bg-surface-muted hover:border-accent`}
              title={file.filename}
              aria-label={`View ${file.filename}`}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- an authenticated API stream, not a static asset */}
              <img
                src={apiPath(file.download_url)}
                alt={`Screenshot ${index + 1}`}
                loading="lazy"
                className="aspect-video w-full object-cover object-left-top"
              />
            </button>
          ))}
        </div>
      ) : null}
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle">
        {files.map((file) => (
          <li key={file.public_id} className="flex items-center gap-2 px-3 py-1.5">
            <Paperclip className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-sm" title={file.filename}>
              {file.filename}
            </span>
            <span className="shrink-0 text-2xs text-muted-foreground">
              {formatBytes(file.size)}
            </span>
            <a
              href={apiPath(file.download_url)}
              download={file.filename}
              className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Download className="size-3.5" aria-hidden />
              <span className="sr-only sm:not-sr-only">Download</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SubmitPanel({ assignment }: { assignment: AssignmentResponse }) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const picker = useRef<HTMLInputElement>(null);
  const takesFiles = assignment.submission_type === "FILE_UPLOAD";

  /*
   * The files are uploaded before the work is submitted, not with it.
   *
   * The submit endpoint carries the written answer only; attachments go to
   * `.../attachments` one at a time and are claimed when the submission is
   * written. That is what lets the server own the storage key -- the old
   * shape had the *client* name a `path` in the submit body, so a submission
   * could cite bytes nobody had written.
   */
  const attached = useQuery({
    queryKey: ["assignments", assignment.public_id, "attachments"],
    queryFn: () =>
      api.get<SubmissionFileResponse[]>(
        `/assignments/${segment(assignment.public_id)}/attachments`,
      ),
    enabled: takesFiles,
  });

  const refreshFiles = () =>
    queryClient.invalidateQueries({
      queryKey: ["assignments", assignment.public_id, "attachments"],
    });

  const upload = useApiMutation<SubmissionFileResponse[], FileList>({
    mutationFn: async (chosen) => {
      const saved: SubmissionFileResponse[] = [];
      // Sequentially: a dropped folder of twenty should not open twenty
      // connections, and a per-file refusal is easier to attribute.
      for (const file of Array.from(chosen)) {
        const form = new FormData();
        form.append("file", file);
        saved.push(
          await api.post<SubmissionFileResponse>(
            `/assignments/${segment(assignment.public_id)}/attachments`,
            { body: form },
          ),
        );
      }
      return saved;
    },
    success: (saved) => `Attached ${saved.length === 1 ? "1 file" : saved.length + " files"}.`,
    onSuccess: () => {
      void refreshFiles();
      if (picker.current) picker.current.value = "";
    },
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (fileId) => api.delete<void>(`/submission-files/${segment(fileId)}`),
    success: "File removed.",
    onSuccess: () => void refreshFiles(),
  });

  const files = attached.data ?? [];
  const canSubmit = content.trim() !== "" || files.length > 0;

  const submit = useApiMutation<SubmissionResponse, string>({
    mutationFn: (text) =>
      api.put<SubmissionResponse>(`/assignments/${segment(assignment.public_id)}/submission`, {
        body: { content: text },
      }),
    success: "Submitted.",
    invalidate: [["assignments"], ["submissions"], ["dashboard"]],
    onSuccess: () => void refreshFiles(),
  });

  const accept = assignment.allowed_file_types
    ? assignment.allowed_file_types
        .split(",")
        .map((part) => "." + part.trim().replace(/^[.]/, ""))
        .join(",")
    : undefined;

  return (
    <Card>
      <CardHeader
        title={assignment.my_submission_id ? "Replace your submission" : "Submit your work"}
        description={
          takesFiles
            ? "Attach your files, add anything you want to say, then submit. Re-submitting before the deadline replaces what you sent."
            : "Re-submitting before the deadline replaces what you sent; it does not create a second submission."
        }
      />
      <CardBody className="space-y-3">
        {takesFiles ? (
          <Field
            label="Your files"
            hint={[
              assignment.allowed_file_types ? "Accepted: " + assignment.allowed_file_types + "." : null,
              assignment.max_upload_mb ? "Up to " + assignment.max_upload_mb + " MB each." : null,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {({ id }) => (
              <div className="space-y-2">
                <input
                  id={id}
                  ref={picker}
                  type="file"
                  multiple
                  disabled={upload.isPending}
                  accept={accept}
                  className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-medium"
                  onChange={(event) => {
                    const chosen = event.target.files;
                    if (chosen && chosen.length > 0) upload.mutate(chosen);
                  }}
                />
                {upload.isPending ? (
                  <p className="flex items-center gap-2 text-xs text-muted-foreground">
                    <InlineSpinner /> Uploading&hellip;
                  </p>
                ) : null}
                {files.length > 0 ? (
                  <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle">
                    {files.map((file) => (
                      <li key={file.public_id} className="flex items-center gap-2 px-3 py-1.5">
                        <Paperclip className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="min-w-0 flex-1 truncate text-sm">{file.filename}</span>
                        <span className="text-2xs text-muted-foreground">
                          {formatBytes(file.size)}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={"Remove " + file.filename}
                          disabled={remove.isPending}
                          onClick={() => remove.mutate(file.public_id)}
                        >
                          <Trash2 className="size-3.5 text-danger" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            )}
          </Field>
        ) : null}

        <Field
          label={assignment.submission_type === "LINK" ? "Link to your work" : "Your answer"}
          required={!takesFiles}
          hint={takesFiles ? "Optional once you have attached a file." : undefined}
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
            // The server asks the same question of both halves; this only
            // saves the round trip in the obvious case.
            disabled={!canSubmit}
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
  const [view, setView] = useState("");
  const [grading, setGrading] = useState<SubmissionResponse | null>(null);
  const canRelease = permissions.has("assignment.publish");

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["submissions", assignment.public_id, view, limit, offset],
    queryFn: () =>
      api.get<PageSubmissionResponse>("/submissions", {
        query: {
          assignment_id: assignment.public_id,
          graded: view === "ungraded" ? false : undefined,
          state: view === "GRADED" || view === "PUBLISHED" ? view : undefined,
          limit,
          offset,
        },
      }),
  });

  // How many marks are recorded and still invisible to their students. The
  // release step only makes sense to a tutor who can see it is waiting.
  const waiting = useQuery({
    queryKey: ["submissions", assignment.public_id, "awaiting-release"],
    enabled: canRelease,
    queryFn: () =>
      api.get<PageSubmissionResponse>("/submissions", {
        query: { assignment_id: assignment.public_id, state: "GRADED", limit: 1, offset: 0 },
      }),
  });
  const awaitingRelease = waiting.data?.total ?? 0;

  const [confirmPublish, setConfirmPublish] = useState(false);
  const [releaseOne, setReleaseOne] = useState<SubmissionResponse | null>(null);
  const publish = useApiMutation<{ published: number }, { studentId?: string }>({
    mutationFn: ({ studentId }) =>
      api.post<{ published: number }>(
        `/assignments/${segment(assignment.public_id)}/publish-results`,
        { body: studentId ? { student_ids: [studentId] } : {} },
      ),
    success: (result) =>
      result.published === 0
        ? "Nothing was released: no marked result is waiting."
        : `${result.published} result${result.published === 1 ? "" : "s"} released. Students and their guardians have been notified.`,
    invalidate: [["submissions"], ["assignments"], ["gradebook"], ["dashboard"]],
    onSuccess: () => {
      setConfirmPublish(false);
      setReleaseOne(null);
    },
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
      key: "state",
      header: "Status",
      // §38: scored zero, not yet assessed, absent and exempted are four
      // different facts. A "graded / not graded" badge could show only two of
      // them, and showed an exempted student as "not graded" -- which reads
      // as a tutor who has not done their marking.
      cell: (row) => <SubmissionStateBadge state={row.state} />,
    },
    {
      key: "grade",
      header: "Grade",
      align: "right",
      cell: (row) =>
        row.grade === null || row.grade === undefined ? (
          <span className="text-xs text-muted-foreground">—</span>
        ) : (
          <span className="tabular-nums font-medium">
            {row.grade} / {assignment.max_score}
            {/* The deduction, shown as arithmetic rather than folded into one
                opaque number the student cannot reconcile. */}
            {row.late_penalty_applied && Number(row.late_penalty_applied) > 0 ? (
              <span className="block text-2xs font-normal text-warning">
                {row.raw_grade} less {row.late_penalty_applied} late penalty
              </span>
            ) : null}
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
      key: "files",
      header: "Files",
      hideBelow: "md",
      // Downloadable from the row, not only from inside the grading dialog:
      // a marker reading thirty scripts opens the files first and marks
      // afterwards, and making them open a dialog per student to find out
      // whether there is anything to read is the wrong way round.
      cell: (row) =>
        (row.files ?? []).length === 0 ? (
          <span className="text-subtle-foreground">&mdash;</span>
        ) : (
          <div className="flex flex-wrap items-center gap-1">
            {(row.files ?? []).map((file) => (
              <a
                key={file.public_id}
                href={apiPath(file.download_url)}
                download={file.filename}
                title={file.filename + " \u00b7 " + formatBytes(file.size)}
                className="inline-flex max-w-40 items-center gap-1 rounded-md border border-border-subtle px-1.5 py-0.5 text-2xs hover:bg-muted"
              >
                <Paperclip className="size-3 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{file.filename}</span>
              </a>
            ))}
          </div>
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <span className="inline-flex items-center gap-1.5">
          {canRelease && row.state === "GRADED" ? (
            <Button size="sm" onClick={() => setReleaseOne(row)}>
              <Eye aria-hidden />
              Release
            </Button>
          ) : null}
          {permissions.has("assignment.grade") ? (
            <Button variant="secondary" size="sm" onClick={() => setGrading(row)}>
              {row.grade === null || row.grade === undefined ? "Grade" : "Re-grade"}
            </Button>
          ) : null}
        </span>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Submissions"
        description={`${assignment.submission_count ?? 0} received.`}
        actions={
          <span className="flex flex-wrap items-center gap-2">
          {/* §14's release step, as its own action. Marking thirty scripts
              over a week and releasing them together is the normal workflow;
              releasing each as it is marked tells the first student days
              before the last. */}
          {canRelease ? (
            <Button
              variant={awaitingRelease > 0 ? "primary" : "secondary"}
              size="sm"
              loading={publish.isPending && !releaseOne}
              disabled={awaitingRelease === 0}
              title={awaitingRelease === 0 ? "No marked result is waiting to be released." : undefined}
              onClick={() => setConfirmPublish(true)}
            >
              <Send aria-hidden />
              {awaitingRelease > 0
                ? `Release ${awaitingRelease} result${awaitingRelease === 1 ? "" : "s"}`
                : "Nothing to release"}
            </Button>
          ) : null}
          <Select
            className="w-auto"
            aria-label="Filter submissions"
            value={view || null}
            onValueChange={(next) => {
              setView(next ?? "");
              setPage({ limit, offset: 0 });
            }}
            placeholder="All submissions"
            clearable
            options={[
              { value: "ungraded", label: "Awaiting grading" },
              { value: "GRADED", label: "Graded, not released" },
              { value: "PUBLISHED", label: "Released to student" },
            ]}
          />
          </span>
        }
      />
      {canRelease && awaitingRelease > 0 ? (
        // The release step is easy to miss when it is one button among
        // several; a mark the tutor believes the student has seen, and the
        // student has not, is the failure this banner exists to prevent.
        <div className="mx-4 mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm">
          <span className="text-warning">
            {awaitingRelease} marked result{awaitingRelease === 1 ? " is" : "s are"} not released yet.
            Students and guardians cannot see {awaitingRelease === 1 ? "it" : "them"} until you release.
          </span>
          <Button size="sm" variant="secondary" onClick={() => setView("GRADED")}>
            Show {awaitingRelease === 1 ? "it" : "them"}
          </Button>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirmPublish}
        onOpenChange={setConfirmPublish}
        title={`Release ${awaitingRelease} result${awaitingRelease === 1 ? "" : "s"}?`}
        // A high-impact action gets a confirmation (§27): once a mark is
        // released the student and their guardian have seen it, and there is
        // no taking that back.
        description="Every marked submission that is not released yet becomes visible to its student, and they and their guardians are notified. Work that is not marked yet is left alone."
        confirmLabel="Release results"
        pending={publish.isPending}
        onConfirm={() => publish.mutate({})}
      />
      <ConfirmDialog
        open={releaseOne !== null}
        onOpenChange={(open) => {
          if (!open) setReleaseOne(null);
        }}
        title={releaseOne?.student_username ? `Release ${releaseOne.student_username}’s result?` : "Release this result?"}
        description={`${releaseOne?.grade ?? ""} / ${assignment.max_score} becomes visible to this student only, and they and their guardians are notified.`}
        confirmLabel="Release"
        pending={publish.isPending}
        onConfirm={() => {
          if (releaseOne) publish.mutate({ studentId: releaseOne.student_id });
        }}
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
              columnsKey="assignment-submissions"
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
        key={grading?.public_id ?? "closed"}
        submission={grading}
        assignmentId={assignment.public_id}
        maxScore={assignment.max_score}
        canRelease={canRelease}
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
            <RichText html={data.description} />
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
