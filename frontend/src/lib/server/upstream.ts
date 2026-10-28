/**
 * The single place this console talks to the LMS API.
 *
 * Refresh is serialised per refresh-token value. The backend rotates refresh
 * tokens and treats a second presentation of an already-used one as theft,
 * revoking the whole family -- so a page that fires six queries at once, each
 * getting a 401 and each refreshing independently, would sign the user out
 * rather than recover. Concurrent callers holding the same token share one
 * in-flight refresh instead.
 */

import { isIP } from "node:net";
import { apiBaseUrl } from "@/lib/env";

/**
 * How long the API has to *start* responding.
 *
 * The timeout is cleared the moment the response headers arrive, so it bounds
 * time-to-first-byte and leaves the body free to stream for as long as it
 * needs -- a large CSV export or a file download must not be cut off by the
 * same clock that catches an unresponsive server.
 *
 * Without this, `fetch` waits indefinitely: when the API was stopped
 * mid-request during development the console sat on "Loading your account"
 * for 118 seconds with no error, because nothing ever rejected. Failing at 30
 * seconds instead surfaces the error state, which says what happened and
 * offers a retry.
 */
export const UPSTREAM_HEADERS_TIMEOUT_MS = Number(
  process.env.LMS_API_TIMEOUT_MS ?? 30_000,
);

/**
 * `fetch`, bounded by time-to-first-byte rather than total duration.
 *
 * Throws `UpstreamTimeout` when the API does not begin responding in time, so
 * the caller can answer 504 instead of hanging or reporting a generic 500.
 */
export class UpstreamTimeout extends Error {
  constructor() {
    super(`The API did not respond within ${UPSTREAM_HEADERS_TIMEOUT_MS}ms.`);
    this.name = "UpstreamTimeout";
  }
}

export async function fetchUpstream(
  input: string | URL,
  init: RequestInit = {},
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_HEADERS_TIMEOUT_MS);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) throw new UpstreamTimeout();
    throw error;
  } finally {
    // Cleared as soon as the headers are in. The body streams unbounded from
    // here, which is the point.
    clearTimeout(timer);
  }
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const inFlight = new Map<string, Promise<Tokens | null>>();

export async function refreshTokens(refreshToken: string, client?: Headers): Promise<Tokens | null> {
  const existing = inFlight.get(refreshToken);
  if (existing) return existing;

  const attempt = (async (): Promise<Tokens | null> => {
    try {
      const response = await fetchUpstream(`${apiBaseUrl()}/auth/refresh`, {
        method: "POST",
        // The refresh is made on the browser's behalf, so its session row
        // records the browser's address, not this server's.
        headers: withClientAddress(new Headers({ "content-type": "application/json" }), client),
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      if (!response.ok) return null;
      const body = (await response.json()) as Partial<Tokens>;
      if (!body.access_token || !body.refresh_token) return null;
      return {
        access_token: body.access_token,
        refresh_token: body.refresh_token,
        expires_in: body.expires_in ?? 900,
      };
    } catch {
      // A refresh that cannot reach the API is not proof the session ended.
      // Returning null makes the caller report 401 and sign the user out,
      // which is the safe direction: the alternative is retrying a rotating
      // token, which is exactly what reuse detection punishes.
      return null;
    } finally {
      // Cleared in `finally` so a failed refresh does not pin a permanently
      // rejected promise in the map for the life of the process.
      inFlight.delete(refreshToken);
    }
  })();

  inFlight.set(refreshToken, attempt);
  return attempt;
}

/**
 * Headers that must not be forwarded upstream (hop-by-hop, or ours to set).
 * `cookie` is the important one: the browser's session cookies are for this
 * origin and mean nothing to the API -- forwarding them would leak the
 * refresh token to a service that never needed it.
 */
const STRIPPED_REQUEST_HEADERS = new Set([
  "connection",
  "content-length",
  "cookie",
  "host",
  "keep-alive",
  "authorization",
  "transfer-encoding",
  "upgrade",
]);

/**
 * Client-address headers a browser can simply send. None of them is passed
 * on as received: the API would otherwise record whatever address the caller
 * chose to claim. The one address this server vouches for is added back by
 * `withClientAddress`.
 */
const CLIENT_ADDRESS_HEADERS = new Set([
  "forwarded",
  "x-forwarded-for",
  "x-real-ip",
  "x-client-ip",
  "x-cluster-client-ip",
  "cf-connecting-ip",
  "true-client-ip",
  "fastly-client-ip",
]);

/**
 * The browser's address, as the reverse proxy in front of this server reported
 * it -- or null when there is no such proxy or it said nothing usable.
 *
 * `LMS_CLIENT_IP_HEADER` names the header that proxy *sets* (production:
 * nginx's `X-Real-IP $remote_addr`, which it overwrites, so a client cannot
 * supply it). It is only trustworthy because this server is reachable through
 * that proxy alone (bound to 127.0.0.1 in docker-compose.yml). Unset -- local
 * development, where the browser talks to this server directly -- nothing is
 * vouched for, and the API records the client as unknown rather than as this
 * server's own address.
 */
export function clientAddress(source: Headers): string | null {
  const header = process.env.LMS_CLIENT_IP_HEADER?.trim().toLowerCase();
  if (!header) return null;
  const raw = source.get(header);
  if (!raw) return null;
  // A single address is expected; if a list arrives, the entry the proxy
  // itself appended is the last one.
  const candidate = raw.split(",").pop()?.trim() ?? "";
  return isIP(candidate) ? candidate : null;
}

/** Add the one client address this server vouches for, as a single-entry X-Forwarded-For. */
export function withClientAddress(headers: Headers, source: Headers | undefined): Headers {
  const address = source ? clientAddress(source) : null;
  if (address) headers.set("x-forwarded-for", address);
  return headers;
}

export function forwardableRequestHeaders(source: Headers): Headers {
  const headers = new Headers();
  source.forEach((value, key) => {
    const name = key.toLowerCase();
    if (!STRIPPED_REQUEST_HEADERS.has(name) && !CLIENT_ADDRESS_HEADERS.has(name)) headers.set(key, value);
  });
  return withClientAddress(headers, source);
}

const STRIPPED_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "set-cookie",
  "transfer-encoding",
]);

export function forwardableResponseHeaders(source: Headers): Headers {
  const headers = new Headers();
  source.forEach((value, key) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });
  return headers;
}

/** Statuses whose response must carry no body at all. */
export const NULL_BODY_STATUSES = new Set([204, 205, 304]);
