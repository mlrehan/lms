/**
 * Best-effort locale and timezone discovery (spec §53).
 *
 * The database stores UTC. What varies is *display*, and the honest default
 * for that is the viewer's own timezone. Three sources, in descending order
 * of reliability:
 *
 *  1. The account's stored `timezone`, if the user has set one -- resolved by
 *     the client, not here, because only it knows who is signed in.
 *  2. The browser's own `Intl.DateTimeFormat().resolvedOptions().timeZone`,
 *     which is accurate and needs no network call at all.
 *  3. This endpoint, which asks `icanhazip.com` for the public IP and
 *     `ipapi.co` what that IP implies.
 *
 * (3) exists because the spec asks for it, and it is deliberately last: it
 * involves telling two third parties an IP address, and behind a proxy or in
 * local development the IP it discovers is the *server's*, not the viewer's.
 * The response says which address was used so a wrong answer is diagnosable
 * rather than mysterious.
 *
 * The lookup happens server-side so the browser never contacts either
 * service directly, and no user identifier is ever sent to them.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

interface LocaleHint {
  ip: string | null;
  timezone: string | null;
  country_code: string | null;
  country_name: string | null;
  locale: string | null;
  source: "client-ip" | "egress-ip" | "unavailable";
}

const CACHE_TTL_MS = 60 * 60 * 1000;
const cache = new Map<string, { at: number; value: LocaleHint }>();

/** RFC1918 / loopback / link-local. A private address tells ipapi nothing. */
function isPublicIpv4(ip: string): boolean {
  const parts = ip.split(".").map((p) => Number.parseInt(p, 10));
  if (parts.length !== 4 || parts.some((p) => Number.isNaN(p) || p < 0 || p > 255)) return false;
  const [a = 0, b = 0] = parts;
  if (a === 10 || a === 127 || a === 0) return false;
  if (a === 172 && b >= 16 && b <= 31) return false;
  if (a === 192 && b === 168) return false;
  if (a === 169 && b === 254) return false;
  return true;
}

function clientIp(request: NextRequest): string | null {
  const forwarded = request.headers.get("x-forwarded-for");
  const candidate = forwarded?.split(",")[0]?.trim() ?? request.headers.get("x-real-ip")?.trim();
  if (candidate && isPublicIpv4(candidate)) return candidate;
  return null;
}

/**
 * A descriptive User-Agent, which is not optional here.
 *
 * `ipapi.co` answers **429 RateLimited** to requests carrying Node's default
 * user agent (or none at all) and 200 to the same request with a real one.
 * Without this the lookup failed silently on every call: the route returned
 * the IP it had found and null for everything else, which looks exactly like
 * "this IP has no known location".
 */
const USER_AGENT = "LMS-Console/1.0 (+timezone-discovery)";

async function fetchJson(url: string, timeoutMs = 4000): Promise<unknown | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      headers: { "user-agent": USER_AGENT, accept: "application/json" },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Record<string, unknown>;
    // ipapi also reports refusal *inside* a 200 body, so the status alone is
    // not enough to decide the lookup worked.
    if (body && typeof body === "object" && body.error === true) return null;
    return body;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function fetchText(url: string, timeoutMs = 4000): Promise<string | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      headers: { "user-agent": USER_AGENT },
    });
    if (!response.ok) return null;
    return (await response.text()).trim();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function GET(request: NextRequest): Promise<NextResponse<LocaleHint>> {
  const unavailable: LocaleHint = {
    ip: null,
    timezone: null,
    country_code: null,
    country_name: null,
    locale: null,
    source: "unavailable",
  };

  const direct = clientIp(request);
  const source: LocaleHint["source"] = direct ? "client-ip" : "egress-ip";
  const ip = direct ?? (await fetchText("https://icanhazip.com"));
  if (!ip || !isPublicIpv4(ip)) return NextResponse.json(unavailable);

  const cached = cache.get(ip);
  if (cached && Date.now() - cached.at < CACHE_TTL_MS) {
    return NextResponse.json(cached.value);
  }

  const raw = await fetchJson(`https://ipapi.co/${encodeURIComponent(ip)}/json/`);
  if (!raw || typeof raw !== "object") return NextResponse.json({ ...unavailable, ip, source });

  const record = raw as Record<string, unknown>;
  const asString = (key: string): string | null =>
    typeof record[key] === "string" && record[key] ? (record[key] as string) : null;

  const value: LocaleHint = {
    ip,
    timezone: asString("timezone"),
    country_code: asString("country_code"),
    country_name: asString("country_name"),
    locale: asString("languages")?.split(",")[0] ?? null,
    source,
  };
  cache.set(ip, { at: Date.now(), value });
  return NextResponse.json(value);
}
