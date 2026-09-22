"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Paperclip, Send, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, segment } from "@/lib/api/client";
import type { MailAttachmentInfo, MailMessageView, MailPerson, ReplyOptions } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { RecipientField } from "@/components/domain/mail/recipient-field";
import { RichEditor } from "@/components/domain/mail/rich-editor";
import { formatDateTime } from "@/lib/format/datetime";
import { useDisplayTimeZone } from "@/lib/preferences";
import { cn } from "@/lib/utils";

export type ComposeSeed =
  | { mode: "new" }
  | { mode: "draft"; draft: MailMessageView }
  | { mode: "reply" | "replyAll" | "forward"; message: MailMessageView };

const MAX_FILES = 10;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const AUTOSAVE_MS = 2500;

function prefix(subject: string, tag: "Re" | "Fwd"): string {
  const re = new RegExp(`^\\s*${tag}:\\s*`, "i");
  return re.test(subject) ? subject : `${tag}: ${subject || "(no subject)"}`;
}

function bytes(n: number): string {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** The quoted original a reply or forward starts from. Its HTML came from the server already sanitised. */
function quoted(message: MailMessageView, when: string, forward: boolean): string {
  const header = forward
    ? `---------- Forwarded message ----------<br>From: ${escapeHtml(message.sender.name)}<br>Date: ${escapeHtml(when)}<br>Subject: ${escapeHtml(message.subject || "(no subject)")}<br>To: ${escapeHtml(message.to.map((p) => p.name).join(", "))}`
    : `On ${escapeHtml(when)}, ${escapeHtml(message.sender.name)} wrote:`;
  return `<p></p><blockquote><p>${header}</p>${message.body_html}</blockquote>`;
}

/**
 * The compose window: To / Cc / Bcc pickers, subject, a rich-text body, attachments and a draft that saves itself.
 *
 * Recipients are chosen from a directory the server has already limited to the people you may write to, and it
 * shows names only. Nothing here ever sees or sends an email address. Send is disabled until there is somebody to
 * send to and no upload is still running.
 */
export function ComposeDialog({ seed, onClose }: { seed: ComposeSeed; onClose: () => void }) {
  const queryClient = useQueryClient();
  const timeZone = useDisplayTimeZone();

  const draft = seed.mode === "draft" ? seed.draft : null;
  const original = seed.mode === "reply" || seed.mode === "replyAll" || seed.mode === "forward" ? seed.message : null;

  const [to, setTo] = useState<MailPerson[]>(draft?.to ?? []);
  const [cc, setCc] = useState<MailPerson[]>(draft?.cc ?? []);
  const [bcc, setBcc] = useState<MailPerson[]>(draft?.bcc ?? []);
  const [showCc, setShowCc] = useState(Boolean(draft?.cc?.length));
  const [showBcc, setShowBcc] = useState(Boolean(draft?.bcc?.length));
  const [subject, setSubject] = useState(
    draft ? draft.subject : original ? prefix(original.subject, seed.mode === "forward" ? "Fwd" : "Re") : "",
  );
  const [bodyHtml, setBodyHtml] = useState(draft?.body_html ?? "");
  const [attachments, setAttachments] = useState<MailAttachmentInfo[]>(draft?.attachments ?? []);
  const [uploading, setUploading] = useState(0);
  const [emailCopy, setEmailCopy] = useState(true);
  const [draftId, setDraftId] = useState<string | null>(draft?.public_id ?? null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [banner, setBanner] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [initialHtml] = useState(() => {
    if (draft) return draft.body_html;
    if (original) return quoted(original, original.sent_at ? formatDateTime(original.sent_at, { timeZone }) : "", seed.mode === "forward");
    return "";
  });

  const fileInput = useRef<HTMLInputElement>(null);
  const [dirty, setDirty] = useState(false);
  const closing = useRef(false);

  // Who a reply would go to comes from the server, already filtered to people this person may write to.
  useEffect(() => {
    if (!original || seed.mode === "forward") return;
    let cancelled = false;
    void api.get<ReplyOptions>(`/messages/${segment(original.public_id)}/reply-options`).then((opts) => {
      if (cancelled) return;
      if (seed.mode === "replyAll") {
        setTo(opts.reply_all_to);
        setCc(opts.reply_all_cc);
        setShowCc(opts.reply_all_cc.length > 0);
      } else {
        setTo(opts.reply);
      }
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // The seed is fixed for the life of this dialog (it is remounted with a new key for a new one).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const payload = useCallback(
    () => ({
      to: to.map((p) => p.public_id),
      cc: cc.map((p) => p.public_id),
      bcc: bcc.map((p) => p.public_id),
      subject,
      body_html: bodyHtml,
      attachment_ids: attachments.map((a) => a.public_id),
      reply_to_id: original && seed.mode !== "forward" ? original.public_id : null,
      draft_id: draftId,
      email_copy: emailCopy,
    }),
    [to, cc, bcc, subject, bodyHtml, attachments, original, seed.mode, draftId, emailCopy],
  );

  const hasContent = to.length + cc.length + bcc.length > 0 || subject.trim() !== "" || bodyHtml.replace(/<[^>]*>/g, "").trim() !== "" || attachments.length > 0;
  const forwardOrReplyUntouched = original !== null && !dirty;

  // The draft saves itself a moment after the last change, like Gmail's.
  useEffect(() => {
    if (!dirty || !hasContent || sending || closing.current) return undefined;
    const timer = window.setTimeout(async () => {
      setSaveState("saving");
      try {
        const saved = await api.post<MailMessageView>("/messages/drafts", { body: payload() });
        setDraftId(saved.public_id);
        setSaveState("saved");
      } catch {
        setSaveState("idle"); // a failed autosave is not worth interrupting anybody for; Send reports real errors
      }
    }, AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
  }, [payload, hasContent, sending, dirty]);

  function touched<T>(setter: (v: T) => void) {
    return (v: T) => {
      setDirty(true);
      setSaveState("idle");
      setter(v);
    };
  }

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (list.length === 0) return;
    if (attachments.length + list.length > MAX_FILES) {
      toast.error(`A message can carry at most ${MAX_FILES} attachments.`);
      return;
    }
    for (const file of list) {
      if (file.size > MAX_FILE_BYTES) {
        toast.error(`${file.name} is larger than ${bytes(MAX_FILE_BYTES)}.`);
        continue;
      }
      setUploading((n) => n + 1);
      try {
        const form = new FormData();
        form.append("file", file);
        const info = await api.post<MailAttachmentInfo>("/messages/attachments", { body: form });
        setDirty(true);
        setAttachments((current) => [...current, info]);
      } catch (error) {
        toast.error(error instanceof ApiError ? error.message : `${file.name} could not be attached.`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  }

  async function removeAttachment(a: MailAttachmentInfo) {
    setDirty(true);
    setAttachments((current) => current.filter((x) => x.public_id !== a.public_id));
    try {
      await api.delete<void>(`/messages/attachments/${segment(a.public_id)}`);
    } catch {
      // Already gone or attached to a saved draft; the next save reconciles it.
    }
  }

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["mail"] });
  }

  async function send() {
    setBanner(null);
    setSending(true);
    try {
      await api.post<MailMessageView>("/messages", { body: payload() });
      closing.current = true;
      toast.success("Message sent.");
      refresh();
      onClose();
    } catch (error) {
      setBanner(error instanceof ApiError ? error.message : "The message could not be sent.");
    } finally {
      setSending(false);
    }
  }

  async function discard() {
    closing.current = true;
    if (draftId) {
      try {
        await api.delete<void>(`/messages/${segment(draftId)}`);
      } catch {
        // Nothing to clean up if it was never saved.
      }
    }
    refresh();
    onClose();
  }

  function close() {
    // Closing keeps what was written as a draft (like Gmail), unless it is an untouched reply or nothing at all.
    closing.current = true;
    if (hasContent && dirty && !forwardOrReplyUntouched) {
      void api.post<MailMessageView>("/messages/drafts", { body: payload() }).then(() => {
        toast.message("Draft saved.");
        refresh();
      }).catch(() => undefined);
    }
    onClose();
  }

  const canSend = to.length + cc.length + bcc.length > 0 && uploading === 0 && !sending;
  const title = seed.mode === "reply" || seed.mode === "replyAll" ? "Reply" : seed.mode === "forward" ? "Forward" : draft ? "Draft" : "New message";

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        size="xl"
        className="flex max-h-[calc(100dvh-1rem)] flex-col gap-0 overflow-hidden p-0"
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void uploadFiles(event.dataTransfer.files);
        }}
      >
        <div className="flex items-center justify-between border-b border-border-subtle bg-surface-muted px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground" role="status">
              {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Draft saved" : ""}
            </span>
            <button type="button" aria-label="Close and keep as a draft" className="rounded p-1 hover:bg-muted" onClick={close}>
              <X className="size-4" aria-hidden />
            </button>
          </div>
        </div>

        <div className="relative min-h-0 flex-1 overflow-y-auto">
          {dragging ? (
            <div className="pointer-events-none absolute inset-2 z-30 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/5 text-sm font-medium text-primary">
              Drop files to attach them
            </div>
          ) : null}

          <div className="relative">
            <RecipientField label="To" value={to} onChange={touched(setTo)} exclude={[...cc, ...bcc]} autoFocus={seed.mode === "new"} />
            <div className="absolute right-3 top-2 flex gap-2 text-xs">
              {!showCc ? (
                <button type="button" className="text-muted-foreground hover:text-foreground hover:underline" onClick={() => setShowCc(true)}>
                  Cc
                </button>
              ) : null}
              {!showBcc ? (
                <button type="button" className="text-muted-foreground hover:text-foreground hover:underline" onClick={() => setShowBcc(true)}>
                  Bcc
                </button>
              ) : null}
            </div>
          </div>
          {showCc ? <RecipientField label="Cc" value={cc} onChange={touched(setCc)} exclude={[...to, ...bcc]} /> : null}
          {showBcc ? <RecipientField label="Bcc" value={bcc} onChange={touched(setBcc)} exclude={[...to, ...cc]} /> : null}

          <div className="border-b border-border-subtle px-3">
            <input
              value={subject}
              onChange={(event) => touched(setSubject)(event.target.value)}
              placeholder="Subject"
              aria-label="Subject"
              maxLength={250}
              className="w-full bg-transparent py-2.5 text-sm font-medium outline-none"
            />
          </div>

          <div className="p-3">
            <RichEditor initialHtml={initialHtml} onChange={(html) => touched(setBodyHtml)(html)} />
          </div>

          {attachments.length > 0 || uploading > 0 ? (
            <ul className="flex flex-wrap gap-2 px-3 pb-3">
              {attachments.map((a) => (
                <li key={a.public_id} className="inline-flex max-w-full items-center gap-2 rounded-lg border border-border-subtle bg-surface-muted px-2.5 py-1.5 text-xs">
                  <Paperclip className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate">{a.filename}</span>
                  <span className="shrink-0 text-muted-foreground">{bytes(a.size)}</span>
                  <button type="button" aria-label={`Remove ${a.filename}`} className="rounded p-0.5 hover:bg-border" onClick={() => void removeAttachment(a)}>
                    <X className="size-3" aria-hidden />
                  </button>
                </li>
              ))}
              {uploading > 0 ? <li className="px-2.5 py-1.5 text-xs text-muted-foreground">Uploading…</li> : null}
            </ul>
          ) : null}
        </div>

        {banner ? (
          <div role="alert" className="border-t border-danger/40 bg-danger/10 px-4 py-2 text-sm text-danger">
            {banner}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle px-3 py-2.5">
          <div className="flex items-center gap-2">
            <Button type="button" onClick={() => void send()} disabled={!canSend} loading={sending}>
              <Send /> Send
            </Button>
            <input ref={fileInput} type="file" multiple hidden onChange={(event) => { if (event.target.files) void uploadFiles(event.target.files); event.target.value = ""; }} />
            <Button type="button" variant="ghost" size="icon" aria-label="Attach files" title="Attach files" onClick={() => fileInput.current?.click()}>
              <Paperclip />
            </Button>
            <label className={cn("hidden cursor-pointer items-center gap-1.5 text-xs text-muted-foreground sm:flex")} title="Also email a copy of this message to your own address">
              <input type="checkbox" checked={emailCopy} onChange={(event) => touched(setEmailCopy)(event.target.checked)} className="size-3.5 accent-[var(--primary)]" />
              Email me a copy
            </label>
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="Discard draft" title="Discard" onClick={() => void discard()}>
            <Trash2 />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
