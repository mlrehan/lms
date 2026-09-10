"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  ManagerResponse,
  MembershipResponse,
  OrganizationResponse,
  PageMembershipResponse,
} from "@/lib/api/types";
import { OrganizationMembershipStatusValues } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormActions, FormGrid, Input, NativeSelect } from "@/components/ui/form";
import { Stat, StatGrid } from "@/components/ui/stat";
import { StatusBadge } from "@/components/domain/status-badge";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function Managers({ organization }: { organization: OrganizationResponse }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const [includeInactive, setIncludeInactive] = useState(false);
  const [appointing, setAppointing] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [removing, setRemoving] = useState<ManagerResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["organizations", organization.public_id, "managers", includeInactive],
    queryFn: () =>
      api.get<ManagerResponse[]>(`/organizations/${segment(organization.public_id)}/managers`, {
        query: { include_inactive: includeInactive || undefined },
      }),
  });

  const appoint = useApiMutation<ManagerResponse, void>({
    mutationFn: () =>
      api.post<ManagerResponse>(`/organizations/${segment(organization.public_id)}/managers`, {
        body: { user_id: userId!, title: title || null },
      }),
    success: "Manager appointed.",
    invalidate: [["organizations"]],
    onSuccess: () => {
      setUserId(null);
      setTitle("");
      setAppointing(false);
    },
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (managerId) =>
      api.delete<void>(`/organizations/${segment(organization.public_id)}/managers/${segment(managerId)}`),
    success: "Manager removed.",
    invalidate: [["organizations"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<ManagerResponse>[] = [
    {
      key: "name",
      header: "Manager",
      cell: (row) => (
        <Link href={`/users/${row.user_id}`} className="font-medium hover:underline">
          {row.full_name || row.username}
        </Link>
      ),
    },
    { key: "title", header: "Title", cell: (row) => row.title ?? "—" },
    {
      key: "active",
      header: "State",
      cell: (row) => (
        <Badge tone={row.is_active ? "success" : "neutral"}>
          {row.is_active ? "Active" : "Removed"}
        </Badge>
      ),
    },
    {
      key: "invited",
      header: "Appointed",
      secondary: true,
      cell: (row) => formatDateTime(row.invited_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("organization.appoint") && row.is_active ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Remove ${row.username}`}
            onClick={() => setRemoving(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Managers"
        description="People who can see and act on this organization's employees."
        actions={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch checked={includeInactive} onCheckedChange={setIncludeInactive} />
              Show removed
            </label>
            {permissions.has("organization.appoint") ? (
              <Button size="sm" onClick={() => setAppointing(true)}>
                <UserPlus /> Appoint
              </Button>
            ) : null}
          </div>
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={data ?? []}
          rowKey={(row) => row.public_id}
          emptyMessage="No managers appointed."
        />
      )}

      <Dialog open={appointing} onOpenChange={setAppointing}>
        <DialogContent size="md">
          <DialogHeader
            title="Appoint a manager"
            description="Must be an account holding the CORPORATE_MANAGER role."
          />
          <div className="space-y-4">
            <Field label="Person" required>
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="CORPORATE_MANAGER"
                  value={userId}
                  onChange={(next) => setUserId(next)}
                />
              )}
            </Field>
            <Field label="Title" hint="e.g. L&amp;D Manager.">
              {({ id }) => (
                <Input id={id} value={title} onChange={(event) => setTitle(event.target.value)} />
              )}
            </Field>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAppointing(false)}>
              Cancel
            </Button>
            <Button loading={appoint.isPending} disabled={!userId} onClick={() => appoint.mutate()}>
              Appoint
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title="Remove this manager?"
        description="They lose visibility of this organization's employees."
        confirmLabel="Remove"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

function Members({ organization }: { organization: OrganizationResponse }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(25);
  const [status, setStatus] = useState("");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({
    user_id: "",
    employee_code: "",
    department: "",
    activate_immediately: true,
  });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["organizations", organization.public_id, "members", status, limit, offset],
    queryFn: () =>
      api.get<PageMembershipResponse>(`/organizations/${segment(organization.public_id)}/members`, {
        query: { status: status || undefined, limit, offset },
      }),
  });

  const add = useApiMutation<MembershipResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<MembershipResponse>(`/organizations/${segment(organization.public_id)}/members`, {
        body: {
          user_id: values.user_id,
          employee_code: values.employee_code || null,
          department: values.department || null,
          activate_immediately: values.activate_immediately,
        },
      }),
    success: "Employee added.",
    invalidate: [["organizations"]],
    onSuccess: () => {
      setDraft({ user_id: "", employee_code: "", department: "", activate_immediately: true });
      setAdding(false);
    },
  });

  const setStatusMutation = useApiMutation<
    MembershipResponse,
    { membershipId: string; status: string }
  >({
    mutationFn: ({ membershipId, status: next }) =>
      api.put<MembershipResponse>(
        `/organizations/${segment(organization.public_id)}/members/${segment(membershipId)}/status`,
        { body: { status: next } },
      ),
    success: "Membership updated.",
    invalidate: [["organizations"]],
  });

  const columns: Column<MembershipResponse>[] = [
    {
      key: "name",
      header: "Employee",
      cell: (row) => (
        <Link href={`/users/${row.user_id}`} className="font-medium hover:underline">
          {row.full_name || row.username}
        </Link>
      ),
    },
    {
      key: "code",
      header: "Employee code",
      secondary: true,
      cell: (row) => <span className="font-mono text-xs">{row.employee_code ?? "—"}</span>,
    },
    { key: "department", header: "Department", secondary: true, cell: (row) => row.department ?? "—" },
    {
      key: "status",
      header: "Status",
      cell: (row) => <StatusBadge value={row.status} kind="membership" />,
    },
    {
      key: "joined",
      header: "Joined",
      secondary: true,
      cell: (row) => formatDateTime(row.joined_at ?? row.invited_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("organization.invite") ? (
          <NativeSelect
            className="ml-auto w-auto"
            aria-label={`Status for ${row.username}`}
            value={row.status}
            disabled={setStatusMutation.isPending}
            onChange={(event) =>
              setStatusMutation.mutate({ membershipId: row.public_id, status: event.target.value })
            }
          >
            {OrganizationMembershipStatusValues.map((value) => (
              <option key={value} value={value}>
                {humanise(value)}
              </option>
            ))}
          </NativeSelect>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Employees"
        description="A REMOVED membership is kept rather than deleted: historical enrollments must still show who sponsored them."
        actions={
          <div className="flex items-center gap-2">
            <NativeSelect
              className="w-auto"
              aria-label="Filter by status"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage({ limit, offset: 0 });
              }}
            >
              <option value="">Any status</option>
              {OrganizationMembershipStatusValues.map((value) => (
                <option key={value} value={value}>
                  {humanise(value)}
                </option>
              ))}
            </NativeSelect>
            {permissions.has("organization.invite") ? (
              <Button size="sm" onClick={() => setAdding(true)}>
                <UserPlus /> Add employee
              </Button>
            ) : null}
          </div>
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
            emptyMessage="No employees on this organization."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="employees"
          />
        </>
      )}

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent size="md">
          <DialogHeader
            title="Add an employee"
            description="Must be an account holding the STUDENT role."
          />
          <div className="space-y-4">
            <Field label="Person" required>
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="STUDENT"
                  value={draft.user_id || null}
                  onChange={(next) => setDraft({ ...draft, user_id: next ?? "" })}
                />
              )}
            </Field>
            <FormGrid>
              <Field label="Employee code">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.employee_code}
                    onChange={(event) => setDraft({ ...draft, employee_code: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Department">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.department}
                    onChange={(event) => setDraft({ ...draft, department: event.target.value })}
                  />
                )}
              </Field>
            </FormGrid>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={draft.activate_immediately}
                onCheckedChange={(checked) =>
                  setDraft({ ...draft, activate_immediately: checked })
                }
              />
              <span>
                Activate immediately
                <span className="block text-xs text-muted-foreground">
                  You adding a known employee is the acceptance step. Leave this off to create an
                  INVITED membership instead.
                </span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button
              loading={add.isPending}
              disabled={!draft.user_id}
              onClick={() => add.mutate(draft)}
            >
              Add employee
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

export default function OrganizationDetailPage({
  params,
}: {
  params: Promise<{ organizationId: string }>;
}) {
  const { organizationId } = use(params);
  const router = useRouter();
  const { permissions } = useSession();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{
    name: string;
    code: string;
    contact_email: string;
    contact_phone: string;
    is_active: boolean;
  } | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["organizations", "detail", organizationId],
    queryFn: () => api.get<OrganizationResponse>(`/organizations/${segment(organizationId)}`),
  });

  const save = useApiMutation<OrganizationResponse, NonNullable<typeof draft>>({
    mutationFn: (values) =>
      api.patch<OrganizationResponse>(`/organizations/${segment(organizationId)}`, {
        body: {
          name: values.name,
          code: values.code || null,
          contact_email: values.contact_email || null,
          contact_phone: values.contact_phone || null,
          is_active: values.is_active,
        },
      }),
    success: "Organization saved.",
    invalidate: [["organizations"]],
    onSuccess: () => {
      setEditing(false);
      setDraft(null);
    },
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/organizations/${segment(organizationId)}`),
    success: "Organization deleted.",
    invalidate: [["organizations"]],
    onSuccess: () => router.push("/organizations"),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Organizations", href: "/organizations" }, { label: data.name }]}
        title={data.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={data.is_active ? "success" : "neutral"}>
              {data.is_active ? "Active" : "Inactive"}
            </Badge>
            {data.code ? <Badge tone="neutral">{data.code}</Badge> : null}
            {data.contact_email ? <span className="text-xs">{data.contact_email}</span> : null}
            {data.contact_phone ? <span className="text-xs">{data.contact_phone}</span> : null}
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            {permissions.has("organization.update") && !editing ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setDraft({
                    name: data.name,
                    code: data.code ?? "",
                    contact_email: data.contact_email ?? "",
                    contact_phone: data.contact_phone ?? "",
                    is_active: data.is_active,
                  });
                  setEditing(true);
                }}
              >
                Edit
              </Button>
            ) : null}
            {permissions.has("organization.delete") ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete organization"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      <StatGrid>
        <Stat label="Managers" value={data.manager_count} />
        <Stat label="Employees" value={data.member_count} />
      </StatGrid>

      {editing && draft ? (
        <Card>
          <CardHeader title="Edit organization" />
          <CardBody className="space-y-4">
            <FormGrid>
              <Field label="Name" required>
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.name}
                    onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Code">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.code}
                    onChange={(event) => setDraft({ ...draft, code: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Contact email">
                {({ id }) => (
                  <Input
                    id={id}
                    type="email"
                    value={draft.contact_email}
                    onChange={(event) => setDraft({ ...draft, contact_email: event.target.value })}
                  />
                )}
              </Field>
              <Field label="Contact phone">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.contact_phone}
                    onChange={(event) => setDraft({ ...draft, contact_phone: event.target.value })}
                  />
                )}
              </Field>
            </FormGrid>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={draft.is_active}
                onCheckedChange={(checked) => setDraft({ ...draft, is_active: checked })}
              />
              Active
            </label>
            <FormActions>
              <Button
                variant="ghost"
                onClick={() => {
                  setEditing(false);
                  setDraft(null);
                }}
              >
                Cancel
              </Button>
              <Button loading={save.isPending} onClick={() => save.mutate(draft)}>
                Save
              </Button>
            </FormActions>
          </CardBody>
        </Card>
      ) : null}

      <Tabs defaultValue="members">
        <TabsList>
          <TabsTab value="members">Employees</TabsTab>
          <TabsTab value="managers">Managers</TabsTab>
        </TabsList>
        <TabsPanel value="members">
          <Members organization={data} />
        </TabsPanel>
        <TabsPanel value="managers">
          <Managers organization={data} />
        </TabsPanel>
      </Tabs>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title="Delete this organization?"
        description="Its managers and memberships go with it. Marking it inactive keeps the record instead."
        confirmPhrase={data.name}
        confirmLabel="Delete organization"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}
