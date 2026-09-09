"use client";

/**
 * Per-viewer display preferences.
 *
 * Deliberately *not* sent to the server. Timezone and locale change how this
 * browser renders an instant; they never change what is stored, and the
 * account's own `timezone` field remains the cross-device default. Keeping
 * the override local means a shared workstation does not silently rewrite a
 * colleague's profile.
 *
 * `localStorage` can throw outright (a browser configured to block site data,
 * a sandboxed frame) as well as simply return nothing, so every access is
 * guarded and the store renders correctly with no stored value.
 */

import { create } from "zustand";
import { browserTimeZone, isValidTimeZone } from "@/lib/format/datetime";

const TIMEZONE_KEY = "lms.timezone";
const LOCALE_KEY = "lms.locale";
const DENSITY_KEY = "lms.density";

export type Density = "comfortable" | "compact";

interface PreferencesState {
  /** `null` means "follow the account, then the browser". */
  timeZoneOverride: string | null;
  localeOverride: string | null;
  density: Density;
  /** Resolved once the account is known; see `useDisplayTimeZone`. */
  accountTimeZone: string | null;
  hydrated: boolean;

  setTimeZoneOverride: (timeZone: string | null) => void;
  setLocaleOverride: (locale: string | null) => void;
  setDensity: (density: Density) => void;
  setAccountTimeZone: (timeZone: string | null) => void;
  hydrate: () => void;
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // A viewer who blocks site data still gets a working console; they just
    // do not get their choice remembered. Failing the render instead would
    // trade a small convenience for the whole page.
  }
}

export const usePreferences = create<PreferencesState>((set) => ({
  timeZoneOverride: null,
  localeOverride: null,
  density: "comfortable",
  accountTimeZone: null,
  hydrated: false,

  setTimeZoneOverride: (timeZone) => {
    write(TIMEZONE_KEY, timeZone);
    set({ timeZoneOverride: timeZone });
  },
  setLocaleOverride: (locale) => {
    write(LOCALE_KEY, locale);
    set({ localeOverride: locale });
  },
  setDensity: (density) => {
    write(DENSITY_KEY, density);
    set({ density });
  },
  setAccountTimeZone: (timeZone) => set({ accountTimeZone: timeZone }),

  hydrate: () => {
    const stored = read(TIMEZONE_KEY);
    const locale = read(LOCALE_KEY);
    const density = read(DENSITY_KEY);
    set({
      timeZoneOverride: stored && isValidTimeZone(stored) ? stored : null,
      localeOverride: locale,
      density: density === "compact" ? "compact" : "comfortable",
      hydrated: true,
    });
  },
}));

/**
 * The precedence that actually applies, in order: an explicit choice in this
 * browser, then the account's stored timezone, then the browser's own.
 *
 * Server-rendered output uses UTC until hydration, because the server cannot
 * know any of the three -- and rendering the server's timezone would produce
 * a hydration mismatch *and* a wrong time.
 */
export function useDisplayTimeZone(): string {
  const { timeZoneOverride, accountTimeZone, hydrated } = usePreferences();
  if (!hydrated) return "UTC";
  if (timeZoneOverride) return timeZoneOverride;
  if (accountTimeZone && isValidTimeZone(accountTimeZone)) return accountTimeZone;
  return browserTimeZone();
}

export function useDisplayLocale(): string {
  const { localeOverride, hydrated } = usePreferences();
  if (!hydrated) return "en-GB";
  return localeOverride ?? "en-GB";
}
