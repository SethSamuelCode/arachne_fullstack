/**
 * JWT verification utilities for Edge Runtime (Next.js middleware).
 *
 * Uses jose library which is compatible with Web Crypto API (Edge Runtime).
 * Supports EdDSA (Ed25519) - fast, secure, small keys.
 */

import { jwtVerify, decodeJwt, importSPKI, type JWTPayload } from "jose";

/**
 * JWT payload with custom claims for auth.
 */
export interface AuthJWTPayload extends JWTPayload {
  sub: string;
  type: "access" | "refresh";
  role?: string;
  is_superuser?: boolean;
  exp?: number;
}

/**
 * Result of token verification.
 */
export interface VerifyTokenResult {
  valid: boolean;
  payload?: AuthJWTPayload;
  error?: string;
}

// Cache the imported public key to avoid re-importing on every request
let cachedPublicKey: CryptoKey | null = null;
let cachedKeyPem: string | null = null;

/**
 * Sanitize a PEM key string from environment variable.
 * 
 * Environment variables often have escaped \n instead of real newlines.
 * This function converts them to actual newlines for proper PEM parsing.
 */
function sanitizePemKey(pem: string): string {
  // Convert escaped \n to actual newlines (common in .env files)
  return pem.replace(/\\n/g, "\n");
}

/**
 * Import and cache the Ed25519 public key for verification.
 *
 * @param publicKeyPem - PEM-encoded Ed25519 public key
 * @returns CryptoKey for JWT verification
 */
async function getPublicKey(publicKeyPem: string): Promise<CryptoKey> {
  // Sanitize the PEM key (convert escaped \n to actual newlines)
  const sanitizedPem = sanitizePemKey(publicKeyPem);
  
  // Return cached key if PEM hasn't changed
  if (cachedPublicKey && cachedKeyPem === sanitizedPem) {
    return cachedPublicKey;
  }

  // EdDSA with Ed25519 curve
  cachedPublicKey = await importSPKI(sanitizedPem, "EdDSA");
  cachedKeyPem = sanitizedPem;
  return cachedPublicKey;
}

/**
 * Verify a JWT token using EdDSA (Ed25519) public key.
 *
 * @param token - JWT token string
 * @param publicKeyPem - PEM-encoded Ed25519 public key (from env)
 * @returns Verification result with payload if valid
 */
export async function verifyToken(
  token: string,
  publicKeyPem: string
): Promise<VerifyTokenResult> {
  try {
    const publicKey = await getPublicKey(publicKeyPem);
    const { payload } = await jwtVerify(token, publicKey, {
      algorithms: ["EdDSA"],
    });

    return {
      valid: true,
      payload: payload as AuthJWTPayload,
    };
  } catch (error) {
    return {
      valid: false,
      error: error instanceof Error ? error.message : "Token verification failed",
    };
  }
}

/**
 * Decode a JWT token WITHOUT verification.
 *
 * Useful for reading claims (like exp) on the client side where
 * we don't have the secret/public key, but trust the token because
 * it came from an httpOnly cookie set by our server.
 *
 * WARNING: Only use this for tokens from trusted sources (httpOnly cookies).
 * Never use for tokens from user input or localStorage.
 *
 * @param token - JWT token string
 * @returns Decoded payload or null if invalid format
 */
export function decodeTokenUnsafe(token: string): AuthJWTPayload | null {
  try {
    return decodeJwt(token) as AuthJWTPayload;
  } catch {
    return null;
  }
}

/**
 * Check if a token is expired based on its exp claim.
 *
 * @param payload - Decoded JWT payload
 * @param bufferSeconds - Seconds before actual expiry to consider expired (default: 0)
 * @returns true if token is expired or will expire within buffer
 */
export function isTokenExpired(
  payload: AuthJWTPayload,
  bufferSeconds: number = 0
): boolean {
  if (!payload.exp) {
    return true; // No expiry = treat as expired
  }

  const nowSeconds = Math.floor(Date.now() / 1000);
  return payload.exp - bufferSeconds <= nowSeconds;
}

/**
 * Get seconds until token expires.
 *
 * @param payload - Decoded JWT payload
 * @returns Seconds until expiry, or 0 if already expired
 */
export function getSecondsUntilExpiry(payload: AuthJWTPayload): number {
  if (!payload.exp) {
    return 0;
  }

  const nowSeconds = Math.floor(Date.now() / 1000);
  const remaining = payload.exp - nowSeconds;
  return Math.max(0, remaining);
}

/**
 * Check if user has admin role based on JWT claims.
 *
 * @param payload - Decoded JWT payload
 * @returns true if user is admin or superuser
 */
export function isAdmin(payload: AuthJWTPayload): boolean {
  return payload.role === "admin" || payload.is_superuser === true;
}
