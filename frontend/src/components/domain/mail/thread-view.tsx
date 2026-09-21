"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, Forward, Mail as MailIcon, Paperclip, Reply, ReplyAll, Star, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { MailAttachmentInfo, MailDelivery, MailMessageView, MailPerson, MailThread } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import type { ComposeSeed } from "@/components/domain/mail/compose-dialog";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

function bytes(n: number): string {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
}

function names(people: readonly MailPerson[]): string {
  return people.map((p) => p.name).join(", ");
}

function Attachment({ a }: { a: MailAttachmentInfo }) {
  return (
    <a
      // Same-origin through the console's proxy, which adds the sign-in; always downloaded, never rendered.
      href={`/api/backend/messages/attachments/${segment(a.public_id)}/download`}
      download={a.filename}
      className="inline-flex max-w-full items-center gap-2 rounded-lg border border-border bg-surface-muted px-2.5 py-1.5 text-xs hover:bg-muted"
    >
      <Paperclip className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="truncate">{a.filename}</span>
      <span className="shrink-0 text-muted-foreground">{bytes(a.size)}</span>
    </a>
  );
}

function DeliveryNote({ delivery }: { delivery: MailDelivery }) {
  if (!delivery.enabled) return <p className="text-xs text-muted-foreground">Delivered in the LMS. Email delivery is switched off, so no email copies were sent.</p>;
  const parts = [
    delivery.sent ? `${delivery.sent} emailed` : null,
    delivery.failed ? `${delivery.failed} failed${delivery.failures?.length ? ` (${delivery.failures.join(", ")})` : ""}` : null,
    delivery.skipped ? `${delivery.skipped} had no address` : null,
    delivery.pending ? `${delivery.pending} sending` : null,
    delivery.copy_to_me ? `copy to you: ${delivery.copy_to_me.toLowerCase()}` : null,
  ].filter(Boolean);
  return <p className={cn("text-xs", delivery.failed ? "text-warning" : "text-muted-foreground")}>Delivered in the LMS. Email: {parts.join(" · ") || "nothing to send"}.</p>;
}

