"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PageUserSummary, RoleResponse, UserSummary } from "@/lib/api/types";
import { UserStatusValues } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { CreateUserDialog } from "@/components/domain/create-user-dialog";
import { LaitSyncControls } from "@/components/domain/lait-sync";
import { UserAvatar } from "@/components/domain/user-avatar";
import { Badge } from "@/components/ui/primitives";
import { useSession } from "@/lib/auth/session";

export default function UsersPage() {
  const { permissions } = useSession();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState();
  const [status, setStatus] = useState("");
  const [role, setRole] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["users", "list", debouncedSearch, status, role, limit, offset],
    queryFn: () =>
      api.get<PageUserSummary>("/users", {
        query: {
          query: debouncedSearch || undefined,
          status: status || undefined,
          role: role || undefined,
          limit,
          offset,
        },
      }),
  });

  const { data: roles } = useQuery({
    queryKey: ["roles"],
    queryFn: () => api.get<RoleResponse[]>("/roles"),
    enabled: permissions.has("role.read"),
    staleTime: 5 * 60_000,
  });

  const columns: Column<PageUserSummary["items"][number]>[] = [
    {
      key: "name",
      header: "Name",
      cell: (user) => (
        <Link href={`/users/${user.public_id}`} className="inline-flex items-center gap-2.5 font-medium hover:underline">
          <UserAvatar name={user.full_name || user.username} src={user.profile_picture} size="sm" />
          {user.full_name || user.username}
        </Link>
      ),
    },
    // Login names and emails are the Super Admin's to see; for everyone else the columns would only repeat the name.
    ...(permissions.has("user.view_contact") ? [
    {
      key: "username",
      header: "Username",
      secondary: true,
      cell: (user: UserSummary) => <span className="font-mono text-xs">{user.username}</span>,
    },
    {
      key: "email",
      header: "Email",
      secondary: true,
      cell: (user: UserSummary) => user.email ?? <span className="text-muted-foreground">—</span>,
    }
    ] : []),
    {
      key: "status",
      header: "Status",
      cell: (user) => (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <StatusBadge value={user.status} kind="user" />
          {user.can_login === false ? <Badge tone="warning">Sign-in off</Badge> : null}
          {user.is_synced ? <Badge tone="neutral">LAIT</Badge> : null}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Users"
        description="Every account in the institution. Roles decide what each person can do; the server enforces that on every request."
        actions={
          <>
            <LaitSyncControls canSync={permissions.has("user.sync")} />
            {permissions.has("user.create") ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus /> New account
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle p-3">
          <div className="relative min-w-56 flex-1">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name, username or email"
              aria-label="Search users"
              className="pl-8"
            />
          </div>
          <Select
            value={(status) || null}
            onValueChange={(next) => {
              setStatus((next ?? ""));
              setPage({ limit, offset: 0 });
            }}
            aria-label="Filter by status"
            className="w-auto"
           placeholder="Any status" clearable options={optionsFromValues(UserStatusValues)} />
          <Select
            value={(role) || null}
            onValueChange={(next) => {
              setRole((next ?? ""));
              setPage({ limit, offset: 0 });
            }}
            aria-label="Filter by role"
            className="w-auto"
           placeholder="Any role" clearable options={(roles ?? []).map((item) => ({ value: item.name, label: item.name }))} />
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(user) => user.public_id}
              emptyMessage={
                debouncedSearch || status || role
                  ? "No accounts match these filters."
                  : "No accounts yet."
              }
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

      {!permissions.has("user.create") ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <ShieldAlert className="size-3.5" aria-hidden />
          You can view accounts but not create them.
        </p>
      ) : null}

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} roles={roles ?? []} />
    </div>
  );
}
