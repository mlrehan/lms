"use client";

import Link from "next/link";
import { useTheme } from "next-themes";
import { useQuery } from "@tanstack/react-query";
import {
  Bell,
  Check,
  Clock,
  LogOut,
  Mail,
  Menu,
  Monitor,
  Moon,
  PanelLeft,
  Sun,
  SunMoon,
  Sparkles,
  User as UserIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { api } from "@/lib/api/client";
import type { UnreadCountResponse } from "@/lib/api/types";
import { useSession, useSignOut } from "@/lib/auth/session";
import { useRealtime } from "@/lib/realtime";
import { useSidebarState } from "@/lib/sidebar-state";
import { useAIStore } from "@/lib/ai-store";
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
import { CountBadge } from "@/components/ui/count-badge";
import { GlobalSearch } from "@/components/shell/global-search";
import { TimeZoneMenu } from "@/components/shell/timezone-menu";
import { UserAvatar } from "@/components/domain/user-avatar";
import { cn } from "@/lib/utils";

/**
 * The count on a topbar icon.
 *
 * Positioned against the 36px button, not the 16px icon it sits over. Anchored to
 * the icon it was the same size as the thing it was annotating and covered about
 * three quarters of it -- a red disc where the mail glyph should be. Against the
 * button there is room for it to clip the icon's top-right corner and no more,
 * which is what a badge is supposed to do.
 *
 * Ringed in the canvas colour so it reads as sitting on top of the icon rather
 * than being punched through it.
 */
function UnreadDot({ count, label }: { count: number; label: string }): ReactNode {
  if (count <= 0) return null;
  return (
    <CountBadge
      count={count}
      // Nine is the most that fits on a 15px disc without the badge growing
      // over the icon it annotates. Anything larger abbreviates and is
      // revealed on hover or tap -- which is the whole reason this is a
      // shared component rather than two near-identical spans.
      max={9}
      label={label}
      side="bottom"
      className="absolute right-0.5 top-0.5"
      badgeClassName={cn(
        "flex h-[15px] min-w-[15px] items-center justify-center",
        "rounded-full bg-danger px-[3px] text-[9px] font-semibold leading-none text-danger-foreground",
        "ring-2 ring-background",
      )}
    />
  );
}

function useUnread(path: string, enabled: boolean, live: boolean): number {
  const { data } = useQuery({
    queryKey: ["unread", path],
    queryFn: () => api.get<UnreadCountResponse>(path),
    enabled,
    // Pushed now -- `useRealtime` invalidates this key the moment something
    // arrives. The poll stays as a backstop rather than the mechanism: a
    // stream can be down (realtime disabled, a proxy that eats it, a
    // reconnect in progress) and the badge must still be right eventually.
    // Five minutes when the stream is up, one when it is not.
    refetchInterval: live ? 300_000 : 60_000,
    staleTime: 30_000,
    // A tab that comes back to the foreground may have missed events while
    // the browser had the connection suspended.
    refetchOnWindowFocus: true,
  });
  return data?.unread ?? 0;
}

function ThemeMenu(): ReactNode {
  const { theme, setTheme } = useTheme();

  /*
   * The trigger shows a fixed icon rather than the current theme's.
   *
   * Mirroring the theme here would mean rendering an icon the server cannot
   * know, which needs a mounted flag, which means setting state from an
   * effect and a second render on every page load. The active choice is
   * marked inside the menu instead, where it is more useful anyway.
   */
  const options = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "Match system", icon: Monitor },
  ] as const;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="Appearance">
            <SunMoon />
          </Button>
        }
      />
      <DropdownMenuContent>
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        {options.map((option) => {
          const Icon = option.icon;
          return (
            <DropdownMenuItem key={option.value} onClick={() => setTheme(option.value)}>
              <Icon /> {option.label}
              {theme === option.value ? <Check className="ml-auto" /> : null}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar({ onOpenNav }: { onOpenNav: () => void }): ReactNode {
  const { user, permissions, roles } = useSession();
  const signOut = useSignOut();

  const canMessage = permissions.has("message.read");
  const canBeNotified = permissions.has("notification.read");
  // One connection for the whole app, opened here because the topbar is the
  // one component mounted on every signed-in screen.
  const { connected } = useRealtime(
    canMessage || canBeNotified,
    // The person's own chime setting, carried on the session so the first
    // notification of a visit already honours it.
    user?.notification_sound ?? "subtle",
  );

  const unreadMessages = useUnread("/messages/unread-count", canMessage, connected);
  const unreadNotifications = useUnread(
    "/notifications/unread-count",
    canBeNotified,
    connected,
  );

  const { collapsed, toggle } = useSidebarState();
  const openAiDrawer = useAIStore((state) => state.openDrawer);

  return (
    // `glass` rather than a near-opaque fill: at 95% the bar is effectively
    // solid and the blur is decorative. At 72% with saturation lifted, content
    // scrolling underneath stays legible as movement, which is the whole point
    // of a translucent bar.
    <header className="glass sticky top-0 z-30 flex h-14 items-center gap-2 border-b px-3 sm:px-4">
      {/* Mobile drawer button (< 768px) */}
      <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation" onClick={onOpenNav}>
        <Menu />
      </Button>

      {/* Desktop & tablet collapse toggle (>= 768px) */}
      <Button
        variant="ghost"
        size="icon"
        className="hidden md:flex text-muted-foreground hover:text-foreground"
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        onClick={toggle}
      >
        <PanelLeft className="size-4" />
      </Button>

      <div className="min-w-0 flex-1">
        <GlobalSearch />
      </div>

      <div className="flex items-center gap-0.5">
        {permissions.has("message.read") ? (
          <Link
            href="/messages"
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "relative")}
            aria-label={`Messages${unreadMessages ? `, ${unreadMessages} unread` : ""}`}
          >
            <Mail />
            <UnreadDot count={unreadMessages} label="unread messages" />
          </Link>
        ) : null}

        {permissions.has("notification.read") ? (
          <Link
            href="/notifications"
            className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "relative")}
            aria-label={`Notifications${unreadNotifications ? `, ${unreadNotifications} unread` : ""}`}
          >
            <Bell />
            <UnreadDot count={unreadNotifications} label="unread notifications" />
          </Link>
        ) : null}

        <Button
          variant="ghost"
          size="icon"
          className="text-primary hover:text-primary hover:bg-primary/10 relative"
          aria-label="Open AI Assistant"
          title="AI Assistant (Ctrl+J)"
          onClick={() => openAiDrawer()}
        >
          <Sparkles className="size-4" />
        </Button>
        <TimeZoneMenu />
        <ThemeMenu />

        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <button
                type="button"
                className="ml-1 flex items-center gap-2 rounded-md px-1.5 py-1 transition-all duration-200 ease-out hover:bg-muted data-[popup-open]:bg-muted"
                aria-label="Account menu"
              >
                <UserAvatar name={user?.full_name ?? user?.username} src={user?.profile_picture} size="sm" />
                <span className="hidden max-w-32 truncate text-[13px] font-medium sm:inline">
                  {user?.full_name || user?.username}
                </span>
              </button>
            }
          />
          <DropdownMenuContent className="min-w-56">
            <div className="px-2.5 py-2">
              <p className="truncate text-[13px] font-semibold tracking-tight">{user?.full_name || user?.username}</p>
              {user?.email ? (
                <p className="truncate text-2xs text-subtle-foreground">{user.email}</p>
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
