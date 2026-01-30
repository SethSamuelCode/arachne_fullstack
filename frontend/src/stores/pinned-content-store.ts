import { create } from "zustand";
import type {
  PinnedContentInfo,
  PinProgress,
  StalenessResponse,
} from "@/types/pinned-content";

interface PinnedContentState {
  // Per-conversation pinned content metadata
  pinnedContent: Record<string, PinnedContentInfo>;

  // Current pinning operation state
  isPinning: boolean;
  pinProgress: PinProgress | null;

  // Staleness data per conversation
  stalenessData: Record<string, StalenessResponse>;

  // Actions
  setPinnedContent: (conversationId: string, data: PinnedContentInfo) => void;
  clearPinnedContent: (conversationId: string) => void;
  setPinProgress: (progress: PinProgress | null) => void;
  setIsPinning: (isPinning: boolean) => void;
  setStalenessData: (conversationId: string, data: StalenessResponse) => void;

  // Getters
  getPinnedContent: (conversationId: string) => PinnedContentInfo | null;
  getStalenessData: (conversationId: string) => StalenessResponse | null;
}

export const usePinnedContentStore = create<PinnedContentState>((set, get) => ({
  pinnedContent: {},
  isPinning: false,
  pinProgress: null,
  stalenessData: {},

  setPinnedContent: (conversationId, data) =>
    set((state) => ({
      pinnedContent: {
        ...state.pinnedContent,
        [conversationId]: data,
      },
    })),

  clearPinnedContent: (conversationId) =>
    set((state) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { [conversationId]: _removed, ...rest } = state.pinnedContent;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { [conversationId]: _removedStaleness, ...restStaleness } = state.stalenessData;
      return {
        pinnedContent: rest,
        stalenessData: restStaleness,
      };
    }),

  setPinProgress: (progress) =>
    set({
      pinProgress: progress,
    }),

  setIsPinning: (isPinning) =>
    set({
      isPinning,
    }),

  setStalenessData: (conversationId, data) =>
    set((state) => ({
      stalenessData: {
        ...state.stalenessData,
        [conversationId]: data,
      },
    })),

  getPinnedContent: (conversationId) => {
    return get().pinnedContent[conversationId] || null;
  },

  getStalenessData: (conversationId) => {
    return get().stalenessData[conversationId] || null;
  },
}));
