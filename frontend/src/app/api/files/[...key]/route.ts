import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ key: string[] }>;
}

/**
 * GET /api/files/[...key]/download - Get presigned download URL
 * The URL path ends with "/download", so we need to strip that from the key
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { key } = await params;
    
    // The last segment should be "download" - strip it to get the actual file key
    if (key[key.length - 1] !== "download") {
      return NextResponse.json({ detail: "Invalid endpoint" }, { status: 400 });
    }
    
    const fileKey = key.slice(0, -1).join("/");
    
    if (!fileKey) {
      return NextResponse.json({ detail: "File key is required" }, { status: 400 });
    }

    const data = await backendFetch(`/api/v1/files/${encodeURIComponent(fileKey)}/download-url`, {
      headers: buildBackendHeaders(accessToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = typeof error.data === "object" && error.data !== null && "detail" in error.data
        ? (error.data as { detail: string }).detail
        : error.message || "Failed to get download URL";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}

/**
 * DELETE /api/files/[...key] - Delete a file
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { key } = await params;
    const fileKey = key.join("/");

    const data = await backendFetch(`/api/v1/files/${encodeURIComponent(fileKey)}`, {
      method: "DELETE",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = typeof error.data === "object" && error.data !== null && "detail" in error.data
        ? (error.data as { detail: string }).detail
        : error.message || "Failed to delete file";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
