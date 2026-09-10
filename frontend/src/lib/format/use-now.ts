"use client";

import { useSyncExternalStore } from "react";

/**
 * A clock that ticks without setting state from inside an effect.
 *
 * The obvious version -- `useState(null)` plus an effect that immediately
 * calls `setNow(new Date())` -- schedules a second render on mount for every
 * component that shows a time, and the React Compiler flags it. This uses the
 * mechanism React provides for exactly this: an external store, with a
 * *server* snapshot of `null` so the server renders nothing rather than a
 * time that is already wrong by the time the HTML arrives.
 *
 * The snapshot is bucketed to the tick interval so it is referentially stable
 * between ticks; `getSnapshot` returning a fresh object every call would make
 * React re-render forever.
 */
export function useNow(intervalMs = 30_000): Date | null {
  const bucket = useSyncExternalStore(
    (onChange) => {
      const timer = setInterval(onChange, intervalMs);
      return () => clearInterval(timer);
    },
    () => Math.floor(Date.now() / intervalMs),
    () => null,
  );

  return bucket === null ? null : new Date(bucket * intervalMs);
}
