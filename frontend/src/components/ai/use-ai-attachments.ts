"use client";

import { useCallback, useRef, useState } from "react";
import { api, apiPath } from "@/lib/api/client";

/**
 * Files staged in the AI composer, uploaded as soon as they are added.
 *
 * Uploading on add (rather than on send) is what lets the composer say
 * "this notebook could not be read" before the person has typed their
 * question, and lets Send carry only ids. The server is the authority on
 * what it accepts; the checks here only spare a round trip for the obvious
 * cases (too big, wrong kind, too many) and use the same limits.
 */

export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_FILES = 10;
/** Pasted text longer than this becomes a text attachment instead of a prompt. */
export const LONG_PASTE_CHARS = 8_000;

export const ACCEPTED_EXTENSIONS = [
  "ipynb", "py", "pdf", "docx", "xlsx", "csv", "tsv", "txt", "md", "markdown", "log", "json",
  "sql", "js", "ts", "tsx", "jsx", "java", "c", "h", "cpp", "cs", "r", "rb", "go", "php",
  "html", "css", "xml", "yaml", "yml", "sh", "kt", "swift", "scala", "m",
  "png", "jpg", "jpeg", "webp", "gif",
] as const;

export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.map((e) => `.${e}`).join(",");

export type AttachmentKind =
  | "NOTEBOOK" | "CODE" | "TEXT" | "CSV" | "PDF" | "DOCX" | "XLSX" | "IMAGE";

export interface StagedAttachment {
  /** Local key; stable while uploading. */
  key: string;
  /** Server id once uploaded. */
  id?: string;
  filename: string;
  size: number;
  kind?: AttachmentKind;
  status: "uploading" | "ready" | "failed";
  progress: number;
  /** Why it failed, or a note the server attached (e.g. "no text layer"). */
  message?: string;
  /** Local preview for images. */
  previewUrl?: string;
}

/** What a sent message records about its files. */
export interface SentAttachment {
  id: string;
  filename: string;
  kind?: string;
  size?: number;
  status?: string;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function precheck(file: File, alreadyStaged: number): string | null {
  if (alreadyStaged >= MAX_FILES) return `Up to ${MAX_FILES} files can be attached to one message.`;
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_FILE_BYTES) return `Files can be up to ${MAX_FILE_BYTES / (1024 * 1024)} MB.`;
  const ext = extensionOf(file.name);
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
    return ext
      ? `.${ext} files cannot be read here.`
      : "Files without an extension cannot be read here.";
  }
  return null;
}

/** A long paste as a file. JSON that looks like a notebook keeps its notebook-ness. */
export function pastedTextAsFile(text: string, index: number): File {
  const trimmed = text.trimStart();
  const notebook = trimmed.startsWith("{") && /"cells"\s*:/.test(trimmed.slice(0, 20_000));
  const name = notebook ? `pasted-notebook-${index}.ipynb` : `pasted-text-${index}.txt`;
  return new File([text], name, { type: notebook ? "application/json" : "text/plain" });
}

interface UploadResult {
  id: string;
  kind: AttachmentKind;
  status: string;
  note?: string | null;
}

function upload(file: File, onProgress: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    // XMLHttpRequest rather than fetch: fetch has no upload progress, and a
    // 20 MB notebook on a slow line needs a bar, not a spinner.
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiPath("/ai/attachments"));
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(xhr.responseText || "{}");
      } catch {
        // non-JSON error page
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as unknown as UploadResult);
      } else {
        const message =
          (typeof body.message === "string" && body.message) ||
          (xhr.status === 413 ? "The file is too large." : `Upload failed (${xhr.status}).`);
        reject(new Error(message));
      }
    };
    xhr.onerror = () => reject(new Error("The upload could not reach the server."));
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}

export function useAIAttachments() {
  const [items, setItems] = useState<StagedAttachment[]>([]);
  const counter = useRef(0);
  const countRef = useRef(0);

  const patch = useCallback((key: string, changes: Partial<StagedAttachment>) => {
    setItems((prev) => prev.map((item) => (item.key === key ? { ...item, ...changes } : item)));
  }, []);

  const addFiles = useCallback(
    (files: Iterable<File>) => {
      for (const file of files) {
        counter.current += 1;
        const key = `att-${Date.now()}-${counter.current}`;
        const problem = precheck(file, countRef.current);
        const isImage = file.type.startsWith("image/") && !problem;
        const staged: StagedAttachment = {
          key,
          filename: file.name,
          size: file.size,
          status: problem ? "failed" : "uploading",
          progress: 0,
          message: problem ?? undefined,
          previewUrl: isImage ? URL.createObjectURL(file) : undefined,
        };
        if (!problem) countRef.current += 1;
        setItems((prev) => [...prev, staged]);
        if (problem) continue;
        upload(file, (fraction) => patch(key, { progress: fraction }))
          .then((result) =>
            patch(key, {
              id: result.id,
              kind: result.kind,
              status: "ready",
              progress: 1,
              message: result.note ?? undefined,
            }),
          )
          .catch((err: Error) => {
            countRef.current = Math.max(0, countRef.current - 1);
            patch(key, { status: "failed", message: err.message });
          });
      }
    },
    [patch],
  );

  // Side effects live outside the state updaters, which React may run twice.
  const remove = useCallback(
    (key: string) => {
      const item = items.find((i) => i.key === key);
      if (!item) return;
      if (item.status !== "failed") countRef.current = Math.max(0, countRef.current - 1);
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      // Removed before sending: delete it on the server too, best effort.
      if (item.id) void api.delete(`/ai/attachments/${encodeURIComponent(item.id)}`).catch(() => undefined);
      setItems((prev) => prev.filter((i) => i.key !== key));
    },
    [items],
  );

  /** After sending: forget the staged list without deleting the files (the message uses them). */
  const reset = useCallback(() => {
    items.forEach((i) => i.previewUrl && URL.revokeObjectURL(i.previewUrl));
    setItems([]);
    countRef.current = 0;
  }, [items]);

  const ready = items.filter((i) => i.status === "ready" && i.id);
  return {
    items,
    addFiles,
    remove,
    reset,
    uploading: items.some((i) => i.status === "uploading"),
    readyAttachments: ready.map<SentAttachment>((i) => ({
      id: i.id!,
      filename: i.filename,
      kind: i.kind,
      size: i.size,
    })),
  };
}
