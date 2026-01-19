/**
 * SSE (Server-Sent Events) client utility.
 *
 * Provides a typed interface for consuming SSE streams from the backend.
 * Handles authentication, parsing, and cleanup.
 */

import { ApiError } from "./api-client";

export interface SSEEvent<T = unknown> {
  event: string;
  data: T;
}

export interface SSEOptions {
  /** Called for each event received */
  onEvent: (event: SSEEvent) => void;
  /** Called when the stream completes successfully */
  onComplete?: () => void;
  /** Called on error */
  onError?: (error: Error) => void;
  /** Abort signal for cancellation */
  signal?: AbortSignal;
}

/**
 * Consume an SSE stream from the backend.
 *
 * @param url - The endpoint URL (relative to /api, e.g., "/files/rename/folder")
 * @param params - Query parameters to include
 * @param options - Event handlers and abort signal
 * @returns A promise that resolves when the stream ends
 *
 * @example
 * ```ts
 * await consumeSSE("/files/rename/folder", { old_path: "a", new_path: "b" }, {
 *   onEvent: (event) => {
 *     if (event.event === "progress") {
 *       setProgress(event.data as FolderRenameProgress);
 *     }
 *   },
 *   onComplete: () => console.log("Done!"),
 *   onError: (err) => console.error(err),
 * });
 * ```
 */
export async function consumeSSE(
  url: string,
  params: Record<string, string>,
  options: SSEOptions
): Promise<void> {
  const { onEvent, onComplete, onError, signal } = options;

  // Build URL with query params
  const queryString = new URLSearchParams(params).toString();
  const fullUrl = `/api${url}${queryString ? `?${queryString}` : ""}`;

  try {
    const response = await fetch(fullUrl, {
      method: "GET",
      headers: {
        Accept: "text/event-stream",
      },
      signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        errorData.detail || response.statusText,
        errorData
      );
    }

    if (!response.body) {
      throw new Error("Response body is null");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        // Process any remaining buffer content
        if (buffer.trim()) {
          processSSEBuffer(buffer, onEvent);
        }
        onComplete?.();
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by double newlines
      const events = buffer.split("\n\n");
      // Keep the last incomplete event in the buffer
      buffer = events.pop() || "";

      for (const eventText of events) {
        if (eventText.trim()) {
          processSSEBuffer(eventText, onEvent);
        }
      }
    }
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      // Stream was cancelled - not an error
      return;
    }
    onError?.(error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

/**
 * Parse and process a single SSE event buffer.
 */
function processSSEBuffer(
  buffer: string,
  onEvent: (event: SSEEvent) => void
): void {
  const lines = buffer.split("\n");
  let eventType = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }

  if (data) {
    try {
      const parsedData = JSON.parse(data);
      onEvent({ event: eventType, data: parsedData });
    } catch {
      // If not valid JSON, pass as string
      onEvent({ event: eventType, data });
    }
  }
}

/**
 * Type guard for folder rename progress events.
 */
export interface FolderRenameProgress {
  event: "progress" | "complete" | "error";
  total: number;
  completed: number;
  current_file: string | null;
  old_path: string;
  new_path: string;
  error: string | null;
}

export function isFolderRenameProgress(data: unknown): data is FolderRenameProgress {
  return (
    typeof data === "object" &&
    data !== null &&
    "event" in data &&
    "old_path" in data &&
    "new_path" in data
  );
}
