"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GraduationCap, X } from "lucide-react";
import type { ReactNode } from "react";
import { NAVIGATION } from "@/lib/navigation";
import { useSession } from "@/lib/auth/session";
import { Button } from "@/components/ui/button";
import { HelpNavItem } from "@/components/help/help-nav-item";
import { cn } from "@/lib/utils";

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }): ReactNode {
  const pathname = usePathname();
  const { permissions, roles } = useSession();

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
    <nav className="flex h-full flex-col gap-6 overflow-y-auto scrollbar-thin px-3 py-4" aria-label="Main">
      {sections.map((section) => (
        <div key={section.label} className="space-y-1">
          <p className="eyebrow px-2.5 pb-0.5">{section.label}</p>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const active = isActive(pathname, item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    /*
                     * The rail sits on the canvas, so the selected item is the one
                     * thing on it rendered as a raised surface -- a chip pulled out
                     * of the nav rather than a coloured pill painted onto it. The
                     * icon carries the accent; the label stays foreground, because
                     * tinting both makes the row read as a link rather than a place.
                     */
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
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      {/*
        The user guide. Chosen from the roles the *server* reports, not from
        what the sidebar happens to render: the guide somebody needs follows
        from who they are, and a person with no screens at all still needs to
        be able to read about signing in. Nothing is shown for a role whose
        guide is not written yet, because a link to an empty guide is worse
        than no link.
      */}
      <HelpNavItem roles={roles} onNavigate={onNavigate} />

      {sections.length === 0 ? (
        <p className="px-2.5 text-xs leading-relaxed text-muted-foreground">
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
  return (
    <>
      <aside className="hidden w-60 shrink-0 border-r border-border-subtle bg-background lg:block">
        <div className="flex h-14 items-center gap-2.5 border-b border-border-subtle px-4">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-xs shadow-[inset_0_1px_0_0_rgb(255_255_255_/_0.16)]">
            <GraduationCap className="size-4" />
          </div>
          <span className="font-display text-sm font-semibold tracking-tight">LMS Console</span>
        </div>
        <div className="h-[calc(100dvh-3.5rem)]">
          <SidebarContent />
        </div>
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
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
              <SidebarContent onNavigate={onMobileClose} />
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
