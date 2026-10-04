"use client";

import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";

/*
 * One focus treatment for every control in the console: the border goes to
 * the accent and a soft halo appears outside it.
 *
 * The halo replaces the global `:focus-visible` outline on form controls
 * deliberately -- an outline offset 2px from a 36px input collides with its
 * neighbour in a dense two-column form, whereas a ring hugs the control. It
 * is 3px and 18% opacity: unmistakable, without the "glowing" look that a
 * saturated ring gives.
 */
export const controlClasses = cn(
  "w-full rounded-md border border-border-strong bg-surface px-2.5 py-2",
  "text-sm text-foreground placeholder:text-subtle-foreground",
  "shadow-xs transition-all duration-200 ease-out",
  "hover:border-slate-400/70 dark:hover:border-slate-500/70",
  "focus-visible:outline-none focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-primary/18",
  "disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-60 disabled:shadow-none",
  "aria-[invalid=true]:border-danger aria-[invalid=true]:focus-visible:border-danger",
  "aria-[invalid=true]:focus-visible:ring-danger/18",
);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(controlClasses, "h-9", className)} {...props} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, rows = 4, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        rows={rows}
        className={cn(controlClasses, "resize-y leading-relaxed", className)}
        {...props}
      />
    );
  },
);

export interface FieldProps {
  label: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  className?: string;
  children: ReactNode | ((ids: { id: string; describedBy: string | undefined }) => ReactNode);
}

/**
 * Label, control, hint and error as one unit.
 *
 * The `children`-as-function form exists so the control receives `id` and
 * `aria-describedby` that actually match the elements rendered here. A label
 * that merely sits next to an input is not associated with it, and an error
 * message that is not referenced is invisible to a screen reader -- the
 * person who most needs to be told why the form was rejected.
 */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: FieldProps): ReactNode {
  const generated = useId();
  const id = htmlFor ?? generated;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={id}
        className="block text-xs font-medium tracking-normal text-muted-foreground"
      >
        {label}
        {required ? (
          <span className="ml-0.5 text-danger" aria-hidden>
            *
          </span>
        ) : null}
      </label>
      {typeof children === "function" ? children({ id, describedBy }) : children}
      {hint ? (
        <p id={hintId} className="text-2xs leading-relaxed text-subtle-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-2xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The footer of a form. A top hairline separates the commit actions from the
 * fields, so "Save" never looks like it belongs to the last input.
 */
export function FormActions({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="flex items-center justify-end gap-2 border-t border-border-subtle pt-4">
      {children}
    </div>
  );
}

export function FormGrid({
  children,
  columns = 2,
}: {
  children: ReactNode;
  columns?: 1 | 2 | 3;
}): ReactNode {
  return (
    <div
      className={cn(
        "grid gap-x-4 gap-y-4",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-1 sm:grid-cols-2",
        columns === 3 && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
      )}
    >
      {children}
    </div>
  );
}
