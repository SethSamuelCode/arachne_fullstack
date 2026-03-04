import { NextRequest } from "next/server";
import { buildBackendHeaders } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://srv.fluffyb.net:8550";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    return new Response(JSON.stringify({ detail: "Not authenticated" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const headers: Record<string, string> = {
    ...buildBackendHeaders(accessToken),
    Accept: "text/event-stream",
  };

  // Forward Last-Event-ID header for reconnection
  const lastEventId = request.headers.get("Last-Event-ID");
  if (lastEventId) {
    headers["Last-Event-ID"] = lastEventId;
  }

  const backendResponse = await fetch(
    `${BACKEND_URL}/api/v1/agent/run/${jobId}/stream`,
    { headers }
  );

  if (!backendResponse.ok) {
    const errorData = await backendResponse.json().catch(() => ({}));
    return new Response(JSON.stringify(errorData), {
      status: backendResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Pass through the SSE stream
  return new Response(backendResponse.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
