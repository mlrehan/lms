import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forwardableRequestHeaders, forwardableResponseHeaders, refreshTokens } from "./upstream";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.LMS_API_URL = "http://api.test/api/v1";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

function tokenResponse(suffix: string): Response {
  return new Response(
    JSON.stringify({
      access_token: `access-${suffix}`,
      refresh_token: `refresh-${suffix}`,
      expires_in: 900,
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

describe("refreshTokens", () => {
  /**
   * The reason this function is not a plain `fetch`.
   *
   * The backend rotates refresh tokens and treats a second presentation of
   * an already-used one as theft, revoking the whole family. A page that
   * fires six queries at once, each getting a 401 and each refreshing
   * independently, would therefore sign the user out rather than recover.
   */
  it("makes one upstream call for concurrent callers holding the same token", async () => {
    let calls = 0;
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    globalThis.fetch = vi.fn(async () => {
      calls += 1;
      await gate;
      return tokenResponse("1");
    }) as unknown as typeof fetch;

    const inFlight = [
      refreshTokens("shared-token"),
      refreshTokens("shared-token"),
      refreshTokens("shared-token"),
    ];
    release?.();
    const results = await Promise.all(inFlight);

    expect(calls).toBe(1);
    for (const result of results) {
      expect(result?.access_token).toBe("access-1");
    }
  });

  it("does not share a refresh between two different tokens", async () => {
    let calls = 0;
    globalThis.fetch = vi.fn(async () => {
      calls += 1;
      return tokenResponse(String(calls));
    }) as unknown as typeof fetch;

    await Promise.all([refreshTokens("token-a"), refreshTokens("token-b")]);
    expect(calls).toBe(2);
  });

  it("allows a later refresh after the first finishes", async () => {
    let calls = 0;
    globalThis.fetch = vi.fn(async () => {
      calls += 1;
      return tokenResponse(String(calls));
    }) as unknown as typeof fetch;

    await refreshTokens("same");
    await refreshTokens("same");
    expect(calls).toBe(2);
  });

  it("reports failure as null rather than throwing", async () => {
    globalThis.fetch = vi.fn(
      async () => new Response("nope", { status: 401 }),
    ) as unknown as typeof fetch;
    await expect(refreshTokens("dead")).resolves.toBeNull();
  });

  it("treats a malformed success body as a failure", async () => {
    globalThis.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ access_token: "only-half" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ) as unknown as typeof fetch;
    await expect(refreshTokens("half")).resolves.toBeNull();
  });

  it("does not pin a failed attempt for the life of the process", async () => {
    let calls = 0;
    globalThis.fetch = vi.fn(async () => {
      calls += 1;
      return calls === 1 ? new Response("no", { status: 401 }) : tokenResponse("recovered");
    }) as unknown as typeof fetch;

    expect(await refreshTokens("retry")).toBeNull();
    expect((await refreshTokens("retry"))?.access_token).toBe("access-recovered");
  });
});

describe("header forwarding", () => {
  it("never forwards the browser's cookies upstream", () => {
    // The session cookies belong to this origin. The API neither needs them
    // nor should ever see the refresh token they carry.
    const headers = forwardableRequestHeaders(
      new Headers({
        cookie: "lms_rt=secret-refresh-token",
        authorization: "Bearer stale",
        host: "console.test",
        "content-type": "application/json",
        "x-request-id": "abc",
      }),
    );
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("host")).toBeNull();
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("x-request-id")).toBe("abc");
  });

  it("does not let the API set cookies on this origin", () => {
    const headers = forwardableResponseHeaders(
      new Headers({ "set-cookie": "sneaky=1", "content-type": "text/csv" }),
    );
    expect(headers.get("set-cookie")).toBeNull();
    expect(headers.get("content-type")).toBe("text/csv");
  });
});

describe("upstream timeout", () => {
  /**
   * The failure this exists to prevent: with no bound, a backend that stops
   * responding leaves the console on a spinner indefinitely. Observed at 118
   * seconds during development before this was added.
   */
  it("gives up when the API never starts responding", async () => {
    process.env.LMS_API_TIMEOUT_MS = "50";
    vi.resetModules();
    const { fetchUpstream, UpstreamTimeout } = await import("./upstream");

    globalThis.fetch = vi.fn(
      (_input: unknown, init?: { signal?: AbortSignal }) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    ) as unknown as typeof fetch;

    await expect(fetchUpstream("http://api.test/slow")).rejects.toBeInstanceOf(UpstreamTimeout);
    delete process.env.LMS_API_TIMEOUT_MS;
  });

  it("lets a response through once its headers arrive", async () => {
    process.env.LMS_API_TIMEOUT_MS = "5000";
    vi.resetModules();
    const { fetchUpstream } = await import("./upstream");

    globalThis.fetch = vi.fn(async () => new Response("ok", { status: 200 })) as unknown as typeof fetch;
    const response = await fetchUpstream("http://api.test/fast");
    expect(response.status).toBe(200);
    delete process.env.LMS_API_TIMEOUT_MS;
  });

  it("reports a connection refusal as itself, not as a timeout", async () => {
    vi.resetModules();
    const { fetchUpstream, UpstreamTimeout } = await import("./upstream");
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;

    await expect(fetchUpstream("http://api.test/down")).rejects.not.toBeInstanceOf(UpstreamTimeout);
  });
});
