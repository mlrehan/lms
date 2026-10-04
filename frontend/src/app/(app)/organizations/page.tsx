"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Building2, Plus, Search } from "lucide-react";
import { api } from "@/lib/api/client";
import type { OrganizationResponse, OrganizationSummary, PageOrganizationSummary } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input } from "@/components/ui/form";
import { BooleanBadge } from "@/components/domain/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";

export default function OrganizationsPage() {
  const router = useRouter();
  const { permissions } = useSession();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState();
  const [active, setActive] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", code: "", contact_email: "", contact_phone: "" });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["organizations", "list", debouncedSearch, active, limit, offset],
    queryFn: () =>
      api.get<PageOrganizationSummary>("/organizations", {
        query: {
          query: debouncedSearch || undefined,
          is_active: active === "" ? undefined : active === "true",
          limit,
          offset,
        },
      }),
  });

  const create = useApiMutation<OrganizationResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<OrganizationResponse>("/organizations", {
        body: {
          name: values.name,
          code: values.code || null,
          contact_email: values.contact_email || null,
          contact_phone: values.contact_phone || null,
        },
      }),
    success: "Organization created.",
    invalidate: [["organizations"]],
    onSuccess: (organization) => {
      setDraft({ name: "", code: "", contact_email: "", contact_phone: "" });
      setCreateOpen(false);
      router.push(`/organizations/${organization.public_id}`);
    },
  });

  const columns: Column<OrganizationSummary>[] = [
    {
      key: "name",
      header: "Organization",
      cell: (row) => (
        <Link href={`/organizations/${row.public_id}`} className="font-medium hover:underline">
          {row.name}
        </Link>
      ),
    },
    {
      key: "code",
      header: "Code",
      secondary: true,
      cell: (row) => <span className="font-mono text-xs">{row.code ?? "—"}</span>,
    },
    {
      key: "active",
      header: "State",
      cell: (row) => <BooleanBadge value={row.is_active} trueLabel="Active" falseLabel="Inactive" />,
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Organizations"
        description="Corporate sponsors: employers whose staff are enrolled on the institution's courses."
        actions={
          permissions.has("organization.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New organization
            </Button>
          ) : null
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
              className="pl-8"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search organizations"
              aria-label="Search organizations"
            />
          </div>
          <Select
            className="w-auto"
            aria-label="Filter by state"
            value={(active) || null}
            onValueChange={(next) => {
              setActive((next ?? ""));
              setPage({ limit, offset: 0 });
            }}
           placeholder="Any state" clearable options={[{ value: "true", label: "Active" }, { value: "false", label: "Inactive" }]} />
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columnsKey="organizations"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(row) => row.public_id}
              emptyMessage="No organizations yet."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="organizations"
            />
          </>
        )}
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="New organization"
            description="Managers and members are added once it exists."
          />
          <div className="space-y-4">
            <Field label="Name" required>
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              )}
            </Field>
            <FormGrid>
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
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={create.isPending}
              disabled={draft.name.trim() === ""}
              onClick={() => create.mutate(draft)}
            >
              <Building2 /> Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
