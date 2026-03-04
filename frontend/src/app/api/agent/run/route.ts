import { NextRequest, NextResponse } from "next/server";
import {
  backendFetch,
  BackendApiError,
  buildBackendHeaders,
} from "@/lib/server-api";

export async function POST(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json(
        { detail: "Not authenticated" },
        { status: 401 }
      );
    }

    const body = await request.json();

    const data = await backendFetch("/api/v1/agent/run", {
      method: "POST",
      headers: {
        ...buildBackendHeaders(accessToken, csrfToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    return NextResponse.json(data, { status: 202 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.message || "Failed to start agent run" },
        { status: error.status }
      );
    }
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
