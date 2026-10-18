"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2, Lock } from "lucide-react";
import Link from "next/link";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { EmptyState } from "@/components/ui/states";
import { Card, TooltipProvider } from "@/components/ui/primitives";
import { buttonVariants } from "@/components/ui/button";
import { useSession } from "@/lib/auth/session";
import { alsoRequiresForPath, permissionForPath } from "@/lib/navigation";

/**
 * The signed-in shell, and the route guard.
 *
 * **This guard is navigation, not security.** It decides which screen to
 * render; it does not decide what data anyone may read. Every request the
 * screens then make is authorised again by the API, which is the only place
 * the answer counts. Someone who edits their permission list in memory gets a
 * page full of 403s, not access.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { isLoading, isSignedOut, permissions, error } = useSession();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (isSignedOut) {
      const next = encodeURIComponent(pathname);
      router.replace(`/login?next=${next}`);
    }
  }, [isSignedOut, pathname, router]);

  // There is deliberately no effect closing the drawer on navigation: every
  // link inside it calls `onNavigate`, which closes it directly. An effect
  // here would set state during render for the same result.

  if (isLoading || isSignedOut) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
        <span className="sr-only">Loading your account</span>
      </div>
    );
  }

  if (error && !isSignedOut) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <EmptyState
          title="Could not load your account"
          description={error.message}
          action={
            <button
              type="button"
              className="text-sm font-medium text-primary underline-offset-4 hover:underline"
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
          }
        />
      </div>
    );
  }

  const required = permissionForPath(pathname);
  const alsoRequired = alsoRequiresForPath(pathname);
  const missing =
    (required && !permissions.has(required) ? required : undefined) ??
    (alsoRequired && !permissions.has(alsoRequired) ? alsoRequired : undefined);
  const allowed = !missing;

  return (
    <TooltipProvider>
      <div className="flex min-h-dvh bg-background">
        <Sidebar mobileOpen={navOpen} onMobileClose={() => setNavOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar onOpenNav={() => setNavOpen(true)} />
          <main className="min-w-0 flex-1 px-4 py-6 sm:px-6">
            {allowed ? (
              children
            ) : (
              /*
               * Somebody without the permission sees this instead of a screen, and on a
               * console where roles are narrow that is a lot of the navigation. Framed and
               * centred with a way out, because an unframed message floating at the top of
               * an otherwise blank page reads as a page that failed to load rather than as
               * an answer.
               */
              <div className="flex min-h-[60vh] items-center justify-center">
                <Card className="w-full max-w-md">
                  <EmptyState
                    icon={<Lock />}
                    title="You do not have access to this screen"
                    description={
                      <>
                        It needs the{" "}
                        <code className="rounded-xs bg-muted px-1 py-0.5 font-mono text-2xs text-foreground">
                          {missing}
                        </code>{" "}
                        permission, which your roles do not grant. Ask an administrator if you
                        need it.
                      </>
                    }
                    action={
                      <Link href="/" className={buttonVariants({ variant: "secondary", size: "sm" })}>
                        Back to dashboard
                      </Link>
                    }
                  />
                </Card>
              </div>
            )}
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
