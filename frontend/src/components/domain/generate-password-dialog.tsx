"use client";

/**
 * Generate (or regenerate) a person's password: confirm, generate on the
 * server, then show it once with a Copy button.
 *
 * The password is made by the server (`secrets`, 16 characters) and arrives in
 * exactly one response. This component keeps it only in memory while the
 * dialog is open and drops it on close: nothing writes it to storage, the URL
 * or the query cache, so closing the dialog is the end of it.
 */

import { useState, type ReactNode } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, segment } from "@/lib/api/client";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";

interface GeneratedPasswordResponse {
  password: string;
  sessions_ended?: boolean;
}

export function GeneratePasswordDialog({
  userId,
  name,
  open,
  onOpenChange,
}: {
  userId: string;
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}): ReactNode {
  const [password, setPassword] = useState<string | null>(null);
  const [shown, setShown] = useState(true);
  const [copied, setCopied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const generate = useApiMutation<GeneratedPasswordResponse, void>({
    mutationFn: () =>
      api.post<GeneratedPasswordResponse>(`/users/${segment(userId)}/password/generate`),
    // The result is the password itself, so no cache entry is invalidated or
    // written; only the account's own lists move (sessions ended).
    invalidate: [["users", "detail", userId]],
    onSuccess: (data) => {
      setProblem(null);
      setPassword(data.password);
    },
    onError: (error) => setProblem(error.message),
  });

  function close(next: boolean) {
    if (!next) {
      setPassword(null);
      setProblem(null);
      setCopied(false);
      setShown(true);
    }
    onOpenChange(next);
  }

  async function copy() {
    if (!password) return;
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Copying is blocked in this browser. Select the password and copy it manually.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="md">
        {password ? (
          <>
            <DialogHeader
              title="New password"
              description={`This is the only time ${name}'s new password is shown. Copy it now and pass it on through a channel you trust.`}
            />
            <div className="space-y-3">
              <div className="flex items-center gap-2 rounded-lg border border-border-subtle bg-surface-raised p-2">
                <code
                  className="flex-1 select-all break-all px-1 font-mono text-base tracking-wide"
                  aria-label="Generated password"
                >
                  {shown ? password : "•".repeat(password.length)}
                </code>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={shown ? "Hide password" : "Show password"}
                  onClick={() => setShown(!shown)}
                >
                  {shown ? <EyeOff /> : <Eye />}
                </Button>
                <Button type="button" variant="secondary" size="sm" onClick={() => void copy()}>
                  {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Every sign-in for this account has been ended, and they have been notified that
                their password was reset. If their sign-in is switched off, turn it on separately.
              </p>
            </div>
            <DialogFooter>
              <Button type="button" onClick={() => close(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader
              title={`Generate a new password for ${name}?`}
              description="A secure random password replaces the current one straight away."
            />
            <div className="space-y-3 text-sm">
              <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-warning">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <div className="space-y-1">
                  <p className="font-medium">Their current password stops working immediately.</p>
                  <p>Every device they are signed in on is signed out, and they are told their password was reset.</p>
                </div>
              </div>
              {problem ? (
                <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
                  {problem}
                </div>
              ) : null}
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                loading={generate.isPending}
                onClick={() => generate.mutate()}
              >
                <KeyRound /> Generate password
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
