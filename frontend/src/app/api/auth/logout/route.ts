import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/server-api";

export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get("refresh_token")?.value;

  // Invalidate session on backend (if we have a refresh token)
  if (refreshToken) {
    try {
      await backendFetch("/api/v1/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // Continue with local logout even if backend call fails
      // Session will eventually expire on backend anyway
    }
  }

  const response = NextResponse.json({ message: "Logged out successfully" });

  // Clear auth cookies
  response.cookies.set("access_token", "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 0,
    path: "/",
  });

  response.cookies.set("refresh_token", "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 0,
    path: "/",
  });

  return response;
}
