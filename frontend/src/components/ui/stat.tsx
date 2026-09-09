"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/primitives";

/**
 * A single number with a label.
 *
 * `value === null | undefined` renders a dash, never `0`. The difference
 * matters: "no attendance has been recorded yet" and "attendance is zero
 * percent" would look identical, and one of them is an emergency.
 */
export function Stat({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
  loading = false,
  suffix,
}: {
  label: string;
  value: number | string | null | undefined;
  hint?: ReactNode;
  icon?: LucideIcon;
  tone?: "default" | "warning" | "danger" | "success";
  loading?: boolean;
  suffix?: string;
}): ReactNode {
  const display =
    value === null || value === undefined
      ? "—"
      : typeof value === "number"
        ? value.toLocaleString()
        : value;

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        {Icon ? <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden /> : null}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-16" />
      ) : (
        <p
          className={cn(
            "mt-1 text-2xl font-semibold tabular-nums tracking-tight",
            tone === "warning" && "text-warning",
            tone === "danger" && "text-danger",
            tone === "success" && "text-success",
          )}
        >
          {display}
          {suffix && value !== null && value !== undefined ? (
            <span className="ml-0.5 text-base font-normal text-muted-foreground">{suffix}</span>
          ) : null}
        </p>
      )}
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }): ReactNode {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}
