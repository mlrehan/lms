"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Search } from "lucide-react";
import { api } from "@/lib/api/client";
import type { PermissionResponse, RoleResponse } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Badge, Card, CardHeader, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { Input } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { humanise, moduleOf } from "@/lib/utils";

/**
 * The permission catalog, and the role-to-permission matrix.
 *
 * There is deliberately no "create permission" control. A permission row that
 * no `require_permissions(...)` call checks grants nothing -- it would look
 * like authority and be inert, which is worse than an obviously missing
 * feature. New permissions are added in the backend catalog, where the check
 * that enforces them is written.
 */
export default function PermissionsPage() {
  const { permissions: mine } = useSession();
  const [filter, setFilter] = useState("");

  const catalog = useQuery({
    queryKey: ["permissions"],
    queryFn: () => api.get<PermissionResponse[]>("/permissions"),
  });

  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: () => api.get<RoleResponse[]>("/roles"),
    enabled: mine.has("role.read"),
  });

  const grouped = useMemo(() => {
    const term = filter.trim().toLowerCase();
    const groups = new Map<string, PermissionResponse[]>();
    for (const permission of catalog.data ?? []) {
      if (
        term &&
        !permission.name.toLowerCase().includes(term) &&
        !(permission.description ?? "").toLowerCase().includes(term)
      ) {
        continue;
      }
      const key = permission.module ?? moduleOf(permission.name);
      const list = groups.get(key) ?? [];
      list.push(permission);
      groups.set(key, list);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [catalog.data, filter]);

  const matrix = useMemo(() => {
    const list = catalog.data ?? [];
    const term = filter.trim().toLowerCase();
    return list.filter((permission) => !term || permission.name.toLowerCase().includes(term));
  }, [catalog.data, filter]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Permissions"
        description="Every permission the API recognises. A role holds a subset; a person's effective permissions are the union of their roles'."
      />

      <div className="relative max-w-sm">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter permissions"
          aria-label="Filter permissions"
          className="pl-8"
        />
      </div>

      {catalog.isPending ? (
        <LoadingState rows={6} />
      ) : catalog.error ? (
        <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} />
      ) : (
        <Tabs defaultValue="catalog">
          <TabsList>
            <TabsTab value="catalog">Catalog</TabsTab>
            <TabsTab value="matrix">Role matrix</TabsTab>
            <TabsTab value="mine">What I hold</TabsTab>
          </TabsList>

          <TabsPanel value="catalog">
            <div className="grid gap-3 md:grid-cols-2">
              {grouped.map(([module, items]) => (
                <Card key={module}>
                  <CardHeader
                    title={humanise(module)}
                    actions={<Badge tone="neutral">{items.length}</Badge>}
                  />
                  <ul className="divide-y divide-border">
                    {items.map((permission) => (
                      <li key={permission.name} className="px-4 py-2">
                        <p className="font-mono text-xs font-medium">{permission.name}</p>
                        {permission.description ? (
                          <p className="text-xs text-muted-foreground">{permission.description}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </Card>
              ))}
            </div>
          </TabsPanel>

          <TabsPanel value="matrix">
            {!mine.has("role.read") ? (
              <p className="text-sm text-muted-foreground">
                The matrix needs <code className="font-mono text-xs">role.read</code> to list roles.
              </p>
            ) : roles.isPending ? (
              <LoadingState rows={6} />
            ) : (
              <Card>
                <div className="overflow-x-auto scrollbar-thin">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-border">
                        <th
                          scope="col"
                          className="sticky left-0 z-10 bg-surface px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                        >
                          Permission
                        </th>
                        {(roles.data ?? []).map((role) => (
                          <th
                            key={role.name}
                            scope="col"
                            className="whitespace-nowrap px-3 py-2 text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                          >
                            {role.name}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {matrix.map((permission) => (
                        <tr key={permission.name} className="border-b border-border/70 last:border-0">
                          <th
                            scope="row"
                            className="sticky left-0 z-10 bg-surface px-4 py-1.5 text-left font-mono text-xs font-normal"
                          >
                            {permission.name}
                          </th>
                          {(roles.data ?? []).map((role) => (
                            <td key={role.name} className="px-3 py-1.5 text-center">
                              {(role.permissions ?? []).includes(permission.name) ? (
                                <Check className="mx-auto size-4 text-success" aria-label="granted" />
                              ) : (
                                <span className="text-muted-foreground/40" aria-label="not granted">
                                  ·
                                </span>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </TabsPanel>

          <TabsPanel value="mine">
            <Card>
              <CardHeader
                title="Your effective permissions"
                description="Resolved by the server from your roles. This is the exact list every screen in this console asks about."
                actions={<Badge tone="primary">{mine.all.length}</Badge>}
              />
              <div className="flex flex-wrap gap-1.5 p-4">
                {[...mine.all].sort().map((permission) => (
                  <Badge key={permission} tone="neutral" className="font-mono">
                    {permission}
                  </Badge>
                ))}
              </div>
            </Card>
          </TabsPanel>
        </Tabs>
      )}
    </div>
  );
}
