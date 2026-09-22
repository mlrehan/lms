"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ExternalLink } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { GoogleBatchResponse, GoogleStatusResponse } from "@/lib/api/types";
import { buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { LaitSyncControls } from "@/components/domain/lait-sync";
import { GOOGLE_STATUS_KEY } from "@/components/domain/google-calendar-panel";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

/**
 * A batch's Google calendar: open it, see how much of the schedule is mirrored, and push this
 * batch alone. Shown only to people who may read the Google integration.
 */
export function BatchGoogleCard({ batchId }: { batchId: string }) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const canRead = permissions.has("google.read");

  const status = useQuery({
    queryKey: GOOGLE_STATUS_KEY,
    queryFn: () => api.get<GoogleStatusResponse>("/integrations/google/status"),
    enabled: canRead,
    staleTime: 60_000,
  });
  const batch = useQuery({
    queryKey: ["google", "batch", batchId],
    queryFn: () => api.get<GoogleBatchResponse>(`/integrations/google/batches/${segment(batchId)}`),
    enabled: canRead,
  });

  if (!canRead || !status.data || !batch.data) return null;
  const b = batch.data;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border-subtle bg-surface px-4 py-3 text-sm">
      <span className="inline-flex items-center gap-2 font-medium">
        <CalendarDays className="size-4 text-primary" aria-hidden /> Google Calendar
      </span>
      {!status.data.connected ? (
        <Badge tone="neutral">Google is not connected</Badge>
      ) : b.has_calendar ? (
        <>
          <Badge tone={b.sessions_in_google === b.sessions ? "success" : "warning"}>
            {b.sessions_in_google} of {b.sessions} sessions in Google
          </Badge>
          {b.last_synced_at ? <span className="text-xs text-muted-foreground">synced {formatDateTime(b.last_synced_at, { timeZone })}</span> : null}
          {b.calendar_url ? (
            <a
              href={b.calendar_url}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "secondary" }), "gap-1")}
            >
              Open calendar <ExternalLink className="size-3.5" aria-hidden />
            </a>
          ) : null}
        </>
      ) : (
        <Badge tone="neutral">Not in Google yet</Badge>
      )}
      {status.data.connected ? (
        <LaitSyncControls
          canSync={permissions.has("google.sync")}
          runsPath="/integrations/google"
          startPath={`/integrations/google/sync?batch_id=${segment(batchId)}`}
          label={b.has_calendar ? "Sync this batch" : "Create calendar"}
          invalidate={[["google", "batch", batchId], [...GOOGLE_STATUS_KEY]]}
        />
      ) : null}
    </div>
  );
}
