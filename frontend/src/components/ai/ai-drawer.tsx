"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  Eraser,
  Loader2,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, apiPath, ApiError } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session";
import { useAIStore } from "@/lib/ai-store";
import { Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { AIMessageList, type ChatMessage } from "./ai-message-list";
import { VoiceInputButton } from "./voice-input-button";
import {
  ActionConfirmationDialog,
  type TicketDetails,
} from "./action-confirmation-dialog";
import type { AssessmentDraftData } from "./assessment-preview-card";

interface AIChatResponsePayload {
  message: string;
  role: string;
  tool_calls?: Array<{ tool: string; result?: unknown }>;
  draft_assessments?: AssessmentDraftData[];
  confirmation_ticket?: TicketDetails | null;
  success: boolean;
}

interface HistoryResponsePayload {
  messages: Array<{
    message_id: string;
    role: "user" | "assistant" | "system";
    content: string;
    tool_calls?: Array<{ tool: string; result?: unknown }>;
    created_at?: string;
  }>;
  total: number;
}

export function AIDrawer() {
  const { isOpen, closeDrawer, initialPrompt } = useAIStore();
  const { user, roles } = useSession();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Active confirmation ticket dialog
  const [activeTicket, setActiveTicket] = useState<TicketDetails | null>(null);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const ROLE_HIERARCHY = ["SUPER_ADMIN", "ADMIN", "CORPORATE_MANAGER", "TUTOR", "GUARDIAN", "STUDENT"];
  const primaryRole = ROLE_HIERARCHY.find((r) => roles.includes(r)) || roles[0] || "STUDENT";

  // Load history when drawer opens
  useEffect(() => {
    if (!isOpen) return;

    let mounted = true;
    setHistoryLoading(true);

    api
      .get<HistoryResponsePayload>("/ai/history?limit=30")
      .then((data) => {
        if (!mounted || !data?.messages) return;
        const loaded: ChatMessage[] = data.messages.map((m) => {
          // Extract draft assessments if recorded in tool calls
          const drafts: AssessmentDraftData[] = [];
          if (m.tool_calls) {
            for (const tc of m.tool_calls) {
              const res = tc?.result as any;
              if (
                tc.tool === "create_assessment_draft" &&
                res &&
                res.success &&
                res.assessment_id
              ) {
                drafts.push(res);
              }
            }
          }

          return {
            id: m.message_id,
            role: m.role,
            content: m.content,
            agentRole: m.role === "assistant" ? primaryRole : undefined,
            toolCalls: m.tool_calls,
            draftAssessments: drafts.length > 0 ? drafts : undefined,
            createdAt: m.created_at,
          };
        });
        setMessages(loaded);
      })
      .catch((err) => {
        console.error("Failed to load AI history:", err);
      })
      .finally(() => {
        if (mounted) setHistoryLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [isOpen, primaryRole]);

  // Handle initial prompt if supplied
  useEffect(() => {
    if (isOpen && initialPrompt) {
      setInput(initialPrompt);
      textareaRef.current?.focus();
    }
  }, [isOpen, initialPrompt]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !confirmDialogOpen && !clearDialogOpen) {
        closeDrawer();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, confirmDialogOpen, clearDialogOpen, closeDrawer]);

  const handleSend = async (textToSend?: string) => {
    const prompt = (textToSend ?? input).trim();
    if (!prompt || loading) return;

    setInput("");
    const userMessageId = `user-${Date.now()}`;
    const userMsg: ChatMessage = {
      id: userMessageId,
      role: "user",
      content: prompt,
    };

    const assistantMessageId = `ai-${Date.now()}`;
    const initialAssistantMsg: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      agentRole: primaryRole,
      isStreaming: true,
      statusText: "Analyzing intent and consulting LMS records...",
      toolCalls: [],
    };

    setMessages((prev) => [...prev, userMsg, initialAssistantMsg]);
    setLoading(true);

    try {
      const response = await fetch(apiPath("/ai/chat"), {
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "text/event-stream",
        },
        body: JSON.stringify({
          prompt,
          stream: true,
        }),
        credentials: "same-origin",
      });

      if (!response.ok) {
        let errPayload: any = {};
        try {
          errPayload = await response.json();
        } catch {
          // ignore non-json error responses
        }
        throw new Error(errPayload.message || `Server error: ${response.status}`);
      }

      const contentType = response.headers.get("content-type") || "";

      // Handle non-streaming JSON fallback
      if (contentType.includes("application/json")) {
        const resp: AIChatResponsePayload = await response.json();
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: resp?.message || "Task processed.",
                  agentRole: resp?.role || msg.agentRole,
                  draftAssessments: resp?.draft_assessments,
                  confirmationTicket: resp?.confirmation_ticket,
                  toolCalls: resp?.tool_calls,
                  isStreaming: false,
                  statusText: undefined,
                }
              : msg,
          ),
        );
        if (resp?.confirmation_ticket) {
          setActiveTicket(resp.confirmation_ticket);
        }
        return;
      }

      if (!response.body) {
        throw new Error("No response stream received from server.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let accumulatedContent = "";
      let activeToolCalls: Array<{ tool: string; result?: unknown }> = [];
      let receivedDone = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(":")) {
            // keep-alive or comment marker
            continue;
          }

          if (trimmed.startsWith("data: ")) {
            const jsonStr = trimmed.slice(6);
            try {
              const event = JSON.parse(jsonStr);

              if (event.type === "status") {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? { ...msg, statusText: event.content || msg.statusText }
                      : msg,
                  ),
                );
              } else if (event.type === "tool_start") {
                const tc = { tool: event.tool, result: undefined };
                activeToolCalls = [...activeToolCalls, tc];
                const desc = event.content || `Executing ${event.tool}...`;
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          statusText: desc,
                          toolCalls: [...activeToolCalls],
                        }
                      : msg,
                  ),
                );
              } else if (event.type === "tool_end") {
                activeToolCalls = activeToolCalls.map((tc) =>
                  tc.tool === event.tool ? { ...tc, result: event.result } : tc,
                );
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          statusText: "Processing result...",
                          toolCalls: [...activeToolCalls],
                        }
                      : msg,
                  ),
                );
              } else if (event.type === "confirmation_required") {
                if (event.ticket) {
                  setActiveTicket(event.ticket);
                }
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          confirmationTicket: event.ticket,
                          statusText: undefined,
                          isStreaming: false,
                        }
                      : msg,
                  ),
                );
              } else if (event.type === "delta") {
                accumulatedContent += event.delta || "";
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          content: accumulatedContent,
                          statusText: undefined,
                        }
                      : msg,
                  ),
                );
              } else if (event.type === "done") {
                receivedDone = true;
                const finalMessage = event.message || accumulatedContent || "Task completed.";
                if (event.confirmation_ticket) {
                  setActiveTicket(event.confirmation_ticket);
                }
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          content: finalMessage,
                          agentRole: event.role || msg.agentRole,
                          toolCalls: event.tool_calls || activeToolCalls,
                          draftAssessments: event.draft_assessments,
                          confirmationTicket: event.confirmation_ticket,
                          isStreaming: false,
                          statusText: undefined,
                        }
                      : msg,
                  ),
                );
              } else if (event.type === "error") {
                const errMsg = event.message || "An error occurred.";
                toast.error("AI Error", { description: errMsg });
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          content: accumulatedContent
                            ? `${accumulatedContent}\n\nError: ${errMsg}`
                            : `Error: ${errMsg}`,
                          isStreaming: false,
                          statusText: undefined,
                        }
                      : msg,
                  ),
                );
              }
            } catch (parseErr) {
              console.error("Failed to parse SSE event:", jsonStr, parseErr);
            }
          }
        }
      }

      if (!receivedDone) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: accumulatedContent || "Task finished.",
                  isStreaming: false,
                  statusText: undefined,
                }
              : msg,
          ),
        );
      }
    } catch (err: any) {
      const message = err?.message || "Failed to obtain response from AI assistant.";
      toast.error("AI Error", { description: message });

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                content: `Error: ${message}`,
                agentRole: "SYSTEM",
                isStreaming: false,
                statusText: undefined,
              }
            : msg,
        ),
      );
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleClearHistory = async () => {
    setClearing(true);
    try {
      await api.delete("/ai/history");
      setMessages([]);
      setClearDialogOpen(false);
      toast.success("AI conversation history erased.");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Failed to erase conversation history.";
      toast.error("Error", { description: message });
    } finally {
      setClearing(false);
    }
  };

  const handlePublishClick = async (draft: AssessmentDraftData) => {
    try {
      toast.info("Requesting cryptographic approval ticket...");
      const ticket = await api.post<TicketDetails>(
        "/ai/tickets/publish-assessment",
        {
          body: {
            quiz_id: draft.assessment_id,
          },
        },
      );

      setActiveTicket(ticket);
      setConfirmDialogOpen(true);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Could not stage assessment publishing.";
      toast.error("Staging Error", { description: message });
    }
  };

  const handleDirectConfirm = async (ticket: TicketDetails, confirmed: boolean) => {
    // An action that demands a typed phrase is confirmed in the dialog, where
    // the phrase is typed -- never by a one-click "Yes".
    if (confirmed && ticket.typed_confirmation) {
      setActiveTicket(ticket);
      setConfirmDialogOpen(true);
      return;
    }
    if (!confirmed) {
      // Cancelled on the server, not just in the chat: a declined action left
      // pending could be carried out by the next stray "yes".
      let cancelText = "Cancelled. Nothing was changed.";
      try {
        await api.post(`/ai/tickets/${encodeURIComponent(ticket.ticket_id)}/cancel`, {});
      } catch (err) {
        cancelText =
          err instanceof ApiError
            ? `Could not cancel: ${err.message}`
            : "Could not reach the server to cancel; the action may still be pending.";
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `user-no-${Date.now()}`,
          role: "user",
          content: "No",
        },
        {
          id: `assistant-cancel-${Date.now()}`,
          role: "assistant",
          agentRole: primaryRole,
          content: cancelText,
        },
      ]);
      return;
    }

    setLoading(true);
    try {
      const resp = await api.post<{ success: boolean; result: Record<string, unknown> }>(
        "/ai/confirm",
        {
          body: {
            ticket_id: ticket.ticket_id,
            parameters: ticket.parameters,
          },
        },
      );
      const succeeded = resp?.success !== false;
      const successMsg =
        (resp?.result?.message as string) ||
        (succeeded ? "Action executed." : "The action did not complete.");

      setMessages((prev) => [
        ...prev,
        {
          id: `user-yes-${Date.now()}`,
          role: "user",
          content: "Yes",
        },
        {
          id: `assistant-result-${Date.now()}`,
          role: "assistant",
          agentRole: primaryRole,
          content: successMsg,
        },
      ]);
      if (succeeded) toast.success("Action Executed", { description: successMsg });
      else toast.error("Action not completed", { description: successMsg });
    } catch (err) {
      const errorMsg =
        err instanceof ApiError ? err.message : "Failed to execute confirmed action.";
      setMessages((prev) => [
        ...prev,
        {
          id: `user-yes-${Date.now()}`,
          role: "user",
          content: "Yes",
        },
        {
          id: `assistant-err-${Date.now()}`,
          role: "assistant",
          agentRole: primaryRole,
          content: `Operation failed: ${errorMsg}`,
        },
      ]);
      toast.error("Execution Failed", { description: errorMsg });
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-xs transition-opacity duration-200"
        onClick={closeDrawer}
        aria-hidden="true"
      />

      {/* Drawer */}
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-background border-l border-border-subtle shadow-2xl transition-transform duration-300 ease-out",
          "sm:max-w-[460px] md:max-w-[500px]",
        )}
        aria-label="AI Assistant"
      >
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b border-border-subtle px-4 bg-muted/20">
          <div className="flex items-center gap-2">
            <div className="size-8 rounded-xl bg-primary/10 text-primary flex items-center justify-center">
              <Sparkles className="size-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-xs tracking-tight text-foreground">
                  AI Assistant
                </span>
                <Badge tone="primary" className="text-2xs px-1.5 py-0.5">
                  {primaryRole}
                </Badge>
              </div>
              <p className="text-2xs text-muted-foreground truncate max-w-48">
                {user?.full_name || user?.username}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-danger"
                onClick={() => setClearDialogOpen(true)}
                title="Erase conversation memory"
                aria-label="Erase conversation memory"
              >
                <Eraser className="size-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground hover:text-foreground"
              onClick={closeDrawer}
              title="Close drawer"
              aria-label="Close drawer"
            >
              <X className="size-4" />
            </Button>
          </div>
        </header>

        {/* Messages Body */}
        {historyLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <AIMessageList
            messages={messages}
            loading={loading}
            onPublishClick={handlePublishClick}
            onConfirmTicketClick={(ticket) => {
              setActiveTicket(ticket);
              setConfirmDialogOpen(true);
            }}
            onConfirmDirect={handleDirectConfirm}
            onSuggestionClick={(suggestion) => void handleSend(suggestion)}
            userRole={primaryRole}
          />
        )}

        {/* Footer Input */}
        <footer className="border-t border-border-subtle bg-background p-3 space-y-2">
          <div className="relative rounded-xl border border-border-subtle bg-muted/30 focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all p-1.5 flex items-end gap-1.5">
            <textarea
              ref={textareaRef}
              value={input}
              disabled={loading}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={loading ? "AI Assistant is responding..." : `Ask anything as ${primaryRole.toLowerCase()}... (Enter to send)`}
              className="w-full resize-none bg-transparent px-2 py-1 text-xs placeholder:text-muted-foreground focus:outline-none max-h-28 min-h-[38px] scrollbar-thin disabled:opacity-60"
              rows={1}
            />

            <div className="flex items-center gap-1 pb-0.5 shrink-0">
              <VoiceInputButton
                onTranscript={(transcript) => {
                  setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
                  textareaRef.current?.focus();
                }}
                disabled={loading}
              />
              <Button
                type="button"
                variant="primary"
                size="icon"
                disabled={!input.trim() || loading}
                onClick={() => void handleSend()}
                className="size-8 shrink-0"
                aria-label="Send prompt"
                title="Send"
              >
                {loading ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Send className="size-3.5" />
                )}
              </Button>
            </div>
          </div>

          <div className="flex items-center justify-between px-1 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Bot className="size-3 text-primary" />
              Role-scoped & verified against database
            </span>
            <span>Shift + Enter for new line</span>
          </div>
        </footer>
      </aside>

      {/* Action Approval Confirmation Dialog */}
      <ActionConfirmationDialog
        open={confirmDialogOpen}
        onOpenChange={setConfirmDialogOpen}
        ticket={activeTicket}
        onSuccess={(result) => {
          // Append confirmation success note into current chat
          const confirmedMsg: ChatMessage = {
            id: `conf-${Date.now()}`,
            role: "assistant",
            content: `Confirmed action executed successfully: ${(result?.message as string) || "Operation complete."}`,
            agentRole: "SYSTEM",
          };
          setMessages((prev) => [...prev, confirmedMsg]);
        }}
      />

      {/* Clear History Confirmation Dialog */}
      <ConfirmDialog
        open={clearDialogOpen}
        onOpenChange={setClearDialogOpen}
        title="Erase Conversation Memory"
        description="Permanently delete all stored AI conversation messages for your account. This action cannot be undone."
        confirmLabel="Erase Memory"
        destructive
        pending={clearing}
        onConfirm={handleClearHistory}
      />
    </>
  );
}
