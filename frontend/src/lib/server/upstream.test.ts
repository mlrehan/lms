import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clientAddress, forwardableRequestHeaders, forwardableResponseHeaders, refreshTokens } from "./upstream";

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

describe("client address", () => {
  afterEach(() => {
    delete process.env.LMS_CLIENT_IP_HEADER;
  });

  it("never passes on an address the browser supplied", () => {
    const forwarded = forwardableRequestHeaders(
      new Headers({
        "x-forwarded-for": "6.6.6.6",
        "x-real-ip": "6.6.6.6",
        forwarded: "for=6.6.6.6",
        "cf-connecting-ip": "6.6.6.6",
        "true-client-ip": "6.6.6.6",
        accept: "application/json",
      }),
    );
    expect(forwarded.get("x-forwarded-for")).toBeNull();
    expect(forwarded.get("x-real-ip")).toBeNull();
    expect(forwarded.get("forwarded")).toBeNull();
    expect(forwarded.get("cf-connecting-ip")).toBeNull();
    expect(forwarded.get("accept")).toBe("application/json");
  });

  it("forwards the proxy-set address as the only X-Forwarded-For entry", () => {
    process.env.LMS_CLIENT_IP_HEADER = "x-real-ip";
    const forwarded = forwardableRequestHeaders(
      new Headers({ "x-real-ip": "103.170.173.46", "x-forwarded-for": "6.6.6.6, 103.170.173.46" }),
    );
    expect(forwarded.get("x-forwarded-for")).toBe("103.170.173.46");
  });

  it("accepts IPv6 and refuses anything that is not an address", () => {
    process.env.LMS_CLIENT_IP_HEADER = "x-real-ip";
    expect(clientAddress(new Headers({ "x-real-ip": "2a02:c204:2110:73::99" }))).toBe("2a02:c204:2110:73::99");
    expect(clientAddress(new Headers({ "x-real-ip": "evil.example" }))).toBeNull();
    expect(clientAddress(new Headers({ "x-real-ip": "1.2.3.4; drop" }))).toBeNull();
  });

  it("vouches for nothing when no proxy header is configured", () => {
    expect(clientAddress(new Headers({ "x-real-ip": "103.170.173.46" }))).toBeNull();
  });

  it("sends the browser's address with a server-side token refresh", async () => {
    process.env.LMS_CLIENT_IP_HEADER = "x-real-ip";
    const fetchMock = vi.fn(async () => tokenResponse("ip"));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await refreshTokens("ip-token", new Headers({ "x-real-ip": "103.170.173.46" }));
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(new Headers(init.headers).get("x-forwarded-for")).toBe("103.170.173.46");
  });
});
