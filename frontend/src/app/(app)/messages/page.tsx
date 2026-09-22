"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileEdit, Inbox, Paperclip, Pencil, Search, Send, Star } from "lucide-react";
import { toast } from "sonner";
import { api, segment } from "@/lib/api/client";
import type { MailListItem, MailMessageView, PageMailListItem, UnreadCountResponse } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { ComposeDialog, type ComposeSeed } from "@/components/domain/mail/compose-dialog";
import { ThreadView } from "@/components/domain/mail/thread-view";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

type Folder = "inbox" | "starred" | "sent" | "drafts";

const FOLDERS: { id: Folder; label: string; icon: typeof Inbox }[] = [
  { id: "inbox", label: "Inbox", icon: Inbox },
  { id: "starred", label: "Starred", icon: Star },
  { id: "sent", label: "Sent", icon: Send },
  { id: "drafts", label: "Drafts", icon: FileEdit },
];
const PAGE_SIZE = 25;

/** Today: the time. Otherwise the date. The same shorthand a mail list always uses. */
function shortWhen(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "";
  const then = new Date(iso);
  const sameDay = new Intl.DateTimeFormat("en-CA", { timeZone }).format(then) === new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date());
  return sameDay ? formatTime(iso, { timeZone }) : formatDateTime(iso, { timeZone }).replace(/,?\s*\d{2}:\d{2}$/, "");
}

