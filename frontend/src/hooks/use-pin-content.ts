"use client";

import { useState, useCallback, useRef } from "react";
import { consumeSSE } from "@/lib/sse";
import { apiClient } from "@/lib/api-client";

// =============================================================================
// Types
// =============================================================================

export interface PinProgress {
  phase: "fetching" | "serializing" | "uploading" | "complete";
  current: number;
  total: number;
  message?: string;
  currentFile?: string;
}

export interface PinWarning {
  type: "budget_warning" | "file_error";
  message: string;
  path?: string;
  percent?: number;
}

export interface PinError {
  code: string;
  message: string;
}

export interface PinResult {
  content_hash: string;
  total_tokens: number;
  file_count: number;
}

export interface PinnedContentInfo {
  content_hash: string;
  file_paths: string[];
  file_hashes: Record<string, string>;
  total_tokens: number;
  pinned_at: string;
}

export interface StalenessResult {
  is_stale: boolean;
  changed_files: string[];
  added_files: string[];
  removed_files: string[];
  has_pinned_content: boolean;
}

export interface UsePinContentReturn {
  // State
  isPinning: boolean;
  progress: PinProgress | null;
  warnings: PinWarning[];
  error: PinError | null;
  result: PinResult | null;
  pinnedInfo: PinnedContentInfo | null;

  // Actions
  pinContent: (conversationId: string, s3Paths: string[], modelName?: string) => Promise<boolean>;
  fetchPinnedInfo: (conversationId: string) => Promise<PinnedContentInfo | null>;
  checkStaleness: (conversationId: string, currentHashes: Record<string, string>) => Promise<StalenessResult | null>;
  cancel: () => void;
  reset: () => void;
}

// =============================================================================
// Hook Implementation
// =============================================================================

export function usePinContent(): UsePinContentReturn {
  const [isPinning, setIsPinning] = useState(false);
  const [progress, setProgress] = useState<PinProgress | null>(null);
  const [warnings, setWarnings] = useState<PinWarning[]>([]);
  const [error, setError] = useState<PinError | null>(null);
  const [result, setResult] = useState<PinResult | null>(null);
  const [pinnedInfo, setPinnedInfo] = useState<PinnedContentInfo | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  /**
   * Pin content to a conversation's cache via SSE stream.
   */
  const pinContent = useCallback(
    async (
      conversationId: string,
      s3Paths: string[],
      modelName: string = "gemini-2.5-flash"
    ): Promise<boolean> => {
      // Reset state
      setIsPinning(true);
      setProgress(null);
      setWarnings([]);
      setError(null);
      setResult(null);

      // Create abort controller
      abortControllerRef.current = new AbortController();

      try {
        await consumeSSE(
          `/conversations/${conversationId}/pin`,
          {
            s3_paths: s3Paths.join(","),
            model_name: modelName,
          },
          {
            signal: abortControllerRef.current.signal,
            onEvent: (event) => {
              switch (event.event) {
                case "progress":
                  setProgress(event.data as PinProgress);
                  break;
                case "warning":
                  setWarnings((prev) => [...prev, event.data as PinWarning]);
                  break;
                case "error":
                  setError(event.data as PinError);
                  break;
                case "complete":
                  setResult(event.data as PinResult);
                  setProgress({
                    phase: "complete",
                    current: 1,
                    total: 1,
                    message: "Content pinned successfully",
                  });
                  break;
              }
            },
            onComplete: () => {
              setIsPinning(false);
            },
            onError: (err) => {
              setError({
                code: "SSE_ERROR",
                message: err.message,
              });
              setIsPinning(false);
            },
          }
        );

        return !error;
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // Cancelled by user
          setError({
            code: "CANCELLED",
            message: "Pin operation cancelled",
          });
        } else {
          setError({
            code: "UNEXPECTED_ERROR",
            message: (err as Error).message,
          });
        }
        setIsPinning(false);
        return false;
      }
    },
    [error]
  );

  /**
   * Fetch current pinned content info for a conversation.
   */
  const fetchPinnedInfo = useCallback(
    async (conversationId: string): Promise<PinnedContentInfo | null> => {
      try {
        const info = await apiClient.get<PinnedContentInfo | null>(
          `/conversations/${conversationId}/pinned`
        );
        setPinnedInfo(info);
        return info;
      } catch {
        return null;
      }
    },
    []
  );

  /**
   * Check if pinned content is stale.
   */
  const checkStaleness = useCallback(
    async (
      conversationId: string,
      currentHashes: Record<string, string>
    ): Promise<StalenessResult | null> => {
      try {
        const result = await apiClient.post<StalenessResult>(
          `/conversations/${conversationId}/check-staleness`,
          { current_hashes: currentHashes }
        );
        return result;
      } catch {
        return null;
      }
    },
    []
  );

  /**
   * Cancel ongoing pin operation.
   */
  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  /**
   * Reset all state.
   */
  const reset = useCallback(() => {
    setIsPinning(false);
    setProgress(null);
    setWarnings([]);
    setError(null);
    setResult(null);
  }, []);

  return {
    isPinning,
    progress,
    warnings,
    error,
    result,
    pinnedInfo,
    pinContent,
    fetchPinnedInfo,
    checkStaleness,
    cancel,
    reset,
  };
}
