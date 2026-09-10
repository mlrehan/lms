"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Database, Gauge, RefreshCw } from "lucide-react";
import { api } from "@/lib/api/client";
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
import { Column, DataTable } from "@/components/ui/data-table";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

/*
 * The ops endpoints return untyped JSON (`dict[str, Any]` on the server), so
 * these local shapes describe what the service actually builds rather than
 * pretending the OpenAPI document constrains them. Every field is optional:
 * a diagnostic endpoint that omits a section under load must not blank the
 * page.
 */

interface HealthResponse {
  status?: string;
  checked_at?: string;
  checks?: Record<string, { ok?: boolean; latency_ms?: number; backend?: string; error?: string }>;
}

interface RouteMetric {
  method: string;
  route: string;
  requests: number;
  errors: number;
  client_errors: number;
  average_ms: number;
  max_ms: number;
  buckets: Record<string, number>;
}

interface MetricsResponse {
  uptime_seconds?: number;
  total_requests?: number;
  total_errors?: number;
  routes?: RouteMetric[];
  scope?: string;
}

interface TableStat {
  table: string;
  live_rows: number;
  dead_rows: number;
  seq_scans: number;
  index_scans: number;
  size: string;
  size_bytes: number;
  mostly_sequential: boolean;
}

interface DatabaseResponse {
  captured_at?: string;
  size?: { bytes?: number; pretty?: string };
  connections?: Record<string, unknown>;
  pool?: Record<string, unknown>;
  tables?: TableStat[];
  unused_indexes?: { index?: string; table?: string; size?: string }[];
  statement_timing?: Record<string, unknown>;
}

