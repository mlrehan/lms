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
import { Select } from "@/components/ui/select";
import { Badge, Card, CardBody, CardHeader, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { Field, Input } from "@/components/ui/form";
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
              <Select
                id={id}
                value={groupBy}
                onValueChange={(next) => setGroupBy((next ?? ""))}
               options={GROUPS[kind].map((value) => ({ value: value, label: humanise(value) }))} />
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
            <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
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
                    {/*
                      `barCategoryGap` keeps a visible surface gap between adjacent bars, and
                      `maxBarSize` stops three groups rendering as three slabs the width of the
                      panel. A magnitude chart is read along the tops of the bars; their width
                      carries no information, so it should not dominate the panel.
                    */}
                    <BarChart
                      data={chartData}
                      margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
                      barCategoryGap="28%"
                    >
                      {/* Solid hairline, not a dashed rule: dashes are texture competing with
                          the data, and the grid's job is to recede. */}
                      <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 11, fill: "var(--subtle-foreground)" }}
                        tickLine={false}
                        axisLine={{ stroke: "var(--border-subtle)" }}
                        interval="preserveStartEnd"
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: "var(--subtle-foreground)" }}
                        tickLine={false}
                        axisLine={false}
                        width={44}
                        allowDecimals={false}
                      />
                      <RechartsTooltip
                        cursor={{ fill: "var(--muted)", radius: 4 }}
                        contentStyle={{
                          background: "var(--overlay)",
                          border: "1px solid var(--border-subtle)",
                          borderRadius: 8,
                          boxShadow: "var(--elevation-overlay)",
                          fontSize: 12,
                          padding: "6px 10px",
                        }}
                        labelStyle={{ color: "var(--foreground)", fontWeight: 600, marginBottom: 2 }}
                        itemStyle={{ color: "var(--muted-foreground)" }}
                      />
                      <Bar dataKey="value" fill={BAR_COLOR} radius={[4, 4, 0, 0]} maxBarSize={48} />
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
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <th className="eyebrow px-4 py-2 text-left">
                      {humanise(data.group_by)}
                    </th>
                    {data.columns.map((column) => (
                      <th
                        key={column}
                        className="eyebrow whitespace-nowrap px-4 py-2 text-right"
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
                        className="px-4 py-12 text-center text-xs text-subtle-foreground"
                      >
                        Nothing matches these filters.
                      </td>
                    </tr>
                  ) : (
                    data.rows.map((row) => (
                      <tr
                        key={row.key}
                        className="border-b border-border-subtle transition-colors duration-200 ease-out last:border-0 hover:bg-surface-muted/60"
                      >
                        <th scope="row" className="px-4 py-1.5 text-left font-medium">
                          {row.label}
                        </th>
                        {data.columns.map((column) => (
                          <td key={column} className="px-4 py-1.5 text-right tabular-nums">
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
