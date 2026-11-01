"use client";

/**
 * Which grading scheme a course or batch is graded under, and where it came from.
 *
 * The order is batch -> course -> institution default, resolved on the server
 * (`GradingSchemeService.resolve`); this only shows the answer and, for a holder
 * of `grading_scheme.manage`, changes the record's own choice. Changing it
 * re-grades every student it covers at once, so the change is confirmed.
 */

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { GradingSchemeSummary, SchemeAssignment } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { useSession } from "@/lib/auth/session";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";

/** Sentinel for "no scheme of its own" -- a Select value cannot be null and selected at once. */
const INHERIT = "__inherit__";

const SOURCE_LABEL: Record<string, string> = {
  BATCH: "Set on this batch",
  COURSE: "From the course",
  DEFAULT: "Institution default",
  NONE: "No scheme applies",
};

export function SchemeAssignmentCard({
  kind,
  id,
}: {
  kind: "course" | "batch";
  id: string;
}): ReactNode {
  const { permissions } = useSession();
  const canRead = permissions.has("grading_scheme.read");
  const canManage = permissions.has("grading_scheme.manage");
  const path = `/${kind === "course" ? "courses" : "batches"}/${segment(id)}/grading-scheme`;

  const current = useQuery({
    queryKey: ["grading-scheme-assignment", kind, id],
    queryFn: () => api.get<SchemeAssignment>(path),
    enabled: canRead,
  });
  const schemes = useQuery({
    queryKey: ["grading-schemes"],
    queryFn: () => api.get<GradingSchemeSummary[]>("/grading-schemes"),
    enabled: canManage,
  });

  const [pending, setPending] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const assign = useApiMutation<SchemeAssignment, string | null>({
    mutationFn: (schemeId) => api.put<SchemeAssignment>(path, { body: { scheme_id: schemeId } }),
    success: "Grading scheme updated.",
    invalidate: [["grading-scheme-assignment"], ["grading-schemes"], ["performance"], ["gradebook"]],
    onSuccess: () => {
      setPending(null);
      setConfirming(false);
    },
  });

  if (!canRead) return null;

  const inheritLabel =
    kind === "batch" ? "Use the course's scheme" : "Use the institution default";
  const options = [
    { value: INHERIT, label: inheritLabel },
    // Only activated schemes: an inactive one's weights were never checked,
    // and the server refuses it.
    ...(schemes.data ?? [])
      .filter((s) => s.is_active)
      .map((s) => ({ value: s.public_id, label: s.is_default ? `${s.name} (default)` : s.name })),
  ];
  const data = current.data;
  const ownValue = data?.own_scheme_id ?? INHERIT;
  const chosenLabel = options.find((o) => o.value === pending)?.label;

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <Scale className="size-4 text-muted-foreground" aria-hidden /> Grading scheme
          </span>
        }
        description={
          kind === "batch"
            ? "A batch uses its course's scheme unless it has its own."
            : "A course uses the institution default unless it has its own. A batch can override it."
        }
      />
      <CardBody className="space-y-3">
        {current.isPending ? (
          <LoadingState rows={1} />
        ) : current.error ? (
          <ErrorState error={current.error} onRetry={() => void current.refetch()} />
        ) : data ? (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{data.effective_scheme_name ?? "None"}</span>
            <Badge tone={data.source === "NONE" ? "warning" : "neutral"}>
              {SOURCE_LABEL[data.source] ?? data.source}
            </Badge>
          </div>
        ) : null}

        {canManage && data ? (
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Grading scheme for this record"
              className="min-w-64"
              value={pending ?? ownValue}
              options={options}
              disabled={schemes.isPending}
              onValueChange={(next) => setPending(next && next !== ownValue ? next : null)}
            />
            <Button
              disabled={pending === null}
              loading={assign.isPending}
              onClick={() => setConfirming(true)}
            >
              Apply
            </Button>
          </div>
        ) : null}
      </CardBody>

      <ConfirmDialog
        open={confirming && pending !== null}
        onOpenChange={setConfirming}
        title="Change the grading scheme?"
        description={`Every student ${
          kind === "batch" ? "in this batch" : "in this course's batches without a scheme of their own"
        } will be graded under "${chosenLabel ?? ""}" from now on. Finalised transcripts keep the scheme they were issued under.`}
        confirmLabel="Change scheme"
        pending={assign.isPending}
        onConfirm={() => assign.mutate(pending === INHERIT ? null : pending)}
      />
    </Card>
  );
}
