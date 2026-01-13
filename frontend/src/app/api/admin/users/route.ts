import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, buildBackendHeaders } from "@/lib/server-api";
import type { User } from "@/types";

interface PaginatedUsers {
  items: User[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export async function GET(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    // Forward query params
    const { searchParams } = new URL(request.url);
    const params: Record<string, string> = {};
    
    // Pagination params
    const page = searchParams.get("page");
    const size = searchParams.get("size");
    if (page) params.page = page;
    if (size) params.size = size;
    
    // Filter params
    const includeDeleted = searchParams.get("include_deleted");
    const search = searchParams.get("search");
    const role = searchParams.get("role");
    
    if (includeDeleted) params.include_deleted = includeDeleted;
    if (search) params.search = search;
    if (role) params.role = role;

    const data = await backendFetch<PaginatedUsers>("/api/v1/users", {
      method: "GET",
      headers: buildBackendHeaders(accessToken),
      params,
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.data || "Failed to fetch users" },
        { status: error.status }
      );
    }
    console.error("Admin users fetch error:", error);
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const csrfToken = request.cookies.get("csrf_token")?.value;

    if (!accessToken) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }

    const body = await request.json();

    const data = await backendFetch<User>("/api/v1/users", {
      method: "POST",
      headers: buildBackendHeaders(accessToken, csrfToken),
      body: JSON.stringify(body),
    });

    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.data || "Failed to create user" },
        { status: error.status }
      );
    }
    console.error("Admin user create error:", error);
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
