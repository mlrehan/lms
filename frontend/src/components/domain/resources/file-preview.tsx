"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FileQuestion, Loader2 } from "lucide-react";
import { EmptyState } from "@/components/ui/states";
import { cn } from "@/lib/utils";

/**
 * Show a file in place, without handing over a copy.
 *
 * Everything here loads `/resources/{id}/preview`, which needs only VIEW, rather
 * than `/download`, which needs DOWNLOAD. That is the whole point of the two
 * endpoints existing: a file can be readable by someone who may not keep it.
 *
 * The server streams the bytes through its own origin and never issues a
 * presigned URL for a preview, so there is no third-party link here to copy out
 * of the DOM. It is not DRM -- anything the browser renders can be captured --
 * but it does mean the obvious routes (right-click save, share the URL) lead
 * back through the permission check rather than around it.
 */

/** Rendered by the browser itself; the bytes never become text we interpret. */
type Kind = "pdf" | "image" | "video" | "audio" | "text" | "none";

function kindOf(mimeType: string | null | undefined): Kind {
  const type = (mimeType ?? "").split(";")[0]?.trim().toLowerCase() ?? "";
  if (type === "application/pdf") return "pdf";
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("text/")) return "text";
  return "none";
}

/**
 * Text is fetched and printed rather than framed.
 *
 * An `<iframe>` would ask the browser to *interpret* the bytes, and the one
 * thing we never want is a file deciding how it is rendered. Printing it into a
 * `<pre>` as React text means a file full of markup shows its markup -- which is
 * also the "plain-text view" the brief asks for.
 */
function TextPreview({ src }: { src: string }): ReactNode {
  const [state, setState] = useState<{ text?: string; error?: string; loading: boolean }>({
    loading: true,
  });

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch(src, { signal: controller.signal });
        if (!response.ok) throw new Error(`The file could not be read (${response.status}).`);
        // Bounded on purpose: a multi-megabyte log pasted into the DOM freezes
        // the tab, and nobody reads past the first screen of a preview anyway.
        const raw = await response.text();
        const limit = 200_000;
        setState({
          loading: false,
          text: raw.length > limit ? `${raw.slice(0, limit)}\n\n… truncated for preview.` : raw,
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({ loading: false, error: (error as Error).message });
      }
    })();
    return () => controller.abort();
  }, [src]);

  if (state.loading) return <PreviewSpinner />;
  if (state.error) {
    return <EmptyState icon={<FileQuestion />} title="Could not read this file" description={state.error} />;
  }
  return (
    <pre className="max-h-[70vh] overflow-auto scrollbar-thin whitespace-pre-wrap break-words rounded-lg border border-border-subtle bg-surface-muted p-4 font-mono text-2xs leading-relaxed text-foreground">
      {state.text}
    </pre>
  );
}

function PreviewSpinner(): ReactNode {
  return (
    <div className="flex min-h-64 items-center justify-center" aria-busy>
      <Loader2 className="size-5 animate-spin text-subtle-foreground" />
      <span className="sr-only">Loading preview</span>
    </div>
  );
}

export function FilePreview({
  resourceId,
  name,
  mimeType,
  canPreview,
  className,
}: {
  resourceId: string;
  name: string | null | undefined;
  mimeType: string | null | undefined;
  /** The server's own answer. It decides; this component only renders. */
  canPreview: boolean;
  className?: string;
}): ReactNode {
  const src = `/api/backend/resources/${encodeURIComponent(resourceId)}/preview`;
  const kind = canPreview ? kindOf(mimeType) : "none";
  const label = name ?? "file";

  if (kind === "none") {
    return (
      <EmptyState
        icon={<FileQuestion />}
        title="No preview for this file type"
        description={
          <>
            {mimeType ? <span className="font-mono text-2xs">{mimeType}</span> : "This type"} cannot
            be shown in the browser. Download it to open it in an application that can.
          </>
        }
      />
    );
  }

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border-subtle bg-surface-muted", className)}>
      {kind === "pdf" ? (
        // A PDF is rendered by the browser's own viewer, which is sandboxed by
        // the browser itself -- it cannot reach this page's cookies or DOM.
        <iframe src={src} title={`Preview of ${label}`} className="h-[70vh] w-full border-0 bg-white" />
      ) : null}

      {kind === "image" ? (
        <div className="flex max-h-[70vh] items-center justify-center overflow-auto scrollbar-thin p-4">
          {/* Not next/image: the bytes are permission-gated and streamed, so the
              optimiser cannot fetch them, and its cache would outlive access. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={`Preview of ${label}`} className="max-h-[66vh] max-w-full object-contain" />
        </div>
      ) : null}

      {kind === "video" ? (
        <video
          src={src}
          controls
          // `nodownload` hides the browser's own save button. It is a courtesy,
          // not a control -- the network tab is still right there -- and this is
          // the honest limit of protecting playback without DRM.
          controlsList="nodownload"
          onContextMenu={(event) => event.preventDefault()}
          className="max-h-[70vh] w-full bg-black"
        >
          Your browser cannot play this video.
        </video>
      ) : null}

      {kind === "audio" ? (
        <div className="p-4">
          <audio src={src} controls controlsList="nodownload" className="w-full">
            Your browser cannot play this audio.
          </audio>
        </div>
      ) : null}

      {kind === "text" ? <TextPreview src={src} /> : null}
    </div>
  );
}
