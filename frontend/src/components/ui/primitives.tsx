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

/**
 * A raised plane on the canvas.
 *
 * Depth is the surface step plus a hairline, not a shadow. `shadow-xs` here
 * is a seat, not a lift -- just enough to stop the card's bottom edge from
 * dissolving into the canvas on a low-contrast display.
 */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>): ReactNode {
  return (
    <div
      className={cn(
        "rounded-xl border border-border-subtle bg-surface shadow-xs",
        className,
      )}
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
        "flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle px-4 py-3",
        className,
      )}
    >
      <div className="min-w-0 space-y-0.5">
        <h3 className="truncate text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {description ? (
          <p className="text-xs leading-relaxed text-muted-foreground">{description}</p>
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
  return <div role="separator" className={cn("h-px w-full bg-border-subtle", className)} />;
}

/**
 * The small uppercase label that sits above a figure or names a group of
 * fields. Its own component so the tracking and colour cannot drift.
 */
export function Eyebrow({ className, ...props }: HTMLAttributes<HTMLSpanElement>): ReactNode {
  return <span className={cn("eyebrow block", className)} {...props} />;
}

/**
 * The rule that separates one band of a long page from the next.
 *
 * The label sits on a hairline that runs to the right edge, so the eye gets a
 * horizontal anchor to scan along rather than a floating caption. Cheaper
 * than a card, and it keeps a stack of stat grids from reading as one
 * undifferentiated wall.
 */
export function SectionHeader({
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
    <div className={cn("flex items-center gap-3", className)}>
      <div className="min-w-0 shrink-0">
        <h2 className="eyebrow">{title}</h2>
        {description ? (
          <p className="mt-0.5 text-2xs text-subtle-foreground">{description}</p>
        ) : null}
      </div>
      <span className="h-px min-w-4 flex-1 bg-border-subtle" aria-hidden />
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Status                                                                      */
/* -------------------------------------------------------------------------- */

export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

/*
 * Tinted fill plus an inset ring of the same hue. The ring is what keeps a
 * pale badge legible on a white card -- without it, low-saturation tones
 * float with no edge and read as a rendering artefact.
 */
const badgeTones: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-foreground ring-slate-400/20",
  primary: "bg-accent text-accent-foreground ring-primary/25",
  success: "bg-success/10 text-success ring-success/25",
  warning: "bg-warning/10 text-warning ring-warning/30",
  danger: "bg-danger/10 text-danger ring-danger/25",
  info: "bg-info/10 text-info ring-info/25",
};

const dotTones: Record<BadgeTone, string> = {
  neutral: "bg-slate-400",
  primary: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
};

export function Badge({
  tone = "neutral",
  dot = false,
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone; dot?: boolean }): ReactNode {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-2xs font-medium",
        "ring-1 ring-inset",
        badgeTones[tone],
        className,
      )}
      {...props}
    >
      {dot ? (
        <span className={cn("size-1.5 shrink-0 rounded-full", dotTones[tone])} aria-hidden />
      ) : null}
      {children}
    </span>
  );
}

/**
 * A loading placeholder.
 *
 * It sweeps rather than pulses: a pulsing block reads as an alert, and half
 * the screen pulsing at once reads as an outage. A left-to-right sweep is
 * legible as "this is arriving".
 */
