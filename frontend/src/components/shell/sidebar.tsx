"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { GraduationCap, PanelLeft, PanelLeftClose, X } from "lucide-react";
import type { ReactNode } from "react";
import { NAVIGATION } from "@/lib/navigation";
import { useSession } from "@/lib/auth/session";
import { badgeFor, useSidebarCounts } from "@/lib/sidebar-counts";
import { useSidebarState } from "@/lib/sidebar-state";
import { CountBadge } from "@/components/ui/count-badge";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/primitives";
import { HelpNavItem } from "@/components/help/help-nav-item";
import { EditorNav } from "@/components/shell/editor-nav";
import { cn } from "@/lib/utils";

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarContent({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}): ReactNode {
  const pathname = usePathname();
  const { permissions, roles, user } = useSession();
  // One request for every badge, and not until there is a session to fetch
  // it for: the sidebar renders during loading and on the sign-in redirect,
  // and asking then is one guaranteed 401 per mount.
  const { data: counts } = useSidebarCounts(Boolean(user));

  const sections = NAVIGATION.map((section) => ({
    ...section,
    items: section.items.filter((item) => {
      if (item.anyPermission) return permissions.hasAny(...item.anyPermission);
      if (!item.permission) return true;
      if (!permissions.has(item.permission)) return false;
      // A second grant, where one cannot tell two audiences apart. See
      // `NavItem.alsoRequires`.
      return !item.alsoRequires || permissions.has(item.alsoRequires);
    }),
  })).filter((section) => section.items.length > 0);

  return (
    <nav
      className={cn(
        "flex h-full flex-col overflow-y-auto scrollbar-thin py-4 transition-all duration-200",
        collapsed ? "items-center gap-3 px-2" : "gap-6 px-3",
      )}
      aria-label="Main"
    >
      {sections.map((section, idx) => (
        <div key={section.label} className={cn("w-full space-y-1", collapsed && "flex flex-col items-center")}>
          {collapsed ? (
            idx > 0 ? <div className="my-1 h-px w-6 bg-border-subtle" /> : null
          ) : (
            <p className="eyebrow px-2.5 pb-0.5">{section.label}</p>
          )}
          <ul className={cn("space-y-0.5", collapsed && "w-full space-y-1 flex flex-col items-center")}>
            {section.items.map((item) => {
              const active = isActive(pathname, item.href);
              const Icon = item.icon;
              const count = badgeFor(item.href, counts);

              if (collapsed) {
                return (
                  <li key={item.href} className="flex justify-center">
                    <Tooltip content={item.label} side="right">
                      <Link
                        href={item.href}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        aria-label={item.label}
                        className={cn(
                          "group relative flex size-9 items-center justify-center rounded-md text-[13px]",
                          "transition-all duration-200 ease-out",
                          active
                            ? "bg-surface font-medium text-primary shadow-xs ring-1 ring-border-subtle"
                            : "font-normal text-muted-foreground hover:bg-surface/70 hover:text-foreground",
                        )}
                      >
                        <Icon
                          className={cn(
                            "size-4 shrink-0 transition-colors duration-200",
                            active ? "text-primary" : "text-subtle-foreground group-hover:text-muted-foreground",
                          )}
                          aria-hidden
                        />
                        {count !== undefined && count > 0 && (
                          <span
                            className={cn(
                              "absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px] font-bold leading-none ring-2 ring-background",
                              active ? "bg-primary text-primary-foreground" : "bg-danger text-danger-foreground",
                            )}
                          >
                            {count > 99 ? "99+" : count}
                          </span>
                        )}
                        <span className="sr-only">{item.label}</span>
                      </Link>
                    </Tooltip>
                  </li>
                );
              }

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px]",
                      "transition-all duration-200 ease-out",
                      active
                        ? "bg-surface font-medium text-foreground shadow-xs ring-1 ring-border-subtle"
                        : "font-normal text-muted-foreground hover:bg-surface/70 hover:text-foreground",
                    )}
                  >
                    <Icon
                      className={cn(
                        "size-4 shrink-0 transition-colors duration-200",
                        active ? "text-primary" : "text-subtle-foreground group-hover:text-muted-foreground",
                      )}
                      aria-hidden
                    />
                    <span className="truncate">{item.label}</span>
                    {(() => {
                      if (count === undefined) return null;
                      return (
                        <CountBadge
                          count={count}
                          max={999}
                          label="waiting"
                          className="ml-auto"
                          badgeClassName={cn(
                            active
                              ? "bg-primary/10 text-primary"
                              : "bg-surface-muted text-muted-foreground group-hover:text-foreground",
                          )}
                        />
                      );
                    })()}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <EditorNav enabled={Boolean(user)} onNavigate={onNavigate} collapsed={collapsed} />
      <HelpNavItem roles={roles} onNavigate={onNavigate} collapsed={collapsed} />

      {sections.length === 0 ? (
        <p className={cn("px-2.5 text-xs leading-relaxed text-muted-foreground", collapsed && "sr-only")}>
          Your account holds no permissions that open a screen here. Ask an
          administrator to review your roles.
        </p>
      ) : null}
    </nav>
  );
}

export function Sidebar({
  mobileOpen,
  onMobileClose,
}: {
  mobileOpen: boolean;
  onMobileClose: () => void;
}): ReactNode {
  const { collapsed, toggle, hydrate } = useSidebarState();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  return (
    <>
      <aside
        className={cn(
          "hidden shrink-0 border-r border-border-subtle bg-background transition-[width] duration-200 ease-in-out md:block",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center border-b border-border-subtle",
            collapsed ? "justify-center px-2" : "justify-between px-3.5",
          )}
        >
          {!collapsed ? (
            <>
              <Link href="/" className="flex items-center gap-2.5 min-w-0 group">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-xs shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.16)]">
                  <GraduationCap className="size-4" />
                </div>
                <span className="font-display text-sm font-semibold tracking-tight truncate group-hover:text-primary transition-colors">
                  LMS Console
                </span>
              </Link>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-muted-foreground hover:text-foreground"
                onClick={toggle}
                title="Collapse sidebar"
                aria-label="Collapse sidebar"
              >
                <PanelLeftClose className="size-4" />
              </Button>
            </>
          ) : (
            <Tooltip content="Expand sidebar" side="right">
              <Button
                variant="ghost"
                size="icon"
                className="size-9 text-muted-foreground hover:text-foreground"
                onClick={toggle}
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-xs shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.16)]">
                  <GraduationCap className="size-4" />
                </div>
              </Button>
            </Tooltip>
          )}
        </div>
        <div className="h-[calc(100dvh-3.5rem)]">
          <SidebarContent collapsed={collapsed} />
        </div>
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-950/30 backdrop-blur-[3px] dark:bg-slate-950/65"
            onClick={onMobileClose}
          />
          <div className="relative flex h-full w-64 flex-col border-r border-border-subtle bg-background shadow-overlay">
            <div className="flex h-14 items-center justify-between border-b border-border-subtle px-4">
              <span className="font-display text-sm font-semibold tracking-tight">LMS Console</span>
              <Button variant="ghost" size="icon" aria-label="Close" onClick={onMobileClose}>
                <X />
              </Button>
            </div>
            <div className="min-h-0 flex-1">
              <SidebarContent onNavigate={onMobileClose} collapsed={false} />
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
