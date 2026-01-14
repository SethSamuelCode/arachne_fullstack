/**
 * Client-side API client with automatic token refresh.
 *
 * All requests go through Next.js API routes (/api/*), never directly to the backend.
 * This keeps the backend URL hidden from the browser.
 *
 * Features:
 * - Automatic 401 handling with token refresh and retry
 * - Prevents refresh loops with retry tracking
 * - Redirects to login on refresh failure
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public data?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  params?: Record<string, string>;
  body?: unknown;
  /** Skip 401 retry (used internally to prevent loops) */
  _skipRetry?: boolean;
}

/** Routes where we should NOT redirect to login on auth failure */
const AUTH_PAGES = ["/login", "/register"];

class ApiClient {
  /** Track if a refresh is in progress to prevent concurrent refreshes */
  private refreshPromise: Promise<boolean> | null = null;

  /**
   * Attempt to refresh the access token.
   * Returns true if refresh succeeded, false otherwise.
   */
  private async refreshToken(): Promise<boolean> {
    // If refresh is already in progress, wait for it
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      try {
        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });

        if (response.ok) {
          return true;
        }

        // Refresh failed - clear auth state
        return false;
      } catch {
        return false;
      } finally {
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  /**
   * Check if we're currently on an auth page (login, register).
   */
  private isOnAuthPage(): boolean {
    if (typeof window === "undefined") return false;
    const pathname = window.location.pathname;
    // Check if pathname ends with any auth page (handles locale prefixes like /en/login)
    return AUTH_PAGES.some((page) => pathname === page || pathname.endsWith(page));
  }

  /**
   * Handle authentication failure by redirecting to login.
   * Does nothing if already on an auth page to prevent redirect loops.
   */
  private handleAuthFailure(): void {
    if (typeof window === "undefined") return;

    // Don't redirect if already on login/register page
    if (this.isOnAuthPage()) {
      // Just clear stored state, no redirect
      localStorage.removeItem("auth-storage");
      return;
    }

    // Clear zustand persisted state
    localStorage.removeItem("auth-storage");

    // Get current path for callback
    const currentPath = window.location.pathname;
    const loginUrl = `/login?callbackUrl=${encodeURIComponent(currentPath)}`;
    window.location.href = loginUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestOptions = {}
  ): Promise<T> {
    const { params, body, _skipRetry, ...fetchOptions } = options;

    let url = `/api${endpoint}`;

    if (params) {
      const searchParams = new URLSearchParams(params);
      url += `?${searchParams.toString()}`;
    }

    const response = await fetch(url, {
      ...fetchOptions,
      headers: {
        "Content-Type": "application/json",
        ...fetchOptions.headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    // Handle 401 Unauthorized - attempt token refresh and retry
    if (response.status === 401 && !_skipRetry) {
      const refreshed = await this.refreshToken();

      if (refreshed) {
        // Retry the original request with skip flag to prevent infinite loop
        return this.request<T>(endpoint, { ...options, _skipRetry: true });
      }

      // Refresh failed - redirect to login
      this.handleAuthFailure();
      throw new ApiError(401, "Session expired. Please log in again.");
    }

    if (!response.ok) {
      let errorData;
      try {
        errorData = await response.json();
      } catch {
        errorData = null;
      }
      throw new ApiError(
        response.status,
        errorData?.detail || errorData?.message || "Request failed",
        errorData
      );
    }

    // Handle empty responses
    const text = await response.text();
    if (!text) {
      return null as T;
    }

    return JSON.parse(text);
  }

  get<T>(endpoint: string, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "GET" });
  }

  post<T>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "POST", body });
  }

  put<T>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "PUT", body });
  }

  patch<T>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "PATCH", body });
  }

  delete<T>(endpoint: string, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "DELETE" });
  }
}

export const apiClient = new ApiClient();
