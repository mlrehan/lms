import { describe, expect, it, beforeEach, vi } from "vitest";
import { useSidebarState } from "./sidebar-state";

describe("useSidebarState", () => {
  beforeEach(() => {
    localStorage.clear();
    useSidebarState.setState({ collapsed: false, hydrated: false });
  });

  it("toggles collapsed state and updates localStorage", () => {
    expect(useSidebarState.getState().collapsed).toBe(false);

    useSidebarState.getState().toggle();
    expect(useSidebarState.getState().collapsed).toBe(true);
    expect(localStorage.getItem("lms.sidebar_collapsed")).toBe("true");

    useSidebarState.getState().toggle();
    expect(useSidebarState.getState().collapsed).toBe(false);
    expect(localStorage.getItem("lms.sidebar_collapsed")).toBe("false");
  });

  it("explicitly sets collapsed state", () => {
    useSidebarState.getState().setCollapsed(true);
    expect(useSidebarState.getState().collapsed).toBe(true);
    expect(localStorage.getItem("lms.sidebar_collapsed")).toBe("true");

    useSidebarState.getState().setCollapsed(false);
    expect(useSidebarState.getState().collapsed).toBe(false);
    expect(localStorage.getItem("lms.sidebar_collapsed")).toBe("false");
  });

  it("defaults to collapsed on small screens (< 1280px)", () => {
    vi.stubGlobal("innerWidth", 1024);
    useSidebarState.getState().hydrate();
    expect(useSidebarState.getState().collapsed).toBe(true);
    expect(useSidebarState.getState().hydrated).toBe(true);
  });

  it("defaults to expanded on large screens (>= 1280px)", () => {
    vi.stubGlobal("innerWidth", 1440);
    useSidebarState.getState().hydrate();
    expect(useSidebarState.getState().collapsed).toBe(false);
    expect(useSidebarState.getState().hydrated).toBe(true);
  });

  it("respects saved preference over screen width on hydration", () => {
    localStorage.setItem("lms.sidebar_collapsed", "false");
    vi.stubGlobal("innerWidth", 1024); // small screen
    useSidebarState.getState().hydrate();
    expect(useSidebarState.getState().collapsed).toBe(false); // honors saved preference
  });
});

