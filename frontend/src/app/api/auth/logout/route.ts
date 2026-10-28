/**
 * Sign-out.
 *
 * `POST /auth/logout` needs **both** halves and neither is optional:
 *
 *  - a bearer token, because the route is authenticated like any other and
 *    resolves `current_user` from it;
 *  - the raw refresh token in the body, because that is what identifies
 *    *which* session to end, and the browser has never had it by design.
 *
 * Sending only the body -- which this route did at first -- gets a 401 from
 * the API. The cookies still clear, the console still returns to the sign-in
 * screen, and the session stays live in the database until it expires
 * naturally. It looks exactly like success. The `revoked` flag in the
 * response exists so it does not: it reports what the server actually did,
 * and it is what made the fault visible.
 *
 * The cookies are cleared whatever the API answers. If revocation failed,
 * keeping a credential in the browser makes that worse, not better.
 */

import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/env";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies } from "@/lib/server/session";
import { fetchUpstream, withClientAddress } from "@/lib/server/upstream";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const everywhere = request.nextUrl.searchParams.get("scope") === "all";

  let revoked = false;
  try {
    if (accessToken) {
      const headers: Record<string, string> = { authorization: `Bearer ${accessToken}` };
      const target = everywhere ? "logout-all" : "logout";
      let body: string | undefined;
      if (!everywhere) {
        headers["content-type"] = "application/json";
        body = JSON.stringify({ refresh_token: refreshToken ?? "" });
      }
      const upstream = await fetchUpstream(`${apiBaseUrl()}/auth/${target}`, {
        method: "POST",
        headers: withClientAddress(new Headers(headers), request.headers),
        body,
        cache: "no-store",
      });
      revoked = upstream.ok;
    }
  } catch {
    // An unreachable API cannot revoke anything; say so rather than claiming
    // a sign-out that did not happen.
    revoked = false;
  }

  const response = NextResponse.json({ ok: true, revoked });
  clearSessionCookies(response);
  return response;
}
