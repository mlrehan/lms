"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, UserMinus, UserPlus, X } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { GoogleChangeRequestResponse, PageGoogleChangeRequestResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

export const GOOGLE_CHANGES_KEY = ["google", "changes"] as const;

function statusTone(status: string): "warning" | "success" | "neutral" {
  if (status === "PENDING") return "warning";
  if (status === "APPROVED") return "success";
  return "neutral";
}

/**
 * Enrolment changes somebody made in Google Calendar, waiting for a person to decide.
 *
 * A guest added to or removed from an event is a *proposal*: Google does not say who made the
 * edit, and an enrolment carries a fee, a certificate and a grade book. Approving here applies
 * it through the same rules as the Enrol and Drop buttons; if those refuse (the batch is full,
 * say) the request stays pending with the reason beside it.
 */
export function GoogleChangeQueue() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const canDecide = permissions.has("google.sync");
  const canApprove = canDecide && permissions.has("enrollment.create") && permissions.has("enrollment.update");
  const [filter, setFilter] = useState<"PENDING" | "">("PENDING");

  const { data, isPending, error, refetch } = useQuery({
    queryKey: [...GOOGLE_CHANGES_KEY, filter],
    queryFn: () =>
      api.get<PageGoogleChangeRequestResponse>("/integrations/google/changes", {
        query: { status: filter || undefined, limit: 50 },
      }),
  });

  const decide = useApiMutation<GoogleChangeRequestResponse, { id: string; action: "approve" | "reject" }>({
    mutationFn: ({ id, action }) =>
      api.post<GoogleChangeRequestResponse>(`/integrations/google/changes/${segment(id)}/${action}`),
    invalidate: [[...GOOGLE_CHANGES_KEY], ["google", "status"], ["batches"], ["enrollments"]],
    success: (result, { action }) =>
      result.status === "PENDING"
        ? "Not applied. See the reason on the request."
        : action === "approve"
          ? "Approved and applied."
          : "Rejected. The calendar will be put back to match the LMS.",
  });

  return (
    <Card>
      <CardHeader
        title="Changes from Google"
        description="Guests added to or removed from an event in Google Calendar. Nothing changes until a person approves it here."
        actions={
          <NativeSelect
            className="w-auto"
            value={filter}
            aria-label="Show"
            onChange={(event) => setFilter(event.target.value as "PENDING" | "")}
          >
            <option value="PENDING">Awaiting a decision</option>
            <option value="">Everything</option>
          </NativeSelect>
        }
      />
      <CardBody>
        {isPending ? (
          <LoadingState rows={2} />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (data?.items ?? []).length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {filter === "PENDING" ? "Nothing is waiting for a decision." : "No changes have been proposed from Google yet."}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {data?.items.map((change) => {
              const adding = change.kind === "ENROL_ADD";
              return (
                <li key={change.public_id} className="flex flex-wrap items-start justify-between gap-3 py-3 text-sm">
                  <div className="min-w-0 space-y-1">
                    <p className="flex flex-wrap items-center gap-2 font-medium">
                      {adding ? <UserPlus className="size-4 text-success" aria-hidden /> : <UserMinus className="size-4 text-warning" aria-hidden />}
                      {adding ? "Enrol" : "Drop"} {change.student_name ?? "a student"}
                      <span className="font-normal text-muted-foreground">in</span>
                      <Link href={`/batches/${change.batch_id}`} className="font-mono text-xs hover:underline">
                        {change.batch_code}
                      </Link>
                      <Badge tone={statusTone(change.status)}>{change.status}</Badge>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {change.email ? `${change.email} · ` : ""}{change.note} · detected {formatDateTime(change.detected_at, { timeZone })}
                      {change.decided_by ? ` · decided by ${change.decided_by}` : ""}
                    </p>
                    {change.last_error ? (
                      <p role="alert" className="text-xs text-danger">
                        Could not be applied: {change.last_error}
                      </p>
                    ) : null}
                  </div>
                  {change.status === "PENDING" && canDecide ? (
                    <div className="flex gap-2">
                      <Button
                        variant="secondary"
                        disabled={decide.isPending || !canApprove}
                        title={canApprove ? undefined : "Approving needs permission to enrol and update enrolments"}
                        onClick={() => decide.mutate({ id: change.public_id, action: "approve" })}
                      >
                        <Check /> Approve
                      </Button>
                      <Button variant="ghost" disabled={decide.isPending} onClick={() => decide.mutate({ id: change.public_id, action: "reject" })}>
                        <X /> Reject
                      </Button>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
