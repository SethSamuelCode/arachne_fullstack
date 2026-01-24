import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

/**
 * GET /api/plans - List user's plans
 */
export async function GET(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    // Forward query params
    const url = new URL(request.url);
    const backendUrl = `/api/v1/plans${url.search}`;

    const data = await backendFetch(backendUrl, {
      headers: buildBackendHeaders(accessToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail =
        typeof error.data === "object" && error.data !== null && "detail" in error.data
          ? (error.data as { detail: string }).detail
          : error.message || "Failed to list plans";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

/**
 * POST /api/plans - Create a new plan
 */
export async function POST(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const body = await request.json();

    const data = await backendFetch("/api/v1/plans", {
      method: "POST",
      headers: buildBackendHeaders(accessToken, csrfToken),
      body: JSON.stringify(body),
    });

    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail =
        typeof error.data === "object" && error.data !== null && "detail" in error.data
          ? (error.data as { detail: string }).detail
          : error.message || "Failed to create plan";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
