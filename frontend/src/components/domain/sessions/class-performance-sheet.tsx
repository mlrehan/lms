"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, Save } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  ClassPerformanceMarkResponse,
  ClassPerformanceSheetResponse,
  ResultState,
} from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge, CardBody } from "@/components/ui/primitives";
import { Input } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

/**
 * §11's grid: how each student took part in one class.
 *
 * **Blank is not zero, and the input has to preserve that.** A criterion left
 * empty means "not assessed" and is excluded from the average; a typed `0`
 * means "assessed, scored nothing" and is counted. So every cell holds a
 * *string* and is sent as `null` only when it is genuinely empty — parsing to a
 * number eagerly would turn every untouched cell into 0 and fail a whole class
 * the tutor never assessed.
 *
 * The criteria are laid out as columns rather than a form per student because a
 * tutor fills in a whole class at once, which is also why the API takes the
 * entire sheet in one request: thirty calls would leave a half-recorded class if
 * the fifteenth failed.
 */

/** Must match `CRITERIA` in `backend/services/class_performance_service.py`. */
const CRITERIA = [
  { key: "participation", label: "Part." , title: "Participation" },
  { key: "interaction", label: "Inter.", title: "Interaction" },
  { key: "preparation", label: "Prep.", title: "Preparation" },
  { key: "practical", label: "Prac.", title: "Practical work" },
  { key: "presentation", label: "Pres.", title: "Presentation" },
  { key: "teamwork", label: "Team", title: "Teamwork" },
  { key: "communication", label: "Comm.", title: "Communication" },
  { key: "professionalism", label: "Prof.", title: "Professionalism" },
] as const;

type CriterionKey = (typeof CRITERIA)[number]["key"];

const STATE_TONE: Record<ResultState, string> = {
  DRAFT: "border-border-subtle text-muted-foreground",
  UNDER_REVIEW: "border-warning bg-warning/20 text-warning",
  FINALIZED: "border-info bg-info/15 text-info",
  PUBLISHED: "border-success bg-success/15 text-success",
};

interface Row {
  studentId: string;
  username: string;
  scores: Record<CriterionKey, string>;
  overall: string;
  comment: string;
  state: ResultState | null;
  /** The engine's own figure for the saved row, so the grid shows what the
   * transcript will use rather than a second calculation of it. */
  average: string | null;
}

