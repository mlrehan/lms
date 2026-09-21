"use client";

import { useState } from "react";
import { BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";

const SIZES = {
  sm: "size-9 [&>svg]:size-4",
  md: "size-12 [&>svg]:size-5",
  lg: "size-20 [&>svg]:size-8",
} as const;

/**
 * The URL to put in an `<img>`.
 *
 * The API returns an absolute URL for an image LAIT hosts, and a path
 * (`/courses/<id>/image/small?v=...`) for one an administrator uploaded. The
 * path needs the session, so it goes through the same-origin proxy; the
 * absolute URL is used as it is.
 */
export function imageSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `/api/backend${url}` : url;
}

/**
 * A course's thumbnail, or a neutral placeholder.
 *
 * An image that fails to load (a dead external link, a removed file) falls back
 * to the placeholder rather than a broken-image icon, so the list stays tidy
 * whatever the catalogue's images are doing.
 */
export function CourseThumb({
  src,
  title,
  size = "md",
  className,
}: {
  src?: string | null;
  title: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const url = imageSrc(src);
  const [failed, setFailed] = useState<string | null>(null);
  const show = Boolean(url) && failed !== url;

  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-accent text-accent-foreground",
        SIZES[size],
        className,
      )}
    >
      {show ? (
        // eslint-disable-next-line @next/next/no-img-element -- external or authenticated, not optimisable
        <img
          src={url ?? undefined}
          alt=""
          loading="lazy"
          onError={() => setFailed(url)}
          className="size-full bg-surface object-contain"
        />
      ) : (
        <BookOpen aria-hidden />
      )}
      <span className="sr-only">{title}</span>
    </span>
  );
}
