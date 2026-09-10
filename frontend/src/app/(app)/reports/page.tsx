"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, downloadFile, type QueryParams } from "@/lib/api/client";
import type { ReportResponse } from "@/lib/api/types";
import {
  AttendanceGroupByValues,
  EnrollmentGroupByValues,
  PerformanceGroupByValues,
} from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

type ReportKind = "attendance" | "enrollment" | "performance";

const GROUPS: Record<ReportKind, readonly string[]> = {
  attendance: AttendanceGroupByValues,
  enrollment: EnrollmentGroupByValues,
  performance: PerformanceGroupByValues,
};

const DESCRIPTIONS: Record<ReportKind, string> = {
  attendance: "Present, late, absent and excused counts, and the resulting rate.",
  enrollment: "How many enrollments exist, grouped as you choose.",
  performance: "Scores and pass rates across the grade book.",
};

/** Colours are read from the theme so the chart follows light/dark. */
const BAR_COLOR = "var(--primary)";

function ReportPanel({ kind }: { kind: ReportKind }) {
  const timeZone = useDisplayTimeZone();
  const { permissions } = useSession();
  const [groupBy, setGroupBy] = useState(GROUPS[kind][0] as string);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [exporting, setExporting] = useState(false);

  const supportsDates = kind !== "performance";
  const supportsBatch = kind !== "enrollment";

  const filters: QueryParams = {
    group_by: groupBy,
    date_from: supportsDates && dateFrom ? dateFrom : undefined,
    date_to: supportsDates && dateTo ? dateTo : undefined,
    course_id: courseId || undefined,
    batch_id: supportsBatch && batchId ? batchId : undefined,
  };

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["reports", kind, filters],
    queryFn: () =>
      api.get<ReportResponse>(`/reports/${kind}`, { query: { ...filters, format: "json" } }),
  });

  async function exportCsv() {
    setExporting(true);
    try {
      await downloadFile(`/reports/${kind}`, `${kind}-report.csv`, { ...filters, format: "csv" });
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "The export failed.");
    } finally {
      setExporting(false);
    }
  }

  // The first numeric column is the one worth charting; the rest stay in the
  // table. Guessing at more than one would produce a chart nobody asked for.
  const chartMetric = data?.columns?.[0];
  const chartData =
    data && chartMetric
      ? data.rows.map((row) => ({ label: row.label, value: row.metrics[chartMetric] ?? 0 }))
      : [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Filters"
          actions={
            permissions.has("report.export") ? (
              <Button variant="secondary" size="sm" loading={exporting} onClick={() => void exportCsv()}>
                <Download /> Export CSV
              </Button>
            ) : null
          }
        />
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Group by">
            {({ id }) => (
              <NativeSelect
                id={id}
                value={groupBy}
                onChange={(event) => setGroupBy(event.target.value)}
              >
                {GROUPS[kind].map((value) => (
                  <option key={value} value={value}>
                    {humanise(value)}
                  </option>
                ))}
              </NativeSelect>
            )}
          </Field>
          {supportsDates ? (
            <>
              <Field label="From">
                {({ id }) => (
                  <Input
                    id={id}
                    type="date"
                    value={dateFrom}
                    onChange={(event) => setDateFrom(event.target.value)}
                  />
                )}
              </Field>
              <Field label="To">
                {({ id }) => (
                  <Input
                    id={id}
                    type="date"
                    value={dateTo}
                    onChange={(event) => setDateTo(event.target.value)}
                  />
                )}
              </Field>
            </>
          ) : null}
          <Field label="Course id" hint="Optional.">
            {({ id }) => (
              <Input
                id={id}
                value={courseId}
                onChange={(event) => setCourseId(event.target.value.trim())}
              />
            )}
          </Field>
          {supportsBatch ? (
            <Field label="Batch id" hint="Optional.">
              {({ id }) => (
                <Input
                  id={id}
                  value={batchId}
                  onChange={(event) => setBatchId(event.target.value.trim())}
                />
              )}
            </Field>
          ) : null}
        </div>
      </Card>

      {isPending ? (
        <LoadingState rows={6} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data ? (
        <>
          {data.truncated ? (
            <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning-foreground dark:text-warning">
              This result hit the server&rsquo;s group cap and is incomplete. Narrow the filters to
              see the rest.
            </p>
          ) : null}

          {chartData.length > 0 ? (
            <Card>
              <CardHeader
                title={humanise(chartMetric ?? "")}
                description={`Grouped by ${humanise(data.group_by)}.`}
              />
              <CardBody>
                <div className="h-72 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        tickLine={false}
                        axisLine={{ stroke: "var(--border)" }}
                        interval="preserveStartEnd"
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                        tickLine={false}
                        axisLine={false}
                        width={48}
                      />
                      <RechartsTooltip
                        cursor={{ fill: "var(--muted)" }}
                        contentStyle={{
                          background: "var(--surface)",
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                      <Bar dataKey="value" fill={BAR_COLOR} radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardBody>
            </Card>
          ) : null}

          <Card>
            <CardHeader
              title={`${humanise(data.report)} report`}
              description={
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{data.rows.length} groups</Badge>
                  <span className="text-xs">
                    Generated {formatDateTime(data.generated_at, { timeZone })}
                  </span>
                </span>
              }
            />
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {humanise(data.group_by)}
                    </th>
                    {data.columns.map((column) => (
                      <th
                        key={column}
                        className="whitespace-nowrap px-4 py-2 text-right text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                      >
                        {humanise(column)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={data.columns.length + 1}
                        className="px-4 py-10 text-center text-sm text-muted-foreground"
                      >
                        Nothing matches these filters.
                      </td>
                    </tr>
                  ) : (
                    data.rows.map((row) => (
                      <tr key={row.key} className="border-b border-border/70 last:border-0">
                        <th scope="row" className="px-4 py-2 text-left font-normal">
                          {row.label}
                        </th>
                        {data.columns.map((column) => (
                          <td key={column} className="px-4 py-2 text-right tabular-nums">
                            {/*
                              `null` is not zero: it means the metric is not
                              computable for this group, e.g. an attendance
                              rate where nothing has been recorded.
                            */}
                            {row.metrics[column] === null || row.metrics[column] === undefined
                              ? "—"
                              : row.metrics[column]?.toLocaleString()}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}

export default function ReportsPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Reports"
        description="Aggregates computed by the server, scoped to what you are allowed to see."
      />

      <Tabs defaultValue="attendance">
        <TabsList>
          <TabsTab value="attendance">Attendance</TabsTab>
          <TabsTab value="enrollment">Enrollment</TabsTab>
          <TabsTab value="performance">Performance</TabsTab>
        </TabsList>
        {(["attendance", "enrollment", "performance"] as const).map((kind) => (
          <TabsPanel key={kind} value={kind}>
            <p className="mb-3 text-sm text-muted-foreground">{DESCRIPTIONS[kind]}</p>
            <ReportPanel kind={kind} />
          </TabsPanel>
        ))}
      </Tabs>
    </div>
  );
}