/** Empty means "not assessed"; `0` is a real mark. */
function toValue(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function cell(mark: ClassPerformanceMarkResponse | null | undefined, key: CriterionKey): string {
  const value = mark?.[key];
  return value === null || value === undefined ? "" : String(value);
}

/**
 * The mean of whatever has been typed, shown live so a tutor sees the figure
 * they are creating before saving it. Computed the same way the backend does
 * (tutor's own overall wins; blanks excluded) — which is a duplication of the
 * rule and is why the *saved* row shows `mark.average` from the server instead.
 * This one is a preview of unsaved edits, which the server cannot provide.
 */
function previewAverage(row: Row): string | null {
  const overall = toValue(row.overall);
  if (overall !== null) return overall.toFixed(2);
  const values = CRITERIA.map(({ key }) => toValue(row.scores[key])).filter(
    (value): value is number => value !== null,
  );
  if (values.length === 0) return null;
  return (values.reduce((total, value) => total + value, 0) / values.length).toFixed(2);
}

export function ClassPerformanceSheet({ sessionId }: { sessionId: string }) {
  const { permissions } = useSession();
  const canRelease = permissions.has("class_performance.publish");

  const sheet = useQuery({
    queryKey: ["class-performance", sessionId],
    queryFn: () =>
      api.get<ClassPerformanceSheetResponse>(
        `/class-performance/sessions/${segment(sessionId)}`,
      ),
  });

  const [rows, setRows] = useState<Row[] | null>(null);
  const [maxScore, setMaxScore] = useState<string>("");

  const data = sheet.data;

  const initial = useMemo<Row[]>(
    () =>
      (data?.rows ?? []).map((row) => ({
        studentId: row.student.public_id,
        username: row.student.name,
        scores: Object.fromEntries(
          CRITERIA.map(({ key }) => [key, cell(row.mark, key)]),
        ) as Record<CriterionKey, string>,
        overall: row.mark?.overall_score == null ? "" : String(row.mark.overall_score),
        comment: row.mark?.comment ?? "",
        state: row.mark?.state ?? null,
        average: row.mark?.average == null ? null : String(row.mark.average),
      })),
    [data?.rows],
  );

  /*
   * Discard local edits when the server's copy changes underneath them.
   * Adjusting state during render is the mechanism React documents for this;
   * doing it in an effect renders the stale rows once first, which is visible
   * as a flicker on a long class.
   */
  const [seed, setSeed] = useState(initial);
  if (seed !== initial) {
    setSeed(initial);
    setRows(null);
  }

  const ceiling = data?.rows.find((row) => row.mark)?.mark?.max_score ?? 10;
  const current = rows ?? initial;

  const save = useApiMutation<ClassPerformanceMarkResponse[], Row[]>({
    mutationFn: (entries) =>
      api.put<ClassPerformanceMarkResponse[]>(
        `/class-performance/sessions/${segment(sessionId)}`,
        {
          body: {
            max_score: toValue(maxScore),
            entries: entries.map((row) => ({
              student_id: row.studentId,
              ...Object.fromEntries(
                CRITERIA.map(({ key }) => [key, toValue(row.scores[key])]),
              ),
              overall_score: toValue(row.overall),
              comment: row.comment.trim() || null,
            })),
          },
        },
      ),
    success: (result) => `Class performance saved for ${result.length} student(s).`,
    // The weighted result and the transcript both read these marks, so the
    // grade book and performance views are stale the moment this lands.
    invalidate: [["class-performance"], ["performance"], ["gradebook"], ["transcripts"]],
    onSuccess: () => setRows(null),
  });

  const release = useApiMutation<ClassPerformanceMarkResponse[], ResultState>({
    mutationFn: (state) =>
      api.post<ClassPerformanceMarkResponse[]>(
        `/class-performance/sessions/${segment(sessionId)}/state`,
        { body: { state } },
      ),
    success: (result, state) =>
      state === "PUBLISHED"
        ? `Released ${result.length} mark(s) to students and guardians.`
        : `Withdrew ${result.length} mark(s).`,
    invalidate: [["class-performance"], ["performance"], ["gradebook"], ["transcripts"]],
  });

  if (sheet.isPending) return <LoadingState rows={4} />;
  if (sheet.error) return <ErrorState error={sheet.error} onRetry={() => void sheet.refetch()} />;
  if (!data) return null;

  if (current.length === 0) {
    return (
      <CardBody>
        <p className="text-sm text-muted-foreground">
          Nobody is enrolled on this batch, so there is nobody to assess.
        </p>
      </CardBody>
    );
  }

  function update(studentId: string, patch: Partial<Row>) {
    setRows((previous) =>
      (previous ?? initial).map((row) =>
        row.studentId === studentId ? { ...row, ...patch } : row,
      ),
    );
  }

  function updateScore(studentId: string, key: CriterionKey, value: string) {
    setRows((previous) =>
      (previous ?? initial).map((row) =>
        row.studentId === studentId
          ? { ...row, scores: { ...row.scores, [key]: value } }
          : row,
      ),
    );
  }

  const dirty = rows !== null;
  const published = current.some((row) => row.state === "PUBLISHED");
  const canEdit = data.can_edit;

  return (
    <>
      <CardBody className="space-y-3">
        {!canEdit ? (
          <p className="rounded-lg border border-border-subtle bg-surface-subtle px-3 py-2 text-sm text-muted-foreground">
            Only this session&rsquo;s assigned tutor can record these marks. You are seeing them
            read-only.
          </p>
        ) : null}

        {canEdit && data.would_be_on_behalf ? (
          <p className="rounded-lg border-warning bg-warning/10 px-3 py-2 text-sm">
            You are not this session&rsquo;s assigned tutor. Anything you save here is recorded
            against your own name in the audit trail.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-muted-foreground">
            {data.marked} of {data.total} assessed
          </span>
          {data.state ? (
            <Badge className={STATE_TONE[data.state]}>{data.state.replace("_", " ")}</Badge>
          ) : data.marked > 0 ? (
            <Badge className="border-border-subtle text-muted-foreground">Mixed states</Badge>
          ) : null}
          {canEdit ? (
            <label className="ml-auto flex items-center gap-2">
              <span className="text-muted-foreground">Out of</span>
              <Input
                className="w-20"
                inputMode="decimal"
                placeholder={String(ceiling)}
                value={maxScore}
                onChange={(event) => setMaxScore(event.target.value)}
              />
            </label>
          ) : null}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="sticky left-0 bg-surface px-2 py-1.5 font-medium">Student</th>
                {CRITERIA.map(({ key, label, title }) => (
                  <th key={key} className="px-1 py-1.5 text-center font-medium" title={title}>
                    {label}
                  </th>
                ))}
                <th className="px-1 py-1.5 text-center font-medium" title="The tutor's own overall figure; leave blank to average the criteria.">
                  Overall
                </th>
                <th className="px-2 py-1.5 text-center font-medium">Score</th>
                <th className="px-2 py-1.5 font-medium">Comment</th>
              </tr>
            </thead>
            <tbody>
              {current.map((row) => {
                const locked = row.state === "PUBLISHED";
                const preview = previewAverage(row);
                return (
                  <tr key={row.studentId} className="border-t border-border-subtle">
                    <td className="sticky left-0 bg-surface px-2 py-1.5">
                      <Link
                        href={`/users/${row.studentId}`}
                        className="font-medium hover:underline"
                      >
                        {row.username}
                      </Link>
                      {row.state ? (
                        <Badge className={cn("ml-2 text-[10px]", STATE_TONE[row.state])}>
                          {row.state.replace("_", " ")}
                        </Badge>
                      ) : null}
                    </td>
                    {CRITERIA.map(({ key, title }) => (
                      <td key={key} className="px-1 py-1.5">
                        <Input
                          aria-label={`${title} for ${row.username}`}
                          className="w-14 text-center"
                          inputMode="decimal"
                          disabled={!canEdit || locked}
                          value={row.scores[key]}
                          onChange={(event) => updateScore(row.studentId, key, event.target.value)}
                        />
                      </td>
                    ))}
                    <td className="px-1 py-1.5">
                      <Input
                        aria-label={`Overall for ${row.username}`}
                        className="w-16 text-center"
                        inputMode="decimal"
                        disabled={!canEdit || locked}
                        value={row.overall}
                        onChange={(event) => update(row.studentId, { overall: event.target.value })}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      {/* Blank, never "0" -- nothing assessed is excluded from
                          the weighted result, not counted as a zero. */}
                      <span className={cn("tabular-nums", preview === null && "text-muted-foreground")}>
                        {preview ?? "—"}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <Input
                        aria-label={`Comment for ${row.username}`}
                        disabled={!canEdit || locked}
                        value={row.comment}
                        onChange={(event) => update(row.studentId, { comment: event.target.value })}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {published && canEdit ? (
          <p className="text-sm text-muted-foreground">
            Released marks are locked. Withdraw them below to correct one — somebody has already
            seen the figure, so changing it is a deliberate act.
          </p>
        ) : null}
      </CardBody>

      {canEdit ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border-subtle px-4 py-3">
          <Button
            loading={save.isPending}
            disabled={!dirty}
            onClick={() => save.mutate(current)}
          >
            <Save className="size-4" aria-hidden /> Save marks
          </Button>
          {canRelease && data.marked > 0 ? (
            published ? (
              <Button
                variant="secondary"
                loading={release.isPending}
                onClick={() => release.mutate("DRAFT")}
              >
                <EyeOff className="size-4" aria-hidden /> Withdraw
              </Button>
            ) : (
              <Button
                variant="secondary"
                loading={release.isPending}
                onClick={() => release.mutate("PUBLISHED")}
              >
                <Eye className="size-4" aria-hidden /> Release to students
              </Button>
            )
          ) : null}
          {dirty ? (
            <span className="text-sm text-muted-foreground">Unsaved changes</span>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
