"use client";

import { create } from "zustand";

const SIDEBAR_COLLAPSED_KEY = "lms.sidebar_collapsed";

interface SidebarState {
  collapsed: boolean;
  hydrated: boolean;
  setCollapsed: (collapsed: boolean) => void;
  toggle: () => void;
  hydrate: () => void;
}

export const useSidebarState = create<SidebarState>((set, get) => ({
  collapsed: false,
  hydrated: false,

  setCollapsed: (collapsed: boolean) => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
    } catch {}
    set({ collapsed });
  },

  toggle: () => {
    const next = !get().collapsed;
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
    } catch {}
    set({ collapsed: next });
  },

  hydrate: () => {
    if (typeof window === "undefined") return;

    try {
      const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
      if (stored !== null) {
        set({ collapsed: stored === "true", hydrated: true });
        return;
      }
    } catch {}

    // On small screens (< 1280px), by default the sidebar is collapsed
    const isSmall = window.innerWidth < 1280;
    set({ collapsed: isSmall, hydrated: true });
  },
}));

