import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useRealtime } from "./realtime";

/**
 * The hook's job is narrow and entirely about consequences: when a frame
 * arrives, which cached queries stop being trusted. Getting that mapping wrong
 * produces a badge that never clears, which is the bug people actually report,
 * and it is invisible to a typecheck.
 *
 * `EventSource` does not exist in jsdom, so it is replaced with a fake that
 * records what was opened and lets a test deliver frames. That is the whole of
 * the browser API this hook uses.
 */

const toasts: string[] = [];
vi.mock("sonner", () => ({ toast: Object.assign((m: string) => void toasts.push(m), {}) }));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  onerror: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(kind: string, fn: (e: MessageEvent) => void): void {
    this.listeners.set(kind, [...(this.listeners.get(kind) ?? []), fn]);
  }

  close(): void {
    this.closed = true;
  }

  emit(kind: string, data: unknown): void {
    const event = { type: kind, data: JSON.stringify(data) } as MessageEvent;
    for (const fn of this.listeners.get(kind) ?? []) fn(event);
  }

  /** A frame whose body is not JSON, as a half-deployed format change produces. */
  emitRaw(kind: string, data: string): void {
    for (const fn of this.listeners.get(kind) ?? []) fn({ type: kind, data } as MessageEvent);
  }
}

function setup(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const view = renderHook(() => useRealtime(enabled), { wrapper });
  return { view, invalidate, source: () => FakeEventSource.instances.at(-1)! };
}

type InvalidateSpy = { mock: { calls: unknown[][] } };

function invalidatedKeys(spy: InvalidateSpy): string[] {
  return spy.mock.calls.map((call) =>
    JSON.stringify((call[0] as { queryKey: string[] }).queryKey),
  );
}

