import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";
import type { RefreshTokenResponse } from "@/types";

export async function POST(request: NextRequest) {
  try {
    const refreshToken = request.cookies.get("refresh_token")?.value;

    if (!refreshToken) {
      return NextResponse.json(
        { detail: "No refresh token" },
        { status: 401 }
      );
    }

    const data = await backendFetch<RefreshTokenResponse>(
      "/api/v1/auth/refresh",
      {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      }
    );

    const response = NextResponse.json({ message: "Token refreshed" });

    // Use secure cookies only when explicitly enabled (for HTTPS environments)
    const secureCookies = process.env.SECURE_COOKIES === "true";

    // Update access token cookie (matches backend ACCESS_TOKEN_EXPIRE_MINUTES)
    response.cookies.set("access_token", data.access_token, {
      httpOnly: true,
      secure: secureCookies,
      sameSite: "lax",
      maxAge: 60 * 30, // 30 minutes - aligned with backend token expiry
      path: "/",
    });

    // Update refresh token cookie (backend rotates tokens on each refresh)
    if (data.refresh_token) {
      response.cookies.set("refresh_token", data.refresh_token, {
        httpOnly: true,
        secure: secureCookies,
        sameSite: "lax",
        maxAge: 60 * 60 * 24 * 7, // 7 days
        path: "/",
      });
    }

    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      // Clear cookies on refresh failure
      const response = NextResponse.json(
        { detail: "Session expired" },
        { status: 401 }
      );

      response.cookies.set("access_token", "", { maxAge: 0, path: "/" });
      response.cookies.set("refresh_token", "", { maxAge: 0, path: "/" });

      return response;
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
