/**
 * How an audit row's client address and IP-estimated location are described.
 *
 * Every state says what is actually known. "No location" has five different
 * causes -- a row written before locations were captured, an address with no
 * public location by nature, a lookup that is not configured, one the
 * database cannot place, one that failed -- and an auditor needs to tell them
 * apart, because only some of them mean "this looks wrong".
 */

import type { AuditLocation, AuditLogResponse } from "@/lib/api/types";

type Origin = Pick<AuditLogResponse, "ip_address" | "ip_scope" | "location">;

/** "Dhaka, Dhaka Division, Bangladesh" -- the most specific parts known. */
export function placeName(location: AuditLocation | null | undefined): string | null {
  if (!location || location.status !== "OK") return null;
  const parts = [location.city, location.region, location.country].filter(
    (part, index, all): part is string => !!part && all.indexOf(part) === index,
  );
  return parts.length ? parts.join(", ") : location.country_code ?? null;
}

/** One line for a table cell. */
export function originSummary(row: Origin): string {
  const place = placeName(row.location);
  if (place) return place;
  return locationStatusText(row) ?? "—";
}

/** Why there is no place name, or null when there is one. */
export function locationStatusText(row: Origin): string | null {
  const location = row.location;
  if (!location) {
    if (row.ip_scope == null) {
      return row.ip_address ? "Not recorded (logged before locations were captured)" : null;
    }
    return null;
  }
  switch (location.status) {
    case "OK":
      return null;
    case "NOT_APPLICABLE":
      switch (row.ip_scope) {
        case "PRIVATE":
          return "Private network address: no public location";
        case "LOOPBACK":
          return "Same machine (loopback): no public location";
        case "RESERVED":
          return "Reserved address: no public location";
        default:
          return "Client address could not be determined";
      }
    case "NOT_FOUND":
      return "Address not in the location database";
    case "UNAVAILABLE":
      return "Location lookup not configured";
    case "ERROR":
      return "Location lookup failed";
    default:
      return "Location unknown";
  }
}

export function scopeLabel(scope: string | null | undefined): string | null {
  switch (scope) {
    case "PUBLIC":
      return "Public";
    case "PRIVATE":
      return "Private";
    case "LOOPBACK":
      return "Loopback";
    case "RESERVED":
      return "Reserved";
    case "UNAVAILABLE":
      return "Unknown";
    default:
      return null;
  }
}

/** "23.81, 90.41 (within about 20 km)" -- or null when no coordinates were given. */
export function coordinatesText(location: AuditLocation | null | undefined): string | null {
  if (!location || location.latitude == null || location.longitude == null) return null;
  const base = `${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`;
  return location.accuracy_km != null ? `${base} (within about ${location.accuracy_km} km)` : base;
}
