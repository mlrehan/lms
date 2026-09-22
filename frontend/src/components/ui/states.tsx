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

/*
 * Rows are staggered in width. Uniform full-width bars read as a striped
 * placeholder graphic; varied ones read as text that has not arrived, which
 * is what is actually happening.
 */
const SKELETON_WIDTHS = ["w-full", "w-11/12", "w-full", "w-9/12", "w-10/12", "w-8/12"];

export function LoadingState({ label = "Loading", rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div className="space-y-2.5 p-4" aria-busy aria-live="polite">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn("h-8", SKELETON_WIDTHS[index % SKELETON_WIDTHS.length])}
        />
      ))}
    </div>
  );
}

export function InlineSpinner({ className }: { className?: string }): ReactNode {
  return <Loader2 className={cn("size-4 animate-spin text-subtle-foreground", className)} />;
}

/**
 * An empty screen is an invitation to act, so it always has room for one.
 *
 * The icon sits in a bordered tile rather than a filled circle: the circle
 * is the decorative default, while a tile that matches the console's own
 * radius and hairline reads as part of the same system.
 */
export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  // ReactNode, not string: a table's empty message may already carry emphasis or a
  // filter value, and forcing it through `string` would strip that at the call site.
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}): ReactNode {
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
      <div
        className={cn(
          "flex size-11 items-center justify-center rounded-xl",
          "border border-border-subtle bg-surface-muted text-subtle-foreground shadow-xs",
          "[&_svg]:size-5",
        )}
        aria-hidden
      >
        {icon ?? <Inbox />}
      </div>
      <div className="space-y-1.5">
        <p className="font-display text-sm font-semibold tracking-tight text-foreground">{title}</p>
        {description ? (
          <p className="mx-auto max-w-sm text-xs leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="pt-0.5">{action}</div> : null}
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
        icon={<Lock />}
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
    return <EmptyState icon={<Ban />} title="Not found" description={api.message} />;
  }

  const offline = typeof navigator !== "undefined" && navigator.onLine === false;
  const icon = offline ? (
    <WifiOff />
  ) : api && api.status >= 500 ? (
    <ServerCrash />
  ) : (
    <AlertTriangle />
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
        <span className="space-y-1.5">
          <span className="block">{message}</span>
          {api?.code && api.code !== "UNKNOWN" ? (
            <span className="block font-mono text-2xs tracking-normal text-subtle-foreground">
              {api.code}
            </span>
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
  empty?: { title: ReactNode; description?: ReactNode; action?: ReactNode } | null;
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
