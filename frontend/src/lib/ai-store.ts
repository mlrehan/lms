import { create } from "zustand";

interface AIState {
  isOpen: boolean;
  initialPrompt: string | null;
  openDrawer: (prompt?: string) => void;
  closeDrawer: () => void;
  toggleDrawer: () => void;
}

export const useAIStore = create<AIState>((set) => ({
  isOpen: false,
  initialPrompt: null,
  openDrawer: (prompt) => set({ isOpen: true, initialPrompt: prompt ?? null }),
  closeDrawer: () => set({ isOpen: false, initialPrompt: null }),
  toggleDrawer: () => set((state) => ({ isOpen: !state.isOpen, initialPrompt: null })),
}));

