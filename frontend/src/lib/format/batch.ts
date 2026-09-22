/**
 * Presentation helpers for a batch's schedule facts.
 *
 * Shared rather than duplicated: the batches table and the batch workspace both
 * show the delivery method, and when only one of them shortened it the same batch
 * read as "Online · Zoom" in the list and "Online Training using ..." (truncated)
 * on its own page.
 */

/**
 * "Classroom Training" -> "Classroom"; "Online Training using Zoom" -> "Online · Zoom".
 *
 * The method is a filter and a glance, not prose. Left whole it wraps to three lines
 * in a table row and truncates mid-word in a summary card; the full string belongs on
 * the element's `title`.
 */
export function shortMethod(method: string | null | undefined): string {
  const raw = (method ?? "").trim();
  if (!raw) return "";
  const platform = raw.match(/\b(zoom|teams|meet|webex|skype)\b/i)?.[1] ?? "";
  const base = raw
    .replace(/\busing\b[\s\S]*$/i, "")
    .replace(/\btraining\b/i, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  const label = base || raw;
  if (!platform) return label;
  return `${label} \u00b7 ${platform.charAt(0).toUpperCase()}${platform.slice(1).toLowerCase()}`;
}

/** `360` -> `"6h"`, `90` -> `"1h 30m"`. Empty for null, so a caller can fall back to a dash. */
export function durationLabel(minutes: number | null | undefined): string {
  if (!minutes) return "";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return [h ? `${h}h` : "", m ? `${m}m` : ""].filter(Boolean).join(" ");
}
