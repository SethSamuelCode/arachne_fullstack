import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/conversations/[id]/pinned - Get pinned content metadata
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { id } = await params;

    const data = await backendFetch(`/api/v1/conversations/${id}/pinned`, {
      headers: buildBackendHeaders(accessToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      // Return null for 404 (no pinned content) instead of error
      if (error.status === 404) {
        return NextResponse.json(null);
      }
      return NextResponse.json(
        { detail: error.message || "Failed to fetch pinned content" },
        { status: error.status }
      );
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
