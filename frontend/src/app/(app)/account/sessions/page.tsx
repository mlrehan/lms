"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LogOut, Monitor } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { AuthSessionResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Column, DataTable } from "@/components/ui/data-table";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSignOut } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";

export default function MySessionsPage() {
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const signOut = useSignOut();
  const [confirmAll, setConfirmAll] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["auth", "sessions"],
    queryFn: () => api.get<AuthSessionResponse[]>("/auth/sessions"),
  });

  const revoke = useApiMutation<void, string>({
    mutationFn: (sessionId) => api.delete<void>(`/auth/sessions/${segment(sessionId)}`),
    success: "Session ended.",
    invalidate: [["auth", "sessions"]],
  });

  const columns: Column<AuthSessionResponse>[] = [
    {
      key: "device",
      header: "Device",
      cell: (session) => (
        <div className="min-w-0">
          <p className="flex items-center gap-2 truncate text-sm font-medium">
            <Monitor className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            {session.user_agent ?? "Unknown device"}
            {session.is_current ? <Badge tone="success">This device</Badge> : null}
          </p>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {session.ip_address ?? "IP not recorded"}
          </p>
        </div>
      ),
    },
    {
      key: "created",
      header: "Signed in",
      secondary: true,
      cell: (session) => (
        <span title={formatDateTime(session.created_at, { timeZone })}>
          {formatRelative(session.created_at, locale)}
        </span>
      ),
    },
    {
      key: "expires",
      header: "Expires",
      secondary: true,
      cell: (session) => formatDateTime(session.expires_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (session) => (
        <Button
          variant="ghost"
          size="sm"
          disabled={revoke.isPending}
          onClick={() => revoke.mutate(session.public_id)}
        >
          {session.is_current ? "Sign out here" : "End session"}
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "My account", href: "/account" }, { label: "Sessions" }]}
        title="Active sessions"
        description="Every device holding a live sign-in for your account. Ending one takes effect at once."
        actions={
          <Button variant="danger" onClick={() => setConfirmAll(true)}>
            <LogOut /> Sign out everywhere
          </Button>
        }
      />

      <Card>
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <DataTable
              columnsKey="account-sessions"
            columns={columns}
            rows={data ?? []}
            rowKey={(session) => session.public_id}
            emptyMessage="No other sessions."
          />
        )}
      </Card>

      <ConfirmDialog
        open={confirmAll}
        onOpenChange={setConfirmAll}
        destructive
        title="Sign out on every device?"
        description="Every session ends, including this one."
        confirmLabel="Sign out everywhere"
        onConfirm={() => signOut({ everywhere: true })}
      />
    </div>
  );
}
