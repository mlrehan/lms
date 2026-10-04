"use client";

import type { ReactNode } from "react";
import { Check, Columns3, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

/**
 * "Columns" — show and hide a table's columns.
 *
 * A `DropdownMenu`, deliberately: this performs *actions* on the view rather
 * than choosing a value, which is the line the design system draws between a
 * menu and a `Select`. It is also why the items toggle on click and the menu
 * does not close, which a value selector would not do.
 */

export interface ColumnToggle {
  id: string;
  label: ReactNode;
  visible: boolean;
  /** Identity columns a table is unreadable without cannot be hidden. */
  locked?: boolean;
}

export function TableViewOptions({
  columns,
  onToggle,
  onReset,
  label = "Columns",
}: {
  columns: ColumnToggle[];
  onToggle: (id: string, visible: boolean) => void;
  onReset?: () => void;
  label?: string;
}): ReactNode {
  const hidden = columns.filter((column) => !column.visible).length;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="secondary" size="sm" className="gap-1.5">
            <Columns3 />
            {label}
            {hidden > 0 ? (
              <span className="rounded-xs bg-muted px-1 text-2xs tabular-nums">{hidden}</span>
            ) : null}
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuLabel>Shown in this table</DropdownMenuLabel>
        {columns.map((column) => (
          <DropdownMenuItem
            key={column.id}
            disabled={column.locked}
            // Base UI menu items fire `onClick`; `onSelect` is silently inert
            // (see components/ui/dropdown-menu.tsx).
            onClick={(event) => {
              // Keep the menu open: hiding four columns should not mean
              // reopening the menu four times.
              event.preventDefault();
              if (!column.locked) onToggle(column.id, !column.visible);
            }}
            className="gap-2"
          >
            <Check
              className={cn("size-4 shrink-0", column.visible ? "opacity-100" : "opacity-0")}
              aria-hidden
            />
            <span className="flex-1 truncate">{column.label}</span>
          </DropdownMenuItem>
        ))}
        {onReset && hidden > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onReset} className="gap-2">
              <RotateCcw /> Show all
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
