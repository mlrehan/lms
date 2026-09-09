"use client";

import Link from "next/link";
import { useTheme } from "next-themes";
import { useQuery } from "@tanstack/react-query";
import {
  Bell,
  Clock,
  LogOut,
  Mail,
  Menu,
  Monitor,
  Moon,
  Sun,
  User as UserIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api/client";
import type { UnreadCountResponse } from "@/lib/api/types";
import { useSession, useSignOut } from "@/lib/auth/session";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/primitives";
import { GlobalSearch } from "@/components/shell/global-search";
import { TimeZoneMenu } from "@/components/shell/timezone-menu";
import { cn } from "@/lib/utils";

function UnreadDot({ count }: { count: number }): ReactNode {
  if (count <= 0) return null;
  return (
    <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold leading-4 text-danger-foreground">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function useUnread(path: string, enabled: boolean): number {
  const { data } = useQuery({
    queryKey: ["unread", path],
    queryFn: () => api.get<UnreadCountResponse>(path),
    enabled,
    // Polled rather than pushed: this backend has no realtime channel, and a
    // badge that only updates on navigation is worse than one that lags a
    // minute. Stated plainly rather than dressed up as live.
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  return data?.unread ?? 0;
}

function ThemeMenu(): ReactNode {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="Appearance">
            {/* Before mount the resolved theme is unknown; rendering either
                icon then produces a hydration mismatch. */}
            {!mounted ? <Monitor /> : theme === "dark" ? <Moon /> : theme === "light" ? <Sun /> : <Monitor />}
          </Button>
        }
      />
      <DropdownMenuContent>
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuItem onClick={() => setTheme("light")}>
          <Sun /> Light
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("dark")}>
          <Moon /> Dark
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("system")}>
          <Monitor /> Match system
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar({ onOpenNav }: { onOpenNav: () => void }): ReactNode {
  const { user, permissions, roles } = useSession();
  const signOut = useSignOut();

  const unreadMessages = useUnread("/messages/unread-count", permissions.has("message.read"));
  const unreadNotifications = useUnread(
    "/notifications/unread-count",
    permissions.has("notification.read"),
  );

  const initials =
    (user?.full_name ?? user?.username ?? "?")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("") || "?";

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-surface/95 px-3 backdrop-blur sm:px-4">
      <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={onOpenNav}>
        <Menu />
      </Button>

      <div className="min-w-0 flex-1">
        <GlobalSearch />
      </div>

      <div className="flex items-center gap-0.5">
        {permissions.has("message.read") ? (
          <Link
            href="/messages"
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }))}
            aria-label={`Messages${unreadMessages ? `, ${unreadMessages} unread` : ""}`}
          >
            <span className="relative inline-flex">
              <Mail />
              <UnreadDot count={unreadMessages} />
            </span>
          </Link>
        ) : null}

        {permissions.has("notification.read") ? (
          <Link
            href="/notifications"
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }))}
            aria-label={`Notifications${unreadNotifications ? `, ${unreadNotifications} unread` : ""}`}
          >
            <span className="relative inline-flex">
              <Bell />
              <UnreadDot count={unreadNotifications} />
            </span>
          </Link>
        ) : null}

        <TimeZoneMenu />
        <ThemeMenu />

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button
                type="button"
                className="ml-1 flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-muted"
                aria-label="Account menu"
              >
                <span
                  className={cn(
                    "flex size-7 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground",
                  )}
                  aria-hidden
                >
                  {initials}
                </span>
                <span className="hidden max-w-32 truncate text-sm font-medium sm:inline">
                  {user?.full_name || user?.username}
                </span>
              </button>
            }
          />
          <DropdownMenuContent className="min-w-56">
            <div className="px-2.5 py-2">
              <p className="truncate text-sm font-medium">{user?.full_name || user?.username}</p>
              {user?.email ? (
                <p className="truncate text-xs text-muted-foreground">{user.email}</p>
              ) : null}
              <div className="mt-1.5 flex flex-wrap gap-1">
                {roles.map((role) => (
                  <Badge key={role} tone="primary">
                    {role}
                  </Badge>
                ))}
              </div>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem render={<Link href="/account" />}>
              <UserIcon /> My account
            </DropdownMenuItem>
            <DropdownMenuItem render={<Link href="/account/sessions" />}>
              <Clock /> Active sessions
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {/*
              Base UI fires `onClick`, not `onSelect`. `onSelect` is a real DOM
              handler on a div, so it type-checks and never runs -- which is
              how six menu items in a sibling project were silently inert.
            */}
            <DropdownMenuItem destructive onClick={() => void signOut()}>
              <LogOut /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
