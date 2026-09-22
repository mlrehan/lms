"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Plus, Save, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { PageSettingResponse, SettingResponse } from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, FormGrid, Input, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";

/**
 * The system settings store.
 *
 * It is a generic key/value table, not a typed configuration schema -- the
 * backend has no endpoint describing what keys exist or what values are
 * valid. So this screen is a key/value editor and says so, rather than
 * inventing a "Password policy" or "Lockout threshold" form whose fields
 * nothing on the server reads. What is enforced lives in the backend's own
 * configuration; see docs/BACKEND-GAPS.md.
 */
export default function SettingsPage() {
  const { permissions } = useSession();
  const canWrite = permissions.has("setting.update");
  const { limit, offset, setPage } = useListState(50);
  const [prefix, setPrefix] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ key: "", value: "", description: "" });
  const [removing, setRemoving] = useState<SettingResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["settings", prefix, limit, offset],
    queryFn: () =>
      api.get<PageSettingResponse>("/settings", {
        query: { prefix: prefix || undefined, limit, offset },
      }),
  });

  const save = useApiMutation<SettingResponse, { key: string; value: string; description?: string }>({
    mutationFn: ({ key, value, description }) =>
      api.put<SettingResponse>(`/settings/${segment(key)}`, {
        body: { value, description: description ?? null },
      }),
    success: "Setting saved.",
    invalidate: [["settings"]],
    onSuccess: (_result, variables) => {
      setEdits((previous) => {
        const next = { ...previous };
        delete next[variables.key];
        return next;
      });
      setCreating(false);
      setDraft({ key: "", value: "", description: "" });
    },
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (key) => api.delete<void>(`/settings/${segment(key)}`),
    success: "Setting deleted.",
    invalidate: [["settings"]],
    onSuccess: () => setRemoving(null),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="System settings"
        description="A key/value store. Writing to it needs setting.update, which by design not even an Administrator holds."
        actions={
          canWrite ? (
            <Button onClick={() => setCreating(true)}>
              <Plus /> New setting
            </Button>
          ) : null
        }
      />

      <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          These are free-form strings. The API exposes no schema for them, so this screen cannot
          validate a value or tell you which keys the server actually reads. Treat a typo here as a
          setting that silently does nothing.
        </span>
      </p>

      <Card>
        <CardHeader
          title="Settings"
          actions={
            <Input
              className="w-56"
              value={prefix}
              onChange={(event) => {
                setPrefix(event.target.value.trim());
                setPage({ limit, offset: 0 });
              }}
              placeholder="Filter by key prefix"
              aria-label="Filter by key prefix"
            />
          }
        />
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <CardBody>
            <p className="text-sm text-muted-foreground">No settings stored.</p>
          </CardBody>
        ) : (
          <>
            <ul className="divide-y divide-border-subtle">
              {(data?.items ?? []).map((setting) => {
                const edited = edits[setting.key];
                const value = edited ?? setting.value ?? "";
                const dirty = edited !== undefined && edited !== (setting.value ?? "");
                return (
                  <li key={setting.key} className="space-y-2 px-4 py-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="font-mono text-sm font-medium">{setting.key}</p>
                      {canWrite ? (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={!dirty || save.isPending}
                            onClick={() =>
                              save.mutate({
                                key: setting.key,
                                value,
                                description: setting.description ?? undefined,
                              })
                            }
                          >
                            <Save /> Save
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Delete ${setting.key}`}
                            onClick={() => setRemoving(setting)}
                          >
                            <Trash2 className="text-danger" />
                          </Button>
                        </div>
                      ) : null}
                    </div>
                    {setting.description ? (
                      <p className="text-xs text-muted-foreground">{setting.description}</p>
                    ) : null}
                    <Textarea
                      rows={2}
                      aria-label={`Value of ${setting.key}`}
                      value={value}
                      readOnly={!canWrite}
                      disabled={!canWrite}
                      onChange={(event) =>
                        setEdits((previous) => ({ ...previous, [setting.key]: event.target.value }))
                      }
                    />
                  </li>
                );
              })}
            </ul>
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="settings"
            />
          </>
        )}
      </Card>

      {creating ? (
        <Card>
          <CardHeader title="New setting" />
          <CardBody className="space-y-4">
            <FormGrid>
              <Field label="Key" required>
                {({ id }) => (
                  <Input
                    id={id}
                    className="font-mono"
                    value={draft.key}
                    onChange={(event) => setDraft({ ...draft, key: event.target.value.trim() })}
                  />
                )}
              </Field>
              <Field label="Description">
                {({ id }) => (
                  <Input
                    id={id}
                    value={draft.description}
                    onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                  />
                )}
              </Field>
            </FormGrid>
            <Field label="Value">
              {({ id }) => (
                <Textarea
                  id={id}
                  rows={2}
                  value={draft.value}
                  onChange={(event) => setDraft({ ...draft, value: event.target.value })}
                />
              )}
            </Field>
            <FormActions>
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button
                loading={save.isPending}
                disabled={draft.key === ""}
                onClick={() =>
                  save.mutate({
                    key: draft.key,
                    value: draft.value,
                    description: draft.description || undefined,
                  })
                }
              >
                Create setting
              </Button>
            </FormActions>
          </CardBody>
        </Card>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.key ?? "this setting"}?`}
        description="Anything reading it falls back to its built-in default."
        confirmPhrase={removing?.key}
        confirmLabel="Delete setting"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.key);
        }}
      />
    </div>
  );
}
