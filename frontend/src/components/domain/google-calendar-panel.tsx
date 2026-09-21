"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CalendarDays, Check, CheckCircle2, Copy, Link2Off, Plug } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import type { GoogleConnectResponse, GoogleStatusResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { LaitSyncControls } from "@/components/domain/lait-sync";
import { GoogleChangeQueue } from "@/components/domain/google-change-queue";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

export const GOOGLE_STATUS_KEY = ["google", "status"] as const;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[11rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function CopyValue({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return (
    <span className="inline-flex items-center gap-1">
      <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-xs">{value}</code>
      <Button
        type="button"
        variant="ghost"
        aria-label="Copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          } catch {
            toast.error("Copying is blocked in this browser. Select the text and copy it manually.");
          }
        }}
      >
        {done ? <Check /> : <Copy />}
      </Button>
    </span>
  );
}

/**
 * The Google Calendar connection and its synchronisation.
 *
 * The institution acts as **one Google account**. A Super Admin signs in once; the LMS then
 * keeps one calendar per batch up to date, administrators are given write access to those
 * calendars, and everyone else sees their sessions because they are guests on the events.
 */
export function GoogleCalendarPanel() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const canConnect = permissions.has("google.update");
  const canSync = permissions.has("google.sync");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: GOOGLE_STATUS_KEY,
    queryFn: () => api.get<GoogleStatusResponse>("/integrations/google/status"),
  });

  const connect = useApiMutation<GoogleConnectResponse, void>({
    mutationFn: () => api.post<GoogleConnectResponse>("/integrations/google/connect"),
    // Leaves the console for Google's own consent screen; Google sends the browser back to the callback page.
    onSuccess: (result) => {
      window.location.assign(result.url);
    },
  });

  const disconnect = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>("/integrations/google/connection"),
    success: "Google Calendar disconnected. Existing calendars stay in Google but stop being updated.",
    invalidate: [[...GOOGLE_STATUS_KEY]],
    onSuccess: () => setConfirmDisconnect(false),
  });

  if (isPending) return <LoadingState rows={4} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <div className="space-y-5">
      {data.problem ? (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-warning/50 bg-warning/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div className="space-y-1">
            <p className="font-medium">Google sign-in is not set up correctly</p>
            <p className="text-muted-foreground">{data.problem}</p>
            <p className="text-muted-foreground">Fix the value in <code className="font-mono text-xs">.env</code>, then restart the API.</p>
          </div>
        </div>
      ) : null}

      <Card>
        <CardHeader
          title="Google Calendar"
          description="One calendar per batch, one event per session. People see their sessions because they are guests on the events."
          actions={
            data.connected ? (
              <Badge tone="success">
                <CheckCircle2 className="size-3.5" aria-hidden /> Connected
              </Badge>
            ) : (
              <Badge tone="neutral">Not connected</Badge>
            )
          }
        />
        <CardBody className="space-y-4">
          <dl className="divide-y divide-border rounded-lg border border-border px-4">
            <Row label="Account">
              {data.connected ? (
                <span>
                  {data.account_email}
                  {data.connected_at ? (
                    <span className="text-muted-foreground"> · connected {formatDateTime(data.connected_at, { timeZone })}</span>
                  ) : null}
                </span>
              ) : (
                <span className="text-muted-foreground">
                  {data.expected_email ? `Sign in as ${data.expected_email}` : "No account connected"}
                </span>
              )}
            </Row>
            <Row label="Batch calendars">{data.calendars}</Row>
            <Row label="Guests on events">
              {data.invite_attendees ? "Tutors, enrolled students, their guardians and their employers' managers" : "Nobody (events are created without guests)"}
            </Row>
            <Row label="Guest emails">
              {data.send_updates === "none" ? "Not sent. Guests see the event on their calendar without an email." : `Sent (${data.send_updates}).`}
            </Row>
            <Row label="Who can edit in Google">
              {data.share_with_admins
                ? data.admins_can_edit
                  ? "Super Admins and Administrators. Everyone else only sees their own sessions."
                  : "Super Admins only. Administrators can view every calendar; everyone else sees only their own sessions."
                : "Not shared automatically"}
            </Row>
            <Row label="Awaiting review">
              {(data.pending_changes ?? 0) > 0 ? <Badge tone="warning">{data.pending_changes} enrolment change(s) from Google</Badge> : "Nothing"}
            </Row>
          </dl>

          <div className="flex flex-wrap items-center gap-2">
            {canConnect ? (
              data.connected ? (
                <>
                  <Button variant="secondary" loading={connect.isPending} disabled={Boolean(data.problem)} onClick={() => connect.mutate()}>
                    <Plug /> Reconnect
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirmDisconnect(true)}>
                    <Link2Off /> Disconnect
                  </Button>
                </>
              ) : (
                <Button loading={connect.isPending} disabled={Boolean(data.problem)} onClick={() => connect.mutate()}>
                  <CalendarDays /> Connect Google Calendar
                </Button>
              )
            ) : (
              <p className="text-xs text-muted-foreground">Only a Super Admin can connect or disconnect Google.</p>
            )}
            {data.connected ? (
              <LaitSyncControls
                canSync={canSync}
                runsPath="/integrations/google"
                startPath="/integrations/google/sync"
                label="Sync to Google now"
                previewLabel="Preview changes"
                invalidate={[[...GOOGLE_STATUS_KEY], ["batches"]]}
              />
            ) : null}
          </div>
        </CardBody>
      </Card>

      {data.connected ? (
        <Card>
          <CardHeader title="Managing the schedule from Google Calendar" description="Open a batch's calendar in Google (the batch page has a link). Changes are read on the next sync." />
          <CardBody>
            <dl className="divide-y divide-border rounded-lg border border-border px-4 text-sm">
              <Row label="Add a session">
                Create an event in the batch calendar. Add the tutor as a guest, and put the place in Location: <em>Zoom Video Conferencing</em> or the classroom address. It becomes a session, and the
                event is renamed to the standard <em>Course (batch code)</em> form. If it cannot be added, the reason is written at the top of the event.
              </Row>
              <Row label="Reschedule">Drag or resize the event. The session time is updated.</Row>
              <Row label="Cancel a class">
                Start the title with <strong>CANCEL</strong> and the record is kept as cancelled. Deleting the event removes the session, unless it already has attendance, in which case it is kept as cancelled.
              </Row>
              <Row label="Enrolments">
                Adding or removing a guest is a <strong>proposal</strong>. It appears below and is applied only when you approve it. The calendar is put back to match the LMS until then.
              </Row>
            </dl>
          </CardBody>
        </Card>
      ) : null}

      {data.connected ? <GoogleChangeQueue /> : null}

      {canConnect ? (
        <Card>
          <CardHeader title="Set-up" description="What Google needs to know about this console, once." />
          <CardBody className="space-y-3 text-sm">
            <p>
              In Google Cloud Console, open <strong>APIs &amp; Services &rarr; Credentials</strong>, choose the Web application OAuth client, and add
              this as an <strong>Authorized redirect URI</strong>:
            </p>
            <CopyValue value={data.redirect_uri} />
            <p className="text-muted-foreground">
              Only the Google Calendar API is used. The LMS asks for access to calendars it creates itself, plus permission to share them with
              administrators. It cannot read your other calendars, and no Classroom, Meet or YouTube access is requested.
            </p>
          </CardBody>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmDisconnect}
        onOpenChange={setConfirmDisconnect}
        destructive
        title="Disconnect Google Calendar?"
        description="Access is revoked at Google. Existing batch calendars stay where they are but stop being updated until you connect again."
        confirmLabel="Disconnect"
        pending={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
      />
    </div>
  );
}
