/**
 * Date and time display (spec section 53).
 *
 * **The database stores UTC and the API returns UTC.** Nothing here changes
 * that; this module only decides how an instant is *shown*. Every format call
 * names a timezone explicitly rather than relying on the machine's default,
 * because "the server's timezone" and "the viewer's timezone" are different
 * questions and a default silently answers the wrong one during SSR.
 *
 * Formatting goes through `Intl.DateTimeFormat`, not a date library, because
 * it is the only implementation that knows the IANA database -- including the
 * DST transition that makes "add 5 hours" wrong twice a year.
 */

export const EMPTY = "—";

/**
 * The API returns UTC instants; some columns carry a trailing `Z` and some do
 * not. A string with no offset is UTC by the backend's own contract, so it is
 * marked as such before parsing. Left alone, JavaScript reads it as *local*
 * time and the entire display is wrong by the viewer's offset, which looks
 * like a data problem rather than a parsing one.
 */
export function parseApiInstant(value: string | Date | null | undefined): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const hasTime = trimmed.includes("T") || trimmed.includes(" ");
  const normalised = hasTime && !hasZone ? `${trimmed.replace(" ", "T")}Z` : trimmed;
  const parsed = new Date(normalised);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** A date-only value (`1998-04-21`) has no instant and no timezone. */
export function parseApiDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

export interface FormatOptions {
  timeZone: string;
  locale?: string;
}

const cache = new Map<string, Intl.DateTimeFormat>();

function formatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let existing = cache.get(key);
  if (!existing) {
    existing = new Intl.DateTimeFormat(locale, options);
    cache.set(key, existing);
  }
  return existing;
}

export function formatDateTime(
  value: string | Date | null | undefined,
  { timeZone, locale = "en-GB" }: FormatOptions,
): string {
  const date = parseApiInstant(value);
  if (!date) return EMPTY;
  return formatter(locale, {
    timeZone,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDate(
  value: string | Date | null | undefined,
  { timeZone, locale = "en-GB" }: FormatOptions,
): string {
  const date = parseApiInstant(value);
  if (!date) return EMPTY;
  return formatter(locale, {
    timeZone,
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(date);
}

/** For a date-only column, where applying a timezone would shift the day. */
export function formatCalendarDate(value: string | null | undefined, locale = "en-GB"): string {
  const date = parseApiDate(value);
  if (!date) return EMPTY;
  return formatter(locale, { year: "numeric", month: "short", day: "2-digit" }).format(date);
}

export function formatTime(
  value: string | Date | null | undefined,
  { timeZone, locale = "en-GB" }: FormatOptions,
): string {
  const date = parseApiInstant(value);
  if (!date) return EMPTY;
  return formatter(locale, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 60 * 60 * 1000],
  ["month", 30 * 24 * 60 * 60 * 1000],
  ["week", 7 * 24 * 60 * 60 * 1000],
  ["day", 24 * 60 * 60 * 1000],
  ["hour", 60 * 60 * 1000],
  ["minute", 60 * 1000],
];

export function formatRelative(
  value: string | Date | null | undefined,
  locale = "en-GB",
  now: Date = new Date(),
): string {
  const date = parseApiInstant(value);
  if (!date) return EMPTY;
  const diff = date.getTime() - now.getTime();
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, ms] of RELATIVE_UNITS) {
    if (Math.abs(diff) >= ms) return rtf.format(Math.round(diff / ms), unit);
  }
  return rtf.format(Math.round(diff / 1000), "second");
}

/** `Europe/London` -> `Europe / London (GMT+1)`, for the timezone picker. */
export function describeTimeZone(timeZone: string, at: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone,
      timeZoneName: "shortOffset",
    }).formatToParts(at);
    const offset = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    const label = timeZone.replace(/_/g, " ").replace("/", " / ");
    return offset ? `${label} (${offset})` : label;
  } catch {
    return timeZone;
  }
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone });
    return true;
  } catch {
    return false;
  }
}

/**
 * `datetime-local` inputs carry no timezone: they read and write a wall-clock
 * string. These two convert between that and the UTC instant the API wants,
 * anchored to the display timezone -- so a tutor scheduling "09:00" in
 * Europe/London sends 08:00Z in summer and 09:00Z in winter, which is what
 * they meant both times.
 */
export function toLocalInputValue(
  value: string | Date | null | undefined,
  timeZone: string,
): string {
  const date = parseApiInstant(value);
  if (!date) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? "00";
  // Some engines render midnight as hour 24 under `hour12: false`.
  const hour = get("hour") === "24" ? "00" : get("hour");
  return `${get("year")}-${get("month")}-${get("day")}T${hour}:${get("minute")}`;
}

export function fromLocalInputValue(value: string, timeZone: string): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  const asUtc = Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
  );
  // The offset is measured at the candidate instant rather than at "now",
  // because the two differ across a DST boundary -- which is the whole reason
  // this is not `new Date(value)`.
  const offset = timeZoneOffsetMs(new Date(asUtc), timeZone);
  return new Date(asUtc - offset).toISOString();
}

function timeZoneOffsetMs(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(instant);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((p) => p.type === type)?.value ?? "0");
  const hour = get("hour") === 24 ? 0 : get("hour");
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    hour,
    get("minute"),
    get("second"),
  );
  return asUtc - instant.getTime();
}
