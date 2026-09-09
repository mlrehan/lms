"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Eye } from "lucide-react";
import { toast } from "sonner";
import { api, downloadFile, segment, type QueryParams } from "@/lib/api/client";
import type { AuditCatalogResponse, AuditLogResponse, PageAuditLogResponse } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogHeader } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function DetailDialog({
  log,
  onClose,
}: {
  log: AuditLogResponse | null;
  onClose: () => void;
}) {
  const timeZone = useDisplayTimeZone();
  return (
    <Dialog open={log !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent size="lg">
        {log ? (
          <>
            <DialogHeader
              title={humanise(log.action)}
              description={formatDateTime(log.created_at, { timeZone })}
            />
            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-muted-foreground">Outcome</dt>
                <dd>
                  <Badge tone={log.success === false ? "danger" : "success"}>
                    {log.success === false ? "Failed" : "Succeeded"}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Actor</dt>
                <dd>
                  {log.actor_id ? (
                    <Link href={`/users/${log.actor_id}`} className="hover:underline">
                      {log.actor_username ?? log.actor_email ?? log.actor_id}
                    </Link>
                  ) : (
                    // The column is nullable on purpose: a scheduled job has
                    // no actor, and inventing one would be a lie in the record
                    // that exists precisely to be trustworthy.
                    "System (no actor)"
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Entity</dt>
                <dd className="break-words">
                  {log.entity_type ? (
                    <>
                      {humanise(log.entity_type)}
                      {log.entity_label ? ` · ${log.entity_label}` : ""}
                      {log.entity_id ? (
                        <span className="block font-mono text-xs text-muted-foreground">
                          {log.entity_id}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Request</dt>
                <dd className="font-mono text-xs break-all">{log.request_id ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">IP address</dt>
                <dd className="font-mono text-xs">{log.ip_address ?? "—"}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-muted-foreground">User agent</dt>
                <dd className="break-words text-xs">{log.user_agent ?? "—"}</dd>
              </div>
            </dl>

            {log.details && Object.keys(log.details).length > 0 ? (
              <div className="mt-4 space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Details</p>
                {/*
                  Rendered as text, never as markup. These values are written
                  by whoever performed the action -- a course title, a filename
                  -- and treating attacker-influenced content as HTML is how a
                  stored XSS lands in the one screen a security team reads.
                */}
                <pre className="max-h-72 overflow-auto scrollbar-thin whitespace-pre-wrap break-words rounded-lg border border-border bg-surface-muted p-3 font-mono text-xs">
                  {JSON.stringify(log.details, null, 2)}
                </pre>
              </div>
            ) : null}
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export default function AuditPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState();
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [success, setSuccess] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selected, setSelected] = useState<AuditLogResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const catalog = useQuery({
    queryKey: ["audit", "catalog"],
    queryFn: () => api.get<AuditCatalogResponse>("/audit-logs/catalog"),
    staleTime: 10 * 60_000,
  });

  const filters: QueryParams = {
    q: debouncedSearch || undefined,
    action: action || undefined,
    entity_type: entityType || undefined,
    success: success === "" ? undefined : success === "true",
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["audit", "list", filters, limit, offset],
    queryFn: () =>
      api.get<PageAuditLogResponse>("/audit-logs", { query: { ...filters, limit, offset } }),
  });

  async function exportCsv() {
    setExporting(true);
    try {
      await downloadFile("/audit-logs/export", "audit-log.csv", { ...filters, format: "csv" });
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "The export failed.");
    } finally {
      setExporting(false);
    }
  }

  const columns: Column<AuditLogResponse>[] = [
    {
      key: "when",
      header: "When",
      cell: (row) => (
        <span title={formatDateTime(row.created_at, { timeZone })}>
          {formatRelative(row.created_at, locale)}
        </span>
      ),
    },
    {
      key: "action",
      header: "Action",
      cell: (row) => (
        <Badge tone={row.success === false ? "danger" : "neutral"}>{humanise(row.action)}</Badge>
      ),
    },
    {
      key: "actor",
      header: "Actor",
      cell: (row) =>
        row.actor_id ? (
          <Link href={`/users/${row.actor_id}`} className="hover:underline">
            {row.actor_username ?? row.actor_email ?? "Unknown"}
          </Link>
        ) : (
          <span className="text-muted-foreground">System</span>
        ),
    },
    {
      key: "entity",
      header: "Entity",
      secondary: true,
      cell: (row) =>
        row.entity_type ? (
          <span className="block max-w-64 truncate">
            {humanise(row.entity_type)}
            {row.entity_label ? ` · ${row.entity_label}` : ""}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <Button variant="ghost" size="sm" onClick={() => setSelected(row)}>
          <Eye /> Details
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit log"
        description="Append-only. Rows cannot be edited or deleted through the API or the database role the application uses."
        actions={
          permissions.has("audit.export") ? (
            <Button variant="secondary" loading={exporting} onClick={() => void exportCsv()}>
              <Download /> Export CSV
            </Button>
          ) : null
        }
      />

      <Card>
        <CardHeader
          title="Filters"
          description="The export uses exactly the filters set here, so what you see is what you get."
        />
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Search">
            {({ id }) => (
              <Input
                id={id}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Actor, entity or details"
              />
            )}
          </Field>
          <Field label="Action">
            {({ id }) => (
              <NativeSelect
                id={id}
                value={action}
                onChange={(event) => {
                  setAction(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any action</option>
                {(catalog.data?.actions ?? []).map((value) => (
                  <option key={value} value={value}>
                    {humanise(value)}
                  </option>
                ))}
              </NativeSelect>
            )}
          </Field>
          <Field label="Entity type">
            {({ id }) => (
              <NativeSelect
                id={id}
                value={entityType}
                onChange={(event) => {
                  setEntityType(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any entity</option>
                {(catalog.data?.entity_types ?? []).map((value) => (
                  <option key={value} value={value}>
                    {humanise(value)}
                  </option>
                ))}
              </NativeSelect>
            )}
          </Field>
          <Field label="Outcome">
            {({ id }) => (
              <NativeSelect
                id={id}
                value={success}
                onChange={(event) => {
                  setSuccess(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any outcome</option>
                <option value="true">Succeeded</option>
                <option value="false">Failed</option>
              </NativeSelect>
            )}
          </Field>
          <Field label="From" hint="Interpreted by the server in UTC.">
            {({ id }) => (
              <Input
                id={id}
                type="date"
                value={dateFrom}
                onChange={(event) => {
                  setDateFrom(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          <Field label="To">
            {({ id }) => (
              <Input
                id={id}
                type="date"
                value={dateTo}
                onChange={(event) => {
                  setDateTo(event.target.value);
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
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="Nothing matches these filters."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="entries"
            />
          </>
        )}
      </Card>

      <DetailDialog log={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
