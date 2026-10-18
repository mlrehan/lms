"use client";

/**
 * A number that is small enough to sit beside a label, and honest about it.
 *
 * **The problem it solves.** A badge has to fit in a sidebar row or on a 36px
 * icon, so a large count gets abbreviated -- and "99+" tells somebody there is
 * a lot without telling them whether it is 100 or 4,000. Those are different
 * days.
 *
 * **Desktop**: hovering or focusing reveals the exact figure.
 *
 * **Touch**: there is no hover, so the badge takes the tap itself and shows the
 * exact figure instead of following the link underneath. That is a deliberate
 * exception to "the whole row navigates": the badge is a ~20px target inside a
 * much larger one, and somebody aiming at it specifically wants the number.
 * Tapping anywhere else on the row navigates exactly as before, and a second
 * tap on the badge dismisses the reveal.
 *
 * **Why a span and never a button.** These badges render *inside* `<Link>`.
 * A button inside an anchor is invalid HTML and hydrates inconsistently --
 * a trap this console has already hit once, in the tenant switcher. A span
 * carries no implicit interactive role, so nesting is legal; the exact count
 * reaches assistive technology through `aria-label` on every render, so a
 * screen reader never hears "99 plus" and never depends on the reveal at all.
 */

import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** How long a tapped reveal stays up before it tidies itself away. */
const REVEAL_MS = 2_500;

export interface CountBadgeProps {
  count: number;
  /** Above this, the badge abbreviates and the exact value needs revealing. */
  max?: number;
  /** What the number counts, for the accessible name: "3 unread messages". */
  label: string;
  /** The wrapper. The topbar positions its dot against the button with this. */
  className?: string;
  /** The pill itself. `twMerge` means these win over the defaults. */
  badgeClassName?: string;
  /** Where the reveal sits relative to the badge. */
  side?: "top" | "bottom";
}

export function CountBadge({
  count,
  max = 99,
  label,
  className,
  badgeClassName,
  side = "top",
}: CountBadgeProps): ReactNode {
  const [revealed, setRevealed] = useState(false);
  const [hovered, setHovered] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const id = useId();

  const abbreviated = count > max;
  const display = abbreviated ? `${max}+` : String(count);
  const exact = count.toLocaleString();

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const reveal = () => {
    if (timer.current) clearTimeout(timer.current);
    setRevealed(true);
    timer.current = setTimeout(() => setRevealed(false), REVEAL_MS);
  };

  // Only an abbreviated number needs revealing; a badge showing "7" already
  // shows everything it has, and making it swallow taps would break
  // navigation to no purpose.
  const interactive = abbreviated;
  const open = interactive && (hovered || revealed);

  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      <span
        // The exact figure, always, regardless of what is drawn. A screen
        // reader must not be told "99 plus".
        aria-label={`${exact} ${label}`}
        aria-describedby={open ? id : undefined}
        role="status"
        tabIndex={interactive ? 0 : undefined}
        className={cn(
          "min-w-[1.25rem] rounded-full px-1.5 py-0.5",
          "text-center text-[11px] font-medium leading-none tabular-nums",
          interactive && "cursor-default focus-visible:outline-2 focus-visible:outline-offset-2",
          "bg-surface-muted text-muted-foreground",
          badgeClassName,
        )}
        onPointerEnter={(event) => {
          // `pointerenter` fires for touch too, just before the tap. Only a
          // real hover should open on enter, or a tap would open it twice.
          if (event.pointerType === "mouse") setHovered(true);
        }}
        onPointerLeave={() => setHovered(false)}
        onFocus={() => interactive && setHovered(true)}
        onBlur={() => setHovered(false)}
        onClick={(event) => {
          if (!interactive) return;
          // The badge sits inside a link. Taking the click here is what makes
          // "tap the badge to see the number" possible at all; everything
          // around it still navigates.
          event.preventDefault();
          event.stopPropagation();
          if (revealed) {
            if (timer.current) clearTimeout(timer.current);
            setRevealed(false);
            return;
          }
          reveal();
        }}
      >
        {display}
      </span>
      {open ? (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap",
            "rounded-md bg-foreground px-2 py-1 text-2xs font-medium text-background shadow-md",
            side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
          )}
        >
          {exact} {label}
        </span>
      ) : null}
    </span>
  );
}
