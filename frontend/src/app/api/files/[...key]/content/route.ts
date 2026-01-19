import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ key: string[] }>;
}

/**
 * GET /api/files/[...key]/content - Get file content for preview
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { key } = await params;
    const fileKey = key.join("/");

    if (!fileKey) {
      return NextResponse.json({ detail: "File key is required" }, { status: 400 });
    }

    const data = await backendFetch(`/api/v1/files/${encodeURIComponent(fileKey)}/content`, {
      headers: buildBackendHeaders(accessToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = typeof error.data === "object" && error.data !== null && "detail" in error.data
        ? (error.data as { detail: string }).detail
        : error.message || "Failed to get file content";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
