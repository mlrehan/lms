/**
 * Sign-in. The one route that receives a password, and the only one that
 * ever sees a token in a response body -- which it moves straight into
 * `httpOnly` cookies and does not pass on.
 *
 * The password is read, forwarded and discarded. It is never logged, never
 * stored, and never placed in a URL.
 */

import { NextRequest, NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/env";
import { writeSessionCookies } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { code: "VALIDATION_ERROR", message: "Expected a JSON body." },
      { status: 400 },
    );
  }

  const upstream = await fetch(`${apiBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  const text = await upstream.text();
  if (!upstream.ok) {
    // Forwarded verbatim: the backend deliberately answers a bad password
    // and an unknown account identically, and rewording it here risks
    // reintroducing the account-enumeration difference it avoids.
    return new NextResponse(text, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }

  const tokens = JSON.parse(text) as {
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
  };
  if (!tokens.access_token || !tokens.refresh_token) {
    return NextResponse.json(
      { code: "INTERNAL_ERROR", message: "The sign-in service returned an unexpected response." },
      { status: 502 },
    );
  }

  const response = NextResponse.json({ ok: true });
  writeSessionCookies(response, {
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    expires_in: tokens.expires_in ?? 900,
  });
  return response;
}
