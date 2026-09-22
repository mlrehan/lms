"use client";

import type { ComponentProps, ReactNode } from "react";
import { Menu } from "@base-ui/react/menu";
import { cn } from "@/lib/utils";

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;
export const DropdownMenuGroup = Menu.Group;

export function DropdownMenuContent({
  className,
  align = "end",
  sideOffset = 6,
  children,
  ...props
}: ComponentProps<typeof Menu.Popup> & {
  align?: "start" | "center" | "end";
  sideOffset?: number;
}): ReactNode {
  return (
    <Menu.Portal>
      <Menu.Positioner align={align} sideOffset={sideOffset} className="z-50 outline-none">
        <Menu.Popup
          className={cn(
            "min-w-48 origin-(--transform-origin) rounded-lg border border-border-subtle bg-overlay p-1",
            "shadow-overlay",
            "data-[open]:animate-[lms-fade-in_120ms_ease-out] data-[closed]:animate-[lms-fade-out_100ms_ease-in]",
            className,
          )}
          {...props}
        >
          {children}
        </Menu.Popup>
      </Menu.Positioner>
    </Menu.Portal>
  );
}

/**
 * **This is Base UI, not Radix: the handler is `onClick`, and there is no
 * `onSelect` prop.**
 *
 * The trap is that `onSelect` *is* a real DOM handler on a `<div>` (the text
 * selection event), so `MenuItemProps` -- which extends the div's props --
 * accepts it, TypeScript stays silent, and the function is spread onto the
 * element and never called. The menu item is then simply inert, and nothing
 * anywhere reports a problem.
 *
 * Icons sit at 70% until the row is highlighted, so a long menu reads as a
 * list of words with supporting marks rather than a column of competing
 * glyphs.
 */
export function DropdownMenuItem({
  className,
  destructive = false,
  ...props
}: ComponentProps<typeof Menu.Item> & { destructive?: boolean }): ReactNode {
  return (
    <Menu.Item
      className={cn(
        "flex cursor-default select-none items-center gap-2.5 rounded-md px-2 py-1.5",
        "text-sm font-medium text-muted-foreground outline-none",
        "transition-colors duration-150 ease-out",
        "data-[highlighted]:bg-muted data-[highlighted]:text-foreground",
        "data-[disabled]:pointer-events-none data-[disabled]:opacity-45",
        "[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:opacity-70 data-[highlighted]:[&_svg]:opacity-100",
        destructive &&
          "text-danger data-[highlighted]:bg-danger/10 data-[highlighted]:text-danger",
        className,
      )}
      {...props}
    />
  );
}

/**
 * A caption above a run of menu items.
 *
 * A plain element, **not** `Menu.GroupLabel`. Base UI's group label reads
 * `MenuGroupContext` and throws outright -- "Menu group parts must be used within
 * <Menu.Group>" -- if it is not inside one, which is what made the appearance menu
 * in the topbar raise an uncaught error every time it opened. A caption that
 * crashes unless its caller remembers a wrapper is a trap, so the default is the
 * safe one; use `DropdownMenuGroupLabel` inside `DropdownMenuGroup` when the
 * grouping really is semantic and you want the `aria-labelledby` association.
 */
export function DropdownMenuLabel({
  className,
  ...props
}: ComponentProps<"div">): ReactNode {
  return <div role="presentation" className={cn("eyebrow px-2 pb-1 pt-2", className)} {...props} />;
}

/** The accessible label for a real `DropdownMenuGroup`. Throws outside one, by design. */
export function DropdownMenuGroupLabel({
  className,
  ...props
}: ComponentProps<typeof Menu.GroupLabel>): ReactNode {
  return <Menu.GroupLabel className={cn("eyebrow px-2 pb-1 pt-2", className)} {...props} />;
}

export function DropdownMenuSeparator({ className }: { className?: string }): ReactNode {
  return <Menu.Separator className={cn("-mx-1 my-1 h-px bg-border-subtle", className)} />;
}
