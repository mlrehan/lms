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
 */
export function DialogContent({
  className,
  children,
  size = "md",
  ...props
}: ComponentProps<typeof BaseDialog.Popup> & { size?: "sm" | "md" | "lg" | "xl" }): ReactNode {
  return (
    <BaseDialog.Portal>
      <BaseDialog.Backdrop className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[1px] data-[open]:animate-[lms-fade-in_120ms_ease-out]" />
      <BaseDialog.Popup
        className={cn(
          "fixed left-1/2 top-1/2 z-50 grid w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2",
          "grid-cols-[minmax(0,1fr)] max-h-[calc(100dvh-2rem)] overflow-y-auto",
          "rounded-xl border border-border bg-surface p-5 shadow-xl outline-none",
          size === "sm" && "max-w-md",
          size === "md" && "max-w-lg",
          size === "lg" && "max-w-2xl",
          size === "xl" && "max-w-4xl",
          "data-[open]:animate-[lms-fade-in_140ms_ease-out]",
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
    <div className="mb-4 flex items-start justify-between gap-4">
      <div className="min-w-0 space-y-1">
        <BaseDialog.Title className="text-base font-semibold text-foreground">
          {title}
        </BaseDialog.Title>
        {description ? (
          <BaseDialog.Description className="text-sm text-muted-foreground">
            {description}
          </BaseDialog.Description>
        ) : null}
      </div>
      {showClose ? (
        <BaseDialog.Close
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Close"
        >
          <X className="size-4" />
        </BaseDialog.Close>
      ) : null}
    </div>
  );
}

export function DialogFooter({ children }: { children: ReactNode }): ReactNode {
  return <div className="mt-5 flex flex-wrap items-center justify-end gap-2">{children}</div>;
}