export function Skeleton({ className }: { className?: string }): ReactNode {
  // A `<span>` rather than a `<div>`: skeletons sit inside table cells and
  // paragraphs, and a block element there is invalid HTML that React reports
  // as a hydration error.
  return (
    <span
      className={cn(
        "block rounded-sm bg-muted",
        "bg-[linear-gradient(100deg,transparent_25%,var(--color-surface)_50%,transparent_75%)]",
        "bg-[length:200%_100%] [animation:lms-shimmer_1.6s_ease-in-out_infinite]",
        className,
      )}
      aria-hidden
    />
  );
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
        "flex size-4 shrink-0 items-center justify-center rounded-xs border border-border-strong bg-surface",
        "transition-all duration-200 ease-out",
        "hover:border-primary/60",
        "data-[checked]:border-primary data-[checked]:bg-primary data-[unchecked]:bg-surface",
        "data-[indeterminate]:border-primary data-[indeterminate]:bg-primary",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-border-strong",
        className,
      )}
      {...props}
    >
      <BaseCheckbox.Indicator className="flex text-primary-foreground data-[unchecked]:hidden">
        {props.indeterminate ? (
          <Minus className="size-3" strokeWidth={3} />
        ) : (
          <Check className="size-3" strokeWidth={3} />
        )}
      </BaseCheckbox.Indicator>
    </BaseCheckbox.Root>
  );
}

export function Switch({ className, ...props }: ComponentProps<typeof BaseSwitch.Root>): ReactNode {
  return (
    <BaseSwitch.Root
      className={cn(
        /*
         * `inline-flex`, not the default. Base UI's switch root computes to
         * `display: inline`, and width/height do not apply to a non-replaced inline
         * box -- so `h-5 w-9` were ignored and the control collapsed to its 16px
         * thumb wherever it was not already a flex child. It looked correct on the
         * notification preferences (a flex row blockifies its children) and rendered
         * as a stray vertical mark inside a plain table cell.
         */
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-border-strong bg-muted",
        "transition-colors duration-200 ease-out",
        "data-[checked]:border-primary data-[checked]:bg-primary",
        "disabled:cursor-not-allowed disabled:opacity-45",
        className,
      )}
      {...props}
    >
      <BaseSwitch.Thumb
        className={cn(
          "block size-4 translate-x-0.5 rounded-full bg-white shadow-sm",
          "transition-transform duration-200 ease-out data-[checked]:translate-x-[18px]",
        )}
      />
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
        // `overflow-y-hidden` is load-bearing. Setting only `overflow-x` computes the
        // other axis to `auto`, and the selected tab's `-mb-px` makes the content one
        // pixel taller than the box -- so a vertical scrollbar appeared on every tab
        // strip in the console, drawing arrow glyphs and eating 15px of width.
        "relative flex items-center gap-0.5 overflow-x-auto overflow-y-hidden border-b border-border-subtle",
        className,
      )}
      {...props}
    />
  );
}

/*
 * The selected tab is marked by a 2px rule sitting exactly on the list's own
 * border, so the two read as one line with a segment lit rather than as a
 * bar floating near a border.
 */
export function TabsTab({ className, ...props }: ComponentProps<typeof BaseTabs.Tab>): ReactNode {
  return (
    <BaseTabs.Tab
      className={cn(
        "-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2",
        "text-sm font-medium text-muted-foreground",
        "transition-all duration-200 ease-out",
        "hover:border-border-strong hover:text-foreground",
        /*
         * Keyed on `aria-selected`, not `data-selected`.
         *
         * Base UI marks the active tab with `data-active`; there is no
         * `data-selected` attribute, so the previous selector matched nothing and
         * every tab strip in the console rendered with a transparent underline and
         * no selected state at all. `aria-selected` is the accessibility contract
         * rather than an implementation detail, so it survives a library rename.
         */
        "aria-selected:border-primary aria-selected:font-semibold aria-selected:text-foreground",
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

/**
 * Inverted against the page.
 *
 * `bg-foreground text-background` means the tooltip is dark on a light theme
 * and light on a dark one without a second rule: it is always the highest
 * contrast thing on screen, which is what makes it read as an annotation
 * rather than another panel.
 */
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
          <BaseTooltip.Popup
            className={cn(
              "max-w-xs rounded-md bg-foreground px-2 py-1 text-2xs font-medium text-background shadow-md",
              "data-[open]:animate-[lms-fade-in_120ms_ease-out]",
            )}
          >
            {content}
          </BaseTooltip.Popup>
        </BaseTooltip.Positioner>
      </BaseTooltip.Portal>
    </BaseTooltip.Root>
  );
}
