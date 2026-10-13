"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileQuestion,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { apiPath, segment } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { cn } from "@/lib/utils";
import { PdfView } from "./pdf-view";
import { DocView, SheetView, TextView } from "./renderers";
import { extensionOf, typeLabel, viewerKind, type FileLike } from "./kinds";

/**
 * One file, opened in place.
 *
 * **Nothing is fetched until a file is chosen**, and only the renderer that
 * file needs is mounted -- `pdfjs-dist` and the Office readers are dynamic
 * imports, so a list of twenty files costs twenty rows of metadata and no
 * bytes. Switching files unmounts the previous renderer, which is what
 * releases its document handle and cancels its in-flight request; a viewer
 * that merely swapped its `src` would leave both behind.
 *
 * **The bytes come from `/resources/{id}/preview`**, which needs VIEW where
 * `/download` needs DOWNLOAD -- the whole reason a file can be shown to
 * somebody who may not keep it. So the Download button appears only when the
 * share actually says DOWNLOAD, and the server checks again regardless.
 */

/** The toolbar's link actions, matching `Button variant="ghost" size="xs"`. */
const ACTION =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground " +
  "transition-colors hover:bg-muted hover:text-foreground";

export interface ViewerFile extends FileLike {
  resource_id: string;
  resource_name?: string | null;
  level?: string | null;
  size?: number | null;
  shared_by_name?: string | null;
}

function Unsupported({ file, canDownload }: { file: ViewerFile; canDownload: boolean }): ReactNode {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        icon={<FileQuestion />}
        title={`${typeLabel(file)} files open outside the browser`}
        description={
          canDownload
            ? "Download it to read it in the application it belongs to."
            : "This file was shared to view only, and your browser cannot display this type. Ask whoever shared it for a copy you can open."
        }
      />
    </div>
  );
}

function Body({ file, src }: { file: ViewerFile; src: string }): ReactNode {
  const kind = viewerKind(file);
  const canDownload = (file.level ?? "").toUpperCase() === "DOWNLOAD";

  switch (kind) {
    case "pdf":
      return <PdfView src={src} title={file.resource_name ?? "Document"} />;
    case "image":
      return (
        <div className="h-full overflow-auto bg-surface-muted p-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- the source is
              our own permission-checked stream, not a static asset Next can
              optimise, and the optimiser would proxy it without the cookie. */}
          <img
            src={src}
            alt={file.resource_name ?? "Image"}
            className="mx-auto max-h-full rounded shadow-sm"
          />
        </div>
      );
    case "video":
      return (
        <div className="flex h-full items-center justify-center bg-black">
          <video
            src={src}
            controls
            // The player's own save button, withheld when the share was.
            controlsList={canDownload ? undefined : "nodownload"}
            preload="metadata"
            playsInline
            className="max-h-full w-full"
          >
            Your browser cannot play this file.
          </video>
        </div>
      );
    case "audio":
      return (
        <div className="flex h-full items-center justify-center bg-surface-muted p-6">
          <audio
            src={src}
            controls
            controlsList={canDownload ? undefined : "nodownload"}
            preload="metadata"
            className="w-full max-w-lg"
          >
            Your browser cannot play this file.
          </audio>
        </div>
      );
    case "sheet":
      return <SheetView src={src} delimited={["csv", "tsv"].includes(extensionOf(file))} />;
    case "document":
      // `.doc` is the old binary format, which is not a ZIP and cannot be read
      // here. Saying so beats showing a parse error.
      return extensionOf(file) === "doc" ? (
        <Unsupported file={file} canDownload={canDownload} />
      ) : (
        <DocView src={src} />
      );
    case "markdown":
      return <TextView src={src} markdown />;
    case "text":
      return <TextView src={src} markdown={false} />;
    default:
      return <Unsupported file={file} canDownload={canDownload} />;
  }
}

export function UniversalViewer({
  file,
  onBack,
  className,
}: {
  file: ViewerFile | null;
  /** Shown on phones, where the viewer replaces the list. */
  onBack?: () => void;
  className?: string;
}): ReactNode {
  const frame = useRef<HTMLDivElement | null>(null);
  const [full, setFull] = useState(false);

  useEffect(() => {
    const sync = () => setFull(document.fullscreenElement === frame.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  if (!file) {
    return (
      <div className={cn("flex h-full items-center justify-center", className)}>
        <EmptyState
          icon={<FileQuestion />}
          title="Choose a file"
          description="Pick something from the list to read, watch or listen to it here."
        />
      </div>
    );
  }

  const src = apiPath(`/resources/${segment(file.resource_id)}/preview`);
  const canDownload = (file.level ?? "").toUpperCase() === "DOWNLOAD";

  async function toggleFullscreen(): Promise<void> {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
      return;
    }
    // Fails on a browser that refuses the request (an iOS phone, or a user
    // gesture it did not like). There is nothing to recover: the file is
    // already on screen, just not filling it.
    await frame.current?.requestFullscreen().catch(() => undefined);
  }

  return (
    <div
      ref={frame}
      className={cn("flex h-full min-h-0 flex-col bg-surface", className)}
    >
      <div className="flex items-center gap-2 border-b border-border-subtle px-3 py-2">
        {onBack ? (
          <Button
            type="button"
            size="xs"
            variant="ghost"
            onClick={onBack}
            className="lg:hidden"
          >
            <ArrowLeft className="size-4" aria-hidden />
            <span className="sr-only sm:not-sr-only">Back to resources</span>
          </Button>
        ) : null}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={file.resource_name ?? undefined}>
            {file.resource_name ?? "Untitled"}
          </p>
          <p className="flex items-center gap-1.5 text-2xs text-muted-foreground">
            <Badge tone="neutral" className="text-2xs">
              {typeLabel(file)}
            </Badge>
            {file.shared_by_name ? <span>Shared by {file.shared_by_name}</span> : null}
          </p>
        </div>

        {canDownload ? (
          // A real navigation, so the browser's own download manager handles
          // it; `download` names the file rather than the uuid in the path.
          // An anchor rather than a Button, because this one has to *be* a
          // link -- middle-click, copy, and the browser's own handling all
          // come from the element, not from an onClick that mimics it.
          <a
            href={apiPath(`/resources/${segment(file.resource_id)}/download`)}
            download={file.resource_name ?? undefined}
            className={ACTION}
          >
            <Download className="size-4" aria-hidden />
            <span className="sr-only md:not-sr-only">Download</span>
          </a>
        ) : null}

        <a href={src} target="_blank" rel="noopener noreferrer" className={ACTION}>
          <ExternalLink className="size-4" aria-hidden />
          <span className="sr-only">Open in a new tab</span>
        </a>

        <Button
          type="button"
          size="xs"
          variant="ghost"
          aria-label={full ? "Leave full screen" : "Full screen"}
          onClick={() => void toggleFullscreen()}
        >
          {full ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
      </div>

      <div className="min-h-0 flex-1">
        {/* Keyed by file, so switching unmounts the previous renderer rather
            than handing it a new `src` and leaving its state behind. */}
        <Body key={file.resource_id} file={file} src={src} />
      </div>
    </div>
  );
}
