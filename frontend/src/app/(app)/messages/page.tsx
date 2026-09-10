"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCheck, Mail, MailOpen, PenSquare, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  ConversationResponse,
  MessageResponse,
  MarkReadResponse,
  PageConversationResponse,
  PageMessageResponse,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardHeader,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { UserPicker } from "@/components/domain/user-picker";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { useDisplayLocale, useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime, formatRelative } from "@/lib/format/datetime";

function ComposeDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [recipient, setRecipient] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  const send = useApiMutation<MessageResponse, void>({
    mutationFn: () =>
      api.post<MessageResponse>("/messages", {
        body: { recipient_id: recipient!, subject: subject || null, body },
      }),
    success: "Message sent.",
    invalidate: [["messages"], ["unread"]],
    onSuccess: () => {
      setRecipient(null);
      setSubject("");
      setBody("");
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader title="New message" description="Sent within the institution; no email leaves the system." />
        <div className="space-y-4">
          <Field label="To" required>
            {({ id }) => <UserPicker id={id} value={recipient} onChange={(next) => setRecipient(next)} />}
          </Field>
          <Field label="Subject">
            {({ id }) => (
              <Input id={id} value={subject} onChange={(event) => setSubject(event.target.value)} />
            )}
          </Field>
          <Field label="Message" required>
            {({ id }) => (
              <Textarea id={id} rows={6} value={body} onChange={(event) => setBody(event.target.value)} />
            )}
          </Field>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            loading={send.isPending}
            disabled={!recipient || body.trim() === ""}
            onClick={() => send.mutate()}
          >
            Send
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MessageList({ box }: { box: "inbox" | "sent" }) {
  const timeZone = useDisplayTimeZone();
  const locale = useDisplayLocale();
  const { permissions, user } = useSession();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(20);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [open, setOpen] = useState<MessageResponse | null>(null);
  const [deleting, setDeleting] = useState<MessageResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["messages", box, debouncedSearch, unreadOnly, limit, offset],
    queryFn: () =>
      api.get<PageMessageResponse>("/messages", {
        query: {
          box,
          q: debouncedSearch || undefined,
          unread_only: box === "inbox" && unreadOnly ? true : undefined,
          limit,
          offset,
        },
      }),
  });

  const markRead = useApiMutation<MessageResponse, string>({
    mutationFn: (messageId) => api.post<MessageResponse>(`/messages/${segment(messageId)}/read`),
    invalidate: [["messages"], ["unread"]],
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (messageId) => api.delete<void>(`/messages/${segment(messageId)}`),
    success: "Message deleted.",
    invalidate: [["messages"], ["unread"]],
    onSuccess: () => setDeleting(null),
  });

  function openMessage(message: MessageResponse) {
    setOpen(message);
    // Reading it is what marks it read; there is no separate "mark as read"
    // the recipient has to remember.
    if (box === "inbox" && !message.is_read) markRead.mutate(message.public_id);
  }

  return (
    <Card>
      <CardHeader
        title={box === "inbox" ? "Inbox" : "Sent"}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="w-56"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search messages"
              aria-label="Search messages"
            />
            {box === "inbox" ? (
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={unreadOnly}
                  onCheckedChange={(checked) => {
                    setUnreadOnly(checked);
                    setPage({ limit, offset: 0 });
                  }}
                />
                Unread only
              </label>
            ) : null}
          </div>
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon={<Mail className="size-5" />}
          title={box === "inbox" ? "Your inbox is empty" : "You have not sent anything"}
        />
      ) : (
        <>
          <ul className="divide-y divide-border">
            {(data?.items ?? []).map((message) => {
              const counterpart = box === "inbox" ? message.sender : message.recipient;
              const unread = box === "inbox" && !message.is_read;
              return (
                <li key={message.public_id}>
                  <button
                    type="button"
                    onClick={() => openMessage(message)}
                    className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-muted"
                  >
                    <span className="mt-0.5 text-muted-foreground">
                      {unread ? <Mail className="size-4 text-primary" /> : <MailOpen className="size-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-baseline gap-2">
                        <span className={unread ? "font-semibold" : "font-medium"}>
                          {counterpart.full_name || counterpart.username}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {formatRelative(message.created_at, locale)}
                        </span>
                      </span>
                      <span className="block truncate text-sm">
                        {message.subject || <em className="text-muted-foreground">No subject</em>}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {message.body}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="messages"
          />
        </>
      )}

      <Dialog open={open !== null} onOpenChange={(next) => (next ? null : setOpen(null))}>
        <DialogContent size="md">
          {open ? (
            <>
              <DialogHeader
                title={open.subject || "No subject"}
                description={
                  <span className="text-xs">
                    {open.sender.full_name || open.sender.username} &rarr;{" "}
                    {open.recipient.full_name || open.recipient.username} ·{" "}
                    {formatDateTime(open.created_at, { timeZone })}
                  </span>
                }
              />
              {/* Author-supplied text, rendered as text. */}
              <p className="whitespace-pre-wrap break-words text-sm">{open.body}</p>
              <DialogFooter>
                {permissions.has("message.delete") &&
                (open.sender.public_id === user?.public_id ||
                  open.recipient.public_id === user?.public_id) ? (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setDeleting(open);
                      setOpen(null);
                    }}
                  >
                    <Trash2 className="text-danger" /> Delete
                  </Button>
                ) : null}
                <Button variant="secondary" onClick={() => setOpen(null)}>
                  Close
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(next) => (next ? null : setDeleting(null))}
        destructive
        title="Delete this message?"
        description="It disappears from your mailbox."
        confirmLabel="Delete"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.public_id);
        }}
      />
    </Card>
  );
}

