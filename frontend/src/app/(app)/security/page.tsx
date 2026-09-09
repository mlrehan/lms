"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, KeyRound, Lock, LogOut, Repeat, ShieldCheck, Unlock, Users } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  AdminSessionResponse,
  AuditLogResponse,
  LockedAccountResponse,
  PageAdminSessionResponse,
  PageAuditLogResponse,
  PageLockedAccountResponse,
  RevocationResponse,
  SecuritySummaryResponse,
  UnlockResponse,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog, useConfirm } from "@/components/confirm-dialog";
import { Input, NativeSelect } from "@/components/ui/form";
import { Stat, StatGrid } from "@/components/ui/stat";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function Summary() {
  const [hours, setHours] = useState(24);
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["security", "summary", hours],
    queryFn: () => api.get<SecuritySummaryResponse>("/security/summary", { query: { hours } }),
  });

  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <label htmlFor="window" className="text-sm text-muted-foreground">
          Window
        </label>
        <NativeSelect
          id="window"
          className="w-auto"
          value={hours}
          onChange={(event) => setHours(Number(event.target.value))}
        >
          {[1, 6, 24, 72, 168].map((value) => (
            <option key={value} value={value}>
              Last {value} hour{value === 1 ? "" : "s"}
            </option>
          ))}
        </NativeSelect>
      </div>

      <StatGrid>
        <Stat
          label="Failed sign-ins"
          value={data?.failed_logins}
          icon={AlertTriangle}
          loading={isPending}
          tone={data && data.failed_logins > 20 ? "warning" : "default"}
        />
        <Stat
          label="Locked accounts now"
          value={data?.accounts_locked_now}
          icon={Lock}
          loading={isPending}
          tone={data && data.accounts_locked_now > 0 ? "warning" : "default"}
        />
        <Stat label="Lockout events" value={data?.lockout_events} icon={Lock} loading={isPending} />
        <Stat
          label="Token reuse detections"
          value={data?.token_reuse_detections}
          icon={Repeat}
          loading={isPending}
          // A refresh token presented twice is either a bug or a stolen
          // credential. Neither is routine, so any non-zero value is red.
          tone={data && data.token_reuse_detections > 0 ? "danger" : "default"}
          hint="A rotating refresh token presented twice. Never expected."
        />
      </StatGrid>
      <StatGrid>
        <Stat
          label="Permission changes"
          value={data?.permission_changes}
          icon={KeyRound}
          loading={isPending}
        />
        <Stat label="Active sessions" value={data?.active_sessions} icon={Users} loading={isPending} />
      </StatGrid>
    </div>
  );
}

function LockedAccounts() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [includeExpired, setIncludeExpired] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["security", "locked", includeExpired, limit, offset],
    queryFn: () =>
      api.get<PageLockedAccountResponse>("/security/locked-accounts", {
        query: { include_expired: includeExpired, limit, offset },
      }),
  });

  const unlock = useApiMutation<UnlockResponse, string>({
    mutationFn: (userId) => api.post<UnlockResponse>(`/security/accounts/${segment(userId)}/unlock`),
    success: (result) =>
      result.was_locked ? `Unlocked ${result.username}.` : `${result.username} was not locked.`,
    invalidate: [["security"]],
  });

  const columns: Column<LockedAccountResponse>[] = [
    {
      key: "user",
      header: "Account",
      cell: (row) => (
        <Link href={`/users/${row.public_id}`} className="font-medium hover:underline">
          {row.full_name || row.username}
        </Link>
      ),
    },
    {
      key: "email",
      header: "Email",
      secondary: true,
      cell: (row) => row.email ?? "—",
    },
    {
      key: "attempts",
      header: "Failed attempts",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.failed_login_attempts ?? 0}</span>,
    },
    {
      key: "until",
      header: "Locked until",
      cell: (row) =>
        row.locked_until ? (
          <span className="flex items-center gap-2">
            {formatDateTime(row.locked_until, { timeZone })}
            {row.is_expired ? <Badge tone="neutral">Lapsed</Badge> : null}
          </span>
        ) : (
          <Badge tone="danger">Needs an unlock</Badge>
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("security.manage") ? (
          <Button
            variant="secondary"
            size="sm"
            loading={unlock.isPending && unlock.variables === row.public_id}
            onClick={() => unlock.mutate(row.public_id)}
          >
            <Unlock /> Unlock
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Locked accounts"
        description="Accounts that hit the failed-sign-in threshold. A lapsed lock clears itself on the next successful sign-in."
        actions={
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="size-3.5 accent-[var(--primary)]"
              checked={includeExpired}
              onChange={(event) => {
                setIncludeExpired(event.target.checked);
                setPage({ limit, offset: 0 });
              }}
            />
            Include lapsed locks
          </label>
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
            emptyMessage="No locked accounts."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="accounts"
          />
        </>
      )}
    </Card>
  );
}

