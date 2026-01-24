import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ taskId: string }>;
}

/**
 * PATCH /api/tasks/[taskId] - Update a task
 */
export async function PATCH(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { taskId } = await params;
    const body = await request.json();

    const data = await backendFetch(`/api/v1/tasks/${taskId}`, {
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
          : error.message || "Failed to update task";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

/**
 * DELETE /api/tasks/[taskId] - Delete a task
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const { taskId } = await params;

    await backendFetch(`/api/v1/tasks/${taskId}`, {
      method: "DELETE",
      headers: buildBackendHeaders(accessToken, csrfToken),
    });

    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail =
        typeof error.data === "object" && error.data !== null && "detail" in error.data
          ? (error.data as { detail: string }).detail
          : error.message || "Failed to delete task";
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
