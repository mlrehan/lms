"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus, Save, ShieldCheck, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { PermissionResponse, RoleResponse } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormActions, Input, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { humanise, moduleOf } from "@/lib/utils";

const createSchema = z.object({
  name: z
    .string()
    .trim()
    .min(2, "Give the role a name.")
    .regex(/^[A-Z][A-Z0-9_]*$/, "Uppercase letters, digits and underscores, e.g. TEACHING_ASSISTANT."),
  description: z.string().trim().optional(),
});

type CreateValues = z.infer<typeof createSchema>;

function CreateRoleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [banner, setBanner] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<CreateValues>({ resolver: zodResolver(createSchema), defaultValues: { name: "" } });

  const create = useApiMutation<RoleResponse, CreateValues>({
    mutationFn: (values) =>
      api.post<RoleResponse>("/roles", {
        body: { name: values.name, description: values.description || null, permissions: [] },
      }),
    success: (role) => `Created ${role.name}.`,
    invalidate: [["roles"]],
    onSuccess: () => {
      reset();
      onOpenChange(false);
    },
    onError: (error) => {
      if (!applyFieldErrors<CreateValues>(error, setError, ["name", "description"])) {
        setBanner(error.message);
      }
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader
          title="Create a role"
          description="A new role starts with no permissions. Grant them on the role's own card once it exists, so nobody is handed authority by a typo in a create form."
        />
        <form method="post" onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <Field label="Name" error={errors.name?.message} required>
            {({ id }) => <Input id={id} placeholder="TEACHING_ASSISTANT" {...register("name")} />}
          </Field>
          <Field label="Description" error={errors.description?.message}>
            {({ id }) => <Textarea id={id} rows={3} {...register("description")} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create role
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RoleCard({
  role,
  catalog,
  canEdit,
  canDelete,
}: {
  role: RoleResponse;
  catalog: PermissionResponse[];
  canEdit: boolean;
  canDelete: boolean;
}) {
  const [granted, setGranted] = useState<string[]>(role.permissions ?? []);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const byModule = useMemo(() => {
    const groups = new Map<string, PermissionResponse[]>();
    for (const permission of catalog) {
      const key = permission.module ?? moduleOf(permission.name);
      const list = groups.get(key) ?? [];
      list.push(permission);
      groups.set(key, list);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [catalog]);

  const original = new Set(role.permissions ?? []);
  const changed =
    granted.length !== original.size || granted.some((name) => !original.has(name));

  const save = useApiMutation<RoleResponse, string[]>({
    mutationFn: (permissions) =>
      api.put<RoleResponse>(`/roles/${segment(role.name)}/permissions`, { body: { permissions } }),
    success: `Permissions saved for ${role.name}.`,
    invalidate: [["roles"], ["auth", "me"]],
  });

  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/roles/${segment(role.name)}`),
    success: `Deleted ${role.name}.`,
    invalidate: [["roles"]],
  });

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-muted-foreground" aria-hidden />
            {role.name}
          </span>
        }
        description={role.description ?? undefined}
        actions={
          <div className="flex items-center gap-2">
            <Badge tone="neutral">{(role.permissions ?? []).length} permissions</Badge>
            <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>
              {expanded ? "Hide" : "Edit permissions"}
            </Button>
            {canDelete ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${role.name}`}
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="text-danger" />
              </Button>
            ) : null}
          </div>
        }
      />

      {expanded ? (
        <CardBody className="space-y-4">
          {byModule.map(([module, permissions]) => (
            <div key={module} className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {humanise(module)}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {permissions.map((permission) => {
                  const checked = granted.includes(permission.name);
                  return (
                    <label
                      key={permission.name}
                      title={permission.description ?? permission.name}
                      className={`cursor-pointer rounded-full border px-2.5 py-1 text-xs transition-colors ${
                        checked
                          ? "border-primary bg-accent text-accent-foreground"
                          : "border-border-subtle text-muted-foreground hover:border-border-strong"
                      } ${canEdit ? "" : "cursor-not-allowed opacity-70"}`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        disabled={!canEdit}
                        onChange={(event) =>
                          setGranted((previous) =>
                            event.target.checked
                              ? [...previous, permission.name]
                              : previous.filter((name) => name !== permission.name),
                          )
                        }
                      />
                      {permission.action ?? permission.name}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}

          {canEdit ? (
            <FormActions>
              <Button
                variant="ghost"
                onClick={() => setGranted(role.permissions ?? [])}
                disabled={!changed}
              >
                Reset
              </Button>
              <Button loading={save.isPending} disabled={!changed} onClick={() => save.mutate(granted)}>
                <Save /> Save permissions
              </Button>
            </FormActions>
          ) : (
            <p className="text-xs text-muted-foreground">
              You can see this role&rsquo;s permissions but not change them.
            </p>
          )}
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        destructive
        title={`Delete ${role.name}?`}
        description="Anyone holding it loses every permission it grants. Accounts are not deleted."
        confirmPhrase={role.name}
        confirmLabel="Delete role"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Card>
  );
}

export default function RolesPage() {
  const { permissions } = useSession();
  const [createOpen, setCreateOpen] = useState(false);

  const rolesQuery = useQuery({
    queryKey: ["roles"],
    queryFn: () => api.get<RoleResponse[]>("/roles"),
  });

  const catalogQuery = useQuery({
    queryKey: ["permissions"],
    queryFn: () => api.get<PermissionResponse[]>("/permissions"),
    enabled: permissions.has("permission.read"),
    staleTime: 10 * 60_000,
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Roles"
        description="A role is a named set of permissions. Every request is checked against the caller's effective permissions on the server, so what is shown here is what is enforced."
        actions={
          permissions.has("role.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New role
            </Button>
          ) : null
        }
      />

      {!permissions.has("permission.read") ? (
        <p className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-sm text-muted-foreground">
          Editing a role&rsquo;s permissions needs <code className="font-mono text-xs">permission.read</code>{" "}
          as well, so the catalog can be listed. Roles are shown read-only.
        </p>
      ) : null}

      {rolesQuery.isPending ? (
        <LoadingState rows={5} />
      ) : rolesQuery.error ? (
        <ErrorState error={rolesQuery.error} onRetry={() => void rolesQuery.refetch()} />
      ) : (
        <div className="space-y-3">
          {(rolesQuery.data ?? []).map((role) => (
            <RoleCard
              key={role.name}
              role={role}
              catalog={catalogQuery.data ?? []}
              canEdit={permissions.has("role.update") && Boolean(catalogQuery.data)}
              canDelete={permissions.has("role.delete")}
            />
          ))}
        </div>
      )}

      <CreateRoleDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
