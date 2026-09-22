"use client";

import type { ComponentProps, ReactNode } from "react";
import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = BaseDialog.Root;
export const DialogTrigger = BaseDialog.Trigger;
export const DialogClose = BaseDialog.Close;

/**
 * Every dialog in the console is bounded and scrolls internally.
 *
 * `grid-cols-[minmax(0,1fr)]` is what stops a long unbroken string -- a
 * signing secret, a stored URL, a stack of validation messages -- from
 * widening the popup past the viewport, because a grid child's default
 * `min-width: auto` refuses to shrink below its content.
 *
 * The scrim is slate-tinted rather than black. Pure black over a blue-grey
 * canvas greys the hue out and is most of what makes a modal look cheap; a
 * scrim in the neutral's own family reads as the page dimming.
 */
export function DialogContent({
  className,
  children,
  size = "md",
  ...props
}: ComponentProps<typeof BaseDialog.Popup> & { size?: "sm" | "md" | "lg" | "xl" }): ReactNode {
  return (
    <BaseDialog.Portal>
      <BaseDialog.Backdrop
        className={cn(
          "fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-[3px] dark:bg-slate-950/65",
          "data-[open]:animate-[lms-fade-in_140ms_ease-out]",
        )}
      />
      <BaseDialog.Popup
        className={cn(
          "fixed left-1/2 top-1/2 z-50 grid w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2",
          "grid-cols-[minmax(0,1fr)] max-h-[calc(100dvh-2rem)] overflow-y-auto scrollbar-thin",
          "rounded-2xl border border-border-subtle bg-overlay p-5 shadow-overlay outline-none",
          size === "sm" && "max-w-md",
          size === "md" && "max-w-lg",
          size === "lg" && "max-w-2xl",
          size === "xl" && "max-w-4xl",
          "data-[open]:animate-[lms-fade-in_160ms_ease-out]",
          className,
        )}
        {...props}
      >
        {children}
      </BaseDialog.Popup>
    </BaseDialog.Portal>
  );
}

export function DialogHeader({
  title,
  description,
  showClose = true,
}: {
  title: ReactNode;
  description?: ReactNode;
  showClose?: boolean;
}): ReactNode {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="min-w-0 space-y-1">
        <BaseDialog.Title className="font-display text-base font-semibold tracking-tight text-foreground">
          {title}
        </BaseDialog.Title>
        {description ? (
          <BaseDialog.Description className="text-xs leading-relaxed text-muted-foreground">
            {description}
          </BaseDialog.Description>
        ) : null}
      </div>
      {showClose ? (
        <BaseDialog.Close
          className={cn(
            "-mr-1 -mt-1 shrink-0 rounded-md p-1.5 text-subtle-foreground",
            "transition-all duration-200 ease-out hover:bg-muted hover:text-foreground",
          )}
          aria-label="Close"
        >
          <X className="size-4" />
        </BaseDialog.Close>
      ) : null}
    </div>
  );
}

/**
 * Commit actions, separated from the body by a hairline and vented with the
 * dialog's own padding so the buttons sit on the panel edge rather than
 * floating in the middle of it.
 */
export function DialogFooter({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="-mx-5 -mb-5 mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-border-subtle bg-surface-muted/50 px-5 py-3.5">
      {children}
    </div>
  );
}