function Conversations() {
  const locale = useDisplayLocale();
  const { limit, offset, setPage } = useListState(20);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["messages", "conversations", limit, offset],
    queryFn: () =>
      api.get<PageConversationResponse>("/messages/conversations", { query: { limit, offset } }),
  });

  return (
    <Card>
      <CardHeader title="Conversations" description="One row per correspondent, newest first." />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyState title="No conversations yet" />
      ) : (
        <>
          <ul className="divide-y divide-border">
            {(data?.items ?? []).map((conversation: ConversationResponse) => (
              <li
                key={conversation.counterpart.public_id}
                className="flex items-start justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="font-medium">
                    {conversation.counterpart.full_name || conversation.counterpart.username}
                  </p>
                  <p className="truncate text-sm text-muted-foreground">
                    {conversation.last_subject || conversation.last_snippet || "—"}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  {conversation.unread_count ? (
                    <Badge tone="danger">{conversation.unread_count} unread</Badge>
                  ) : null}
                  <p className="text-xs text-muted-foreground">
                    {formatRelative(conversation.last_message_at, locale)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="conversations"
          />
        </>
      )}
    </Card>
  );
}

export default function MessagesPage() {
  const { permissions } = useSession();
  const [composeOpen, setComposeOpen] = useState(false);

  const markAll = useApiMutation<MarkReadResponse, void>({
    mutationFn: () => api.post<MarkReadResponse>("/messages/read-all"),
    success: (result) => `Marked ${result.updated} message(s) read.`,
    invalidate: [["messages"], ["unread"]],
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Messages"
        description="Direct messages between people in the institution."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" loading={markAll.isPending} onClick={() => markAll.mutate()}>
              <CheckCheck /> Mark all read
            </Button>
            {permissions.has("message.create") ? (
              <Button onClick={() => setComposeOpen(true)}>
                <PenSquare /> New message
              </Button>
            ) : null}
          </div>
        }
      />

      <Tabs defaultValue="inbox">
        <TabsList>
          <TabsTab value="inbox">Inbox</TabsTab>
          <TabsTab value="sent">Sent</TabsTab>
          <TabsTab value="conversations">Conversations</TabsTab>
        </TabsList>
        <TabsPanel value="inbox">
          <MessageList box="inbox" />
        </TabsPanel>
        <TabsPanel value="sent">
          <MessageList box="sent" />
        </TabsPanel>
        <TabsPanel value="conversations">
          <Conversations />
        </TabsPanel>
      </Tabs>

      <ComposeDialog open={composeOpen} onOpenChange={setComposeOpen} />
    </div>
  );
}