function KeyValues({ value }: { value: Record<string, unknown> | undefined }) {
  if (!value || Object.keys(value).length === 0) {
    return <p className="text-sm text-muted-foreground">Not reported.</p>;
  }
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt className="text-xs text-muted-foreground">{key}</dt>
          <dd className="break-words font-mono text-xs">
            {typeof item === "object" && item !== null ? JSON.stringify(item) : String(item)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Health() {
  const timeZone = useDisplayTimeZone();
  const { data, isPending, error, refetch, isFetching } = useQuery({
    queryKey: ["ops", "health"],
    queryFn: () => api.get<HealthResponse>("/ops/health"),
    refetchInterval: 30_000,
  });

  if (isPending) return <LoadingState rows={3} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  return (
    <Card>
      <CardHeader
        title="Dependency health"
        description={
          data?.checked_at ? `Checked ${formatDateTime(data.checked_at, { timeZone })}.` : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={data?.status === "ok" ? "success" : "warning"}>
              {data?.status ?? "unknown"}
            </Badge>
            <Button variant="ghost" size="sm" loading={isFetching} onClick={() => void refetch()}>
              <RefreshCw /> Refresh
            </Button>
          </div>
        }
      />
      <CardBody className="space-y-3">
        {Object.entries(data?.checks ?? {}).map(([name, check]) => (
          <div
            key={name}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2"
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              {name === "database" ? (
                <Database className="size-4 text-muted-foreground" aria-hidden />
              ) : (
                <Activity className="size-4 text-muted-foreground" aria-hidden />
              )}
              {name}
            </span>
            <span className="flex items-center gap-2 text-xs">
              {check.latency_ms !== undefined ? (
                <span className="tabular-nums text-muted-foreground">{check.latency_ms} ms</span>
              ) : null}
              {check.backend ? <Badge tone="neutral">{check.backend}</Badge> : null}
              {check.error ? <span className="text-danger">{check.error}</span> : null}
              <Badge tone={check.ok ? "success" : "danger"}>{check.ok ? "OK" : "Failing"}</Badge>
            </span>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function Metrics() {
  const { data, isPending, error, refetch, isFetching } = useQuery({
    queryKey: ["ops", "metrics"],
    queryFn: () => api.get<MetricsResponse>("/ops/metrics"),
    refetchInterval: 30_000,
  });

  if (isPending) return <LoadingState rows={4} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const columns: Column<RouteMetric>[] = [
    {
      key: "route",
      header: "Route",
      cell: (row) => (
        <span className="font-mono text-xs">
          <Badge tone="neutral">{row.method}</Badge> {row.route}
        </span>
      ),
    },
    {
      key: "requests",
      header: "Requests",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.requests.toLocaleString()}</span>,
    },
    {
      key: "errors",
      header: "5xx",
      align: "right",
      cell: (row) => (
        <span className={`tabular-nums ${row.errors > 0 ? "font-medium text-danger" : ""}`}>
          {row.errors}
        </span>
      ),
    },
    {
      key: "client",
      header: "4xx",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.client_errors}</span>,
    },
    {
      key: "avg",
      header: "Average",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.average_ms} ms</span>,
    },
    {
      key: "max",
      header: "Slowest",
      align: "right",
      cell: (row) => (
        <span className={`tabular-nums ${row.max_ms > 2500 ? "font-medium text-warning" : ""}`}>
          {row.max_ms} ms
        </span>
      ),
    },
    {
      key: "buckets",
      header: "Distribution",
      secondary: true,
      cell: (row) => (
        <span className="flex gap-1 text-[10px] text-muted-foreground">
          {Object.entries(row.buckets).map(([bound, count]) => (
            <span key={bound} className="rounded bg-muted px-1 py-0.5 tabular-nums">
              {bound}: {count}
            </span>
          ))}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <StatGrid>
        <Stat
          label="Uptime"
          value={data?.uptime_seconds ? `${Math.round(data.uptime_seconds / 60)} min` : null}
          icon={Gauge}
        />
        <Stat label="Requests" value={data?.total_requests} icon={Activity} />
        <Stat
          label="Server errors"
          value={data?.total_errors}
          tone={data?.total_errors ? "danger" : "default"}
        />
        <Stat label="Routes seen" value={data?.routes?.length ?? 0} />
      </StatGrid>

      {data?.scope ? (
        <p className="rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-muted-foreground">
          {data.scope}
        </p>
      ) : null}

      <Card>
        <CardHeader
          title="By route"
          actions={
            <Button variant="ghost" size="sm" loading={isFetching} onClick={() => void refetch()}>
              <RefreshCw /> Refresh
            </Button>
          }
        />
        <DataTable
          columns={columns}
          rows={data?.routes ?? []}
          rowKey={(row) => `${row.method} ${row.route}`}
          emptyMessage="No requests recorded since this process started."
        />
      </Card>
    </div>
  );
}

function DatabasePanel() {
  const timeZone = useDisplayTimeZone();
  const [limit, setLimit] = useState(15);

  const { data, isPending, error, refetch, isFetching } = useQuery({
    queryKey: ["ops", "database", limit],
    queryFn: () => api.get<DatabaseResponse>("/ops/database", { query: { limit } }),
  });

  if (isPending) return <LoadingState rows={5} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const tableColumns: Column<TableStat>[] = [
    {
      key: "table",
      header: "Table",
      cell: (row) => (
        <span className="flex items-center gap-2 font-mono text-xs">
          {row.table}
          {row.mostly_sequential ? <Badge tone="warning">Mostly sequential</Badge> : null}
        </span>
      ),
    },
    {
      key: "rows",
      header: "Live rows",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.live_rows.toLocaleString()}</span>,
    },
    {
      key: "dead",
      header: "Dead rows",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.dead_rows.toLocaleString()}</span>,
    },
    {
      key: "seq",
      header: "Seq scans",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.seq_scans.toLocaleString()}</span>,
    },
    {
      key: "idx",
      header: "Index scans",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.index_scans.toLocaleString()}</span>,
    },
    { key: "size", header: "Size", align: "right", cell: (row) => row.size },
  ];

  return (
    <div className="space-y-4">
      <StatGrid>
        <Stat label="Database size" value={data?.size?.pretty ?? null} icon={Database} />
        <Stat label="Tables listed" value={data?.tables?.length ?? 0} />
        <Stat
          label="Unused indexes"
          value={data?.unused_indexes?.length ?? 0}
          tone={(data?.unused_indexes?.length ?? 0) > 0 ? "warning" : "default"}
        />
        <Stat
          label="Captured"
          value={data?.captured_at ? formatDateTime(data.captured_at, { timeZone }) : null}
        />
      </StatGrid>

      <p className="rounded-lg border border-border bg-surface-muted px-3 py-2 text-sm text-muted-foreground">
        Diagnostic, not authoritative. The <code className="font-mono text-xs">pg_stat_*</code>{" "}
        counters reset on <code className="font-mono text-xs">pg_stat_reset()</code> and after a
        crash, so &ldquo;never used&rdquo; means &ldquo;not since they were last reset&rdquo;.
      </p>

      <Card>
        <CardHeader
          title="Largest tables"
          actions={
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground" htmlFor="ops-limit">
                Show
              </label>
              <select
                id="ops-limit"
                className="h-8 rounded-md border border-border-strong bg-surface px-2 text-xs"
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
              >
                {[10, 15, 25, 50].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              <Button variant="ghost" size="sm" loading={isFetching} onClick={() => void refetch()}>
                <RefreshCw />
              </Button>
            </div>
          }
        />
        <DataTable
          columns={tableColumns}
          rows={data?.tables ?? []}
          rowKey={(row) => row.table}
          emptyMessage="No table statistics reported."
        />
      </Card>

      <Card>
        <CardHeader
          title="Unused indexes"
          description="Indexes with no recorded scans. They cost write time and disk; confirm against a full statistics window before dropping one."
        />
        {(data?.unused_indexes?.length ?? 0) === 0 ? (
          <CardBody>
            <p className="text-sm text-muted-foreground">None reported.</p>
          </CardBody>
        ) : (
          <ul className="divide-y divide-border">
            {(data?.unused_indexes ?? []).map((index, position) => (
              <li
                key={`${index.index ?? position}`}
                className="flex items-center justify-between gap-2 px-4 py-2 text-sm"
              >
                <span className="font-mono text-xs">{index.index}</span>
                <span className="text-xs text-muted-foreground">
                  {index.table} · {index.size}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Connections" />
          <CardBody>
            <KeyValues value={data?.connections} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Connection pool" />
          <CardBody>
            <KeyValues value={data?.pool} />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Statement timing"
          description="Needs pg_stat_statements in shared_preload_libraries, which requires a server restart."
        />
        <CardBody>
          <KeyValues value={data?.statement_timing} />
        </CardBody>
      </Card>
    </div>
  );
}

export default function OpsPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Operations"
        description="Per-process health, request metrics and database diagnostics. Reset by a restart, and each worker answers about itself."
      />

      <Tabs defaultValue="health">
        <TabsList>
          <TabsTab value="health">Health</TabsTab>
          <TabsTab value="metrics">Request metrics</TabsTab>
          <TabsTab value="database">Database</TabsTab>
        </TabsList>
        <TabsPanel value="health">
          <Health />
        </TabsPanel>
        <TabsPanel value="metrics">
          <Metrics />
        </TabsPanel>
        <TabsPanel value="database">
          <DatabasePanel />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
