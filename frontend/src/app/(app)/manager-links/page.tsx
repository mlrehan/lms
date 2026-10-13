"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link2, Plus, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { ManagedStudentResponse, PageManagedStudentResponse } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, Switch } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

/**
 * Who each Corporate Manager may see.
 *
 * Deliberately a sibling of Guardians rather than a tab inside Organizations:
 * the company records employment, this records access, and putting the second
 * inside the first is what made them the same thing in the first place. A
 * manager appointed to a company gets nobody until somebody is listed here.
 */
export default function ManagerLinksPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [managerId, setManagerId] = useState<string | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<ManagedStudentResponse | null>(null);
  const [draft, setDraft] = useState({
    manager_id: "",
    student_id: "",
    relationship_type: "",
    is_primary: false,
  });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["manager-links", managerId, studentId, limit, offset],
    queryFn: () =>
      api.get<PageManagedStudentResponse>("/manager-links", {
        query: {
          manager_id: managerId ?? undefined,
          student_id: studentId ?? undefined,
          limit,
          offset,
        },
      }),
  });

  const create = useApiMutation<ManagedStudentResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<ManagedStudentResponse>("/manager-links", {
        body: {
          manager_id: values.manager_id,
          student_id: values.student_id,
          relationship_type: values.relationship_type || null,
          is_primary: values.is_primary,
        },
      }),
    success: "Student assigned.",
    invalidate: [["manager-links"], ["team"]],
    onSuccess: () => {
      setDraft({ manager_id: "", student_id: "", relationship_type: "", is_primary: false });
      setCreateOpen(false);
    },
  });

  const setPrimary = useApiMutation<ManagedStudentResponse, { id: string; is_primary: boolean }>({
    mutationFn: ({ id, is_primary }) =>
      api.patch<ManagedStudentResponse>(`/manager-links/${segment(id)}`, { body: { is_primary } }),
    success: "Updated.",
    invalidate: [["manager-links"]],
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/manager-links/${segment(id)}`),
    success: "Student unassigned.",
    invalidate: [["manager-links"], ["team"]],
    onSuccess: () => setDeleting(null),
  });

  const columns: Column<ManagedStudentResponse>[] = [
    {
      key: "manager",
      header: "Manager",
      cell: (row) => (
        <Link href={`/users/${row.manager_id}`} className="font-medium hover:underline">
          {row.manager_name || row.manager_username}
        </Link>
      ),
    },
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <Link href={`/users/${row.student_id}`} className="font-medium hover:underline">
          {row.student_name || row.student_username}
        </Link>
      ),
    },
    {
      key: "relationship",
      header: "Relationship",
      cell: (row) => row.relationship_type ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: "primary",
      header: "First contact",
      cell: (row) =>
        permissions.has("managed_student.update") ? (
          <Switch
            checked={row.is_primary ?? false}
            disabled={setPrimary.isPending}
            onCheckedChange={(checked) =>
              setPrimary.mutate({ id: row.public_id, is_primary: checked })
            }
          />
        ) : row.is_primary ? (
          <Badge tone="success">First contact</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "created",
      header: "Assigned",
      secondary: true,
      cell: (row) => formatDateTime(row.created_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("managed_student.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Unassign student"
            onClick={() => setDeleting(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Manager assignments"
        description="Which students each corporate manager may see. Employing somebody grants nothing on its own — a manager sees the students assigned to them here, and no one else at the company."
        actions={
          permissions.has("managed_student.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> Assign a student
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="Manager" className="w-72">
            {({ id }) => (
              <UserPicker
                id={id}
                role="CORPORATE_MANAGER"
                value={managerId}
                onChange={(next) => {
                  setManagerId(next);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
          <Field label="Student" className="w-72">
            {({ id }) => (
              <UserPicker
                id={id}
                role="STUDENT"
                value={studentId}
                onChange={(next) => {
                  setStudentId(next);
                  setPage({ limit, offset: 0 });
                }}
              />
            )}
          </Field>
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columnsKey="manager-links"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No students assigned to a manager yet."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="assignments"
            />
          </>
        )}
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Assign a student to a manager"
            description="The manager must hold the CORPORATE_MANAGER role and the student the STUDENT role. They do not have to work for the same company — or for any company."
          />
          <div className="space-y-4">
            <Field label="Manager" required>
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="CORPORATE_MANAGER"
                  value={draft.manager_id || null}
                  onChange={(next) => setDraft({ ...draft, manager_id: next ?? "" })}
                />
              )}
            </Field>
            <Field label="Student" required>
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="STUDENT"
                  value={draft.student_id || null}
                  onChange={(next) => setDraft({ ...draft, student_id: next ?? "" })}
                />
              )}
            </Field>
            <Field label="Relationship" hint="e.g. Line manager, L&D sponsor.">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.relationship_type}
                  onChange={(event) => setDraft({ ...draft, relationship_type: event.target.value })}
                />
              )}
            </Field>
            <label className="flex items-center gap-3 text-sm">
              <Switch
                checked={draft.is_primary}
                onCheckedChange={(checked) => setDraft({ ...draft, is_primary: checked })}
              />
              <span>
                First point of contact
                <span className="block text-xs text-muted-foreground">
                  Marks the manager to approach first when a student has several.
                </span>
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={create.isPending}
              disabled={!draft.manager_id || !draft.student_id}
              onClick={() => create.mutate(draft)}
            >
              <Link2 /> Assign
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (open ? null : setDeleting(null))}
        destructive
        title="Unassign this student?"
        description="The manager loses access to that student's records immediately. Their employment record is not affected."
        confirmLabel="Unassign"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.public_id);
        }}
      />
    </div>
  );
}
