import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UserPicker } from "./user-picker";

/**
 * What a caller who cannot look people up is shown.
 *
 * This used to degrade to a plain text field, on the reasoning that somebody
 * handed an id could still type it. Nobody is ever handed one -- a public id
 * appears on no screen a student can reach -- so what the fallback produced
 * was a free-text box whose contents went to the API as a `student_id`. The
 * API expects a uuid and answered **422**, and the list rendered its error
 * state, whose title is "Something went wrong". A single letter was enough,
 * and it broke Batches, Timetable and Attendance the same way.
 *
 * So the test is not "it looks different without the grant" -- it is that
 * **no text input exists**, because an input is the thing that can carry a
 * value the server will refuse.
 */

const sessionMock = vi.hoisted(() => ({ granted: [] as readonly string[] }));
vi.mock("@/lib/auth/session", async () => {
  const actual = await import("@/lib/auth/permissions");
  return { useSession: () => ({ permissions: actual.permissionSet(sessionMock.granted) }) };
});

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api: apiMock }));

function renderWith(granted: readonly string[]) {
  sessionMock.granted = granted;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <UserPicker role="STUDENT" value={null} onChange={() => undefined} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiMock.get.mockReset();
  apiMock.get.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
});

describe("without user.read", () => {
  it("renders no control at all", () => {
    const { container } = renderWith([]);
    expect(container.querySelector("input")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("asks the server for nothing", () => {
    // The old fallback made no request either, but it accepted keystrokes and
    // handed them to whatever screen it sat on. Pinned so a future "just show
    // a disabled box" does not quietly bring the 422 back.
    renderWith([]);
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});

describe("with user.read", () => {
  it("renders a real picker, so the absence above is about the grant", async () => {
    const { container } = renderWith(["user.read"]);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    expect(
      container.querySelector("input") ?? screen.queryByRole("combobox"),
    ).not.toBeNull();
  });

  it("searches people rather than filtering a page it already holds", async () => {
    renderWith(["user.read"]);
    await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
    const [path, options] = apiMock.get.mock.calls[0] as [string, { query?: Record<string, unknown> }];
    expect(path).toBe("/users");
    expect(options.query).toMatchObject({ role: "STUDENT", status: "ACTIVE" });
  });
});