function MessageCard({
  message,
  expanded,
  onToggle,
  onCompose,
  onChanged,
  timeZone,
}: {
  message: MailMessageView;
  expanded: boolean;
  onToggle: () => void;
  onCompose: (seed: ComposeSeed) => void;
  onChanged: () => void;
  timeZone: string;
}) {
  const [details, setDetails] = useState(false);
  const star = useApiMutation<void, boolean>({
    mutationFn: (starred) => api.patch<void>(`/messages/${segment(message.public_id)}/state`, { body: { starred } }),
    onSuccess: onChanged,
  });
  const remove = useApiMutation<void, void>({
    mutationFn: () => api.delete<void>(`/messages/${segment(message.public_id)}`),
    success: "Removed from your mailbox.",
    onSuccess: onChanged,
  });

  const to = [...message.to, ...message.cc];
  const others = to.length + (message.is_mine ? 0 : 1) > 2;
  const summary = message.is_mine ? `to ${names(to) || "—"}` : message.you_were_bcc ? "to me (Bcc)" : `to ${to.length > 3 ? `${names(to.slice(0, 3))} +${to.length - 3}` : names(to) || "me"}`;
  const when = message.sent_at ? formatDateTime(message.sent_at, { timeZone }) : "";

  return (
    <article className={cn("rounded-lg border border-border bg-surface", !message.is_read && "border-primary/50")}>
      <header className="flex cursor-pointer items-start gap-3 p-3" onClick={onToggle}>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary" aria-hidden>
          {initials(message.sender.name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-semibold">{message.is_mine ? "Me" : message.sender.name}</span>
            {message.sender.role && !message.is_mine ? <Badge tone="neutral">{message.sender.role}</Badge> : null}
            <span className="text-xs text-muted-foreground">{when}</span>
          </div>
          <button
            type="button"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            aria-expanded={details}
            onClick={(event) => {
              event.stopPropagation();
              setDetails((d) => !d);
              if (!expanded) onToggle();
            }}
          >
            <span className="truncate">{summary}</span>
            <ChevronDown className={cn("size-3 shrink-0 transition-transform", details && "rotate-180")} aria-hidden />
          </button>
          {details ? (
            <dl className="mt-1.5 grid grid-cols-[3rem_1fr] gap-x-2 gap-y-0.5 text-xs" onClick={(event) => event.stopPropagation()}>
              <dt className="text-muted-foreground">From</dt>
              <dd>{message.sender.name}</dd>
              <dt className="text-muted-foreground">To</dt>
              <dd>{names(message.to) || "—"}</dd>
              {message.cc.length > 0 ? (
                <>
                  <dt className="text-muted-foreground">Cc</dt>
                  <dd>{names(message.cc)}</dd>
                </>
              ) : null}
              {(message.bcc ?? []).length > 0 ? (
                <>
                  <dt className="text-muted-foreground">Bcc</dt>
                  <dd>{names(message.bcc ?? [])}</dd>
                </>
              ) : null}
            </dl>
          ) : null}
          {!expanded ? <p className="mt-1 truncate text-sm text-muted-foreground">{message.body_html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()}</p> : null}
        </div>
        <button
          type="button"
          aria-label={message.is_starred ? "Remove star" : "Star"}
          aria-pressed={message.is_starred}
          className="rounded p-1 hover:bg-muted"
          onClick={(event) => {
            event.stopPropagation();
            star.mutate(!message.is_starred);
          }}
        >
          <Star className={cn("size-4", message.is_starred ? "fill-warning text-warning" : "text-muted-foreground")} aria-hidden />
        </button>
      </header>

      {expanded ? (
        <div className="space-y-3 border-t border-border px-3 pb-3 pt-3 sm:pl-15">
          {/* Server-sanitised: only formatting tags and http/https/mailto links survive (services/mail_html.py). */}
          <div className="mail-body text-sm" dangerouslySetInnerHTML={{ __html: message.body_html }} />
          {(message.attachments ?? []).length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {(message.attachments ?? []).map((a) => (
                <li key={a.public_id} className="max-w-full">
                  <Attachment a={a} />
                </li>
              ))}
            </ul>
          ) : null}
          {message.delivery ? <DeliveryNote delivery={message.delivery} /> : null}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => onCompose({ mode: "reply", message })}>
              <Reply /> Reply
            </Button>
            {others ? (
              <Button variant="secondary" size="sm" onClick={() => onCompose({ mode: "replyAll", message })}>
                <ReplyAll /> Reply all
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={() => onCompose({ mode: "forward", message })}>
              <Forward /> Forward
            </Button>
            <Button variant="ghost" size="sm" className="ml-auto" loading={remove.isPending} onClick={() => remove.mutate()} title="Removes it from your mailbox only">
              <Trash2 /> Delete
            </Button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

/** One conversation, oldest first, with the newest message and any unread ones open. Opening it reads it. */
export function ThreadView({ threadId, onBack, onCompose }: { threadId: string; onBack: () => void; onCompose: (seed: ComposeSeed) => void }) {
  const queryClient = useQueryClient();
  const timeZone = useDisplayTimeZone();
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["mail", "thread", threadId],
    queryFn: async () => {
      const thread = await api.get<MailThread>(`/messages/threads/${segment(threadId)}`);
      // Fetching the thread marked it read on the server; refresh the counts that depend on that.
      void queryClient.invalidateQueries({ queryKey: ["mail", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["mail", "unread"] });
      return thread;
    },
  });

  const changed = () => {
    void queryClient.invalidateQueries({ queryKey: ["mail"] });
  };
  const markUnread = useApiMutation<void, string>({
    mutationFn: (id) => api.patch<void>(`/messages/${segment(id)}/state`, { body: { read: false } }),
    success: "Marked as unread.",
    onSuccess: () => {
      changed();
      onBack();
    },
  });

  if (isPending) return <LoadingState />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const messages = data.messages;
  const last = messages[messages.length - 1];
  const received = [...messages].reverse().find((m) => !m.is_mine);

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2">
        <Button variant="ghost" size="icon" aria-label="Back to the list" className="md:hidden" onClick={onBack}>
          <ArrowLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold leading-tight">{data.subject}</h2>
          <p className="text-xs text-muted-foreground">
            {messages.length} message{messages.length === 1 ? "" : "s"}
          </p>
        </div>
        {received ? (
          <Button variant="ghost" size="sm" title="Mark this conversation unread" onClick={() => markUnread.mutate(received.public_id)}>
            <MailIcon /> Mark unread
          </Button>
        ) : null}
      </div>
      {messages.map((m) => {
        const open = toggled[m.public_id] ?? (m.public_id === last?.public_id || !m.is_read);
        return (
          <MessageCard
            key={m.public_id}
            message={m}
            expanded={open}
            onToggle={() => setToggled((t) => ({ ...t, [m.public_id]: !open }))}
            onCompose={onCompose}
            onChanged={changed}
            timeZone={timeZone}
          />
        );
      })}
    </div>
  );
}
