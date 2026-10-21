"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, Hash, KeyRound, Loader2, Users } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";

export interface TicketDetails {
  ticket_id: string;
  action_name: string;
  parameters: Record<string, unknown>;
  parameters_hash: string;
  affected_records_count: number;
  preview_summary: string;
  expires_at: string;
  status: string;
}

interface ActionConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticket: TicketDetails | null;
  onSuccess?: (result: Record<string, unknown>) => void;
}

export function ActionConfirmationDialog({
  open,
  onOpenChange,
  ticket,
  onSuccess,
}: ActionConfirmationDialogProps) {
  const [submitting, setSubmitting] = useState(false);

  if (!ticket) return null;

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      const response = await api.post<{ success: boolean; result: Record<string, unknown> }>(
        "/ai/confirm",
        {
          body: {
            ticket_id: ticket.ticket_id,
            parameters: ticket.parameters,
          },
        },
      );

      toast.success("Action executed successfully", {
        description: (response?.result?.message as string) || "The confirmed operation has completed.",
      });

      onOpenChange(false);
      onSuccess?.(response?.result || {});
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Confirmation failed to execute.";
      toast.error("Execution failed", { description: message });
    } finally {
      setSubmitting(false);
    }
  };

  const expiresTime = new Date(ticket.expires_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader
          title={
            <div className="flex items-center gap-2 text-warning">
              <AlertTriangle className="size-5 shrink-0" />
              <span>Two-Phase Action Confirmation</span>
            </div>
          }
          description="High-risk and state-mutating LMS actions require explicit cryptographic verification."
        />

        <div className="space-y-3.5 my-2">
          {/* Summary Banner */}
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-3.5 text-xs text-foreground">
            <p className="font-semibold text-sm mb-1">{ticket.preview_summary}</p>
            <p className="text-muted-foreground">
              This action will publish content directly to student dashboards. Please verify the target parameters below.
            </p>
          </div>

          {/* Cryptographic Verification Details */}
          <div className="rounded-xl border border-border-subtle bg-muted/40 p-3 text-xs space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Users className="size-3.5 text-primary" />
                Affected Records:
              </span>
              <span className="font-semibold text-foreground">
                {ticket.affected_records_count} Enrolled Student(s)
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <KeyRound className="size-3.5 text-primary" />
                Ticket Fingerprint:
              </span>
              <span className="font-mono text-2xs text-muted-foreground truncate max-w-48" title={ticket.ticket_id}>
                {ticket.ticket_id}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Hash className="size-3.5 text-primary" />
                Parameter SHA-256:
              </span>
              <span className="font-mono text-2xs text-muted-foreground">
                {ticket.parameters_hash ? `${ticket.parameters_hash.slice(0, 16)}...` : "N/A"}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Clock className="size-3.5 text-warning" />
                Valid Until:
              </span>
              <span className="font-medium text-foreground">{expiresTime} (15m TTL)</span>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={submitting}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={submitting}
            onClick={handleConfirm}
            className="gap-1.5 bg-warning hover:bg-warning/90 text-warning-foreground"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                <span>Executing...</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="size-3.5" />
                <span>Confirm & Publish</span>
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