beforeEach(() => {
  FakeEventSource.instances = [];
  toasts.length = 0;
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useRealtime", () => {
  it("connects to the same-origin proxy, never the API directly", () => {
    // The browser holds no token by design; only the proxy can attach one.
    // A direct API URL would be unauthenticated *and* cross-origin.
    setup();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0]!.url).toBe("/api/backend/realtime/stream");
  });

  it("does not connect at all for someone with no inbox", () => {
    setup(false);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("reports connected only once the server says ready", async () => {
    // "Socket open" and "authenticated and subscribed" are different, and the
    // polling fallback backs off on this flag -- so guessing costs a stale badge.
    const { view, source } = setup();
    expect(view.result.current.connected).toBe(false);
    act(() => source().emit("ready", { kind: "ready" }));
    await waitFor(() => expect(view.result.current.connected).toBe(true));
  });

  it("a new message invalidates the badge, both message lists and the menu counts", () => {
    const { invalidate, source } = setup();
    act(() => source().emit("message.received", { kind: "message.received" }));
    expect(invalidatedKeys(invalidate)).toEqual([
      '["unread"]',
      '["mail","list"]',
      '["mail","unread"]',
      // The sidebar badge beside Messages is one of the counts, so a message
      // arriving has to move it without waiting for a navigation.
      '["sidebar-counts"]',
      // The dashboard counts unread items too. It was the one surface left
      // out, which is exactly why it was the one that needed a page refresh.
      '["dashboard"]',
    ]);
  });

  it("a new notification invalidates the badge, the feed and the menu counts", () => {
    const { invalidate, source } = setup();
    act(() => source().emit("notification.created", { kind: "notification.created", data: { title: "Grade recorded" } }));
    expect(invalidatedKeys(invalidate)).toEqual([
      '["unread"]',
      '["notifications","feed"]',
      // Almost everything that moves a badge also notifies somebody -- work
      // set, work graded, an exam scheduled -- so this is what keeps the
      // assessment counts live without a second event kind.
      '["sidebar-counts"]',
      '["dashboard"]',
    ]);
  });

  it("reading on another device clears the badge here", () => {
    const { invalidate, source } = setup();
    act(() => source().emit("message.updated", { kind: "message.updated" }));
    expect(invalidatedKeys(invalidate)).toContain('["unread"]');
  });

  it("shows the notification title the server composed", () => {
    const { source } = setup();
    act(() => source().emit("notification.created", { kind: "notification.created", data: { title: "Grade recorded" } }));
    expect(toasts).toEqual(["Grade recorded"]);
  });

  it("never invents a sender for a message toast", () => {
    // The server deliberately sends no name: who you may see the name of is
    // decided per reader. Anything here would be a guess rendered as fact.
    const { source } = setup();
    act(() => source().emit("message.received", { kind: "message.received" }));
    expect(toasts).toEqual(["New message"]);
  });

  it("survives a frame it cannot parse", () => {
    // A malformed frame is a server bug or a half-deployed format change.
    // Throwing here would take down the connection for everything else.
    const { invalidate, source } = setup();
    act(() => source().emitRaw("message.received", "<!doctype html>"));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("closes the connection when the app unmounts", () => {
    // Otherwise signing out leaves a stream open against the previous session.
    const { view, source } = setup();
    const stream = source();
    view.unmount();
    expect(stream.closed).toBe(true);
  });
});

/**
 * Topic events -- the half the per-user channel could never carry.
 *
 * Nobody is notified when an administrator adds a batch, so before these
 * existed every badge counting batches stayed wrong until the next refetch.
 * What is worth protecting here is not that an event arrives, but that a burst
 * of them does not turn into a refetch per event in every open browser.
 */
describe("useRealtime topic events", () => {
  it("refreshes the counts and the dashboard when academic data changes", () => {
    const { invalidate, source } = setup();
    act(() =>
      source().emit("data.changed", { kind: "data.changed", topic: "academic" }),
    );
    expect(invalidatedKeys(invalidate)).toEqual(['["sidebar-counts"]', '["dashboard"]']);
  });

  it("refreshes only the presence list when somebody arrives", () => {
    const { invalidate, source } = setup();
    act(() =>
      source().emit("data.changed", { kind: "data.changed", topic: "presence" }),
    );
    // Deliberately not the dashboard: a sign-in moves no KPI, and refetching
    // it would make every arrival cost every administrator a query for nothing.
    expect(invalidatedKeys(invalidate)).toEqual(['["presence"]']);
  });

  it("ignores a topic it does not recognise", () => {
    const { invalidate, source } = setup();
    act(() =>
      source().emit("data.changed", { kind: "data.changed", topic: "something-new" }),
    );
    // A newer server talking to an older console. Ignoring costs a late badge;
    // guessing would invalidate everything on every event.
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("ignores a topic frame with no topic at all", () => {
    const { invalidate, source } = setup();
    act(() => source().emit("data.changed", { kind: "data.changed" }));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("collapses a burst into one refetch instead of one per event", () => {
    vi.useFakeTimers();
    try {
      const { invalidate, source } = setup();

      // A sync importing courses: one transaction, and one frame, each.
      act(() => {
        for (let i = 0; i < 25; i += 1) {
          source().emit("data.changed", { kind: "data.changed", topic: "academic" });
        }
      });

      // Leading edge: the first one went straight through, so the screen is
      // live rather than waiting out a window.
      expect(invalidatedKeys(invalidate)).toEqual(['["sidebar-counts"]', '["dashboard"]']);

      // The remaining twenty-four collapse into a single trailing refetch.
      act(() => void vi.advanceTimersByTime(1_100));
      expect(invalidatedKeys(invalidate)).toEqual([
        '["sidebar-counts"]',
        '["dashboard"]',
        '["sidebar-counts"]',
        '["dashboard"]',
      ]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not throttle a personal event behind a topic burst", () => {
    vi.useFakeTimers();
    try {
      const { invalidate, source } = setup();
      act(() => {
        source().emit("data.changed", { kind: "data.changed", topic: "academic" });
        source().emit("data.changed", { kind: "data.changed", topic: "academic" });
        // One recipient, rare, and a chime that arrives before its badge
        // looks broken -- so personal events bypass the throttle entirely.
        source().emit("message.received", { kind: "message.received" });
      });
      expect(invalidatedKeys(invalidate)).toContain('["mail","list"]');
    } finally {
      vi.useRealTimers();
    }
  });

  it("drops a pending refetch when the hook unmounts", () => {
    vi.useFakeTimers();
    try {
      const { view, invalidate, source } = setup();
      act(() => {
        source().emit("data.changed", { kind: "data.changed", topic: "academic" });
        source().emit("data.changed", { kind: "data.changed", topic: "academic" });
      });
      const before = invalidate.mock.calls.length;

      view.unmount();
      // A trailing timer that survived would fire against a QueryClient this
      // component no longer belongs to.
      act(() => void vi.advanceTimersByTime(5_000));
      expect(invalidate.mock.calls.length).toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });
});
