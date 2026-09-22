"use client";

import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/*
 * The console's tactile vocabulary, set once here and echoed by every other
 * interactive surface (menu items, table rows, tabs).
 *
 * Hover shifts colour, never geometry. A button that grows on hover moves the
 * things next to it, and in a dense toolbar that reads as the layout being
 * unstable. `active:translate-y-px` is the one exception: a single pixel of
 * travel on press is the cheapest possible "this took your click".
 *
 * Solid variants carry a 1px inner top highlight. It is the difference
 * between a coloured rectangle and something that looks lit from above, and
 * it is what most flat-design buttons are missing.
 */
const buttonVariants = cva(
  [
    "group relative inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md",
    "font-medium tracking-normal",
    "transition-all duration-200 ease-out",
    "active:translate-y-px",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    "disabled:pointer-events-none disabled:opacity-45 disabled:shadow-none disabled:active:translate-y-0",
    "[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:transition-transform [&_svg]:duration-200",
  ],
  {
    variants: {
      variant: {
        primary: [
          "bg-primary text-primary-foreground shadow-xs",
          "shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.14)]",
          "hover:bg-primary-hover hover:shadow-sm",
        ],
        secondary: [
          "bg-surface text-foreground border border-border-strong shadow-xs",
          "hover:bg-surface-muted hover:border-slate-400/70 dark:hover:border-slate-500/70",
        ],
        ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
        danger: [
          "bg-danger text-danger-foreground shadow-xs",
          "shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.16)]",
          "hover:brightness-95 hover:shadow-sm",
        ],
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        xs: "h-7 gap-1 px-2 text-2xs [&_svg]:size-3.5",
        sm: "h-8 px-2.5 text-xs",
        md: "h-9 px-3.5 text-sm",
        lg: "h-10 px-5 text-sm",
        icon: "size-9 p-0",
        "icon-sm": "size-8 p-0 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, loading = false, disabled, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      // A submitting form must not be submittable again; leaving the button
      // live is how a duplicate enrollment or a double-charged action happens.
      disabled={disabled || loading}
      // `aria-busy` is what tells a screen reader the wait is deliberate.
      aria-busy={loading || undefined}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    >
      {loading ? <Loader2 className="animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
});

export { buttonVariants };

/**
 * A link that looks like a button.
 *
 * Deliberately a separate component rather than an `asChild`/`render` prop on
 * `Button`: a navigation is a link and must stay a real `<a>` so it opens in a
 * new tab on middle-click, is announced as a link, and works with the
 * keyboard the way the rest of the web does.
 */
export const LinkButton = forwardRef<
  HTMLAnchorElement,
  AnchorHTMLAttributes<HTMLAnchorElement> & VariantProps<typeof buttonVariants>
>(function LinkButton({ className, variant, size, ...props }, ref) {
  return (
    <a ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  );
});
