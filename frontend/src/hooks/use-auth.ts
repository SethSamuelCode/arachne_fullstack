"use client";

import { useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/stores";
import { apiClient, ApiError } from "@/lib/api-client";
import type { User, LoginRequest, RegisterRequest } from "@/types";
import { ROUTES } from "@/lib/constants";

/** Refresh token 5 minutes before expiry */
const REFRESH_BUFFER_SECONDS = 5 * 60;

/** Minimum interval between refresh attempts (30 seconds) */
const MIN_REFRESH_INTERVAL_MS = 30 * 1000;

export function useAuth() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isAuthenticated, isLoading, setUser, setLoading, logout } =
    useAuthStore();

  // Refs for proactive refresh timer
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastRefreshRef = useRef<number>(0);

  /**
   * Clear the proactive refresh timer.
   */
  const clearRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  /**
   * Refresh the access token.
   * Returns true if successful, false otherwise.
   */
  const refreshToken = useCallback(async (): Promise<boolean> => {
    // Prevent rapid refresh attempts
    const now = Date.now();
    if (now - lastRefreshRef.current < MIN_REFRESH_INTERVAL_MS) {
      return true; // Skip if refreshed recently
    }

    try {
      await apiClient.post("/auth/refresh");
      lastRefreshRef.current = Date.now();

      // Re-fetch user after token refresh to get updated data
      const userData = await apiClient.get<User>("/auth/me");
      setUser(userData);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearRefreshTimer();
        logout();
        router.push(ROUTES.LOGIN);
      }
      return false;
    }
  }, [clearRefreshTimer, logout, router, setUser]);

  /**
   * Schedule a proactive token refresh.
   * Uses a fixed interval since we can't decode httpOnly cookies client-side.
   * The server sets cookies with 60-min expiry, so refresh at ~55 mins.
   */
  const scheduleRefresh = useCallback(() => {
    clearRefreshTimer();

    // Schedule refresh 5 minutes before expected expiry
    // Token expires in 60 mins, so refresh at 55 mins = 55 * 60 * 1000 ms
    const refreshInMs = (60 - REFRESH_BUFFER_SECONDS / 60) * 60 * 1000;

    refreshTimerRef.current = setTimeout(async () => {
      const success = await refreshToken();
      if (success) {
        // Schedule next refresh
        scheduleRefresh();
      }
    }, refreshInMs);
  }, [clearRefreshTimer, refreshToken]);

  // Check auth status on mount and validate persisted state
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const userData = await apiClient.get<User>("/auth/me");
        setUser(userData);
        // Start proactive refresh timer after successful auth check
        scheduleRefresh();
      } catch {
        // Clear persisted state if auth check fails
        setUser(null);
        useAuthStore.persist.clearStorage();
      }
    };

    if (isLoading) {
      checkAuth();
    }

    // Cleanup timer on unmount
    return () => {
      clearRefreshTimer();
    };
  }, [isLoading, setUser, scheduleRefresh, clearRefreshTimer]);

  // Restart refresh timer when user changes (e.g., after login)
  useEffect(() => {
    if (user && !isLoading) {
      scheduleRefresh();
    }
    return () => {
      clearRefreshTimer();
    };
  }, [user, isLoading, scheduleRefresh, clearRefreshTimer]);

  const login = useCallback(
    async (credentials: LoginRequest) => {
      setLoading(true);
      try {
        const response = await apiClient.post<{ user: User; message: string }>(
          "/auth/login",
          credentials
        );
        setUser(response.user);

        // Check for callback URL from middleware redirect
        const callbackUrl = searchParams.get("callbackUrl");
        if (callbackUrl && callbackUrl.startsWith("/")) {
          // Only allow relative URLs for security
          router.push(callbackUrl);
        } else {
          router.push(ROUTES.DASHBOARD);
        }

        return response;
      } catch (error) {
        setLoading(false);
        throw error;
      }
    },
    [router, searchParams, setUser, setLoading]
  );

  const register = useCallback(
    async (data: RegisterRequest) => {
      const response = await apiClient.post<{ id: string; email: string }>(
        "/auth/register",
        data
      );
      return response;
    },
    []
  );

  const handleLogout = useCallback(async () => {
    clearRefreshTimer();
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Ignore logout errors
    } finally {
      logout();
      router.push(ROUTES.LOGIN);
    }
  }, [clearRefreshTimer, logout, router]);

  return {
    user,
    isAuthenticated,
    isLoading,
    login,
    register,
    logout: handleLogout,
    refreshToken,
  };
}
