"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";

/**
 * A confirmation an action must pass before it happens.
 *
 * `confirmPhrase` is for the irreversible ones -- purging a resource, revoking
 * every session an account holds. Typing the name is friction on purpose: the
 * two-button dialog is muscle memory by the tenth time, and the point is to
 * make the person read *which* record they are about to destroy.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  confirmPhrase,
  pending = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  confirmPhrase?: string;
  pending?: boolean;
  onConfirm: () => void | Promise<void>;
}): ReactNode {
  const [typed, setTyped] = useState("");
  const satisfied = !confirmPhrase || typed.trim() === confirmPhrase;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setTyped("");
        onOpenChange(next);
      }}
    >
      <DialogContent size="sm">
        <DialogHeader title={title} description={description} />
        {confirmPhrase ? (
          <div className="space-y-1.5">
            <label htmlFor="confirm-phrase" className="block text-sm text-muted-foreground">
              Type <span className="font-mono font-medium text-foreground">{confirmPhrase}</span> to
              continue.
            </label>
            <Input
              id="confirm-phrase"
              value={typed}
              autoComplete="off"
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            loading={pending}
            disabled={!satisfied}
            onClick={() => void onConfirm()}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Small helper so a screen can drive the dialog without four `useState`s. */
export function useConfirm<T>(): {
  target: T | null;
  ask: (target: T) => void;
  close: () => void;
  open: boolean;
} {
  const [target, setTarget] = useState<T | null>(null);
  return {
    target,
    open: target !== null,
    ask: (next: T) => setTarget(next),
    close: () => setTarget(null),
  };
}
