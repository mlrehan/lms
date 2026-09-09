"use client";

import type { ComponentProps, HTMLAttributes, ReactNode } from "react";
import { Checkbox as BaseCheckbox } from "@base-ui/react/checkbox";
import { Switch as BaseSwitch } from "@base-ui/react/switch";
import { Tabs as BaseTabs } from "@base-ui/react/tabs";
import { Tooltip as BaseTooltip } from "@base-ui/react/tooltip";
import { Check, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                    */
/* -------------------------------------------------------------------------- */

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>): ReactNode {
  return (
    <div
      className={cn("rounded-card border border-border bg-surface shadow-sm", className)}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}): ReactNode {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0 space-y-0.5">
        <h3 className="truncate text-sm font-semibold text-foreground">{title}</h3>
        {description ? (
          <p className="text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>): ReactNode {
  return <div className={cn("p-4", className)} {...props} />;
}

export function Separator({ className }: { className?: string }): ReactNode {
  return <div role="separator" className={cn("h-px w-full bg-border", className)} />;
}

/* -------------------------------------------------------------------------- */
/* Status                                                                      */
/* -------------------------------------------------------------------------- */

export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

const badgeTones: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-foreground",
  primary: "bg-accent text-accent-foreground",
  success: "bg-success/15 text-success",
  warning: "bg-warning/20 text-warning-foreground dark:text-warning",
  danger: "bg-danger/15 text-danger",
  info: "bg-info/15 text-info",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }): ReactNode {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        badgeTones[tone],
        className,
      )}
      {...props}
    />
  );
}

export function Skeleton({ className }: { className?: string }): ReactNode {
  // A `<span>` rather than a `<div>`: skeletons sit inside table cells and
  // paragraphs, and a block element there is invalid HTML that React reports
  // as a hydration error.
  return <span className={cn("block animate-pulse rounded-md bg-muted", className)} />;
}

/* -------------------------------------------------------------------------- */
/* Inputs                                                                      */
/* -------------------------------------------------------------------------- */

export function Checkbox({
  className,
  ...props
}: ComponentProps<typeof BaseCheckbox.Root>): ReactNode {
  return (
    <BaseCheckbox.Root
      className={cn(
        "flex size-4 shrink-0 items-center justify-center rounded border border-border-strong bg-surface",
        "data-[checked]:border-primary data-[checked]:bg-primary data-[unchecked]:bg-surface",
        "data-[indeterminate]:border-primary data-[indeterminate]:bg-primary",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <BaseCheckbox.Indicator className="flex text-primary-foreground data-[unchecked]:hidden">
        {props.indeterminate ? <Minus className="size-3" /> : <Check className="size-3" />}
      </BaseCheckbox.Indicator>
    </BaseCheckbox.Root>
  );
}

export function Switch({ className, ...props }: ComponentProps<typeof BaseSwitch.Root>): ReactNode {
  return (
    <BaseSwitch.Root
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full border border-border-strong transition-colors",
        "data-[checked]:border-primary data-[checked]:bg-primary data-[unchecked]:bg-muted",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <BaseSwitch.Thumb className="block size-4 translate-x-0.5 rounded-full bg-surface shadow transition-transform data-[checked]:translate-x-[18px]" />
    </BaseSwitch.Root>
  );
}

/* -------------------------------------------------------------------------- */
/* Navigation                                                                  */
/* -------------------------------------------------------------------------- */

export const Tabs = BaseTabs.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof BaseTabs.List>): ReactNode {
  return (
    <BaseTabs.List
      className={cn(
        "relative flex items-center gap-1 overflow-x-auto border-b border-border",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTab({ className, ...props }: ComponentProps<typeof BaseTabs.Tab>): ReactNode {
  return (
    <BaseTabs.Tab
      className={cn(
        "-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground transition-colors",
        "hover:text-foreground data-[selected]:border-primary data-[selected]:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TabsPanel({
  className,
  ...props
}: ComponentProps<typeof BaseTabs.Panel>): ReactNode {
  return <BaseTabs.Panel className={cn("pt-4 outline-none", className)} {...props} />;
}

/* -------------------------------------------------------------------------- */
/* Tooltip                                                                     */
/* -------------------------------------------------------------------------- */

export const TooltipProvider = BaseTooltip.Provider;

export function Tooltip({
  content,
  children,
}: {
  content: ReactNode;
  children: ReactNode;
}): ReactNode {
  if (!content) return <>{children}</>;
  return (
    <BaseTooltip.Root>
      <BaseTooltip.Trigger render={<span className="inline-flex" />}>{children}</BaseTooltip.Trigger>
      <BaseTooltip.Portal>
        <BaseTooltip.Positioner sideOffset={6} className="z-50">
          <BaseTooltip.Popup className="max-w-xs rounded-md border border-border bg-surface px-2 py-1 text-xs text-foreground shadow-md">
            {content}
          </BaseTooltip.Popup>
        </BaseTooltip.Positioner>
      </BaseTooltip.Portal>
    </BaseTooltip.Root>
  );
}
