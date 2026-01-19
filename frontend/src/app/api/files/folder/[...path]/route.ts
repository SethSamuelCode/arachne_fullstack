import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ path: string[] }>;
}

/**
 * DELETE /api/files/folder/[...path] - Delete a folder and all its contents
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { path } = await params;
    const folderPath = path.join("/");

    if (!folderPath) {
      return NextResponse.json({ detail: "Folder path is required" }, { status: 400 });
    }

    const data = await backendFetch(`/api/v1/files/folder/${encodeURIComponent(folderPath)}`, {
      method: "DELETE",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = typeof error.data === "object" && error.data !== null && "detail" in error.data
        ? (error.data as { detail: string }).detail
        : error.message || "Failed to delete folder";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
