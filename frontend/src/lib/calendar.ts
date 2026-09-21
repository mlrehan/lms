/**
 * Calendar arithmetic for the schedule view.
 *
 * Everything is done on *calendar-date keys* ("2026-09-21") in the viewer's display time zone, never
 * on local `Date` objects: a session at 23:30 UTC belongs to the next day in London in summer, and a
 * grid built from the browser's own zone would put it on the wrong square for anyone whose display
 * zone differs from the machine's.
 */

import { fromLocalInputValue, parseApiInstant } from "@/lib/format/datetime";

const keyFormatters = new Map<string, Intl.DateTimeFormat>();

/** The calendar date an instant falls on in `timeZone`, as `YYYY-MM-DD`. */
export function dayKey(value: string | Date, timeZone: string): string {
  const date = typeof value === "string" ? parseApiInstant(value) : value;
  if (!date) return "";
  let formatter = keyFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
    keyFormatters.set(timeZone, formatter);
  }
  return formatter.format(date);
}

function parts(key: string): [number, number, number] {
  const [y = 1970, m = 1, d = 1] = key.split("-").map(Number);
  return [y, m, d];
}

export function addDays(key: string, days: number): string {
  const [y, m, d] = parts(key);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

export function addMonths(key: string, months: number): string {
  const [y, m] = parts(key);
  return new Date(Date.UTC(y, m - 1 + months, 1)).toISOString().slice(0, 10);
}

export function startOfMonth(key: string): string {
  return `${key.slice(0, 7)}-01`;
}

/** 0 = Monday ... 6 = Sunday. The week starts on Monday, as it does in the UK. */
export function weekdayIndex(key: string): number {
  const [y, m, d] = parts(key);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export interface MonthGrid {
  /** Always 6 rows of 7, so the grid does not jump in height between months. */
  days: string[];
  /** The first of the month being shown. */
  month: string;
  /** UTC instants bounding the grid, ready to send as `from` / `to`. */
  from: string;
  to: string;
}

export function monthGrid(anchor: string, timeZone: string): MonthGrid {
  const month = startOfMonth(anchor);
  const first = addDays(month, -weekdayIndex(month));
  const days = Array.from({ length: 42 }, (_, i) => addDays(first, i));
  const firstDay = days[0] ?? first;
  const lastDay = days[41] ?? first;
  return {
    days,
    month,
    from: fromLocalInputValue(`${firstDay}T00:00`, timeZone) ?? `${firstDay}T00:00:00Z`,
    to: fromLocalInputValue(`${addDays(lastDay, 1)}T00:00`, timeZone) ?? `${addDays(lastDay, 1)}T00:00:00Z`,
  };
}

/** A stable hue per batch, so the same batch is the same colour everywhere without storing one. */
export function batchHue(code: string): number {
  let hash = 0;
  for (let i = 0; i < code.length; i += 1) hash = (hash * 31 + code.charCodeAt(i)) >>> 0;
  return hash % 360;
}
