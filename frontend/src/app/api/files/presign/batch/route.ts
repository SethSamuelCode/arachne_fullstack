import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

/**
 * POST /api/files/presign/batch - Get batch presigned upload URLs for folder uploads
 * Body: { files: [{ filename: string, content_type?: string }, ...] }
 */
export async function POST(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const body = await request.json();

    const data = await backendFetch("/api/v1/files/presign/batch", {
      method: "POST",
      headers: {
        ...buildBackendHeaders(accessToken, csrfToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = typeof error.data === "object" && error.data !== null && "detail" in error.data
        ? (error.data as { detail: string }).detail
        : error.message || "Failed to get batch upload URLs";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
