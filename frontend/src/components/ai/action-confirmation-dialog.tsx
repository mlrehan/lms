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
  /** When set, the person must type this phrase exactly before the action can run. */
  typed_confirmation?: string | null;
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
  const [typed, setTyped] = useState("");

  if (!ticket) return null;

  const phrase = ticket.typed_confirmation ?? null;
  // Exact match, as the server checks it: a phrase that is "close enough"
  // here would only be refused there.
  const phraseMatches = phrase === null || typed.trim() === phrase;

  const close = (next: boolean) => {
    if (!next) setTyped("");
    onOpenChange(next);
  };

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      const response = await api.post<{ success: boolean; result: Record<string, unknown> }>(
        "/ai/confirm",
        {
          body: {
            ticket_id: ticket.ticket_id,
            parameters: ticket.parameters,
            ...(phrase !== null ? { confirmation_text: typed.trim() } : {}),
          },
        },
      );

      // The server reports the action's own outcome; a confirmed action that
      // did nothing (e.g. a sync already running) must not read as success.
      if (response?.success === false) {
        toast.error("Action not completed", {
          description: (response?.result?.message as string) || "The action did not complete.",
        });
        close(false);
        return;
      }
      toast.success("Action executed successfully", {
        description: (response?.result?.message as string) || "The confirmed operation has completed.",
      });

      close(false);
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
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="md">
        <DialogHeader
          title={
            <div className="flex items-center gap-2 text-warning">
              <AlertTriangle className="size-5 shrink-0" />
              <span>Confirm this action</span>
            </div>
          }
          description="Nothing has happened yet. Check what will be done, then confirm or cancel."
        />

        <div className="space-y-3.5 my-2">
          {/* What will happen, as described by the server -- never by the assistant */}
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-3.5 text-xs text-foreground">
            <p className="font-semibold text-sm break-words">{ticket.preview_summary}</p>
          </div>

          <div className="rounded-xl border border-border-subtle bg-muted/40 p-3 text-xs space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Users className="size-3.5 text-primary" />
                Records affected:
              </span>
              <span className="font-semibold text-foreground">{ticket.affected_records_count}</span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <KeyRound className="size-3.5 text-primary" />
                Ticket:
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
                Valid until:
              </span>
              <span className="font-medium text-foreground">{expiresTime}</span>
            </div>
          </div>

          {phrase !== null && (
            <label className="block space-y-1.5 text-xs">
              <span className="text-muted-foreground">
                Type <span className="font-mono font-semibold text-foreground">{phrase}</span> to confirm.
              </span>
              <input
                type="text"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                aria-label="Confirmation phrase"
                data-testid="ai-confirm-phrase"
                className="w-full rounded-md border border-border-subtle bg-background px-2.5 py-1.5 font-mono text-xs"
              />
            </label>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" disabled={submitting} onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={submitting || !phraseMatches}
            onClick={handleConfirm}
            className="gap-1.5 bg-warning hover:bg-warning/90 text-warning-foreground"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                <span>Working...</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="size-3.5" />
                <span>Confirm</span>
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
