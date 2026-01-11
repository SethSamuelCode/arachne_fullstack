import { NextRequest, NextResponse } from "next/server";
import { backendFetch, buildBackendHeaders } from "@/lib/server-api";

export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get("refresh_token")?.value;
  const csrfToken = request.cookies.get("csrf_token")?.value;

  // Invalidate session on backend (if we have a refresh token)
  if (refreshToken) {
    try {
      await backendFetch("/api/v1/auth/logout", {
        method: "POST",
        headers: buildBackendHeaders(null, csrfToken),
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Continue with local logout even if backend call fails
      // Session will eventually expire on backend anyway
    }
  }

  const response = NextResponse.json({ message: "Logged out successfully" });

  // Use secure cookies only when explicitly enabled (for HTTPS environments)
  const secureCookies = process.env.SECURE_COOKIES === "true";

  // Clear auth cookies
  response.cookies.set("access_token", "", {
    httpOnly: true,
    secure: secureCookies,
    sameSite: "lax",
    maxAge: 0,
    path: "/",
  });

  response.cookies.set("refresh_token", "", {
    httpOnly: true,
    secure: secureCookies,
    sameSite: "lax",
    maxAge: 0,
    path: "/",
  });

  return response;
}
