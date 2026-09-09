"use client";

import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/90",
        secondary:
          "bg-surface text-foreground border border-border-strong hover:bg-surface-muted",
        ghost: "text-foreground hover:bg-muted",
        danger: "bg-danger text-danger-foreground hover:bg-danger/90",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-10 px-5",
        icon: "size-9 p-0",
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
