"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link2, Plus, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { GuardianLinkResponse, PageGuardianLinkResponse } from "@/lib/api/types";
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

export default function GuardiansPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState();
  const [guardianId, setGuardianId] = useState<string | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<GuardianLinkResponse | null>(null);
  const [draft, setDraft] = useState({
    guardian_id: "",
    student_id: "",
    relationship_type: "",
    is_primary: false,
  });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["guardian-links", guardianId, studentId, limit, offset],
    queryFn: () =>
      api.get<PageGuardianLinkResponse>("/guardian-links", {
        query: {
          guardian_id: guardianId ?? undefined,
          student_id: studentId ?? undefined,
          limit,
          offset,
        },
      }),
  });

  const create = useApiMutation<GuardianLinkResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<GuardianLinkResponse>("/guardian-links", {
        body: {
          guardian_id: values.guardian_id,
          student_id: values.student_id,
          relationship_type: values.relationship_type || null,
          is_primary: values.is_primary,
        },
      }),
    success: "Guardianship recorded.",
    invalidate: [["guardian-links"]],
    onSuccess: () => {
      setDraft({ guardian_id: "", student_id: "", relationship_type: "", is_primary: false });
      setCreateOpen(false);
    },
  });

  const setPrimary = useApiMutation<GuardianLinkResponse, { id: string; is_primary: boolean }>({
    mutationFn: ({ id, is_primary }) =>
      api.patch<GuardianLinkResponse>(`/guardian-links/${segment(id)}`, { body: { is_primary } }),
    success: "Updated.",
    invalidate: [["guardian-links"]],
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/guardian-links/${segment(id)}`),
    success: "Guardianship removed.",
    invalidate: [["guardian-links"]],
    onSuccess: () => setDeleting(null),
  });

  const columns: Column<GuardianLinkResponse>[] = [
    {
      key: "guardian",
      header: "Guardian",
      cell: (row) => (
        <Link href={`/users/${row.guardian_id}`} className="font-medium hover:underline">
          {row.guardian_name || row.guardian_username}
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
      header: "Primary contact",
      cell: (row) =>
        permissions.has("guardian.update") ? (
          <Switch
            checked={row.is_primary ?? false}
            disabled={setPrimary.isPending}
            onCheckedChange={(checked) =>
              setPrimary.mutate({ id: row.public_id, is_primary: checked })
            }
          />
        ) : row.is_primary ? (
          <Badge tone="success">Primary</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "created",
      header: "Linked",
      secondary: true,
      cell: (row) => formatDateTime(row.created_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("guardian.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label="Remove guardianship"
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
        title="Guardians"
        description="Who may see a student's attendance, grades and schedule on their behalf. A guardian sees only the students linked to them."
        actions={
          permissions.has("guardian.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> Link a guardian
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle p-3">
          <Field label="Guardian" className="w-72">
            {({ id }) => (
              <UserPicker
                id={id}
                role="GUARDIAN"
                value={guardianId}
                onChange={(next) => {
                  setGuardianId(next);
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
              columnsKey="guardians"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No guardianships recorded."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="links"
            />
          </>
        )}
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="Link a guardian to a student"
            description="The guardian must hold the GUARDIAN role and the student the STUDENT role."
          />
          <div className="space-y-4">
            <Field label="Guardian" required>
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="GUARDIAN"
                  value={draft.guardian_id || null}
                  onChange={(next) => setDraft({ ...draft, guardian_id: next ?? "" })}
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
            <Field label="Relationship" hint="e.g. Parent, Legal Guardian.">
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
                Primary contact
                <span className="block text-xs text-muted-foreground">
                  Marks the main point of contact when a student has several guardians.
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
              disabled={!draft.guardian_id || !draft.student_id}
              onClick={() => create.mutate(draft)}
            >
              <Link2 /> Link
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => (open ? null : setDeleting(null))}
        destructive
        title="Remove this guardianship?"
        description="The guardian loses access to that student's records."
        confirmLabel="Remove"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.public_id);
        }}
      />
    </div>
  );
}
