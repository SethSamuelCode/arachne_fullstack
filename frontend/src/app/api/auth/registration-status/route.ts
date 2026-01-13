import { NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

interface RegistrationStatus {
  registration_enabled: boolean;
}

export async function GET() {
  try {
    // This endpoint is public - no auth required
    const data = await backendFetch<RegistrationStatus>("/api/v1/auth/registration-status", {
      method: "GET",
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json(
        { detail: error.data || "Failed to fetch registration status" },
        { status: error.status }
      );
    }
    console.error("Registration status fetch error:", error);
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
  }
}
