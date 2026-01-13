"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

const STORAGE_KEY = "arachne-sidebar-state";

interface SidebarState {
  // Mobile sheet state
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;

  // Desktop collapse state (persisted)
  isCollapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
  toggleCollapsed: () => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      // Mobile sheet state
      isOpen: false,
      open: () => set({ isOpen: true }),
      close: () => set({ isOpen: false }),
      toggle: () => set((state) => ({ isOpen: !state.isOpen })),

      // Desktop collapse state
      isCollapsed: false,
      setCollapsed: (collapsed) => set({ isCollapsed: collapsed }),
      toggleCollapsed: () => set((state) => ({ isCollapsed: !state.isCollapsed })),
    }),
    {
      name: STORAGE_KEY,
      partialize: (state) => ({ isCollapsed: state.isCollapsed }),
    }
  )
);
