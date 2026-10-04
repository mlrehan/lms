import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BatchPicker, CoursePicker } from "./entity-pickers";

/**
 * These pickers replaced `Select`s fed by `limit: 200`, which could not be
 * typed into and silently omitted the 201st row. So what matters here is not
 * that a list renders — it is that **the typed term reaches the server**, that
 * a preset value can still name itself, and that the read permission each
 * screen used to check for itself is still checked now that the control owns
 * the query.
 */

const sessionMock = vi.hoisted(() => ({ granted: [] as readonly string[] }));
vi.mock("@/lib/auth/session", async () => {
  const actual = await import("@/lib/auth/permissions");
  return { useSession: () => ({ permissions: actual.permissionSet(sessionMock.granted) }) };
});

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api: apiMock }));

interface Call {
  path: string;
  query?: Record<string, unknown>;
}

function calls(): Call[] {
  return apiMock.get.mock.calls.map(([path, options]) => ({
    path: path as string,
    query: (options as { query?: Record<string, unknown> } | undefined)?.query,
  }));
}

function renderPicker(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  apiMock.get.mockReset();
  sessionMock.granted = ["batch.read", "course.read"];
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/batches") {
      return Promise.resolve({
        items: [
          { public_id: "b1", batch_code: "PY-01", course_title: "Python", is_active: true },
          { public_id: "b2", batch_code: "JS-02", course_title: "JavaScript", is_active: true },
        ],
        total: 2,
      });
    }
    if (path === "/batches/b9") {
      return Promise.resolve({
        public_id: "b9",
        batch_code: "ARCHIVED-09",
        course_title: "Old course",
        is_active: false,
      });
    }
    if (path === "/courses") {
      return Promise.resolve({
        items: [{ public_id: "c1", title: "Python Fundamentals", code: "PY", level: "BEGINNER" }],
        total: 1,
      });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
});

describe("BatchPicker", () => {
  it("sends the typed term to the server rather than filtering a fetched page", async () => {
    const user = userEvent.setup();
    renderPicker(<BatchPicker value={null} onValueChange={() => {}} />);

    await waitFor(() => expect(calls().some((c) => c.path === "/batches")).toBe(true));
    // The list is fetched small, not in bulk: the point of searching server
    // side is that the whole catalogue never has to arrive.
    expect(calls().find((c) => c.path === "/batches")?.query).toMatchObject({ limit: 20 });

    await user.click(screen.getByRole("combobox"));
    await user.keyboard("JS");

    // `q` is this endpoint's parameter name; `/courses` uses `query`, and the
    // picker absorbs that inconsistency so no screen has to know it.
    await waitFor(
      () => expect(calls().some((c) => c.path === "/batches" && c.query?.q === "JS")).toBe(true),
      { timeout: 2000 },
    );
  });

  it("names a preset value the current search does not return", async () => {
    renderPicker(<BatchPicker value="b9" onValueChange={() => {}} />);
    // Without the single-row lookup this field shows a UUID where a batch code
    // belongs, which is the whole reason the control exists.
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue("ARCHIVED-09"));
    expect(calls().some((c) => c.path === "/batches/b9")).toBe(true);
  });

  it("asks for nothing, and says so, without batch.read", async () => {
    sessionMock.granted = ["course.read"];
    renderPicker(<BatchPicker value={null} onValueChange={() => {}} />);

    // Every screen that used to build its own option list gated that query on
    // `batch.read`. Folding the gate into the control has to keep that, or
    // moving it would have added a request that 403s on nine pages.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls().some((c) => c.path.startsWith("/batches"))).toBe(false);
    const field = screen.getByRole("combobox");
    expect(field).toBeDisabled();
    expect(field).toHaveAttribute("placeholder", "You cannot browse batches");
  });
});

describe("CoursePicker", () => {
  it("uses this endpoint's own search parameter", async () => {
    const user = userEvent.setup();
    renderPicker(<CoursePicker value={null} onValueChange={() => {}} />);

    await waitFor(() => expect(calls().some((c) => c.path === "/courses")).toBe(true));
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("Py");

    await waitFor(
      () => expect(calls().some((c) => c.path === "/courses" && c.query?.query === "Py")).toBe(true),
      { timeout: 2000 },
    );
  });

  it("hands back the chosen row, not just its id", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    renderPicker(<CoursePicker value={null} onValueChange={onValueChange} />);

    await user.click(screen.getByRole("combobox"));
    // Callers need the row itself -- the new-batch dialog suggests a batch code
    // from the course's `code` and prefills its duration.
    await user.click(await screen.findByRole("option", { name: /Python Fundamentals/i }));
    expect(onValueChange).toHaveBeenCalledWith(
      "c1",
      expect.objectContaining({ public_id: "c1", code: "PY" }),
    );
  });

  it("asks for nothing without course.read", async () => {
    sessionMock.granted = ["batch.read"];
    renderPicker(<CoursePicker value={null} onValueChange={() => {}} />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls().some((c) => c.path.startsWith("/courses"))).toBe(false);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
