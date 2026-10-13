import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ClassRecording } from "./class-recording";
import type { SessionRecordingResponse } from "@/lib/api/types";

/**
 * A class recorded on the provider used to leave an entitled viewer looking at
 * "No recording yet": the API withheld the link from anyone who could not edit
 * the session, and nothing else was offered in its place.
 *
 * So what is pinned here is the shape of the fix, and the part of it that
 * lives in the browser:
 *
 *  * the frame points at **our** path, so the browser sends the session cookie
 *    and the redirect behind it is authorised per request;
 *  * the provider's URL is nowhere in the page for a viewer who was not given
 *    it -- a leak would be invisible to a type error and to the eye, since the
 *    frame looks identical either way;
 *  * the player can take the whole screen, and is boxed to 16:9 until it does,
 *    which is the difference between "watchable on a phone" and a sliver;
 *  * a recording stored in the LMS still wins, and is still not downloadable.
 */

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({
  api: apiMock,
  apiPath: (path: string) => `/api/backend${path}`,
  segment: (value: string) => encodeURIComponent(value),
}));

const SESSION = "68e83716-269d-4c66-a910-90f7307622f2";
const PROVIDER = "https://example.zoom.us/rec/share/abc123.def456";

/** `waitFor` only retries on a throw, so a bare `querySelector` would return
 *  null on the first tick and be reported as a type error, not a timeout. */
async function settle<E extends Element>(find: () => E | null): Promise<E> {
  return waitFor(() => {
    const found = find();
    expect(found).not.toBeNull();
    return found as E;
  });
}

function show(recording: SessionRecordingResponse) {
  apiMock.get.mockResolvedValue(recording);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <ClassRecording sessionId={SESSION} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
});

describe("a recording that lives on the provider", () => {
  it("is framed from our own path, never the provider's URL", async () => {
    const { container } = show({ embed_url: `/sessions/${SESSION}/recording/embed` });

    const frame = await settle(() => container.querySelector("iframe"));
    expect(frame.getAttribute("src")).toBe(
      `/api/backend/sessions/${SESSION}/recording/embed`,
    );
    // The whole point of the indirection: a viewer who was not handed the
    // provider link cannot read it out of the page either.
    expect(container.innerHTML).not.toContain("zoom.us");
  });

  it("can take the whole screen, and is watchable at any width before it does", async () => {
    const { container } = show({ embed_url: `/sessions/${SESSION}/recording/embed` });

    const frame = await settle(() => container.querySelector("iframe"));
    expect(frame.hasAttribute("allowfullscreen")).toBe(true);
    expect(frame.getAttribute("allow")).toContain("fullscreen");
    // A frame with no intrinsic size collapses; the 16:9 box is what gives it
    // one on a phone as well as on a desktop.
    expect(frame.parentElement?.className).toContain("aspect-video");
  });

  it("still shows staff the link they set, as a link and not as the frame", async () => {
    const { container } = show({
      embed_url: `/sessions/${SESSION}/recording/embed`,
      external_url: PROVIDER,
    });

    const link = await screen.findByRole("link", { name: /staff only/i });
    expect(link).toHaveAttribute("href", PROVIDER);
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));

    // Holding the provider URL is not a reason to frame it: staff watch
    // through the same path everyone else does, so what they see is what the
    // class sees and the view is recorded the same way.
    const frame = await settle(() => container.querySelector("iframe"));
    expect(frame.getAttribute("src")).toBe(
      `/api/backend/sessions/${SESSION}/recording/embed`,
    );
  });
});

describe("a recording stored in the LMS", () => {
  it("plays through our own stream, with the save control withheld", async () => {
    const { container } = show({
      playback_url: `/sessions/${SESSION}/recording/stream`,
      mime_type: "video/mp4",
      name: "Class 4.mp4",
    });

    const video = await settle(() => container.querySelector("video"));
    expect(video.getAttribute("src")).toBe(
      `/api/backend/sessions/${SESSION}/recording/stream`,
    );
    expect(video.getAttribute("controlslist")).toContain("nodownload");
    // It wins outright: offering the provider frame as well would be a second,
    // weaker route to the same class.
    expect(container.querySelector("iframe")).toBeNull();
  });
});

describe("a class with nothing published", () => {
  it("says so, rather than rendering an empty player", async () => {
    const { container } = show({});
    expect(await screen.findByText(/no recording yet/i)).toBeInTheDocument();
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
  });
});
