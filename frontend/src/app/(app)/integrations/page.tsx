"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  CalendarDays,
  Copy,
  KeyRound,
  Plus,
  Send,
  Trash2,
  Webhook,
} from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  CalendarFeedCreatedResponse,
  CalendarFeedResponse,
  PageWebhookDeliveryResponse,
  PageWebhookEndpointResponse,
  RotateSecretResponse,
  TestDeliveryResponse,
  WebhookCreatedResponse,
  WebhookDeliveryResponse,
  WebhookEndpointResponse,
  WebhookEventCatalogResponse,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { GoogleCalendarPanel } from "@/components/domain/google-calendar-panel";
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
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { StatusBadge } from "@/components/domain/status-badge";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

/**
 * A secret shown exactly once.
 *
 * The backend stores a hash and has no endpoint that returns the value again,
 * so this dialog is the only chance anyone gets to copy it. It is never
 * written to `localStorage`, never logged, and disappears from memory when
 * the dialog closes.
 */
function OneTimeSecret({
  title,
  secret,
  note,
  onClose,
}: {
  title: string;
  secret: string | null;
  note?: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={secret !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent size="md">
        <DialogHeader
          title={title}
          description="Copy it now. The server keeps only a hash, so there is no way to show it again."
        />
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Input
              readOnly
              value={secret ?? ""}
              className="font-mono text-xs"
              aria-label="Secret value"
              onFocus={(event) => event.currentTarget.select()}
            />
            <Button
              variant="secondary"
              onClick={() => {
                if (secret) {
                  void navigator.clipboard
                    .writeText(secret)
                    .then(() => toast.success("Copied to the clipboard."))
                    .catch(() => toast.error("Could not copy. Select the text and copy it manually."));
                }
              }}
            >
              <Copy /> Copy
            </Button>
          </div>
          {note ? (
            <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {note}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Deliveries({ webhook }: { webhook: WebhookEndpointResponse }) {
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(10);
  const [status, setStatus] = useState("");

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["integrations", "deliveries", webhook.public_id, status, limit, offset],
    queryFn: () =>
      api.get<PageWebhookDeliveryResponse>(
        `/integrations/webhooks/${segment(webhook.public_id)}/deliveries`,
        { query: { status: status || undefined, limit, offset } },
      ),
  });

  const columns: Column<WebhookDeliveryResponse>[] = [
    { key: "event", header: "Event", cell: (row) => <Badge tone="neutral">{row.event}</Badge> },
    {
      key: "status",
      header: "Status",
      cell: (row) => <StatusBadge value={row.status} kind="delivery" />,
    },
    {
      key: "attempts",
      header: "Attempts",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.attempts ?? 0}</span>,
    },
    {
      key: "response",
      header: "Response",
      cell: (row) => (
        <span className="text-xs">
          {row.response_status ?? "—"}
          {row.error ? (
            <span className="block max-w-64 truncate text-danger">{row.error}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "when",
      header: "Created",
      secondary: true,
      cell: (row) => formatDateTime(row.created_at, { timeZone }),
    },
    {
      key: "next",
      header: "Next attempt",
      secondary: true,
      cell: (row) => formatDateTime(row.next_attempt_at, { timeZone }),
    },
  ];

  return (
    <div className="border-t border-border-subtle">
      <div className="flex items-center gap-2 p-3">
        <NativeSelect
          className="w-44"
          aria-label="Filter deliveries by status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage({ limit, offset: 0 });
          }}
        >
          <option value="">Any status</option>
          {["queued", "delivered", "failed", "retrying", "abandoned"].map((value) => (
            <option key={value} value={value}>
              {humanise(value)}
            </option>
          ))}
        </NativeSelect>
      </div>
      {isPending ? (
        <LoadingState rows={3} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="Nothing delivered yet."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="deliveries"
          />
        </>
      )}
    </div>
  );
}

function Webhooks() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const { limit, offset, setPage } = useListState(10);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [removing, setRemoving] = useState<WebhookEndpointResponse | null>(null);
  const [draft, setDraft] = useState({ name: "", target_url: "", description: "", events: [] as string[] });

  const catalog = useQuery({
    queryKey: ["integrations", "events"],
    queryFn: () => api.get<WebhookEventCatalogResponse>("/integrations/webhooks/events"),
    staleTime: 10 * 60_000,
  });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["integrations", "webhooks", limit, offset],
    queryFn: () =>
      api.get<PageWebhookEndpointResponse>("/integrations/webhooks", { query: { limit, offset } }),
  });

  const create = useApiMutation<WebhookCreatedResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<WebhookCreatedResponse>("/integrations/webhooks", {
        body: {
          name: values.name,
          target_url: values.target_url,
          events: values.events,
          description: values.description || null,
        },
      }),
    success: "Webhook created.",
    invalidate: [["integrations"]],
    onSuccess: (created) => {
      setSecret(created.secret);
      setDraft({ name: "", target_url: "", description: "", events: [] });
      setCreateOpen(false);
    },
  });

  const setActive = useApiMutation<WebhookEndpointResponse, { id: string; is_active: boolean }>({
    mutationFn: ({ id, is_active }) =>
      api.patch<WebhookEndpointResponse>(`/integrations/webhooks/${segment(id)}`, {
        body: { is_active },
      }),
    success: "Webhook updated.",
    invalidate: [["integrations"]],
  });

  const rotate = useApiMutation<RotateSecretResponse, string>({
    mutationFn: (id) =>
      api.post<RotateSecretResponse>(`/integrations/webhooks/${segment(id)}/rotate-secret`),
    invalidate: [["integrations"]],
    onSuccess: (result) => setSecret(result.secret),
  });

  const test = useApiMutation<TestDeliveryResponse, string>({
    mutationFn: (id) => api.post<TestDeliveryResponse>(`/integrations/webhooks/${segment(id)}/test`),
    success: (result) =>
      result.delivered
        ? `Delivered (HTTP ${result.response_status ?? "?"}).`
        : `Not delivered: ${result.error ?? "unknown error"}.`,
    invalidate: [["integrations"]],
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (id) => api.delete<void>(`/integrations/webhooks/${segment(id)}`),
    success: "Webhook deleted.",
    invalidate: [["integrations"]],
    onSuccess: () => setRemoving(null),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Webhook endpoints"
          description="The server connects out to these URLs. Only public HTTP(S) addresses are accepted -- loopback, private and link-local ranges are refused, including via DNS."
          actions={
            permissions.has("integration.create") ? (
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus /> New endpoint
              </Button>
            ) : null
          }
        />
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (data?.items.length ?? 0) === 0 ? (
          <CardBody>
            <p className="text-sm text-muted-foreground">No endpoints registered.</p>
          </CardBody>
        ) : (
          <>
            <ul className="divide-y divide-border-subtle">
              {(data?.items ?? []).map((webhook) => (
                <li key={webhook.public_id}>
                  <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        <Webhook className="size-4 text-muted-foreground" aria-hidden />
                        {webhook.name}
                        {webhook.failure_count && webhook.failure_count > 0 ? (
                          <Badge tone="danger">{webhook.failure_count} consecutive failures</Badge>
                        ) : null}
                      </p>
                      <p className="break-all font-mono text-xs text-muted-foreground">
                        {webhook.target_url}
                      </p>
                      <p className="mt-1 flex flex-wrap gap-1">
                        {webhook.events.map((event) => (
                          <Badge key={event} tone="neutral">
                            {event}
                          </Badge>
                        ))}
                      </p>
                      {webhook.last_failure_reason ? (
                        <p className="mt-1 text-xs text-danger">
                          Last failure: {webhook.last_failure_reason} (
                          {formatDateTime(webhook.last_failure_at, { timeZone })})
                        </p>
                      ) : webhook.last_success_at ? (
                        <p className="mt-1 text-xs text-muted-foreground">
                          Last delivered {formatDateTime(webhook.last_success_at, { timeZone })}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                      {permissions.has("integration.update") ? (
                        <label className="flex items-center gap-2 text-xs">
                          <Switch
                            checked={webhook.is_active ?? false}
                            disabled={setActive.isPending}
                            onCheckedChange={(checked) =>
                              setActive.mutate({ id: webhook.public_id, is_active: checked })
                            }
                          />
                          Active
                        </label>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setExpanded(expanded === webhook.public_id ? null : webhook.public_id)
                        }
                      >
                        Deliveries
                      </Button>
                      {permissions.has("integration.update") ? (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            loading={test.isPending && test.variables === webhook.public_id}
                            onClick={() => test.mutate(webhook.public_id)}
                          >
                            <Send /> Test
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            loading={rotate.isPending && rotate.variables === webhook.public_id}
                            onClick={() => rotate.mutate(webhook.public_id)}
                          >
                            <KeyRound /> Rotate secret
                          </Button>
                        </>
                      ) : null}
                      {permissions.has("integration.delete") ? (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${webhook.name}`}
                          onClick={() => setRemoving(webhook)}
                        >
                          <Trash2 className="text-danger" />
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {expanded === webhook.public_id ? <Deliveries webhook={webhook} /> : null}
                </li>
              ))}
            </ul>
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="endpoints"
            />
          </>
        )}
      </Card>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="md">
          <DialogHeader
            title="New webhook endpoint"
            description={catalog.data?.note ?? "Deliveries are signed; verify the signature at the receiving end."}
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
            <Field label="Target URL" required hint="Must be a public http(s) address.">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.target_url}
                  placeholder="https://example.com/hooks/lms"
                  onChange={(event) => setDraft({ ...draft, target_url: event.target.value.trim() })}
                />
              )}
            </Field>
            <Field label="Events" required>
              <div className="flex flex-wrap gap-2">
                {(catalog.data?.events ?? []).map((event) => {
                  const checked = draft.events.includes(event);
                  return (
                    <label
                      key={event}
                      className={`cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                        checked
                          ? "border-primary bg-accent text-accent-foreground"
                          : "border-border-subtle text-muted-foreground hover:border-border-strong"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        onChange={(changeEvent) =>
                          setDraft({
                            ...draft,
                            events: changeEvent.target.checked
                              ? [...draft.events, event]
                              : draft.events.filter((name) => name !== event),
                          })
                        }
                      />
                      {event}
                    </label>
                  );
                })}
              </div>
            </Field>
            <Field label="Description">
              {({ id }) => (
                <Textarea
                  id={id}
                  rows={2}
                  value={draft.description}
                  onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                />
              )}
            </Field>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={create.isPending}
              disabled={!draft.name || !draft.target_url || draft.events.length === 0}
              onClick={() => create.mutate(draft)}
            >
              Create endpoint
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <OneTimeSecret
        title="Signing secret"
        secret={secret}
        note="Anything holding this secret can forge a delivery that looks like ours. Store it where the receiving service keeps its credentials."
        onClose={() => setSecret(null)}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.name ?? "this endpoint"}?`}
        description="Queued deliveries to it are abandoned."
        confirmLabel="Delete endpoint"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </div>
  );
}

function CalendarFeeds() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const [name, setName] = useState("My timetable");
  const [created, setCreated] = useState<CalendarFeedCreatedResponse | null>(null);
  const [removing, setRemoving] = useState<CalendarFeedResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["integrations", "calendar-feeds"],
    queryFn: () => api.get<CalendarFeedResponse[]>("/integrations/calendar-feeds"),
  });

  const create = useApiMutation<CalendarFeedCreatedResponse, string>({
    mutationFn: (feedName) =>
      api.post<CalendarFeedCreatedResponse>("/integrations/calendar-feeds", {
        body: { name: feedName },
      }),
    invalidate: [["integrations", "calendar-feeds"]],
    onSuccess: (result) => setCreated(result),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (feedId) => api.delete<void>(`/integrations/calendar-feeds/${segment(feedId)}`),
    success: "Feed revoked.",
    invalidate: [["integrations", "calendar-feeds"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<CalendarFeedResponse>[] = [
    { key: "name", header: "Feed", cell: (row) => <span className="font-medium">{row.name}</span> },
    {
      key: "active",
      header: "State",
      cell: (row) => (
        <Badge tone={row.is_active ? "success" : "neutral"}>
          {row.is_active ? "Active" : "Revoked"}
        </Badge>
      ),
    },
    {
      key: "accessed",
      header: "Last read",
      cell: (row) => formatDateTime(row.last_accessed_at, { timeZone }),
    },
    {
      key: "count",
      header: "Reads",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.access_count ?? 0}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("integration.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Revoke ${row.name}`}
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
        title="Calendar feeds"
        description="A subscribable iCalendar URL for your own timetable. The link is the credential: anyone holding it can read your schedule without signing in."
        actions={
          permissions.has("integration.create") ? (
            <div className="flex items-center gap-2">
              <Input
                className="w-48"
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-label="Feed name"
              />
              <Button size="sm" loading={create.isPending} onClick={() => create.mutate(name)}>
                <CalendarDays /> Create feed
              </Button>
            </div>
          ) : null
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
          emptyMessage="No calendar feeds. Create one to subscribe from a calendar app."
        />
      )}

      <OneTimeSecret
        title="Your calendar feed URL"
        secret={created?.url ?? null}
        note={
          created?.warning ??
          "This URL is unauthenticated by design so calendar apps can poll it. Treat it as a password: anyone with it sees your timetable."
        }
        onClose={() => setCreated(null)}
      />

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Revoke ${removing?.name ?? "this feed"}?`}
        description="Any calendar subscribed to it stops updating immediately."
        confirmLabel="Revoke feed"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

export default function IntegrationsPage() {
  const { permissions } = useSession();
  const showGoogle = permissions.has("google.read");
  return (
    <div className="space-y-5">
      <PageHeader
        title="Integrations"
        description="Outbound webhooks and calendar feeds. Registering an endpoint decides where institution data is sent, which is why it is its own permission."
      />

      <Tabs defaultValue={showGoogle ? "google" : "webhooks"}>
        <TabsList>
          {showGoogle ? <TabsTab value="google">Google Calendar</TabsTab> : null}
          <TabsTab value="webhooks">Webhooks</TabsTab>
          <TabsTab value="calendar">Calendar feeds</TabsTab>
        </TabsList>
        {showGoogle ? (
          <TabsPanel value="google">
            <GoogleCalendarPanel />
          </TabsPanel>
        ) : null}
        <TabsPanel value="webhooks">
          <Webhooks />
        </TabsPanel>
        <TabsPanel value="calendar">
          <CalendarFeeds />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
