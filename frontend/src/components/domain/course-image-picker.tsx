"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ImagePlus, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { imageSrc } from "@/components/domain/course-image";
import { pictureProblem } from "@/components/domain/avatar-uploader";
import { cn } from "@/lib/utils";

/** What the person has chosen but not yet saved: a file to upload, or a request to remove. */
export type StagedImage = File | "remove" | null;

/**
 * Choose, preview and stage a course image. Nothing is uploaded from here: the
 * parent saves the course first and then sends the staged files, so an image can
 * be picked while *creating* a course that does not exist yet, and a cancelled
 * form uploads nothing.
 */
export function CourseImagePicker({
  label,
  hint,
  current,
  staged,
  onChange,
  disabled,
  wide,
}: {
  label: string;
  hint: string;
  /** The saved image URL, if any. */
  current?: string | null;
  staged: StagedImage;
  onChange: (next: StagedImage) => void;
  disabled?: boolean;
  wide?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // Derived, not stored: a preview is a pure function of the staged file.
  const preview = useMemo(() => (staged instanceof File ? URL.createObjectURL(staged) : null), [staged]);
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );

  function choose(file: File | undefined) {
    if (!file) return;
    const issue = pictureProblem(file);
    setProblem(issue);
    if (!issue) onChange(file);
  }

  const shown = staged === "remove" ? null : (preview ?? imageSrc(current));
  const hasImage = Boolean(shown);
  const pending = staged !== null;

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{label}</p>
      <div
        className={cn(
          "relative flex items-center justify-center overflow-hidden rounded-lg border border-dashed border-border-strong bg-surface-muted transition-colors",
          wide ? "h-36 w-full" : "size-36",
          dragging && "border-primary bg-accent",
          !disabled && "cursor-pointer hover:border-primary",
        )}
        onClick={disabled ? undefined : () => input.current?.click()}
        onDragOver={disabled ? undefined : (event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={
          disabled
            ? undefined
            : (event) => {
                event.preventDefault();
                setDragging(false);
                choose(event.dataTransfer.files[0]);
              }
        }
      >
        {shown ? (
          // eslint-disable-next-line @next/next/no-img-element -- local preview or authenticated image
          <img src={shown} alt={`${label} preview`} className="size-full object-contain" />
        ) : (
          <span className="flex flex-col items-center gap-1 px-3 text-center text-xs text-muted-foreground">
            <ImagePlus className="size-6" aria-hidden />
            {disabled ? "No image" : "Click or drop an image"}
          </span>
        )}
      </div>

      {!disabled ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="secondary" onClick={() => input.current?.click()}>
            <Upload /> {hasImage ? "Replace" : "Add"}
          </Button>
          {hasImage ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setProblem(null);
                // A file that was only staged is simply dropped; a saved image needs an explicit removal.
                onChange(staged instanceof File ? null : "remove");
              }}
            >
              <Trash2 /> Remove
            </Button>
          ) : null}
          {staged === "remove" && current ? (
            <Button type="button" variant="ghost" onClick={() => onChange(null)}>
              Undo remove
            </Button>
          ) : null}
        </div>
      ) : null}

      <p className="text-xs text-muted-foreground">{hint}</p>
      {pending ? (
        <p className="text-xs text-primary" aria-live="polite">
          {staged === "remove" ? "Will be removed when you save." : "Will be uploaded when you save."}
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="text-xs text-danger">
          {problem}
        </p>
      ) : null}

      <input
        ref={input}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="sr-only"
        aria-label={`Choose ${label.toLowerCase()}`}
        onChange={(event) => {
          choose(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
    </div>
  );
}
