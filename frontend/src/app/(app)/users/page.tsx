"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus, Search, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PageUserSummary, RoleResponse, UserResponse } from "@/lib/api/types";
import { UserStatusValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { useSession } from "@/lib/auth/session";

const createSchema = z.object({
  username: z.string().trim().min(1, "A username is required."),
  email: z.string().trim().email("Enter a valid email address."),
  password: z.string().min(8, "Use at least 8 characters."),
  first_name: z.string().trim().optional(),
  last_name: z.string().trim().optional(),
  roles: z.array(z.string()).min(1, "Grant at least one role."),
});

type CreateValues = z.infer<typeof createSchema>;

function CreateUserDialog({
  open,
  onOpenChange,
  roles,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roles: RoleResponse[];
}) {
  const [banner, setBanner] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    setError,
    formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { username: "", email: "", password: "", roles: [] },
  });

  const create = useApiMutation<UserResponse, CreateValues>({
    mutationFn: (values) =>
      api.post<UserResponse>("/users", {
        body: {
          ...values,
          first_name: values.first_name || null,
          last_name: values.last_name || null,
        },
      }),
    success: (user) => `Created ${user.username}.`,
    invalidate: [["users"]],
    onSuccess: () => {
      reset();
      setBanner(null);
      onOpenChange(false);
    },
    onError: (error) => {
      const known = ["username", "email", "password", "roles"] as const;
      if (!applyFieldErrors<CreateValues>(error, setError, known)) setBanner(error.message);
      else setBanner(null);
    },
  });

  const selectedRoles = watch("roles");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="Create an account"
          description="The account is usable immediately. This deployment sends no email, so there is no invitation or verification step -- you are the vouching step, and you must pass the password on yourself."
        />
        <form
          method="post"
          className="space-y-4"
          onSubmit={handleSubmit((values) => create.mutate(values))}
          noValidate
        >
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}

          <FormGrid>
            <Field label="Username" error={errors.username?.message} required>
              {({ id }) => <Input id={id} autoComplete="off" {...register("username")} />}
            </Field>
            <Field label="Email" error={errors.email?.message} required>
              {({ id }) => <Input id={id} type="email" autoComplete="off" {...register("email")} />}
            </Field>
            <Field label="First name" error={errors.first_name?.message}>
              {({ id }) => <Input id={id} {...register("first_name")} />}
            </Field>
            <Field label="Last name" error={errors.last_name?.message}>
              {({ id }) => <Input id={id} {...register("last_name")} />}
            </Field>
          </FormGrid>

          <Field
            label="Initial password"
            error={errors.password?.message}
            required
            hint="Shown here once. The console does not store it and cannot show it again."
          >
            {({ id }) => (
              <Input id={id} type="text" autoComplete="new-password" {...register("password")} />
            )}
          </Field>

          <Field label="Roles" error={errors.roles?.message} required>
            <div className="flex flex-wrap gap-2">
              {roles.map((role) => {
                const checked = selectedRoles.includes(role.name);
                return (
                  <label
                    key={role.name}
                    className={`cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                      checked
                        ? "border-primary bg-accent text-accent-foreground"
                        : "border-border text-muted-foreground hover:border-border-strong"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={(event) =>
                        setValue(
                          "roles",
                          event.target.checked
                            ? [...selectedRoles, role.name]
                            : selectedRoles.filter((name) => name !== role.name),
                          { shouldValidate: true },
                        )
                      }
                    />
                    {role.name}
                  </label>
                );
              })}
            </div>
          </Field>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

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
        <Link href={`/users/${user.public_id}`} className="font-medium hover:underline">
          {user.full_name || user.username}
        </Link>
      ),
    },
    {
      key: "username",
      header: "Username",
      secondary: true,
      cell: (user) => <span className="font-mono text-xs">{user.username}</span>,
    },
    {
      key: "email",
      header: "Email",
      secondary: true,
      cell: (user) => user.email ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: "status",
      header: "Status",
      cell: (user) => <StatusBadge value={user.status} kind="user" />,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Users"
        description="Every account in the institution. Roles decide what each person can do; the server enforces that on every request."
        actions={
          permissions.has("user.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New account
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
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
          <NativeSelect
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage({ limit, offset: 0 });
            }}
            aria-label="Filter by status"
            className="w-auto"
          >
            <option value="">Any status</option>
            {UserStatusValues.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            value={role}
            onChange={(event) => {
              setRole(event.target.value);
              setPage({ limit, offset: 0 });
            }}
            aria-label="Filter by role"
            className="w-auto"
          >
            <option value="">Any role</option>
            {(roles ?? []).map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </NativeSelect>
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
