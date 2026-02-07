/**
 * Server-Sent Events (SSE) client utility
 * Provides async generator for consuming SSE streams with error handling
 */

export interface SSEOptions {
  headers?: Record<string, string>;
  withCredentials?: boolean;
  signal?: AbortSignal;
}

export class SSEError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly response?: Response
  ) {
    super(message);
    this.name = "SSEError";
  }
}

/**
 * Creates an async generator that yields parsed SSE events
 * @param url - The SSE endpoint URL
 * @param options - Request options
 * @returns AsyncGenerator yielding parsed event data
 */
export async function* createSSEStream<T>(
  url: string,
  options: SSEOptions = {}
): AsyncGenerator<T, void, unknown> {
  const { headers = {}, withCredentials = true, signal } = options;

  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
      ...headers,
    },
    credentials: withCredentials ? "include" : "same-origin",
    signal,
  });

  if (!response.ok) {
    throw new SSEError(
      `SSE request failed: ${response.statusText}`,
      response.status,
      response
    );
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new SSEError("Response body is not readable");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      // Normalize \r\n to \n (sse_starlette uses \r\n separators)
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      // Split by double newline (SSE event separator)
      const events = buffer.split("\n\n");

      // Keep the last incomplete event in the buffer
      buffer = events.pop() || "";

      for (const event of events) {
        if (!event.trim()) continue;

        const parsed = parseSSEEvent<T>(event);
        if (parsed !== null) {
          yield parsed;
        }
      }
    }

    // Process any remaining data in buffer
    if (buffer.trim()) {
      const parsed = parseSSEEvent<T>(buffer);
      if (parsed !== null) {
        yield parsed;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Parse a single SSE event string into typed data
 * Handles both "data:" and "event:" + "data:" formats
 * Returns an object with { event, data } matching the SSE protocol fields
 */
function parseSSEEvent<T>(eventString: string): T | null {
  const lines = eventString.split("\n");
  let eventType = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventType = line.substring(6).trim();
    } else if (line.startsWith("data:")) {
      data += line.substring(5).trim();
    }
  }

  if (!data) {
    return null;
  }

  try {
    const parsedData = JSON.parse(data);
    return { event: eventType, data: parsedData } as T;
  } catch {
    return { event: eventType, data } as T;
  }
}

/**
 * Creates an async generator for POST SSE requests
 * @param url - The SSE endpoint URL
 * @param body - Request body (JSON)
 * @param options - Request options
 * @returns AsyncGenerator yielding parsed event data
 */
export async function* createPOSTSSEStream<T>(
  url: string,
  body: unknown,
  options: SSEOptions = {}
): AsyncGenerator<T, void, unknown> {
  const { headers = {}, withCredentials = true, signal } = options;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
    credentials: withCredentials ? "include" : "same-origin",
    signal,
  });

  if (!response.ok) {
    throw new SSEError(
      `SSE request failed: ${response.statusText}`,
      response.status,
      response
    );
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new SSEError("Response body is not readable");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      // Normalize \r\n to \n (sse_starlette uses \r\n separators)
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const event of events) {
        if (!event.trim()) continue;

        const parsed = parseSSEEvent<T>(event);
        if (parsed !== null) {
          yield parsed;
        }
      }
    }

    if (buffer.trim()) {
      const parsed = parseSSEEvent<T>(buffer);
      if (parsed !== null) {
        yield parsed;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