export default function MessagesPage() {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();
  const queryClient = useQueryClient();
  const canWrite = permissions.has("message.create");

  const [folder, setFolder] = useState<Folder>("inbox");
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [compose, setCompose] = useState<ComposeSeed | null>(null);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setQ(term.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(id);
  }, [term]);

  const list = useQuery({
    queryKey: ["mail", "list", folder, q, offset],
    queryFn: () => api.get<PageMailListItem>("/messages", { query: { folder, q: q || undefined, limit: PAGE_SIZE, offset } }),
    placeholderData: (previous) => previous,
    refetchInterval: 30_000, // a new message turns up without a reload
  });
  const unread = useQuery({
    queryKey: ["mail", "unread"],
    queryFn: () => api.get<UnreadCountResponse>("/messages/unread-count"),
    refetchInterval: 30_000,
  });

  function chooseFolder(next: Folder) {
    setFolder(next);
    setOffset(0);
    setThreadId(null);
  }

  async function open(item: MailListItem) {
    if (item.is_draft) {
      try {
        setCompose({ mode: "draft", draft: await api.get<MailMessageView>(`/messages/${segment(item.public_id)}`) });
      } catch {
        toast.error("That draft could not be opened.");
      }
      return;
    }
    setThreadId(item.thread_id);
  }

  async function toggleStar(item: MailListItem) {
    try {
      await api.patch<void>(`/messages/${segment(item.public_id)}/state`, { body: { starred: !item.is_starred } });
      void queryClient.invalidateQueries({ queryKey: ["mail", "list"] });
    } catch {
      toast.error("The star could not be changed.");
    }
  }

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const inboxUnread = unread.data?.unread ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Messages"
        description="Write to the people you teach or are taught by, and to the administrators. Names only: nobody's email address is shown or shared here."
        actions={
          canWrite ? (
            <Button onClick={() => setCompose({ mode: "new" })}>
              <Pencil /> Compose
            </Button>
          ) : null
        }
      />

      <Card className="overflow-hidden">
        <div className="grid min-h-[32rem] md:grid-cols-[11.5rem_minmax(0,21rem)_minmax(0,1fr)]">
          {/* Folders: a column on wide screens, a row of tabs on narrow ones. */}
          <nav aria-label="Mail folders" className={cn("flex gap-1 overflow-x-auto border-b border-border-subtle p-2 md:flex-col md:border-b-0 md:border-r", threadId && "hidden md:flex")}>
            {FOLDERS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                aria-current={folder === id ? "page" : undefined}
                onClick={() => chooseFolder(id)}
                className={cn("flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-muted", folder === id && "bg-primary/10 font-semibold text-primary")}
              >
                <Icon className="size-4" aria-hidden />
                <span className="flex-1 text-left">{label}</span>
                {id === "inbox" && inboxUnread > 0 ? <span className="rounded-full bg-primary px-1.5 text-xs font-semibold text-primary-foreground">{inboxUnread}</span> : null}
              </button>
            ))}
          </nav>

          {/* The list. On a phone it gives way to the open conversation. */}
          <section aria-label="Messages" className={cn("flex min-w-0 flex-col border-border-subtle md:border-r", threadId && "hidden md:flex")}>
            <div className="relative border-b border-border-subtle p-2">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <input
                value={term}
                onChange={(event) => setTerm(event.target.value)}
                placeholder="Search subject, text or sender"
                aria-label="Search messages"
                className="h-9 w-full rounded-md border border-border-subtle bg-surface pl-8 pr-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
              />
            </div>
            {list.isPending ? (
              <LoadingState />
            ) : list.error ? (
              <div className="p-3">
                <ErrorState error={list.error} onRetry={() => void list.refetch()} />
              </div>
            ) : items.length === 0 ? (
              <p className="p-8 text-center text-sm text-muted-foreground">{q ? "Nothing matches your search." : folder === "inbox" ? "Your inbox is empty." : `Nothing in ${folder}.`}</p>
            ) : (
              <ul className="min-h-0 flex-1 divide-y divide-border-subtle overflow-y-auto">
                {items.map((item) => {
                  const selected = !item.is_draft && item.thread_id === threadId;
                  const who = folder === "sent" || folder === "drafts" ? `To: ${item.recipients_summary || "—"}` : item.is_mine ? `Me → ${item.recipients_summary}` : item.sender.name;
                  return (
                    <li key={item.public_id}>
                      <div className={cn("group flex items-start gap-2 px-3 py-2.5 hover:bg-muted", selected && "bg-primary/10", !item.is_read && "bg-primary/[0.04]")}>
                        <button
                          type="button"
                          aria-label={item.is_starred ? "Remove star" : "Star"}
                          aria-pressed={item.is_starred}
                          className="mt-0.5 shrink-0 rounded p-0.5 hover:bg-border"
                          onClick={() => void toggleStar(item)}
                        >
                          <Star className={cn("size-4", item.is_starred ? "fill-warning text-warning" : "text-muted-foreground")} aria-hidden />
                        </button>
                        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => void open(item)}>
                          <span className="flex items-baseline justify-between gap-2">
                            <span className={cn("truncate text-sm", !item.is_read ? "font-semibold" : "")}>
                              {who}
                              {(item.thread_count ?? 1) > 1 ? <span className="ml-1 text-xs font-normal text-muted-foreground">({item.thread_count})</span> : null}
                            </span>
                            <span className="shrink-0 text-xs text-muted-foreground">{shortWhen(item.sent_at ?? item.updated_at, timeZone)}</span>
                          </span>
                          <span className={cn("block truncate text-sm", !item.is_read ? "font-medium" : "text-muted-foreground")}>{item.subject}</span>
                          <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <span className="truncate">{item.snippet}</span>
                            {item.has_attachments ? <Paperclip className="size-3 shrink-0" aria-label="Has attachments" /> : null}
                          </span>
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
            {total > PAGE_SIZE ? (
              <div className="flex items-center justify-between border-t border-border-subtle px-3 py-2 text-xs text-muted-foreground">
                <span>
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
                </span>
                <span className="flex gap-1">
                  <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                    Newer
                  </Button>
                  <Button variant="ghost" size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                    Older
                  </Button>
                </span>
              </div>
            ) : null}
          </section>

          {/* The open conversation. */}
          <section aria-label="Conversation" className={cn("min-w-0 p-3", !threadId && "hidden md:block")}>
            {threadId ? (
              <ThreadView key={threadId} threadId={threadId} onBack={() => setThreadId(null)} onCompose={(seed) => setCompose(seed)} />
            ) : (
              <div className="flex h-full min-h-40 items-center justify-center text-sm text-muted-foreground">Select a conversation to read it.</div>
            )}
          </section>
        </div>
      </Card>

      {compose ? (
        <ComposeDialog
          key={compose.mode === "draft" ? compose.draft.public_id : compose.mode === "new" ? "new" : `${compose.mode}-${compose.message.public_id}`}
          seed={compose}
          onClose={() => setCompose(null)}
        />
      ) : null}
    </div>
  );
}
