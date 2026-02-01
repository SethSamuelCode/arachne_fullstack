import { useState, useEffect, useCallback, useRef } from "react";
import { apiClient } from "@/lib/api-client";
import { usePinnedContentStore } from "@/stores/pinned-content-store";
import type {
  PinContentRequest,
  PinProgress,
  PinnedContentInfo,
  StalenessResponse,
  PinProgressEvent,
  PinWarningEvent,
  PinErrorEvent,
  PinCompleteEvent,
} from "@/types/pinned-content";

export interface UsePinFilesOptions {
  /** Conversation ID */
  conversationId: string;
  /** Auto-fetch pinned content on mount */
  autoFetch?: boolean;
  /** Auto-check staleness on mount and periodically */
  autoCheckStaleness?: boolean;
  /** Staleness check interval in milliseconds (default: 5 minutes) */
  stalenessCheckInterval?: number;
}

export interface UsePinFilesReturn {
  /** Current pinned content info */
  pinnedInfo: PinnedContentInfo | null;
  /** Staleness data */
  stalenessData: StalenessResponse | null;
  /** Whether a pin operation is in progress */
  isPinning: boolean;
  /** Current pin progress */
  pinProgress: PinProgress | null;
  /** Error message */
  error: string | null;
  /** Pin files */
  pinFiles: (filePaths: string[]) => Promise<void>;
  /** Check staleness */
  checkStaleness: () => Promise<void>;
  /** Repin files */
  repin: () => Promise<void>;
  /** Clear pinned content */
  clearPinned: () => Promise<void>;
  /** Fetch pinned content metadata */
  fetchPinnedContent: () => Promise<void>;
}

