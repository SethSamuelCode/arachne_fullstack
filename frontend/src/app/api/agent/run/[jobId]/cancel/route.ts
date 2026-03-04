import { NextRequest, NextResponse } from "next/server";
import {
  backendFetch,
  BackendApiError,
  buildBackendHeaders,
} from "@/lib/server-api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await params;
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json(
        { detail: "Not authenticated" },
        { status: 401 }
      );
    }

    const data = await backendFetch(`/api/v1/agent/run/${jobId}/cancel`, {
      method: "POST",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.message || "Failed to cancel" },
        { status: error.status }
      );
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
