/**
 * Next.js Middleware with Authentication and i18n.
 *
 * This middleware runs on the Edge Runtime before every request and handles:
 * 1. JWT token verification for protected routes
 * 2. Role-based access control (admin routes)
 * 3. Internationalization (i18n) locale routing
 *
 * Route Protection:
 * - PUBLIC_ROUTES: Accessible without authentication
 * - ADMIN_ROUTES: Require admin role or is_superuser claim
 * - All other routes: Require valid authentication
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import createIntlMiddleware from "next-intl/middleware";
import { verifyToken, isAdmin, type AuthJWTPayload } from "@/lib/jwt";
import { routing } from "@/i18n/routing";
import { locales } from "@/i18n/config";

// Routes that don't require authentication
const PUBLIC_ROUTES = ["/", "/login", "/register", "/auth/callback"];

// Routes that redirect authenticated users (login/register pages)
const AUTH_ROUTES = ["/login", "/register"];

// Routes that require admin role
const ADMIN_ROUTES = ["/admin"];

// Initialize i18n middleware using shared routing configuration
const intlMiddleware = createIntlMiddleware(routing);

/**
 * Strip locale prefix from pathname for route matching.
 * e.g., "/en/dashboard" → "/dashboard", "/pl/admin/users" → "/admin/users"
 */
function stripLocalePrefix(pathname: string): string {
  const localePattern = new RegExp(`^/(${locales.join("|")})`);
  return pathname.replace(localePattern, "") || "/";
}

/**
 * Check if pathname matches any route in the list.
 * Supports exact matches and prefix matches.
 */
function matchesRoute(pathname: string, routes: string[]): boolean {
  return routes.some((route) => {
    if (route === "/") {
      return pathname === "/";
    }
    return pathname === route || pathname.startsWith(`${route}/`);
  });
}

/**
 * Build redirect URL preserving locale if present.
 */
function buildRedirectUrl(
  request: NextRequest,
  targetPath: string,
  searchParams?: Record<string, string>
): URL {
  const url = new URL(targetPath, request.url);

  if (searchParams) {
    Object.entries(searchParams).forEach(([key, value]) => {
      url.searchParams.set(key, value);
    });
  }

  return url;
}

export default async function middleware(
  request: NextRequest
): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const pathnameWithoutLocale = stripLocalePrefix(pathname);

  // Get JWT public key from environment
  const publicKey = process.env.JWT_PUBLIC_KEY;

  // Verify authentication status
  let isAuthenticated = false;
  let userIsAdmin = false;
  let payload: AuthJWTPayload | undefined;

  const token = request.cookies.get("access_token")?.value;

  if (token && publicKey) {
    const result = await verifyToken(token, publicKey);
    if (result.valid && result.payload) {
      isAuthenticated = true;
      payload = result.payload;
      userIsAdmin = isAdmin(payload);
    }
  } else if (token && !publicKey) {
    // Fallback: If no public key configured, trust token existence
    // This allows development without RS256 keys configured
    // WARNING: This is less secure - configure JWT_PUBLIC_KEY in production
    isAuthenticated = true;
    // Can't verify admin status without decoding - default to false
    // In production, always configure JWT_PUBLIC_KEY
  }

  // Check route types
  const isPublicRoute = matchesRoute(pathnameWithoutLocale, PUBLIC_ROUTES);
  const isAuthRoute = matchesRoute(pathnameWithoutLocale, AUTH_ROUTES);
  const isAdminRoute = matchesRoute(pathnameWithoutLocale, ADMIN_ROUTES);

  // Redirect authenticated users away from login/register pages
  if (isAuthenticated && isAuthRoute) {
    return NextResponse.redirect(buildRedirectUrl(request, "/dashboard"));
  }

  // Redirect unauthenticated users from protected routes to login
  if (!isAuthenticated && !isPublicRoute) {
    return NextResponse.redirect(
      buildRedirectUrl(request, "/login", { callbackUrl: pathname })
    );
  }

  // Redirect non-admin users from admin routes
  if (isAdminRoute && isAuthenticated && !userIsAdmin) {
    return NextResponse.redirect(buildRedirectUrl(request, "/dashboard"));
  }

  // Continue with i18n middleware for all other cases
  return intlMiddleware(request);
}

export const config = {
  // Match all pathnames except for:
  // - /api (API routes)
  // - /_next (Next.js internals)
  // - /static (inside /public)
  // - /_vercel (Vercel internals)
  // - All root files like favicon.ico, robots.txt, etc.
  matcher: ["/((?!api|_next|_vercel|static|.*\\..*).*)" ],
};
