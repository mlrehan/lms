/** @vitest-environment node */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

/**
 * `POST /auth/logout` on the LMS API needs a bearer token *and* the raw
 * refresh token. Sending only the body gets a 401, and the failure is
 * invisible from the outside: the cookies still clear, the console still
 * returns to the sign-in screen, and the session stays live in the database
 * until it expires on its own.
 *
 * That is what this route did at first, and it was found by checking the
 * `tokens` table rather than by watching the browser. These tests pin the two
 * things that were wrong.
 */

const upstream = vi.hoisted(() => ({
  calls: [] as { url: string; init: RequestInit }[],
  ok: true,
}));

vi.mock("@/lib/server/upstream", () => ({
  fetchUpstream: async (url: string, init: RequestInit) => {
    upstream.calls.push({ url, init });
    return new Response(null, { status: upstream.ok ? 204 : 401 });
  },
}));

function requestWith(cookies: Record<string, string>, url = "http://console.test/api/auth/logout") {
  const request = new NextRequest(url, { method: "POST" });
  for (const [name, value] of Object.entries(cookies)) request.cookies.set(name, value);
  return request;
}

beforeEach(() => {
  process.env.LMS_API_URL = "http://api.test/api/v1";
  upstream.calls = [];
  upstream.ok = true;
});

afterEach(() => vi.resetModules());

describe("sign-out", () => {
  it("sends the bearer token, without which the API revokes nothing", async () => {
    const { POST } = await import("./route");
    await POST(requestWith({ lms_at: "access-abc", lms_rt: "refresh-xyz" }));

    expect(upstream.calls).toHaveLength(1);
    const headers = upstream.calls[0]!.init.headers as Record<string, string>;
    expect(headers.authorization).toBe("Bearer access-abc");
  });

  it("sends the raw refresh token, which says *which* session to end", async () => {
    const { POST } = await import("./route");
    await POST(requestWith({ lms_at: "access-abc", lms_rt: "refresh-xyz" }));

    expect(JSON.parse(upstream.calls[0]!.init.body as string)).toEqual({
      refresh_token: "refresh-xyz",
    });
  });

  it("reports what the server actually did, so a failure is not silent", async () => {
    const { POST } = await import("./route");

    upstream.ok = true;
    let body = await (await POST(requestWith({ lms_at: "a", lms_rt: "r" }))).json();
    expect(body).toEqual({ ok: true, revoked: true });

    upstream.ok = false;
    body = await (await POST(requestWith({ lms_at: "a", lms_rt: "r" }))).json();
    expect(body).toEqual({ ok: true, revoked: false });
  });

  it("clears both cookies even when revocation failed", async () => {
    upstream.ok = false;
    const { POST } = await import("./route");
    const response = await POST(requestWith({ lms_at: "a", lms_rt: "r" }));

    // Keeping a credential in the browser after a failed sign-out makes the
    // failure worse, not better.
    expect(response.cookies.get("lms_at")?.value).toBe("");
    expect(response.cookies.get("lms_rt")?.value).toBe("");
  });

  it("uses logout-all, with no body, for sign out everywhere", async () => {
    const { POST } = await import("./route");
    await POST(
      requestWith(
        { lms_at: "access-abc", lms_rt: "refresh-xyz" },
        "http://console.test/api/auth/logout?scope=all",
      ),
    );

    expect(upstream.calls[0]!.url).toContain("/auth/logout-all");
    expect(upstream.calls[0]!.init.body).toBeUndefined();
  });

  it("does not call the API at all without an access token", async () => {
    const { POST } = await import("./route");
    const response = await POST(requestWith({ lms_rt: "refresh-only" }));

    // Nothing to authenticate with, so the call would only ever be a 401.
    expect(upstream.calls).toHaveLength(0);
    expect(await response.json()).toEqual({ ok: true, revoked: false });
  });
});
