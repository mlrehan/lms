"use client";

/**
 * The in-platform video player.
 *
 * It frames `player_url`, a path on our API that re-checks the viewer's access
 * on every open and then hands the browser to the provider's own player. The
 * provider's address is never in this page. Size, theatre mode and fullscreen
 * are ours; captions, quality and playback speed are the provider player's own
 * controls, inside the frame.
 *
 * What it cannot promise is stated under the player, per provider: whether a
 * viewer can download is decided by the owner's settings on that provider,
 * not by the LMS.
 */

import { useState, type ReactNode } from "react";
import { ExternalLink, Maximize2, Minimize2, MonitorPlay } from "lucide-react";
import { apiPath } from "@/lib/api/client";
import type { VideoDetail } from "@/lib/api/types";
import { Button, LinkButton } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Size = "S" | "M" | "L";

const WIDTH: Record<Size, string> = { S: "max-w-2xl", M: "max-w-4xl", L: "max-w-6xl" };

export function VideoPlayer({ video }: { video: VideoDetail }): ReactNode {
  const [size, setSize] = useState<Size>("M");
  const [theatre, setTheatre] = useState(false);

  if (!video.player_url) {
    return (
      <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-xl border border-border-subtle bg-surface-muted p-6 text-center">
        <MonitorPlay className="size-8 text-muted-foreground" aria-hidden />
        <p className="max-w-md text-sm text-muted-foreground">
          {video.provider_label} recordings cannot be played inside the LMS. {video.notes.download}
        </p>
        <LinkButton href={apiPath(video.open_url)} target="_blank" rel="noopener noreferrer">
          <ExternalLink /> Open on {video.provider_label}
        </LinkButton>
      </div>
    );
  }

  const frame = (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black">
      <iframe
        // Keyed on the video so switching tears the old player down.
        key={video.public_id}
        title={video.title}
        src={apiPath(video.player_url)}
        className="absolute inset-0 size-full"
        allow="fullscreen; autoplay; encrypted-media; picture-in-picture"
        allowFullScreen
        // Our origin and nothing more: YouTube refuses to start without it
        // ("Error 153"); the batch and the viewer stay out of it.
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </div>
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-end gap-1">
        <span className="mr-auto text-xs text-muted-foreground">
          Captions, quality and speed are in the player&apos;s own controls.
        </span>
        {!theatre
          ? (["S", "M", "L"] as Size[]).map((s) => (
              <Button
                key={s}
                size="sm"
                variant={size === s ? "secondary" : "ghost"}
                aria-pressed={size === s}
                aria-label={`Player size ${s === "S" ? "small" : s === "M" ? "medium" : "large"}`}
                onClick={() => setSize(s)}
              >
                {s}
              </Button>
            ))
          : null}
        <Button size="sm" variant="ghost" aria-pressed={theatre} onClick={() => setTheatre((t) => !t)}>
          {theatre ? <Minimize2 /> : <Maximize2 />} {theatre ? "Exit theatre" : "Theatre"}
        </Button>
      </div>

      {theatre ? (
        // Theatre: the full width of the content area on a dark band, so the
        // page around the video recedes. Fullscreen is the player's own button.
        <div className="-mx-4 bg-black px-0 py-4 sm:-mx-6 sm:px-4">{frame}</div>
      ) : (
        <div className={cn("mx-auto w-full", WIDTH[size])}>{frame}</div>
      )}

      <p className="text-xs text-muted-foreground">
        If the player shows an error, the link may be private, expired or restricted on{" "}
        {video.provider_label} — ask whoever shared it.
      </p>
    </div>
  );
}
