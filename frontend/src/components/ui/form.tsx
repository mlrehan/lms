"use client";

import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";

const controlClasses =
  "w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-foreground " +
  "placeholder:text-muted-foreground transition-colors disabled:cursor-not-allowed disabled:opacity-60 " +
  "aria-[invalid=true]:border-danger";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(controlClasses, "h-9", className)} {...props} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, rows = 4, ...props }, ref) {
    return <textarea ref={ref} rows={rows} className={cn(controlClasses, className)} {...props} />;
  },
);

/**
 * A plain `<select>`, used wherever the options are a short static list.
 * The Base UI `Select` in `select.tsx` exists for the cases that need
 * searching, async options or rich item content; reaching for it for a
 * three-option enum buys nothing and loses native mobile behaviour.
 */
export const NativeSelect = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement>
>(function NativeSelect({ className, children, ...props }, ref) {
  return (
    <select ref={ref} className={cn(controlClasses, "h-9 pr-8", className)} {...props}>
      {children}
    </select>
  );
});

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
      <label htmlFor={id} className="block text-sm font-medium text-foreground">
        {label}
        {required ? (
          <span className="ml-1 text-danger" aria-hidden>
            *
          </span>
        ) : null}
      </label>
      {typeof children === "function" ? children({ id, describedBy }) : children}
      {hint ? (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function FormActions({ children }: { children: ReactNode }): ReactNode {
  return <div className="flex items-center justify-end gap-2 pt-2">{children}</div>;
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
        "grid gap-4",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-1 sm:grid-cols-2",
        columns === 3 && "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
      )}
    >
      {children}
    </div>
  );
}
