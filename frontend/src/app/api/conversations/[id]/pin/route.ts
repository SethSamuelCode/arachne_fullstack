import { NextRequest, NextResponse } from "next/server";
import { buildBackendHeaders } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://app:8000";
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY || "";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * POST /api/conversations/[id]/pin - Pin files to chat cache via SSE
 */
export async function POST(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { id } = await params;
    const body = await request.json();

    // Forward the SSE request to the backend
    const backendUrl = `${BACKEND_URL}/api/v1/conversations/${id}/pin`;

    const response = await fetch(backendUrl, {
      method: "POST",
      headers: {
        ...buildBackendHeaders(accessToken, csrfToken),
        "Content-Type": "application/json",
        ...(INTERNAL_API_KEY ? { "X-Internal-API-Key": INTERNAL_API_KEY } : {}),
      },
      body: JSON.stringify(body),
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
    console.error("Pin files SSE error:", error);
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

/**
 * GET /api/conversations/[id]/pin - Pin files to chat cache via SSE (query params)
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { id } = await params;
    const { searchParams } = new URL(request.url);

    // Forward the SSE request to the backend with query params
    const backendUrl = `${BACKEND_URL}/api/v1/conversations/${id}/pin?${searchParams.toString()}`;

    const response = await fetch(backendUrl, {
      headers: {
        ...buildBackendHeaders(accessToken),
        ...(INTERNAL_API_KEY ? { "X-Internal-API-Key": INTERNAL_API_KEY } : {}),
      },
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
    console.error("Pin files SSE error:", error);
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