function Sessions() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [userId, setUserId] = useState("");
  const revokeOne = useConfirm<AdminSessionResponse>();
  const revokeAll = useConfirm<AdminSessionResponse>();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["security", "sessions", userId, limit, offset],
    queryFn: () =>
      api.get<PageAdminSessionResponse>("/security/sessions", {
        query: { user_id: userId || undefined, limit, offset },
      }),
  });

  const endSession = useApiMutation<void, string>({
    mutationFn: (sessionId) => api.delete<void>(`/security/sessions/${segment(sessionId)}`),
    success: "Session ended.",
    invalidate: [["security"]],
    onSuccess: () => revokeOne.close(),
  });

  const endAll = useApiMutation<RevocationResponse, string>({
    mutationFn: (targetUserId) =>
      api.post<RevocationResponse>(`/security/accounts/${segment(targetUserId)}/sessions/revoke-all`),
    success: (result) => `Revoked ${result.revoked} session(s).`,
    invalidate: [["security"]],
    onSuccess: () => revokeAll.close(),
  });

  const columns: Column<AdminSessionResponse>[] = [
    {
      key: "user",
      header: "Account",
      cell: (row) => (
        <Link href={`/users/${row.user_id}`} className="font-medium hover:underline">
          {row.username}
        </Link>
      ),
    },
    {
      key: "device",
      header: "Device",
      secondary: true,
      cell: (row) => (
        <span className="block max-w-72 truncate text-xs text-muted-foreground">
          {row.user_agent ?? "Unknown"}
        </span>
      ),
    },
    {
      key: "ip",
      header: "IP",
      secondary: true,
      cell: (row) => <span className="font-mono text-xs">{row.ip_address ?? "—"}</span>,
    },
    {
      key: "created",
      header: "Started",
      cell: (row) => formatDateTime(row.created_at, { timeZone }),
    },
    {
      key: "expires",
      header: "Expires",
      secondary: true,
      cell: (row) => formatDateTime(row.expires_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("security.manage") ? (
          <div className="flex justify-end gap-1">
            <Button variant="ghost" size="sm" onClick={() => revokeOne.ask(row)}>
              End
            </Button>
            <Button variant="ghost" size="sm" onClick={() => revokeAll.ask(row)}>
              <LogOut /> All theirs
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Active sessions"
        description="Every live refresh-token session across the institution."
        actions={
          <Input
            value={userId}
            onChange={(event) => {
              setUserId(event.target.value.trim());
              setPage({ limit, offset: 0 });
            }}
            placeholder="Filter by user id"
            aria-label="Filter sessions by user id"
            className="w-56"
          />
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
            emptyMessage="No active sessions."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="sessions"
          />
        </>
      )}

      <ConfirmDialog
        open={revokeOne.open}
        onOpenChange={(next) => (next ? null : revokeOne.close())}
        destructive
        title="End this session?"
        description={`${revokeOne.target?.username ?? ""} will be signed out on that device.`}
        confirmLabel="End session"
        pending={endSession.isPending}
        onConfirm={() => {
          if (revokeOne.target) endSession.mutate(revokeOne.target.public_id);
        }}
      />

      <ConfirmDialog
        open={revokeAll.open}
        onOpenChange={(next) => (next ? null : revokeAll.close())}
        destructive
        title="End every session for this account?"
        description={`${revokeAll.target?.username ?? ""} will be signed out everywhere.`}
        confirmLabel="Revoke all"
        pending={endAll.isPending}
        onConfirm={() => {
          if (revokeAll.target) endAll.mutate(revokeAll.target.user_id);
        }}
      />
    </Card>
  );
}

function SecurityEvents() {
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["security", "events", debouncedSearch, limit, offset],
    queryFn: () =>
      api.get<PageAuditLogResponse>("/security/events", {
        query: { q: debouncedSearch || undefined, limit, offset },
      }),
  });

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
      header: "Event",
      cell: (row) => (
        <span className="flex items-center gap-2">
          <Badge tone={row.success === false ? "danger" : "neutral"}>{humanise(row.action)}</Badge>
        </span>
      ),
    },
    {
      key: "actor",
      header: "Account",
      cell: (row) =>
        row.actor_id ? (
          <Link href={`/users/${row.actor_id}`} className="hover:underline">
            {row.actor_username ?? row.actor_email ?? row.actor_id}
          </Link>
        ) : (
          <span className="text-muted-foreground">System</span>
        ),
    },
    {
      key: "ip",
      header: "IP",
      secondary: true,
      cell: (row) => <span className="font-mono text-xs">{row.ip_address ?? "—"}</span>,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Security events"
        description="The security-relevant subset of the audit trail: sign-ins, lockouts, token reuse, permission changes."
        actions={
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search events"
            aria-label="Search security events"
            className="w-56"
          />
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
            emptyMessage="Nothing recorded in this window."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="events"
          />
        </>
      )}
    </Card>
  );
}

export default function SecurityPage() {
  const { permissions } = useSession();

  return (
    <div className="space-y-5">
      <PageHeader
        title="Security"
        description="Sign-in failures, lockouts and live sessions. Separate from the audit log on purpose: responding to an incident is a narrower job than reading the institution's whole change history."
        actions={
          permissions.has("security.manage") ? (
            <Badge tone="primary">
              <ShieldCheck className="size-3" /> You can act on these
            </Badge>
          ) : (
            <Badge tone="neutral">Read only</Badge>
          )
        }
      />

      <Summary />

      <Tabs defaultValue="locked">
        <TabsList>
          <TabsTab value="locked">Locked accounts</TabsTab>
          <TabsTab value="sessions">Sessions</TabsTab>
          <TabsTab value="events">Events</TabsTab>
        </TabsList>
        <TabsPanel value="locked">
          <LockedAccounts />
        </TabsPanel>
        <TabsPanel value="sessions">
          <Sessions />
        </TabsPanel>
        <TabsPanel value="events">
          <SecurityEvents />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
