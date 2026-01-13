import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";
import type { User } from "@/types";

type RouteParams = { params: Promise<{ userId: string }> };

export async function POST(
  request: NextRequest,
  { params }: RouteParams
) {
  try {
    const { userId } = await params;
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const data = await backendFetch<User>(`/api/v1/users/${userId}/restore`, {
      method: "POST",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.data || "Failed to restore user" },
        { status: error.status }
      );
    }
    console.error("Admin user restore error:", error);
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
