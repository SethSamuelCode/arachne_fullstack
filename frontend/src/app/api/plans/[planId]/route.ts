import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ planId: string }>;
}

/**
 * GET /api/plans/[planId] - Get a single plan with tasks
 */
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { planId } = await params;

    const data = await backendFetch(`/api/v1/plans/${planId}`, {
      headers: buildBackendHeaders(accessToken),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail =
        typeof error.data === "object" && error.data !== null && "detail" in error.data
          ? (error.data as { detail: string }).detail
          : error.message || "Failed to get plan";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

/**
 * PATCH /api/plans/[planId] - Update a plan
 */
export async function PATCH(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { planId } = await params;
    const body = await request.json();

    const data = await backendFetch(`/api/v1/plans/${planId}`, {
      method: "PATCH",
      headers: buildBackendHeaders(accessToken, csrfToken),
      body: JSON.stringify(body),
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail =
        typeof error.data === "object" && error.data !== null && "detail" in error.data
          ? (error.data as { detail: string }).detail
          : error.message || "Failed to update plan";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

/**
 * DELETE /api/plans/[planId] - Delete a plan
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { planId } = await params;

    await backendFetch(`/api/v1/plans/${planId}`, {
      method: "DELETE",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail =
        typeof error.data === "object" && error.data !== null && "detail" in error.data
          ? (error.data as { detail: string }).detail
          : error.message || "Failed to delete plan";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
