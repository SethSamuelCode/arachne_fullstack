import { NextRequest, NextResponse } from "next/server";
import { buildBackendHeaders } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://app:8000";

/**
 * GET /api/files/rename/folder - Rename a folder with SSE progress streaming
 */
export async function GET(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const oldPath = searchParams.get("old_path");
    const newPath = searchParams.get("new_path");

    if (!oldPath || !newPath) {
      return NextResponse.json(
        { detail: "old_path and new_path query parameters are required" },
        { status: 400 }
      );
    }

    // Forward the SSE request to the backend
    const backendUrl = `${BACKEND_URL}/api/v1/files/rename/folder?old_path=${encodeURIComponent(oldPath)}&new_path=${encodeURIComponent(newPath)}`;

    const response = await fetch(backendUrl, {
      headers: buildBackendHeaders(accessToken),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: "Backend error" }));
      return NextResponse.json(errorData, { status: response.status });
    }

    // Stream the SSE response
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const reader = response.body?.getReader();

    if (!reader) {
      return NextResponse.json({ detail: "No response body" }, { status: 500 });
    }

    // Pipe the response
    (async () => {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          await writer.write(value);
        }
      } finally {
        await writer.close();
      }
    })();

    return new NextResponse(readable, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  } catch (error) {
    console.error("Folder rename SSE error:", error);
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
