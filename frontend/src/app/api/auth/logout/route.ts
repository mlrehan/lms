/**
 * Sign-out.
 *
 * The backend revokes a specific refresh-token family and needs the raw
 * token to do it -- which the browser has never had. So the token is read
 * from the cookie here. Sending a placeholder would clear the cookies, look
 * exactly like success, and leave the session valid in the database until it
 * expired naturally.
 *
 * The cookies are cleared whatever the backend answers: if revocation
 * failed, keeping a credential in the browser makes that worse, not better.
 */

import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/env";
import { REFRESH_COOKIE, clearSessionCookies } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  const everywhere = request.nextUrl.searchParams.get("scope") === "all";
  const accessToken = request.cookies.get("lms_at")?.value;

  let revoked = false;
  try {
    if (everywhere && accessToken) {
      const upstream = await fetch(`${apiBaseUrl()}/auth/logout-all`, {
        method: "POST",
        headers: { authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      });
      revoked = upstream.ok;
    } else if (refreshToken) {
      const upstream = await fetch(`${apiBaseUrl()}/auth/logout`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      revoked = upstream.ok;
    }
  } catch {
    revoked = false;
  }

  const response = NextResponse.json({ ok: true, revoked });
  clearSessionCookies(response);
  return response;
}
