"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GraduationCap, X } from "lucide-react";
import type { ReactNode } from "react";
import { NAVIGATION } from "@/lib/navigation";
import { useSession } from "@/lib/auth/session";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }): ReactNode {
  const pathname = usePathname();
  const { permissions } = useSession();

  const sections = NAVIGATION.map((section) => ({
    ...section,
    items: section.items.filter((item) => {
      if (item.anyPermission) return permissions.hasAny(...item.anyPermission);
      if (!item.permission) return true;
      return permissions.has(item.permission);
    }),
  })).filter((section) => section.items.length > 0);

  return (
    <nav className="flex h-full flex-col gap-5 overflow-y-auto scrollbar-thin px-3 py-4" aria-label="Main">
      {sections.map((section) => (
        <div key={section.label} className="space-y-1">
          <p className="px-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {section.label}
          </p>
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
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-accent font-medium text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    <span className="truncate">{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      {sections.length === 0 ? (
        <p className="px-2.5 text-sm text-muted-foreground">
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
      <aside className="hidden w-60 shrink-0 border-r border-border bg-surface lg:block">
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <GraduationCap className="size-4" />
          </div>
          <span className="text-sm font-semibold tracking-tight">LMS Console</span>
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
            className="absolute inset-0 bg-black/40"
            onClick={onMobileClose}
          />
          <div className="relative flex h-full w-64 flex-col border-r border-border bg-surface">
            <div className="flex h-14 items-center justify-between border-b border-border px-4">
              <span className="text-sm font-semibold">LMS Console</span>
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
