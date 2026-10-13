"use client";

/**
 * Who is signed in, and what they may do.
 *
 * `GET /auth/me` is the single source: it returns the caller's profile, their
 * role names, and their *effective* permissions after role resolution. The
 * console asks the server this question rather than deriving it from a token,
 * partly because the token is not readable here by design, and partly because
 * an access token issued ten minutes ago does not know that a role was
 * revoked five minutes ago.
 */

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api/client";
import { toast } from "sonner";
import type { CurrentUserResponse, LocaleRefreshResponse } from "@/lib/api/types";
import { permissionSet, type PermissionName, type PermissionSet } from "@/lib/auth/permissions";
import { usePreferences } from "@/lib/preferences";

export interface SessionValue {
  user: CurrentUserResponse | null;
  permissions: PermissionSet;
  roles: readonly string[];
  isLoading: boolean;
  /** True once we know for certain there is no usable session. */
  isSignedOut: boolean;
  error: ApiError | null;
  refetch: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export const CURRENT_USER_KEY = ["auth", "me"] as const;

const LOCALE_CHECK_EVERY_MS = 10 * 60_000;
const LOCALE_MIN_GAP_MS = 5 * 60_000;

/**
 * While the console is open, notice when the person's network address changes (a laptop moved from home to an
 * office, a VPN switched on) and let the server update where they are. Every check is one cheap request whose
 * answer is "same address" almost every time; only a *changed* address makes the server do a lookup. A time zone
 * the person chose themselves is never touched by this: the server only moves one it had filled in.
 */
function useLocaleWatcher(active: boolean): void {
  const queryClient = useQueryClient();
  const lastCheck = useRef(0);

  useEffect(() => {
    if (!active) return undefined;

    const check = async () => {
      if (Date.now() - lastCheck.current < LOCALE_MIN_GAP_MS) return;
      lastCheck.current = Date.now();
      try {
        const result = await api.post<LocaleRefreshResponse>("/auth/me/locale/refresh");
        if (result.ip_changed) {
          void queryClient.invalidateQueries({ queryKey: CURRENT_USER_KEY });
          if (result.timezone_changed && result.timezone) {
            toast.info(`Your location changed, so times now show in ${result.timezone.replace(/_/g, " ")}${result.city ? ` (${result.city})` : ""}.`);
          }
        }
      } catch {
        // A check that fails is simply skipped; the next one tries again.
      }
    };

    const onVisible = () => {
      if (document.visibilityState === "visible") void check();
    };
    const timer = window.setInterval(() => void check(), LOCALE_CHECK_EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [active, queryClient]);
}

export function SessionProvider({ children }: { children: ReactNode }): ReactNode {
  const setAccountTimeZone = usePreferences((s) => s.setAccountTimeZone);
  const hydrate = usePreferences((s) => s.hydrate);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // The Help Center is public: a reader with no account opens it from a link
  // somebody sent them. Asking the API who they are would be one guaranteed
  // 401 per page for a page that needs no session at all, so the question is
  // not asked there. Every other route still asks on mount as before.
  const pathname = usePathname();
  const needsSession = !pathname.startsWith("/help");

  const query: UseQueryResult<CurrentUserResponse, ApiError> = useQuery({
    queryKey: CURRENT_USER_KEY,
    queryFn: () => api.get<CurrentUserResponse>("/auth/me"),
    enabled: needsSession,
    // A 401 here is the answer, not a transient failure: retrying it wastes
    // three round trips before showing the sign-in screen.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && (error.isUnauthenticated || error.isForbidden)) &&
      failureCount < 2,
    staleTime: 60_000,
  });

  const accountTimeZone = query.data?.timezone ?? null;
  useEffect(() => {
    setAccountTimeZone(accountTimeZone);
  }, [accountTimeZone, setAccountTimeZone]);

  useLocaleWatcher(needsSession && query.data !== undefined);

  const value = useMemo<SessionValue>(() => {
    const user = query.data ?? null;
    return {
      user,
      permissions: permissionSet(user?.permissions),
      roles: user?.roles ?? [],
      isLoading: needsSession && query.isPending,
      isSignedOut: query.isError && (query.error as ApiError).isUnauthenticated,
      error: query.isError ? (query.error as ApiError) : null,
      refetch: () => void query.refetch(),
    };
  }, [needsSession, query]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside <SessionProvider>.");
  }
  return value;
}

/**
 * `can("user.create")` -- the only sanctioned way to branch on authority.
 *
 * Never `role === "ADMIN"`: an institution that adds a REGISTRAR role holding
 * `institution.view_all` and nothing else must not need a frontend change,
 * and a role-name comparison cannot express that.
 */
export function useCan(): (permission: PermissionName) => boolean {
  const { permissions } = useSession();
  return useMemo(() => (permission: PermissionName) => permissions.has(permission), [permissions]);
}

export function useSignOut(): (options?: { everywhere?: boolean }) => Promise<void> {
  const queryClient = useQueryClient();
  return async ({ everywhere = false } = {}) => {
    try {
      await fetch(`/api/auth/logout${everywhere ? "?scope=all" : ""}`, {
        method: "POST",
        credentials: "same-origin",
      });
    } finally {
      // Cleared regardless: whatever the server said, this browser no longer
      // holds a session, and leaving cached answers on screen would show a
      // signed-out person their own data.
      queryClient.clear();
      window.location.assign("/login");
    }
  };
}
