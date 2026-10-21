"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Bot,
  Check,
  Copy,
  Sparkles,
  Terminal,
  User as UserIcon,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { AssessmentPreviewCard, type AssessmentDraftData } from "./assessment-preview-card";
import type { TicketDetails } from "./action-confirmation-dialog";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agentRole?: string;
  draftAssessments?: AssessmentDraftData[];
  confirmationTicket?: TicketDetails | null;
  toolCalls?: Array<{ tool: string; result?: unknown }>;
  createdAt?: string;
  isStreaming?: boolean;
  statusText?: string;
}

interface AIMessageListProps {
  messages: ChatMessage[];
  loading?: boolean;
  onPublishClick?: (draft: AssessmentDraftData) => void;
  onConfirmTicketClick?: (ticket: TicketDetails) => void;
  onConfirmDirect?: (ticket: TicketDetails, confirmed: boolean) => void;
  onSuggestionClick?: (prompt: string) => void;
  userRole?: string;
}

/**
 * Lightweight Markdown & Code Renderer for AI Chat Stream.
 */
function MarkdownRenderer({ content }: { content: string }): ReactNode {
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <div className="space-y-2 text-xs leading-relaxed break-words">
      {parts.map((part, index) => {
        if (part.startsWith("```") && part.endsWith("```")) {
          const match = part.match(/```(\w+)?\n([\s\S]*?)```/);
          const lang = match ? match[1] || "code" : "code";
          const code = match && match[2] ? match[2].trim() : part.slice(3, -3).trim();

          return <CodeBlock key={index} code={code} language={lang} />;
        }

        // Render regular markdown paragraph
        return <FormattedParagraph key={index} text={part} />;
      })}
    </div>
  );
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-border-subtle bg-slate-950 text-slate-100">
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/80 px-3 py-1.5 text-2xs text-slate-400">
        <span className="flex items-center gap-1 font-mono uppercase">
          <Terminal className="size-3" />
          {language}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-slate-200 transition-colors"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="size-3 text-success" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="size-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-2xs leading-snug">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function FormattedParagraph({ text }: { text: string }) {
  const rawLines = text.split("\n");
  const blocks: Array<{
    type: "heading" | "list" | "table" | "p" | "spacer";
    level?: number;
    content?: string;
    headers?: string[];
    rows?: string[][];
  }> = [];

  let i = 0;
  while (i < rawLines.length) {
    const rawLine = rawLines[i];
    if (rawLine === undefined) {
      i++;
      continue;
    }
    const line = rawLine.trim();
    if (!line) {
      blocks.push({ type: "spacer" });
      i++;
      continue;
    }

    // Markdown Table check: consecutive lines starting and ending with |
    if (line.startsWith("|") && line.endsWith("|")) {
      const tableLines: string[] = [];
      while (i < rawLines.length) {
        const nextRaw = rawLines[i];
        if (nextRaw === undefined) break;
        const nextTrimmed = nextRaw.trim();
        if (!nextTrimmed.startsWith("|") || !nextTrimmed.endsWith("|")) {
          break;
        }
        tableLines.push(nextTrimmed);
        i++;
      }

      const headerLine = tableLines[0];
      if (tableLines.length >= 2 && headerLine) {
        const rawHeaders = headerLine
          .split("|")
          .slice(1, -1)
          .map((h) => h.trim());
        const rawRows = tableLines
          .slice(2)
          .map((r) =>
            r
              .split("|")
              .slice(1, -1)
              .map((c) => c.trim()),
          );
        blocks.push({
          type: "table",
          headers: rawHeaders,
          rows: rawRows,
        });
        continue;
      } else if (tableLines.length > 0 && tableLines[0]) {
        blocks.push({ type: "p", content: tableLines[0] });
        continue;
      }
    }

    if (line.startsWith("### ")) {
      blocks.push({ type: "heading", level: 3, content: line.slice(4) });
    } else if (line.startsWith("## ")) {
      blocks.push({ type: "heading", level: 2, content: line.slice(3) });
    } else if (line.startsWith("# ")) {
      blocks.push({ type: "heading", level: 1, content: line.slice(2) });
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      blocks.push({ type: "list", content: line.slice(2) });
    } else {
      blocks.push({ type: "p", content: line });
    }
    i++;
  }

  return (
    <>
      {blocks.map((b, idx) => {
        if (b.type === "spacer") return <div key={idx} className="h-1.5" />;
        if (b.type === "heading") {
          if (b.level === 1)
            return (
              <h3
                key={idx}
                className="font-bold text-sm text-foreground mt-3 mb-1.5"
              >
                {b.content}
              </h3>
            );
          if (b.level === 2)
            return (
              <h4
                key={idx}
                className="font-bold text-sm text-foreground mt-2 mb-1"
              >
                {b.content}
              </h4>
            );
          return (
            <h5
              key={idx}
              className="font-semibold text-xs text-foreground mt-2 mb-1"
            >
              {b.content}
            </h5>
          );
        }
        if (b.type === "list") {
          return (
            <div key={idx} className="flex items-start gap-1.5 ml-2 my-0.5">
              <span className="text-primary font-bold">•</span>
              <span>{renderInlineFormatting(b.content || "")}</span>
            </div>
          );
        }
        if (b.type === "table" && b.headers && b.rows) {
          return (
            <div
              key={idx}
              className="my-2 overflow-x-auto rounded-lg border border-border-subtle bg-muted/20"
            >
              <table className="w-full border-collapse text-left text-2xs">
                <thead className="bg-muted/80 border-b border-border-subtle text-foreground font-semibold">
                  <tr>
                    {b.headers.map((h, hIdx) => (
                      <th
                        key={hIdx}
                        className="px-2.5 py-1.5 whitespace-nowrap"
                      >
                        {renderInlineFormatting(h)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle/40">
                  {b.rows.map((r, rIdx) => (
                    <tr
                      key={rIdx}
                      className="hover:bg-muted/30 transition-colors"
                    >
                      {r.map((c, cIdx) => (
                        <td
                          key={cIdx}
                          className="px-2.5 py-1.5 text-foreground whitespace-nowrap"
                        >
                          {renderInlineFormatting(c)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return <p key={idx}>{renderInlineFormatting(b.content || "")}</p>;
      })}
    </>
  );
}

function renderInlineFormatting(str: string): ReactNode {
  // Bold & Inline Code parser
  const tokens = str.split(/(\*\*.*?\*\*|`.*?`)/g);

  return (
    <>
      {tokens.map((token, i) => {
        if (token.startsWith("**") && token.endsWith("**")) {
          return (
            <strong key={i} className="font-semibold text-foreground">
              {token.slice(2, -2)}
            </strong>
          );
        }
        if (token.startsWith("`") && token.endsWith("`")) {
          return (
            <code
              key={i}
              className="rounded bg-muted px-1 py-0.5 font-mono text-2xs text-primary font-medium"
            >
              {token.slice(1, -1)}
            </code>
          );
        }
        return token;
      })}
    </>
  );
}

export function AIMessageList({
  messages,
  loading,
  onPublishClick,
  onConfirmTicketClick,
  onConfirmDirect,
  onSuggestionClick,
  userRole,
}: AIMessageListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof bottomRef.current?.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, loading]);

  if (messages.length === 0) {
    const suggestions = getSuggestionsForRole(userRole);

    return (
      <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
        <div className="size-12 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mb-3">
          <Sparkles className="size-6" />
        </div>
        <h3 className="font-semibold text-sm text-foreground">Role-Aware AI Assistant</h3>
        <p className="mt-1 text-xs text-muted-foreground max-w-xs">
          Directly integrated with LMS academic records, quizzes, schedules, and analytics under zero-trust authorization.
        </p>

        {suggestions.length > 0 && (
          <div className="mt-6 w-full space-y-1.5 text-left">
            <span className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground px-1">
              Suggested Prompts:
            </span>
            <div className="grid gap-1.5">
              {suggestions.map((s, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSuggestionClick?.(s)}
                  className="rounded-lg border border-border-subtle bg-muted/40 px-3 py-2 text-left text-xs text-foreground transition-all hover:bg-muted hover:border-primary/30"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
      {messages.map((msg) => {
        const isUser = msg.role === "user";

        return (
          <div
            key={msg.id}
            data-role={msg.role}
            data-testid={`ai-message-${msg.role}`}
            className={cn("flex gap-2.5", isUser ? "justify-end" : "justify-start")}
          >
            {!isUser && (
              <div className="size-7 rounded-lg bg-primary/15 text-primary flex items-center justify-center shrink-0 mt-0.5">
                <Bot className="size-4" />
              </div>
            )}

            <div
              className={cn(
                "rounded-2xl px-3.5 py-2.5 max-w-[85%] shadow-xs",
                isUser
                  ? "bg-primary text-primary-foreground rounded-br-xs text-xs"
                  : "bg-overlay border border-border-subtle text-foreground rounded-bl-xs",
              )}
            >
              {!isUser && msg.agentRole && (
                <div className="mb-1 flex items-center gap-1.5">
                  <Badge tone="primary" className="text-2xs px-1.5 py-0.5">
                    {msg.agentRole}
                  </Badge>
                </div>
              )}

              {isUser ? (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              ) : msg.content ? (
                <div>
                  <MarkdownRenderer content={msg.content} />
                  {msg.isStreaming && (
                    <span className="inline-block w-1.5 h-3 bg-primary ml-1 animate-pulse align-middle" />
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse my-1">
                  <Sparkles className="size-3.5 text-primary animate-spin" />
                  <span>{msg.statusText || "Analyzing intent and consulting LMS records..."}</span>
                </div>
              )}


              {/* Render Assessment Drafts if present */}
              {msg.draftAssessments?.map((draft, idx) => (
                <AssessmentPreviewCard
                  key={idx}
                  draft={draft}
                  onPublishClick={onPublishClick}
                />
              ))}

              {/* Render Confirmation Ticket Banner with direct Yes | No execution */}
              {msg.confirmationTicket && (
                <div className="mt-2.5 rounded-xl border border-warning/40 bg-warning/10 p-3 text-xs">
                  <p className="font-semibold text-warning mb-1 text-xs">
                    {msg.confirmationTicket.preview_summary || `Approval Required: ${msg.confirmationTicket.action_name}`}
                  </p>
                  <div className="mt-2.5 flex items-center gap-2">
                    <button
                      type="button"
                      data-testid="ai-confirm-yes"
                      onClick={() => onConfirmDirect ? onConfirmDirect(msg.confirmationTicket!, true) : onConfirmTicketClick?.(msg.confirmationTicket!)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs"
                    >
                      <Check className="size-3.5" />
                      Yes
                    </button>
                    <button
                      type="button"
                      data-testid="ai-confirm-no"
                      onClick={() => onConfirmDirect ? onConfirmDirect(msg.confirmationTicket!, false) : null}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-muted/80 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                    >
                      No
                    </button>
                    {onConfirmTicketClick && (
                      <button
                        type="button"
                        onClick={() => onConfirmTicketClick(msg.confirmationTicket!)}
                        className="ml-auto text-3xs text-muted-foreground hover:text-foreground hover:underline"
                      >
                        Inspect Details
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>

            {isUser && (
              <div className="size-7 rounded-lg bg-muted text-muted-foreground flex items-center justify-center shrink-0 mt-0.5">
                <UserIcon className="size-4" />
              </div>
            )}
          </div>
        );
      })}

      {loading && !messages.some((m) => m.isStreaming) && (
        <div className="flex gap-2.5 justify-start">
          <div className="size-7 rounded-lg bg-primary/15 text-primary flex items-center justify-center shrink-0 mt-0.5">
            <Bot className="size-4" />
          </div>
          <div className="rounded-2xl rounded-bl-xs bg-overlay border border-border-subtle px-3.5 py-2.5 text-xs text-muted-foreground flex items-center gap-2">
            <Sparkles className="size-3.5 text-primary animate-spin" />
            <span>Thinking & consulting LMS data...</span>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}

function getSuggestionsForRole(role?: string): string[] {
  const r = role?.toUpperCase();
  if (r === "TUTOR") {
    return [
      "Draft a 5-question quiz on Python lists and dictionaries for my course",
      "What is my teaching schedule for this week?",
      "Summarize attendance for my active batches",
      "Find students at risk in my course",
    ];
  }
  if (r === "CORPORATE_MANAGER") {
    return [
      "Show corporate training completion rates",
      "Generate an executive skill-gap summary for our department",
      "Which employees have overdue modules?",
    ];
  }
  if (r === "GUARDIAN") {
    return [
      "What is my student's schedule for tomorrow?",
      "Show latest published grades and attendance record",
      "Are there any upcoming assessment deadlines?",
    ];
  }
  if (r === "SUPER_ADMIN" || r === "ADMIN") {
    return [
      "Check platform sync pipeline status",
      "Audit overall active batch enrollments",
      "Verify system health and recent audit anomalies",
    ];
  }
  // Default (Student)
  return [
    "Explain binary search trees with code examples",
    "What classes do I have this week?",
    "Summarize my recent quiz grades and performance",
    "Give me 3 practice problems on SQL joins",
  ];
}
