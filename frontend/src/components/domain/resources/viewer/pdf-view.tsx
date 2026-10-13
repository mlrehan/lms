"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { FileWarning, ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, InlineSpinner } from "@/components/ui/states";

/**
 * A PDF, with page navigation and zoom.
 *
 * **pdf.js and not the browser's own viewer.** An `<iframe>` pointing at the
 * preview endpoint would be fewer lines, but it fails on both counts that
 * matter here: the preview response carries a `sandbox` CSP, which blocks the
 * built-in plugin outright, and the toolbar it would otherwise draw is the
 * browser's -- not stylable, not translatable, and carrying a save button on a
 * file that may have been shared view-only.
 *
 * **Loaded on demand.** `pdfjs-dist` is megabytes; a dynamic `import()` inside
 * the effect means a student whose list contains no PDF never downloads a byte
 * of it, and the cost is paid once when the first PDF is opened.
 *
 * Rendering is cancellable, which is not optional: clicking through five files
 * in a second leaves four renders in flight, and the last one to finish wins
 * rather than the last one started. Every render checks whether it is still
 * the current one before touching the canvas.
 */
export function PdfView({ src, title }: { src: string; title: string }): ReactNode {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // The loaded document, kept out of React state: it is a mutable handle with
  // a `destroy()`, not a value to render.
  const docRef = useRef<{ numPages: number; getPage: (n: number) => Promise<unknown> } | null>(null);
  // `destroy()` belongs to the *loading task*, not the document: it is what
  // aborts the network request and tears down the worker. Keeping the task is
  // the only way to release both when the viewer moves on mid-download.
  const taskRef = useRef<{ destroy: () => Promise<void> } | null>(null);
  const renderRef = useRef<{ cancel: () => void } | null>(null);
  const generation = useRef(0);

  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [problem, setProblem] = useState<string | null>(null);

  // Reset during render, not at the top of the effect: a synchronous
  // `setState` there paints the previous document once before correcting
  // itself, and the React compiler rejects it outright.
  const [openedFrom, setOpenedFrom] = useState(src);
  if (openedFrom !== src) {
    setOpenedFrom(src);
    setStatus("loading");
    setPage(1);
    setPages(0);
  }

  useEffect(() => {
    let live = true;
    const mine = ++generation.current;

    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        // The worker ships beside the library. Resolving it through
        // `import.meta.url` lets the bundler fingerprint and serve it, rather
        // than relying on a copy in `public/` that can drift from the version
        // actually installed.
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();

        // `withCredentials`: the bytes come from our own API behind the
        // session cookie, and pdf.js fetches them itself rather than through
        // our client.
        const task = pdfjs.getDocument({ url: src, withCredentials: true });
        taskRef.current = task;
        const doc = await task.promise;
        if (!live || mine !== generation.current) {
          void task.destroy();
          return;
        }
        docRef.current = doc as unknown as typeof docRef.current;
        setPages(doc.numPages);
        setStatus("ready");
      } catch (error) {
        if (!live || mine !== generation.current) return;
        setProblem(error instanceof Error ? error.message : "The file could not be read.");
        setStatus("failed");
      }
    })();

    return () => {
      live = false;
      renderRef.current?.cancel();
      renderRef.current = null;
      docRef.current = null;
      const task = taskRef.current;
      taskRef.current = null;
      void task?.destroy();
    };
  }, [src]);

  const draw = useCallback(async () => {
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas || status !== "ready") return;

    renderRef.current?.cancel();
    const mine = generation.current;

    const loaded = (await doc.getPage(page)) as {
      getViewport: (o: { scale: number }) => { width: number; height: number };
      render: (o: object) => { promise: Promise<void>; cancel: () => void };
    };
    if (mine !== generation.current) return;

    // Draw at the device's real pixel density, then scale back with CSS.
    // Rendering at CSS pixels on a retina screen produces text that looks
    // soft, which on a page of body copy reads as a broken viewer.
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const viewport = loaded.getViewport({ scale: zoom * ratio });
    const context = canvas.getContext("2d");
    if (!context) return;

    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = `${Math.floor(viewport.width / ratio)}px`;
    canvas.style.height = `${Math.floor(viewport.height / ratio)}px`;

    const task = loaded.render({ canvasContext: context, viewport });
    renderRef.current = task;
    try {
      await task.promise;
    } catch {
      // A cancelled render is the normal result of changing page quickly.
    }
  }, [page, zoom, status]);

  useEffect(() => {
    void draw();
  }, [draw]);

  if (status === "failed") {
    return (
      <EmptyState icon={<FileWarning />} title="This PDF could not be opened" description={problem ?? "The file may be damaged."} />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b border-border-subtle px-2 py-1.5 text-xs">
        <Button
          type="button"
          size="xs"
          variant="ghost"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => setPage((n) => Math.max(1, n - 1))}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="tabular-nums text-muted-foreground">
          {pages > 0 ? `${page} / ${pages}` : "…"}
        </span>
        <Button
          type="button"
          size="xs"
          variant="ghost"
          aria-label="Next page"
          disabled={pages === 0 || page >= pages}
          onClick={() => setPage((n) => Math.min(pages, n + 1))}
        >
          <ChevronRight className="size-4" />
        </Button>
        <span className="mx-1 h-4 w-px bg-border-subtle" aria-hidden />
        <Button
          type="button"
          size="xs"
          variant="ghost"
          aria-label="Zoom out"
          disabled={zoom <= 0.5}
          onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))}
        >
          <Minus className="size-4" />
        </Button>
        <span className="tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
        <Button
          type="button"
          size="xs"
          variant="ghost"
          aria-label="Zoom in"
          disabled={zoom >= 3}
          onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))}
        >
          <Plus className="size-4" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-surface-muted p-3">
        {status === "loading" ? (
          <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
            <InlineSpinner /> Opening {title}…
          </div>
        ) : null}
        <canvas
          ref={canvasRef}
          aria-label={`${title}, page ${page}`}
          className="mx-auto block rounded shadow-sm"
        />
      </div>
    </div>
  );
}
