"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { X, ZoomIn } from "lucide-react";
import type { Screenshot } from "@/content/help/types";
import { cn } from "@/lib/utils";

/**
 * A screenshot that enlarges when clicked.
 *
 * The enlarged view is a plain fixed overlay rather than a dialog component:
 * it has to work on a public page with no application shell around it, and it
 * has to print sensibly, which a portalled dialog does not.
 *
 * `next/image` is used for the sizing and lazy loading, which matters because
 * a long article can hold a dozen of these.
 */
export function HelpScreenshot({
  image,
  priority = false,
}: {
  image: Screenshot;
  priority?: boolean;
}) {
  const [open, setOpen] = useState(false);

  // Escape closes, and the page behind must not scroll while it is open.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <figure className="my-6 print:my-4">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "group relative block w-full overflow-hidden rounded-lg border border-border bg-muted/40",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        )}
        aria-label={`Enlarge screenshot: ${image.alt}`}
      >
        <Image
          src={`/help/${image.src}`}
          alt={image.alt}
          width={1600}
          height={1000}
          priority={priority}
          sizes="(max-width: 1024px) 100vw, 760px"
          className="h-auto w-full"
        />
        <span
          className={cn(
            "pointer-events-none absolute right-2 top-2 flex items-center gap-1 rounded-md",
            "bg-background/90 px-2 py-1 text-2xs font-medium text-muted-foreground shadow-sm",
            "opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100",
            "print:hidden",
          )}
        >
          <ZoomIn className="size-3" />
          Click to enlarge
        </span>
      </button>
      {image.caption ? (
        <figcaption className="mt-2 text-xs text-muted-foreground">{image.caption}</figcaption>
      ) : null}

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 print:hidden"
          role="dialog"
          aria-modal="true"
          aria-label={image.alt}
          onClick={() => setOpen(false)}
        >
          <button
            type="button"
            className="absolute right-4 top-4 rounded-md bg-background/90 p-2 text-foreground shadow-sm"
            onClick={() => setOpen(false)}
            aria-label="Close enlarged screenshot"
          >
            <X className="size-4" />
          </button>
          <Image
            src={`/help/${image.src}`}
            alt={image.alt}
            width={1600}
            height={1000}
            sizes="100vw"
            className="max-h-[90vh] w-auto max-w-full rounded-lg object-contain shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      ) : null}
    </figure>
  );
}
