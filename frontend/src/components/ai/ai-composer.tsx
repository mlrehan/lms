"use client";

import { useLayoutEffect, useRef } from "react";
import {
  AlertCircle,
  ArrowUp,
  FileCode2,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  Loader2,
  NotebookPen,
  Paperclip,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { VoiceInputButton } from "./voice-input-button";
import {
  ACCEPT_ATTRIBUTE,
  LONG_PASTE_CHARS,
  pastedTextAsFile,
  type StagedAttachment,
} from "./use-ai-attachments";

const MAX_TEXTAREA_PX = 240;

export function formatBytes(bytes: number | undefined): string {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AttachmentIcon({ kind, filename, className }: { kind?: string; filename: string; className?: string }) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const k = kind ?? (ext === "ipynb" ? "NOTEBOOK" : ["png", "jpg", "jpeg", "webp", "gif"].includes(ext) ? "IMAGE"
    : ["xlsx", "csv", "tsv"].includes(ext) ? "XLSX" : ["txt", "md", "pdf", "docx"].includes(ext) ? "TEXT" : "CODE");
  const Icon = k === "NOTEBOOK" ? NotebookPen : k === "IMAGE" ? ImageIcon
    : k === "XLSX" || k === "CSV" ? FileSpreadsheet : k === "CODE" ? FileCode2 : FileText;
  return <Icon className={className} aria-hidden="true" />;
}

function AttachmentChip({ item, onRemove }: { item: StagedAttachment; onRemove: () => void }) {
  const failed = item.status === "failed";
  const uploading = item.status === "uploading";
  return (
    <li
      className={cn(
        "group relative flex w-[11.5rem] shrink-0 items-center gap-2 overflow-hidden rounded-lg border bg-background px-2 py-1.5",
        failed ? "border-danger/40" : "border-border-subtle",
      )}
      title={item.message ? `${item.filename}\n${item.message}` : item.filename}
    >
      {item.previewUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- a local blob preview, not an optimisable asset
        <img src={item.previewUrl} alt="" className="size-8 shrink-0 rounded object-cover" />
      ) : (
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded",
            failed ? "bg-danger/10 text-danger" : "bg-primary/10 text-primary",
          )}
        >
          {failed ? (
            <AlertCircle className="size-4" aria-hidden="true" />
          ) : (
            <AttachmentIcon kind={item.kind} filename={item.filename} className="size-4" />
          )}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-2xs font-medium text-foreground">{item.filename}</span>
        <span className={cn("block truncate text-[10px]", failed ? "text-danger" : "text-muted-foreground")}>
          {failed
            ? item.message
            : uploading
              ? `Uploading ${Math.round(item.progress * 100)}%`
              : item.message ?? formatBytes(item.size)}
        </span>
      </span>
      <button
        type="button"
        onClick={onRemove}
        className="flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        aria-label={`Remove ${item.filename}`}
      >
        <X className="size-3" />
      </button>
      {uploading && (
        <span
          className="absolute inset-x-0 bottom-0 h-0.5 bg-primary transition-[width]"
          style={{ width: `${Math.max(4, item.progress * 100)}%` }}
          aria-hidden="true"
        />
      )}
    </li>
  );
}

export interface AIComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  attachments: StagedAttachment[];
  onAddFiles: (files: File[]) => void;
  onRemoveAttachment: (key: string) => void;
  loading: boolean;
  uploading: boolean;
  placeholder: string;
  textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
}

export function AIComposer({
  value,
  onChange,
  onSend,
  attachments,
  onAddFiles,
  onRemoveAttachment,
  loading,
  uploading,
  placeholder,
  textareaRef,
}: AIComposerProps) {
  const ownRef = useRef<HTMLTextAreaElement | null>(null);
  const ref = textareaRef ?? ownRef;
  const fileInput = useRef<HTMLInputElement | null>(null);
  const pasteCount = useRef(0);

  // Grow with the text up to a cap, then scroll -- measured after every change.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_PX)}px`;
  }, [value, ref]);

  const hasReady = attachments.some((a) => a.status === "ready");
  const canSend = !loading && !uploading && (value.trim().length > 0 || hasReady);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files ?? []);
    if (files.length > 0) {
      e.preventDefault();
      onAddFiles(files);
      return;
    }
    const text = e.clipboardData.getData("text/plain");
    if (text.length > LONG_PASTE_CHARS) {
      // A long paste travels as a file: extracted, budgeted and readable in
      // parts, instead of a prompt too long to send.
      e.preventDefault();
      pasteCount.current += 1;
      onAddFiles([pastedTextAsFile(text, pasteCount.current)]);
    }
  };

  return (
    <div className="rounded-2xl border border-border-subtle bg-muted/30 shadow-xs transition-colors focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20">
      {attachments.length > 0 && (
        <ul className="flex gap-2 overflow-x-auto px-2.5 pt-2.5 pb-1 scrollbar-thin" aria-label="Attached files">
          {attachments.map((item) => (
            <AttachmentChip key={item.key} item={item} onRemove={() => onRemoveAttachment(item.key)} />
          ))}
        </ul>
      )}
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={placeholder}
        aria-label="Message the AI assistant"
        rows={1}
        className="block max-h-60 min-h-[44px] w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-sm leading-relaxed placeholder:text-muted-foreground focus:outline-none scrollbar-thin"
      />
      <div className="flex items-center justify-between gap-2 px-2 pb-2">
        <div className="flex items-center gap-1">
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPT_ATTRIBUTE}
            className="hidden"
            data-testid="ai-file-input"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length) onAddFiles(files);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={loading}
            className="flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            aria-label="Attach files"
            title="Attach files (PDF, Word, Excel, CSV, notebooks, code, images)"
          >
            <Paperclip className="size-4" />
          </button>
          <VoiceInputButton
            onTranscript={(transcript) => {
              onChange(value ? `${value} ${transcript}` : transcript);
              ref.current?.focus();
            }}
            disabled={loading}
          />
        </div>
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          className="flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-xs transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:bg-muted-foreground/30 disabled:text-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          aria-label={uploading ? "Waiting for uploads to finish" : "Send message"}
          title={uploading ? "Waiting for uploads to finish" : "Send (Enter)"}
        >
          {loading || uploading ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
        </button>
      </div>
    </div>
  );
}
