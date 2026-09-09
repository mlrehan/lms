"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Ban, Inbox, Loader2, Lock, ServerCrash, WifiOff } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * The four states every data-backed screen has to render, in one place.
 *
 * They are distinct on purpose. "No results for this filter", "you may not
 * see this", "the server is down" and "you are offline" need four different
 * next actions from the person reading them, and collapsing them into one
 * "Something went wrong" tells nobody what to do.
 */

export function LoadingState({ label = "Loading", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div className="space-y-3 p-4" aria-busy aria-live="polite">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  );
}

export function InlineSpinner({ className }: { className?: string }): ReactNode {
  return <Loader2 className={cn("size-4 animate-spin text-muted-foreground", className)} />;
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}): ReactNode {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="rounded-full bg-muted p-3 text-muted-foreground">
        {icon ?? <Inbox className="size-5" />}
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description ? (
          <p className="mx-auto max-w-md text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  context,
}: {
  error: unknown;
  onRetry?: () => void;
  context?: string;
}): ReactNode {
  const api = error instanceof ApiError ? error : null;

  if (api?.isForbidden) {
    return (
      <EmptyState
        icon={<Lock className="size-5" />}
        title="You do not have access to this"
        description={
          <>
            The server refused this request. {context ? `${context} ` : ""}If you believe you should
            have access, ask an administrator to review your roles.
          </>
        }
      />
    );
  }

  if (api?.isNotFound) {
    return (
      <EmptyState
        icon={<Ban className="size-5" />}
        title="Not found"
        description={api.message}
      />
    );
  }

  const offline = typeof navigator !== "undefined" && navigator.onLine === false;
  const icon = offline ? (
    <WifiOff className="size-5" />
  ) : api && api.status >= 500 ? (
    <ServerCrash className="size-5" />
  ) : (
    <AlertTriangle className="size-5" />
  );

  const message = offline
    ? "This browser is offline. The console will work again once the connection returns."
    : api
      ? api.message
      : "The request could not be completed.";

  return (
    <EmptyState
      icon={icon}
      title={offline ? "No connection" : "Something went wrong"}
      description={
        <span className="space-y-1">
          <span className="block">{message}</span>
          {api?.code && api.code !== "UNKNOWN" ? (
            <span className="block font-mono text-xs text-muted-foreground/80">{api.code}</span>
          ) : null}
        </span>
      }
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : null
      }
    />
  );
}

/**
 * The wrapper the screens actually use: one call covers loading, error and
 * empty, so no screen has to remember all three.
 */
export function QueryBoundary<T>({
  isLoading,
  error,
  data,
  onRetry,
  empty,
  children,
  loadingRows,
}: {
  isLoading: boolean;
  error: unknown;
  data: T | undefined;
  onRetry?: () => void;
  empty?: { title: string; description?: ReactNode; action?: ReactNode } | null;
  children: (data: T) => ReactNode;
  loadingRows?: number;
}): ReactNode {
  if (isLoading) return <LoadingState rows={loadingRows} />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (data === undefined) return <ErrorState error={null} onRetry={onRetry} />;
  const isEmptyList = Array.isArray(data) && data.length === 0;
  const isEmptyPage =
    typeof data === "object" &&
    data !== null &&
    "items" in data &&
    Array.isArray((data as { items: unknown[] }).items) &&
    (data as { items: unknown[] }).items.length === 0;
  if (empty && (isEmptyList || isEmptyPage)) {
    return <EmptyState title={empty.title} description={empty.description} action={empty.action} />;
  }
  return <>{children(data)}</>;
}
