"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell, CheckCheck, Lock, RotateCcw } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  MarkReadResponse,
  NotificationPreferencesResponse,
  NotificationResponse,
  PageNotificationResponse,
  PreferenceResetResponse,
} from "@/lib/api/types";
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
import { Pagination } from "@/components/ui/data-table";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { usePushSubscription } from "@/lib/push";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function Feed() {
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const { limit, offset, setPage } = useListState(25);
  const [unreadOnly, setUnreadOnly] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["notifications", "feed", unreadOnly, limit, offset],
    queryFn: () =>
      api.get<PageNotificationResponse>("/notifications", {
        query: { unread_only: unreadOnly || undefined, limit, offset },
      }),
  });

  const markRead = useApiMutation<NotificationResponse, string>({
    mutationFn: (id) => api.post<NotificationResponse>(`/notifications/${segment(id)}/read`),
    invalidate: [["notifications"], ["unread"]],
  });

  return (
    <Card>
      <CardHeader
        title="Your notifications"
        actions={
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={unreadOnly}
              onCheckedChange={(checked) => {
                setUnreadOnly(checked);
                setPage({ limit, offset: 0 });
              }}
            />
            Unread only
          </label>
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyState icon={<Bell className="size-5" />} title="Nothing to catch up on" />
      ) : (
        <>
          <ul className="divide-y divide-border-subtle">
            {(data?.items ?? []).map((notification) => (
              <li
                key={notification.public_id}
                className={`flex items-start gap-3 px-4 py-3 ${
                  notification.is_read ? "" : "bg-accent/40"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{notification.title}</span>
                    <Badge tone="neutral">{humanise(notification.type)}</Badge>
                    {notification.channel !== "SYSTEM" ? (
                      <Badge tone="info">{notification.channel}</Badge>
                    ) : null}
                  </p>
                  <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">
                    {notification.body}
                  </p>
                  <p
                    className="text-xs text-muted-foreground"
                    title={formatDateTime(notification.sent_at, { timeZone })}
                  >
                    {formatRelative(notification.sent_at, locale)}
                  </p>
                </div>
                {!notification.is_read ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => markRead.mutate(notification.public_id)}
                  >
                    Mark read
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="notifications"
          />
        </>
      )}
    </Card>
  );
}

function DevicePush() {
  const { state, busy, subscribe, unsubscribe, error } = usePushSubscription();

  // Each state is a different, separately-fixable problem. "Subscribe did
  // nothing" is the least actionable message a person can be handed, so none
  // of these collapse into one.
  const explanation: Record<typeof state, string> = {
    checking: "Checking whether this device can receive notifications…",
    unsupported: "This browser does not support push notifications.",
    insecure: "Push notifications need a secure (https) connection.",
    disabled: "Push notifications are not configured on this server.",
    denied:
      "You blocked notifications for this site. Re-allow them in your browser’s site settings to turn them back on here.",
    subscribed: "This device will receive notifications even when the LMS is closed.",
    available: "Get notified on this device when the LMS is closed.",
  };

  return (
    <Card>
      <CardHeader
        title="This device"
        description="Separate from the switches below, which decide what is worth telling you at all."
      />
      <CardBody className="space-y-3">
        <p className="text-sm text-muted-foreground">{explanation[state]}</p>
        {error ? <p className="text-sm text-danger">{error}</p> : null}

        {state === "subscribed" ? (
          <Button variant="secondary" size="sm" loading={busy} onClick={() => void unsubscribe()}>
            Turn off on this device
          </Button>
        ) : null}
        {state === "available" ? (
          // Only ever from a click: an unprompted permission request is the
          // pattern browsers penalise, and a dismissal can cost this origin
          // the ability to ask again at all.
          <Button size="sm" loading={busy} onClick={() => void subscribe()}>
            Turn on for this device
          </Button>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Preferences() {
  const { permissions } = useSession();
  const canEdit = permissions.has("notification.update");

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: () => api.get<NotificationPreferencesResponse>("/notifications/preferences"),
  });

  const setPreference = useApiMutation<unknown, { type: string; enabled: boolean }>({
    mutationFn: ({ type, enabled }) =>
      api.put(`/notifications/preferences/${segment(type)}`, { body: { enabled } }),
    success: "Preference saved.",
    invalidate: [["notifications", "preferences"]],
  });

  const reset = useApiMutation<PreferenceResetResponse, void>({
    mutationFn: () => api.delete<PreferenceResetResponse>("/notifications/preferences"),
    success: (result) => `Cleared ${result.cleared} override(s).`,
    invalidate: [["notifications", "preferences"]],
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <DevicePush />

      {data.channels_note ? (
        <p className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-sm text-muted-foreground">
          {data.channels_note}
        </p>
      ) : null}

      {data.categories.map((category) => {
        const items = data.preferences.filter((preference) => preference.category === category);
        if (items.length === 0) return null;
        return (
          <Card key={category}>
            <CardHeader title={humanise(category)} />
            <CardBody className="space-y-3">
              {items.map((preference) => (
                <label key={preference.type} className="flex items-start gap-3 text-sm">
                  <Switch
                    checked={preference.enabled}
                    // Mandatory notices are locked open on the server too --
                    // this switch is disabled because the API refuses the
                    // change, not instead of it.
                    disabled={!canEdit || preference.mandatory === true || setPreference.isPending}
                    onCheckedChange={(checked) =>
                      setPreference.mutate({ type: preference.type, enabled: checked })
                    }
                  />
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 font-medium">
                      {humanise(preference.type)}
                      {preference.mandatory ? (
                        <Badge tone="warning">
                          <Lock className="size-3" /> Always on
                        </Badge>
                      ) : null}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {preference.description}
                    </span>
                  </span>
                </label>
              ))}
            </CardBody>
          </Card>
        );
      })}

      {canEdit ? (
        <Button variant="secondary" loading={reset.isPending} onClick={() => reset.mutate()}>
          <RotateCcw /> Reset to defaults
        </Button>
      ) : null}
    </div>
  );
}

export default function NotificationsPage() {
  const markAll = useApiMutation<MarkReadResponse, void>({
    mutationFn: () => api.post<MarkReadResponse>("/notifications/read-all"),
    success: (result) => `Marked ${result.updated} notification(s) read.`,
    invalidate: [["notifications"], ["unread"]],
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Notifications"
        description="What the system has told you, and which of those you want to keep receiving."
        actions={
          <Button variant="secondary" loading={markAll.isPending} onClick={() => markAll.mutate()}>
            <CheckCheck /> Mark all read
          </Button>
        }
      />

      <Tabs defaultValue="feed">
        <TabsList>
          <TabsTab value="feed">Feed</TabsTab>
          <TabsTab value="preferences">Preferences</TabsTab>
        </TabsList>
        <TabsPanel value="feed">
          <Feed />
        </TabsPanel>
        <TabsPanel value="preferences">
          <Preferences />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
