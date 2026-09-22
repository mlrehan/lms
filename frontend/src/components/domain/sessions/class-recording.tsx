"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ExternalLink, Film, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/form";
import { EmptyState } from "@/components/ui/states";
import { api, apiPath, segment } from "@/lib/api/client";
import type { PageResourceSummary, SessionRecordingResponse } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** The types a class recording can plausibly be. Anything else in the library
 *  is not a recording, and offering it would only invite mistakes. */
const RECORDING_TYPES = ["Recordings", "Video", "Audio"] as const;

function PublishControls({ sessionId, attached }: { sessionId: string; attached: boolean }): ReactNode {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);

  // Only what this caller can already see; the API additionally requires EDIT
  // on the file before it will publish it to a class.
  const { data } = useQuery({
    queryKey: ["resources", "recordings"],
    queryFn: async () => {
      const pages = await Promise.all(
        RECORDING_TYPES.map((t) =>
          api.get<PageResourceSummary>("/resources", { query: { resource_type: t, page_size: 50 } }),
        ),
      );
      return pages.flatMap((page) => page.items);
    },
  });

  async function run(action: () => Promise<unknown>, done: string): Promise<void> {
    setBusy(true);
    try {
      await action();
      await queryClient.invalidateQueries({ queryKey: ["session", sessionId, "recording"] });
      await queryClient.invalidateQueries({ queryKey: ["sessions", "detail", sessionId] });
      toast.success(done);
    } catch (error) {
      toast.error("That did not work", { description: (error as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <NativeSelect
        aria-label="Recording to publish"
        value={choice}
        onChange={(event) => setChoice(event.target.value)}
        className="h-8 max-w-64 text-xs"
      >
        <option value="">Choose a file from the library…</option>
        {(data ?? []).map((item) => (
          <option key={item.public_id} value={item.public_id}>
            {item.name ?? "Untitled"}
          </option>
        ))}
      </NativeSelect>
      <Button
        type="button"
        size="xs"
        disabled={!choice || busy}
        onClick={() =>
          run(
            () =>
              api.put(`/sessions/${segment(sessionId)}/recording`, { body: { resource_id: choice } }),
            "Recording published to the class.",
          )
        }
      >
        {busy ? <Loader2 className="size-3 animate-spin" /> : null}
        Publish
      </Button>
      {attached ? (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          disabled={busy}
          onClick={() =>
            run(
              () => api.delete(`/sessions/${segment(sessionId)}/recording`),
              "Recording withdrawn. The file itself is untouched.",
            )
          }
        >
          <X className="size-3" />
          Withdraw
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Watch a class back, inside the LMS.
 *
 * The brief's requirement is that an authorised viewer is never handed a direct
 * external link to the recording, and that is a server property, not a styling
 * one: `GET /sessions/{id}/recording` returns a `playback_url` that is a path on
 * our own API, re-authorised on every request, including every seek. There is
 * no URL in this DOM that works for someone who is not in the batch.
 *
 * `external_url` is the provider's own page (a Zoom cloud recording). The API
 * only ever populates it for callers who may edit the session -- they set it --
 * so rendering it here is not a leak; if the field is absent, nothing shows.
 *
 * This is not DRM. Anything a browser plays can be captured, and `nodownload`
 * only hides the player's own save button. What it does buy is that the obvious
 * routes -- copy the link, share the URL, open it signed out -- all lead back
 * through the permission check rather than around it.
 */
export function ClassRecording({
  sessionId,
  canManage = false,
  className,
}: {
  sessionId: string;
  /** Staff get the publish/withdraw controls. The API checks this again. */
  canManage?: boolean;
  className?: string;
}): ReactNode {
  const { data, isPending } = useQuery({
    queryKey: ["session", sessionId, "recording"],
    queryFn: () => api.get<SessionRecordingResponse>(`/sessions/${sessionId}/recording`),
  });

  const video = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    // Reloading on a URL change is not automatic for <video>: React updates the
    // `src` attribute, but the element keeps playing whatever it already
    // buffered until told otherwise.
    video.current?.load();
  }, [data?.playback_url]);

  if (isPending) {
    return <div className={cn("h-40 animate-pulse rounded-lg bg-surface-muted", className)} />;
  }

  const audio = (data?.mime_type ?? "").startsWith("audio/");

  if (!data?.playback_url) {
    return (
      <div className={className}>
        <EmptyState
          icon={<Film />}
          title="No recording yet"
          description={
            data?.external_url
              ? "This class has a provider link but no recording stored in the LMS. Students cannot watch it back here until one is attached."
              : "When a recording is published to this class it will play here."
          }
        />
        {data?.external_url ? (
          <a
            href={data.external_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-xs text-primary underline-offset-4 hover:underline"
          >
            <ExternalLink className="size-3.5" />
            Open the provider&rsquo;s recording
          </a>
        ) : null}
        {canManage ? <PublishControls sessionId={sessionId} attached={false} /> : null}
      </div>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="overflow-hidden rounded-lg border border-border-subtle bg-black">
        {audio ? (
          <audio
            ref={video as unknown as React.RefObject<HTMLAudioElement>}
            src={apiPath(data.playback_url)}
            controls
            controlsList="nodownload"
            preload="metadata"
            className="w-full bg-surface-muted p-4"
          >
            Your browser cannot play this recording.
          </audio>
        ) : (
          <video
            ref={video}
            src={apiPath(data.playback_url)}
            controls
            controlsList="nodownload"
            // Metadata only: a class recording is large, and a page that
            // starts buffering an hour of video because someone opened the
            // session costs the viewer bandwidth they did not ask to spend.
            preload="metadata"
            onContextMenu={(event) => event.preventDefault()}
            playsInline
            className="max-h-[70vh] w-full"
          >
            Your browser cannot play this recording.
          </video>
        )}
      </div>
      <p className="text-2xs text-subtle-foreground">
        {data.name ?? "Class recording"} &middot; played from the LMS, not shared as a link
      </p>
      {data.external_url ? (
        <a
          href={data.external_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-2xs text-subtle-foreground underline-offset-4 hover:underline"
        >
          <ExternalLink className="size-3" />
          Provider recording (staff only)
        </a>
      ) : null}
      {canManage ? <PublishControls sessionId={sessionId} attached /> : null}
    </div>
  );
}
