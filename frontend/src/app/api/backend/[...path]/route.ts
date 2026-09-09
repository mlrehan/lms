/**
 * The BFF proxy: `/api/backend/<anything>` -> `<LMS_API_URL>/<anything>`.
 *
 * Three jobs, and nothing else:
 *  1. Attach the bearer token server-side, so the browser never holds one.
 *  2. Refresh once on a 401 and retry, so an expired access token is
 *     invisible to the user rather than a spurious sign-out.
 *  3. Pass everything else through unchanged -- status, headers and body.
 *
 * The body is read as an `ArrayBuffer`, never `request.text()`. Decoding a
 * request as UTF-8 and re-encoding it replaces every byte that is not valid
 * UTF-8 with U+FFFD; multipart boundaries are ASCII, so the request stays
 * well-formed and the upload still "succeeds" -- with the file's contents
 * destroyed. Responses are streamed for the same reason, and so a CSV export
 * or a file download is not buffered whole in this process.
 */

import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/env";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies, writeSessionCookies } from "@/lib/server/session";
import {
  NULL_BODY_STATUSES,
  forwardableRequestHeaders,
  forwardableResponseHeaders,
  refreshTokens,
} from "@/lib/server/upstream";

export const dynamic = "force-dynamic";

/**
 * Paths where a 401 must NOT trigger a refresh-and-retry.
 *
 * `refresh` is self-evident. `logout` matters more than it looks: retrying it
 * would present the refresh token the first call just revoked, and the
 * backend reads a re-presented token as theft and kills the whole family --
 * so a harmless retry would turn signing out of one device into signing out
 * of all of them.
 */
const NEVER_REFRESH = ["auth/refresh", "auth/login", "auth/logout"];

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  const suffix = path.join("/");
  const target = new URL(`${apiBaseUrl()}/${suffix}`);
  target.search = request.nextUrl.search;

  const method = request.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();

  const accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  const send = async (token: string | undefined): Promise<Response> => {
    const headers = forwardableRequestHeaders(request.headers);
    if (token) headers.set("authorization", `Bearer ${token}`);
    return fetch(target, {
      method,
      headers,
      body: body && body.byteLength > 0 ? body : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  };

  let upstream = await send(accessToken);
  let rotated: Awaited<ReturnType<typeof refreshTokens>> = null;

  const mayRefresh = !NEVER_REFRESH.some((p) => suffix === p || suffix.startsWith(`${p}/`));
  if (upstream.status === 401 && refreshToken && mayRefresh) {
    // The first response's body is abandoned deliberately: we are about to
    // replace it, and leaving it unread keeps the connection from being
    // reused with a half-consumed stream.
    await upstream.body?.cancel();
    rotated = await refreshTokens(refreshToken);
    if (rotated) {
      upstream = await send(rotated.access_token);
    }
  }

  const isNullBody = NULL_BODY_STATUSES.has(upstream.status);
  const response = new NextResponse(isNullBody ? null : upstream.body, {
    status: upstream.status,
    headers: forwardableResponseHeaders(upstream.headers),
  });

  if (rotated) {
    writeSessionCookies(response, rotated);
  } else if (upstream.status === 401 && refreshToken && mayRefresh) {
    // The refresh was attempted and failed: the session is genuinely over.
    // Clearing here is what makes the client's "signed out" state agree with
    // the server's, rather than leaving a dead cookie to fail on every
    // subsequent request.
    clearSessionCookies(response);
  }

  return response;
}

type Context = { params: Promise<{ path: string[] }> };

async function handler(request: NextRequest, context: Context): Promise<NextResponse> {
  const { path } = await context.params;
  return proxy(request, path);
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const HEAD = handler;
