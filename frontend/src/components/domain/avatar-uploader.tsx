"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, Trash2, Upload } from "lucide-react";
import { api } from "@/lib/api/client";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { UserAvatar } from "@/components/domain/user-avatar";
import { cn } from "@/lib/utils";

const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = ["image/jpeg", "image/png", "image/webp"];

/** The same rules the server enforces, checked first so the person is told at once. */
export function pictureProblem(file: { type: string; size: number }): string | null {
  if (!ACCEPT.includes(file.type)) return "Use a JPEG, PNG or WebP image.";
  if (file.size > MAX_BYTES) return "That picture is larger than 5 MB.";
  if (file.size === 0) return "That file is empty.";
  return null;
}

/**
 * Profile picture with upload, drag-and-drop, live preview and removal.
 *
 * `endpoint` is `/users/<id>/picture` for an administrator editing someone
 * else, or `/auth/me/picture` for a person editing themselves -- the two are
 * separate server routes with separate permission checks; this component
 * neither knows nor decides which is allowed.
 */
export function AvatarUploader({
  name,
  src,
  endpoint,
  canEdit,
  invalidate,
}: {
  name: string | null | undefined;
  src: string | null | undefined;
  endpoint: string;
  canEdit: boolean;
  invalidate: string[][];
}) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  const upload = useApiMutation<unknown, File>({
    mutationFn: (file) => {
      const form = new FormData();
      form.append("file", file);
      return api.put(endpoint, { body: form });
    },
    success: "Picture updated.",
    invalidate,
    onSuccess: () => setPreview(null),
    onError: (error) => {
      setPreview(null);
      setProblem(error.message);
    },
  });

  const remove = useApiMutation<unknown, void>({
    mutationFn: () => api.delete(endpoint),
    success: "Picture removed.",
    invalidate,
  });

  function choose(file: File | undefined) {
    if (!file) return;
    const issue = pictureProblem(file);
    setProblem(issue);
    if (issue) return;
    setPreview(URL.createObjectURL(file));
    upload.mutate(file);
  }

  const busy = upload.isPending || remove.isPending;

  return (
    <div className="flex flex-wrap items-center gap-5">
      <div
        className={cn(
          "relative rounded-full transition-shadow",
          dragging && "ring-4 ring-primary/40",
          canEdit && "cursor-pointer",
        )}
        onDragOver={canEdit ? (event) => { event.preventDefault(); setDragging(true); } : undefined}
        onDragLeave={() => setDragging(false)}
        onDrop={
          canEdit
            ? (event) => {
                event.preventDefault();
                setDragging(false);
                choose(event.dataTransfer.files[0]);
              }
            : undefined
        }
        onClick={canEdit ? () => input.current?.click() : undefined}
      >
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element -- local blob preview
          <img src={preview} alt="" className="size-28 rounded-full object-cover opacity-80" />
        ) : (
          <UserAvatar name={name} src={src} size="xl" />
        )}
        {canEdit ? (
          <span className="absolute bottom-0 right-0 flex size-8 items-center justify-center rounded-full border-2 border-surface bg-primary text-primary-foreground">
            <Camera className="size-4" aria-hidden />
          </span>
        ) : null}
      </div>

      <div className="space-y-2">
        {canEdit ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" loading={upload.isPending} disabled={busy} onClick={() => input.current?.click()}>
                <Upload /> {src ? "Replace picture" : "Upload picture"}
              </Button>
              {src ? (
                <Button type="button" variant="ghost" disabled={busy} onClick={() => setConfirmRemove(true)}>
                  <Trash2 /> Remove
                </Button>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground">
              JPEG, PNG or WebP, up to 5 MB. It is cropped to a square and location data is removed.
              You can also drop a file onto the picture.
            </p>
            {problem ? (
              <p role="alert" className="text-xs text-danger">
                {problem}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">You can view this picture but not change it.</p>
        )}
      </div>

      <input
        ref={input}
        type="file"
        accept={ACCEPT.join(",")}
        className="sr-only"
        aria-label="Choose a profile picture"
        onChange={(event) => {
          choose(event.target.files?.[0]);
          event.target.value = ""; // allow choosing the same file again
        }}
      />

      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title="Remove this picture?"
        description="Their initials will be shown instead."
        confirmLabel="Remove picture"
        destructive
        onConfirm={() => {
          remove.mutate();
          setConfirmRemove(false);
        }}
      />
    </div>
  );
}
