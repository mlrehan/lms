"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

const SIZES = {
  xs: "size-6 text-[10px]",
  sm: "size-7 text-xs",
  md: "size-10 text-sm",
  lg: "size-16 text-lg",
  xl: "size-28 text-3xl",
} as const;

export function initialsOf(name: string | null | undefined): string {
  return (
    (name ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("") || "?"
  );
}

/**
 * A person's picture, or their initials.
 *
 * `src` is the API path the server returns (`/users/<id>/picture?v=...`). It is
 * fetched through the same-origin BFF proxy so the session cookie authorises
 * it -- the browser never holds a token, and there is no public image URL.
 * A picture that fails to load falls back to initials rather than a broken-image
 * icon, so a missing file degrades to what the person would have had anyway.
 */
export function UserAvatar({
  name,
  src,
  size = "md",
  className,
}: {
  name: string | null | undefined;
  src?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = Boolean(src) && failedSrc !== src;

  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-accent font-semibold text-accent-foreground",
        SIZES[size],
        className,
      )}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- authenticated, same-origin, already 512px WebP
        <img
          src={`/api/backend${src}`}
          alt=""
          loading="lazy"
          onError={() => setFailedSrc(src ?? null)}
          className="size-full object-cover"
        />
      ) : (
        <span aria-hidden>{initialsOf(name)}</span>
      )}
      <span className="sr-only">{name ?? "User"}</span>
    </span>
  );
}