export function usePinFiles({
  conversationId,
  autoFetch = true,
  autoCheckStaleness = true,
  stalenessCheckInterval = 5 * 60 * 1000, // 5 minutes
}: UsePinFilesOptions): UsePinFilesReturn {
  const {
    isPinning,
    pinProgress,
    setPinnedContent,
    clearPinnedContent,
    setPinProgress,
    setIsPinning,
    setStalenessData,
    getPinnedContent,
    getStalenessData,
  } = usePinnedContentStore();

  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const stalenessIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const pinnedInfo = getPinnedContent(conversationId);
  const stalenessData = getStalenessData(conversationId);

  /**
   * Fetch pinned content metadata from API
   */
  const fetchPinnedContent = useCallback(async () => {
    try {
      const data = await apiClient.getPinnedContent(conversationId);
      if (data) {
        setPinnedContent(conversationId, data);
      }
    } catch (err) {
      console.error("Failed to fetch pinned content:", err);
      // Don't set error state for fetch failures (it's background operation)
    }
  }, [conversationId, setPinnedContent]);

  /**
   * Check if pinned content is stale
   */
  const checkStaleness = useCallback(async () => {
    if (!pinnedInfo) return;

    try {
      const data = await apiClient.checkStaleness(
        conversationId,
        pinnedInfo.file_hashes
      );
      setStalenessData(conversationId, data);
    } catch (err) {
      console.error("Failed to check staleness:", err);
    }
  }, [conversationId, pinnedInfo, setStalenessData]);

  /**
   * Pin files to conversation cache
   */
  const pinFiles = useCallback(
    async (filePaths: string[]) => {
      if (filePaths.length === 0) {
        setError("Please select at least one file to pin");
        return;
      }

      setError(null);
      setIsPinning(true);
      setPinProgress(null);

      // Create abort controller for cancellation
      abortControllerRef.current = new AbortController();

      try {
        const request: PinContentRequest = {
          s3_paths: filePaths,
        };

        for await (const event of apiClient.pinFiles(conversationId, request)) {
          if (event.event === "progress") {
            const progressData = event.data as PinProgressEvent;
            const current = progressData.current ?? 0;
            const total = progressData.total ?? 0;
            setPinProgress({
              phase: progressData.phase,
              current,
              total,
              message: progressData.message,
              currentFile: progressData.current_file || progressData.currentFile,
              percentage: total > 0 ? Math.round((current / total) * 100) : undefined,
              tokens: progressData.tokens,
              budgetUsedPercent: progressData.budget_used_pct,
            });
          } else if (event.event === "warning") {
            const warningData = event.data as PinWarningEvent;
            console.warn("Pin warning:", warningData.message);
          } else if (event.event === "error") {
            const errorData = event.data as PinErrorEvent;
            throw new Error(errorData.message || "Pin operation failed");
          } else if (event.event === "complete") {
            const completeData = event.data as PinCompleteEvent;
            console.log("Pin complete:", completeData.message || "Files pinned successfully");
            // Keep progress set so isComplete can detect success
            setPinProgress({
              phase: "storing",
              current: completeData.file_count,
              total: completeData.file_count,
              tokens: completeData.total_tokens,
            });
            await fetchPinnedContent();
            break;
          }
        }
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to pin files";
        setError(errorMessage);
        throw err;
      } finally {
        setIsPinning(false);
        abortControllerRef.current = null;
      }
    },
    [conversationId, setIsPinning, setPinProgress, fetchPinnedContent]
  );

  /**
   * Repin files (refresh stale content)
   */
  const repin = useCallback(async () => {
    setError(null);
    setIsPinning(true);
    setPinProgress(null);

    try {
      for await (const event of apiClient.repinContent(conversationId)) {
        if (event.event === "progress") {
          const progressData = event.data as PinProgressEvent;
          const current = progressData.current ?? 0;
          const total = progressData.total ?? 0;
          setPinProgress({
            phase: progressData.phase,
            current,
            total,
            message: progressData.message,
            currentFile: progressData.current_file || progressData.currentFile,
            percentage: total > 0 ? Math.round((current / total) * 100) : undefined,
            tokens: progressData.tokens,
            budgetUsedPercent: progressData.budget_used_pct,
          });
        } else if (event.event === "warning") {
          const warningData = event.data as PinWarningEvent;
          console.warn("Repin warning:", warningData.message);
        } else if (event.event === "error") {
          const errorData = event.data as PinErrorEvent;
          throw new Error(errorData.message || "Repin operation failed");
        } else if (event.event === "complete") {
          const completeData = event.data as PinCompleteEvent;
          console.log("Repin complete:", completeData.message || "Files repinned successfully");
          setPinProgress({
            phase: "storing",
            current: completeData.file_count,
            total: completeData.file_count,
            tokens: completeData.total_tokens,
          });
          await fetchPinnedContent();
          await checkStaleness();
          break;
        }
      }
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to repin files";
      setError(errorMessage);
      throw err;
    } finally {
      setIsPinning(false);
    }
  }, [conversationId, setIsPinning, setPinProgress, fetchPinnedContent, checkStaleness]);

  /**
   * Clear pinned content
   */
  const clearPinned = useCallback(async () => {
    // TODO: Implement backend endpoint for clearing pinned content
    // For now, just clear local state
    clearPinnedContent(conversationId);
  }, [conversationId, clearPinnedContent]);

  // Auto-fetch pinned content on mount
  useEffect(() => {
    if (autoFetch) {
      fetchPinnedContent();
    }
  }, [autoFetch, fetchPinnedContent]);

  // Auto-check staleness on mount and periodically
  useEffect(() => {
    if (!autoCheckStaleness || !pinnedInfo) return;

    // Check immediately
    checkStaleness();

    // Check periodically
    stalenessIntervalRef.current = setInterval(
      checkStaleness,
      stalenessCheckInterval
    );

    return () => {
      if (stalenessIntervalRef.current) {
        clearInterval(stalenessIntervalRef.current);
      }
    };
  }, [autoCheckStaleness, pinnedInfo, checkStaleness, stalenessCheckInterval]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (stalenessIntervalRef.current) {
        clearInterval(stalenessIntervalRef.current);
      }
    };
  }, []);

  return {
    pinnedInfo,
    stalenessData,
    isPinning,
    pinProgress,
    error,
    pinFiles,
    checkStaleness,
    repin,
    clearPinned,
    fetchPinnedContent,
  };
}
