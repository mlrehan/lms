"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { ComponentLine, PerformanceResponse, StudentClassPerformanceResponse } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Field } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { cn, humanise } from "@/lib/utils";
import { BatchPicker } from "@/components/domain/entity-pickers";

/**
 * §6 and §37: the weighted picture, and how it was reached.
 *
 * The calculation engine has existed with no screen at all, which made the two
 * numbers below indistinguishable to anybody using the product:
 *
 * * `current_percentage` — the mark out of **what has been assessed so far**.
 * * `final_percentage` — null until **every** weighted component has a mark.
 *
 * They answer different questions, and showing one where the other belongs is
 * the single most misleading thing this screen could do: a student half way
 * through a course seeing 42% presented as a final result reads it as a fail.
 * So they are labelled separately and an incomplete course says so in words.
 *
 * Nothing here is computed in the browser. Every figure, including each
 * component's contribution, comes from the engine — §23, and the reason a
 * tutor's explanation to a student matches the transcript.
 */

function pct(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(2)}%`;
}

function ComponentRow({ line }: { line: ComponentLine }) {
  return (
    <tr className={cn("border-t border-border-subtle", !line.counted && "text-muted-foreground")}>
      <td className="px-2 py-1.5">
        <span className="font-medium">{line.label ?? humanise(line.component_type)}</span>
        {line.is_mandatory ? (
          <Badge className="ml-2 border-warning bg-warning/15 text-[10px] text-warning">
            Must pass
          </Badge>
        ) : null}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums">{Number(line.weight_percentage).toFixed(2)}%</td>
      <td className="px-2 py-1.5 text-right tabular-nums">
        {line.marks_scored != null && line.marks_total != null
          ? `${Number(line.marks_scored)} / ${Number(line.marks_total)}`
          : "—"}
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums">{pct(line.percentage)}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">
        {/* Blank, not 0.00: a component nobody has marked contributes nothing
            *and is excluded from the total*, which is a different statement
            from "contributed zero" (§38). */}
        {line.counted ? pct(line.contribution) : "—"}
      </td>
      <td className="px-2 py-1.5 text-xs">
        {line.counted ? (
          line.meets_component_pass === false ? (
            <span className="text-danger">Below the component pass mark</span>
          ) : (
            <span className="text-muted-foreground">Counted</span>
          )
        ) : (
          <span>{line.excluded_reason ?? "Not assessed yet"}</span>
        )}
      </td>
    </tr>
  );
}

/** §11's marks behind the one `PRACTICAL` line, fetched only when opened. */
function ClassPerformanceDetail({ studentId, batchId }: { studentId: string; batchId: string }) {
  const detail = useQuery({
    queryKey: ["class-performance", "student", studentId, batchId],
    queryFn: () =>
      api.get<StudentClassPerformanceResponse>(
        `/class-performance/students/${segment(studentId)}`,
        { query: { batch_id: batchId } },
      ),
  });

  if (detail.isPending) return <LoadingState rows={2} />;
  if (detail.error) {
    return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  }
  const marks = detail.data?.marks ?? [];
  if (marks.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No class performance has been recorded for this student yet.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        {marks.length} class(es) assessed — average {pct(detail.data?.average)}
      </p>
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle text-sm">
        {marks.map((mark) => (
          <li key={mark.public_id} className="flex flex-wrap items-center gap-3 px-3 py-1.5">
            <span className="tabular-nums">
              {mark.average == null ? "—" : `${Number(mark.average)} / ${Number(mark.max_score)}`}
            </span>
            <Badge className="text-[10px]">{(mark.state ?? "DRAFT").replace("_", " ")}</Badge>
            {mark.comment ? (
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{mark.comment}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StudentBreakdown({ row, batchId }: { row: PerformanceResponse; batchId: string }) {
  const [showClasses, setShowClasses] = useState(false);
  const hasPractical = row.components.some((line) => line.component_type === "PRACTICAL");

  return (
    <div className="space-y-3 border-t border-border-subtle bg-surface-subtle/40 px-4 py-3">
      {row.unconfigured ? (
        <p className="flex items-start gap-2 rounded-lg border border-warning bg-warning/10 px-3 py-2 text-sm">
          <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            This course has no grading scheme with weightings, so there is nothing to compute
            from. Set one up on the Grading schemes screen.
          </span>
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th className="px-2 py-1 text-left font-medium">Component</th>
              <th className="px-2 py-1 text-right font-medium">Weight</th>
              <th className="px-2 py-1 text-right font-medium">Marks</th>
              <th className="px-2 py-1 text-right font-medium">Scored</th>
              <th className="px-2 py-1 text-right font-medium">Contributes</th>
              <th className="px-2 py-1 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {row.components.map((line) => (
              <ComponentRow key={`${line.component_type}-${line.label ?? ""}`} line={line} />
            ))}
          </tbody>
        </table>
      </div>

      <dl className="grid gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted-foreground">Assessed so far</dt>
          <dd className="tabular-nums">
            {Number(row.assessed_weight ?? 0).toFixed(2)}% of{" "}
            {Number(row.total_weight ?? 0).toFixed(2)}%
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Standing so far</dt>
          <dd className="tabular-nums">{pct(row.current_percentage)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Final result</dt>
          <dd className="tabular-nums">
            {row.final_percentage == null ? (
              <span className="text-muted-foreground">Course incomplete</span>
            ) : (
              pct(row.final_percentage)
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Attendance</dt>
          <dd className="tabular-nums">
            {pct(row.attendance_percentage)}
            {row.sessions_total ? (
              <span className="ml-1 text-xs text-muted-foreground">
                ({row.sessions_attended ?? 0}/{row.sessions_total})
              </span>
            ) : null}
          </dd>
        </div>
      </dl>

      {row.failed_mandatory && row.failed_mandatory.length > 0 ? (
        <p className="rounded-lg border border-danger bg-danger/10 px-3 py-2 text-sm">
          Below the pass mark on a component that must be passed:{" "}
          {row.failed_mandatory.map((name) => humanise(name)).join(", ")}.
        </p>
      ) : null}

      {row.scheme_name ? (
        <p className="text-xs text-muted-foreground">
          Computed under &ldquo;{row.scheme_name}&rdquo;.
        </p>
      ) : null}

      {hasPractical ? (
        <div>
          <button
            type="button"
            className="flex items-center gap-1 text-sm font-medium hover:underline"
            onClick={() => setShowClasses((open) => !open)}
          >
            {showClasses ? (
              <ChevronDown className="size-4" aria-hidden />
            ) : (
              <ChevronRight className="size-4" aria-hidden />
            )}
            Class-by-class performance
          </button>
          {showClasses ? (
            <div className="mt-2">
              <ClassPerformanceDetail studentId={row.student_id} batchId={batchId} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function PerformancePage() {
  const { permissions } = useSession();
  const [batchId, setBatchId] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const rows = useQuery({
    queryKey: ["performance", "batch", batchId],
    queryFn: () =>
      api.get<PerformanceResponse[]>(`/performance/batches/${segment(batchId)}`),
    enabled: batchId !== "",
  });

  if (!permissions.has("performance.read")) {
    return (
      <EmptyState
        title="Not available"
        description="You do not have permission to view calculated performance."
      />
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Performance"
        description="The weighted standing of every student in a batch, and the arithmetic behind it."
      />

      <Card>
        <CardBody>
          <Field label="Batch">
            {({ id }) => (
              <BatchPicker id={id} value={(batchId) || null} onValueChange={(next) => {
                  setBatchId((next ?? ""));
                  setOpen(null);
                }} placeholder="Choose a batch…" clearable />
            )}
          </Field>
        </CardBody>
      </Card>

      {batchId === "" ? (
        <EmptyState
          title="Choose a batch"
          description="Performance is computed per batch, because the weighting comes from the course's grading scheme."
        />
      ) : rows.isPending ? (
        <LoadingState rows={6} />
      ) : rows.error ? (
        <ErrorState error={rows.error} onRetry={() => void rows.refetch()} />
      ) : (rows.data ?? []).length === 0 ? (
        <EmptyState
          title="Nobody to report on"
          description="No students on this batch are visible to you, or none are actively enrolled."
        />
      ) : (
        <Card>
          <CardHeader
            title="Students"
            description="Open a row to see every component, its weight and what it contributed."
          />
          <ul className="divide-y divide-border-subtle">
            {(rows.data ?? []).map((row) => {
              const isOpen = open === row.student_id;
              return (
                <li key={row.student_id}>
                  <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                    <button
                      type="button"
                      className="flex min-w-48 flex-1 items-center gap-1 text-left text-sm font-medium hover:underline"
                      onClick={() => setOpen(isOpen ? null : row.student_id)}
                      aria-expanded={isOpen}
                    >
                      {isOpen ? (
                        <ChevronDown className="size-4 shrink-0" aria-hidden />
                      ) : (
                        <ChevronRight className="size-4 shrink-0" aria-hidden />
                      )}
                      {row.student_name ?? row.student_id}
                    </button>

                    <span className="tabular-nums text-sm" title="Out of what has been assessed so far">
                      {pct(row.current_percentage)}
                      <span className="ml-1 text-xs text-muted-foreground">so far</span>
                    </span>

                    <span className="tabular-nums text-sm" title="Null until every weighted component has a mark">
                      {row.final_percentage == null ? (
                        <span className="text-xs text-muted-foreground">incomplete</span>
                      ) : (
                        <>
                          {pct(row.final_percentage)}
                          <span className="ml-1 text-xs text-muted-foreground">final</span>
                        </>
                      )}
                    </span>

                    {row.grade ? (
                      <Badge
                        className={cn(
                          row.is_pass === false
                            ? "border-danger bg-danger/15 text-danger"
                            : "border-success bg-success/15 text-success",
                        )}
                      >
                        {row.grade}
                      </Badge>
                    ) : null}

                    <Link
                      href={`/users/${row.student_id}`}
                      className="text-xs text-muted-foreground hover:underline"
                    >
                      Profile
                    </Link>
                  </div>
                  {isOpen ? <StudentBreakdown row={row} batchId={batchId} /> : null}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
