import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ planId: string }>;
}

/**
 * POST /api/plans/[planId]/tasks - Create a task in a plan
 */
export async function POST(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { planId } = await params;
    const body = await request.json();

    const data = await backendFetch(`/api/v1/plans/${planId}/tasks`, {
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
          : error.message || "Failed to create task";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
