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

import { apiBaseUrl } from "@/lib/env";

export interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const inFlight = new Map<string, Promise<Tokens | null>>();

export async function refreshTokens(refreshToken: string): Promise<Tokens | null> {
  const existing = inFlight.get(refreshToken);
  if (existing) return existing;

  const attempt = (async (): Promise<Tokens | null> => {
    try {
      const response = await fetch(`${apiBaseUrl()}/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json" },
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

export function forwardableRequestHeaders(source: Headers): Headers {
  const headers = new Headers();
  source.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });
  return headers;
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
