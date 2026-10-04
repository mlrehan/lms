"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Lock, Printer } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { TranscriptResponse } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

/**
 * The official document (spec §5), laid out to be printed.
 *
 * **Nothing here is recomputed.** Every figure is read straight off the stored
 * transcript, including `breakdown`, which was frozen when the record was
 * issued. That is the whole reason those columns exist: a transcript that
 * restated itself when a tutor corrected a register, or when the institution
 * changed its weighting, would invalidate a document somebody has already
 * relied on. So this page renders what was certified, not what is true today.
 *
 * **Access is the backend's decision, not this page's.** `GET /transcripts/{id}`
 * already scopes to the students the caller may see and hides a provisional
 * record from anybody without the marking grant, so there is no permission check
 * here to drift out of step with it — an unauthorised id is a 404 and this page
 * shows the error (§46: no frontend-only enforcement).
 *
 * **Print rather than a generated PDF.** The browser's own print-to-PDF produces
 * a file the registrar can save, email or put on headed paper, keeps the text
 * selectable and searchable, and needs no rendering service to keep alive. A
 * `@media print` block below drops the chrome.
 */

function pct(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(2)}%`;
}

interface BreakdownLine {
  component?: string;
  label?: string | null;
  percentage?: string | null;
  weight?: string | null;
  contribution?: string | null;
  counted?: boolean;
  reason?: string | null;
}

export default function TranscriptDocumentPage({
  params,
}: {
  params: Promise<{ transcriptId: string }>;
}) {
  const { transcriptId } = use(params);
  const timeZone = useDisplayTimeZone();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["transcripts", transcriptId],
    queryFn: () =>
      api.get<TranscriptResponse>(`/transcripts/${segment(transcriptId)}`),
  });

  if (isPending) return <LoadingState rows={8} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const lines = (data.breakdown ?? []) as BreakdownLine[];

  return (
    <div className="space-y-4">
      <style>{`
        @media print {
          /* Everything outside the document itself: navigation, the app shell,
             and this page's own controls. */
          body * { visibility: hidden; }
          #transcript-document, #transcript-document * { visibility: visible; }
          #transcript-document {
            position: absolute; inset: 0;
            margin: 0; padding: 0;
            border: none; box-shadow: none;
          }
          .print-hide { display: none !important; }
        }
      `}</style>

      <div className="print-hide flex flex-wrap items-center gap-2">
        <Link href="/transcripts">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="size-4" aria-hidden /> All transcripts
          </Button>
        </Link>
        <div className="ml-auto flex items-center gap-2">
          {data.is_final ? (
            <Badge tone="success">
              <Lock className="size-3" aria-hidden /> Final
            </Badge>
          ) : (
            <Badge tone="neutral">Provisional</Badge>
          )}
          <Button onClick={() => window.print()}>
            <Printer className="size-4" aria-hidden /> Print / Save as PDF
          </Button>
        </div>
      </div>

      {!data.is_final ? (
        <p className="print-hide rounded-lg border border-warning bg-warning/10 px-3 py-2 text-sm">
          This transcript has not been finalised. It can still be regenerated, and
          nobody has certified it — printing it now produces a draft, not an
          official record.
        </p>
      ) : null}

      <Card id="transcript-document" className="mx-auto max-w-3xl p-8 print:p-0">
        <header className="border-b border-border-strong pb-4 text-center">
          <h1 className="text-xl font-semibold tracking-wide">Academic Transcript</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data.course_title ?? "—"}
            {data.batch_code ? ` · ${data.batch_code}` : ""}
          </p>
          {!data.is_final ? (
            <p className="mt-2 text-sm font-semibold uppercase tracking-widest text-warning">
              Provisional — not certified
            </p>
          ) : null}
        </header>

        <dl className="grid gap-3 py-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Student</dt>
            <dd className="font-medium">{data.student_username ?? data.student_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Batch</dt>
            <dd>{data.batch_code ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Issued</dt>
            <dd>
              {data.issued_at
                ? formatDateTime(data.issued_at, { timeZone })
                : "Not yet issued"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Certified by</dt>
            {/* §5's verification. Blank while provisional -- nobody has stood
                behind these figures yet, and naming whoever pressed
                "generate" would imply somebody had. */}
            <dd>{data.issued_by_username ?? "—"}</dd>
          </div>
        </dl>

        {lines.length > 0 ? (
          <table className="w-full border-t border-border-subtle text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground">
                <th className="py-2 text-left font-medium">Component</th>
                <th className="py-2 text-right font-medium">Weight</th>
                <th className="py-2 text-right font-medium">Scored</th>
                <th className="py-2 text-right font-medium">Contributed</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, index) => (
                <tr
                  key={`${line.component ?? "line"}-${index}`}
                  className="border-t border-border-subtle"
                >
                  <td className="py-1.5">
                    {line.label ?? humanise(line.component ?? "")}
                    {line.counted === false ? (
                      <span className="ml-2 text-xs text-muted-foreground">
                        ({line.reason ?? "not assessed"})
                      </span>
                    ) : null}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{pct(line.weight)}</td>
                  <td className="py-1.5 text-right tabular-nums">{pct(line.percentage)}</td>
                  {/* Blank for an excluded component, never 0.00 -- it was left
                      out of the total, which is a different statement (§38). */}
                  <td className="py-1.5 text-right tabular-nums">
                    {line.counted === false ? "—" : pct(line.contribution)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="border-t border-border-subtle py-3 text-sm text-muted-foreground">
            No component breakdown was recorded for this transcript.
          </p>
        )}

        <dl className="grid gap-3 border-t border-border-strong py-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-foreground">Final result</dt>
            <dd className="text-lg font-semibold tabular-nums">
              {data.final_percentage == null ? (
                <span className="text-base font-normal text-muted-foreground">
                  Course incomplete
                </span>
              ) : (
                pct(data.final_percentage)
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Grade</dt>
            <dd className="text-lg font-semibold">{data.overall_grade ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">GPA</dt>
            <dd className="text-lg font-semibold tabular-nums">{data.gpa ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Outcome</dt>
            <dd className="text-lg font-semibold">
              {data.is_pass == null ? "—" : data.is_pass ? "Pass" : "Fail"}
            </dd>
          </div>
        </dl>

        <dl className="grid gap-3 border-t border-border-subtle py-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted-foreground">Attendance</dt>
            <dd className="tabular-nums">
              {pct(data.attendance_percentage)}
              {data.sessions_total ? (
                <span className="ml-1 text-xs text-muted-foreground">
                  ({data.sessions_attended ?? 0} of {data.sessions_total})
                </span>
              ) : null}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Marks</dt>
            <dd className="tabular-nums">
              {data.total_marks_earned == null
                ? "—"
                : `${Number(data.total_marks_earned)} of ${Number(
                    data.total_marks_possible ?? 0,
                  )}`}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Grading policy</dt>
            {/* Schemes change. A transcript that cannot say which policy
                produced its figures cannot be defended at an appeal. */}
            <dd>{data.scheme_name ?? "—"}</dd>
          </div>
        </dl>

        <footer className="border-t border-border-subtle pt-3 text-xs text-muted-foreground">
          <p>
            Computed {formatDateTime(data.generated_at, { timeZone })}
            {data.scheme_name ? ` under "${data.scheme_name}"` : ""}. Figures are as
            they stood when this record was issued and do not change afterwards.
          </p>
          <p className="mt-1 font-mono">Reference {data.public_id}</p>
        </footer>
      </Card>
    </div>
  );
}
