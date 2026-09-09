/**
 * Server-side session storage.
 *
 * **The browser never holds a token.** Both the access and refresh tokens
 * live in `httpOnly` cookies that JavaScript cannot read, and every API call
 * goes through the same-origin proxy in `app/api/backend`, which attaches the
 * bearer header server-side. An XSS bug in this console can therefore make
 * requests as the user (nothing prevents that) but cannot *exfiltrate* a
 * credential that keeps working after the tab is closed.
 *
 * This is also why there is no `NEXT_PUBLIC_LMS_API_URL`: the browser has no
 * reason to know where the API lives, and telling it invites someone to call
 * the API directly with a token this design is built to withhold.
 */

import type { NextResponse } from "next/server";
import { isProduction } from "@/lib/env";

export const ACCESS_COOKIE = "lms_at";
export const REFRESH_COOKIE = "lms_rt";

/**
 * The refresh cookie's lifetime is a *ceiling*, not a claim about validity.
 * The backend issues a longer-lived refresh token when "remember me" is
 * ticked and is the only authority on whether one still works; the cookie
 * merely stops us keeping a value the server will certainly reject.
 */
const REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

type CookieOptions = Parameters<NextResponse["cookies"]["set"]>[2];

function baseOptions(): NonNullable<CookieOptions> {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
  };
}

export function writeSessionCookies(
  response: NextResponse,
  tokens: { access_token: string; refresh_token: string; expires_in: number },
): void {
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...baseOptions(),
    // Deliberately a little shorter than the token itself, so a request that
    // sets off with a cookie the proxy considers live is not routinely
    // rejected by the API a second later. The 401-then-refresh path still
    // exists and still works; this just stops it being the common case.
    maxAge: Math.max(tokens.expires_in - 15, 5),
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...baseOptions(),
    maxAge: REFRESH_MAX_AGE_SECONDS,
  });
}

export function clearSessionCookies(response: NextResponse): void {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE]) {
    response.cookies.set(name, "", { ...baseOptions(), maxAge: 0 });
  }
}
