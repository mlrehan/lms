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
 *
 * This is the one place in the console that goes above weight 600: the
 * figure is set in the display face at 750 with tight tracking, against an
 * 11px uppercase label. That contrast -- small quiet label, large heavy
 * numeral -- is what makes a figure scannable at a glance, and it only works
 * because nothing around it competes.
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

  /*
   * The 750-weight display treatment is for figures, and only figures.
   *
   * A label like a timezone name or a status word set at 28px in the numeral
   * style looks like a mistake -- the tracking is tuned for digits and the
   * weight overpowers everything around it. Text values step down to a size
   * that still leads the card without shouting.
   */
  const isFigure =
    value === null || value === undefined || typeof value === "number" || /^[\d.,+\-%\s]+$/.test(String(value));

  return (
    <div
      className={cn(
        "group rounded-xl border border-border-subtle bg-surface p-4 shadow-xs",
        "transition-colors duration-200 ease-out hover:border-border-strong",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="eyebrow">{label}</span>
        {Icon ? (
          <Icon
            className="size-3.5 shrink-0 text-subtle-foreground transition-colors duration-200 group-hover:text-muted-foreground"
            aria-hidden
          />
        ) : null}
      </div>
      {loading ? (
        <Skeleton className="mt-2.5 h-8 w-20" />
      ) : (
        <p
          className={cn(
            "mt-1.5",
            isFigure
              ? "numeral text-[1.75rem] leading-none"
              : "truncate font-display text-lg font-semibold leading-tight tracking-tight",
            tone === "warning" && "text-warning",
            tone === "danger" && "text-danger",
            tone === "success" && "text-success",
          )}
        >
          {display}
          {suffix && value !== null && value !== undefined ? (
            <span className="ml-0.5 align-baseline text-base font-medium tracking-normal text-subtle-foreground">
              {suffix}
            </span>
          ) : null}
        </p>
      )}
      {hint ? (
        <p className="mt-2 text-2xs leading-relaxed text-subtle-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }): ReactNode {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}
