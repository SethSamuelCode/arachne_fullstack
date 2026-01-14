# Auth Security Upgrade Plan

## Overview

**Problem:** Access tokens expire after 30 minutes with no automatic refresh mechanism. The frontend loses authentication silently, and route protection is inconsistent across pages.

**Solution:** Comprehensive security upgrade using EdDSA (Ed25519) asymmetric JWT (private key signs, public key verifies), 60-min token expiry with proactive refresh, middleware-level route protection with role checking, server-side token refresh on 401, and session invalidation on role changes.

---

## Background

### Current State
- **Token Expiry:** 30 minutes (too short without auto-refresh)
- **JWT Algorithm:** HS256 (symmetric - shared secret)
- **Route Protection:** Inconsistent - only some pages redirect
- **Token Refresh:** Manual only, no 401 retry logic
- **Session Storage:** PostgreSQL (`sessions` table with hashed refresh tokens)

### Target State
- **Token Expiry:** 60 minutes with proactive refresh
- **JWT Algorithm:** EdDSA/Ed25519 (asymmetric - private signs, public verifies)
- **Route Protection:** Middleware-level for all routes including admin
- **Token Refresh:** Automatic on 401 + proactive before expiry
- **Session Storage:** PostgreSQL (unchanged, already secure)

---

## Key Concepts

### Edge Runtime
"Edge" refers to the server-side layer of Next.js (middleware, API routes) that runs before React components. It uses a lightweight V8 isolate with Web APIs only - not full Node.js. Libraries like `jsonwebtoken` don't work; use `jose` instead.

### EdDSA (Ed25519) vs HS256 vs RS256
- **HS256:** Single shared secret for signing AND verifying. If compromised, attacker can forge tokens.
- **RS256:** RSA private key (backend only) signs, public key verifies. Secure but slow with large keys (4096-bit).
- **EdDSA (Ed25519):** Modern elliptic curve. Private key signs, public key verifies. Fast, secure, tiny keys (~64 bytes vs 4096 bytes).

---

## Implementation Steps

### Phase 1: Backend JWT Upgrade

#### Step 1: Generate Ed25519 Key Pair
```bash
openssl genpkey -algorithm Ed25519 -out private_key.pem
openssl pkey -in private_key.pem -pubout -out public_key.pem
```
Store keys securely (not in repo). Add to environment variables.

#### Step 2: Add `cryptography` Dependency
**File:** `backend/pyproject.toml`
```toml
"cryptography>=42.0.0",
```

#### Step 3: Update JWT Configuration
**File:** `backend/app/core/config.py`
- Add `JWT_PRIVATE_KEY: str` (for signing)
- Add `JWT_PUBLIC_KEY: str` (for verification)
- Change `ALGORITHM: str = "RS256"`
- Update `ACCESS_TOKEN_EXPIRE_MINUTES: int = 60`
- Add field validator ensuring keys are set in production

#### Step 4: Update Token Functions
**File:** `backend/app/core/security.py`
- Modify `create_access_token` to sign with `JWT_PRIVATE_KEY`
- Modify `create_refresh_token` to sign with `JWT_PRIVATE_KEY`
- Add `role: str` and `is_superuser: bool` parameters to token payload
- Update verification to use `JWT_PUBLIC_KEY`

#### Step 5: Pass Role Claims During Token Creation
**File:** `backend/app/api/routes/v1/auth.py`
- During login: pass `user.role.value` and `user.is_superuser` to `create_access_token`
- During refresh: same - include role claims in new token

#### Step 6: Invalidate Sessions on Role Change
**File:** `backend/app/services/user.py`
- When `role` or `is_superuser` is updated, call `session_repo.deactivate_all_user_sessions(db, user_id)`
- Forces re-login with fresh token containing updated claims

---

### Phase 2: Frontend Auth Infrastructure

#### Step 7: Install `jose` Library
```bash
cd frontend && npm install jose
```

#### Step 8: Add JWT Public Key to Frontend Environment
**Files:** `.env.local`, `frontend/next.config.ts`
- Add `JWT_PUBLIC_KEY` (server-only, not `NEXT_PUBLIC_`)
- Middleware runs server-side so can access non-public env vars

#### Step 9: Create JWT Verification Utility
**File:** `frontend/src/lib/jwt.ts` (new file)
- Use `jose.importSPKI` to import public key (cache for performance)
- Use `jose.jwtVerify` to verify and decode tokens
- Export `verifyToken(token: string)` function returning payload or error

#### Step 10: Update Cookie Max Age
**Files:**
- `frontend/src/app/api/auth/login/route.ts` - change `maxAge: 60 * 60` (60 mins)
- `frontend/src/app/api/auth/refresh/route.ts` - same change

---

### Phase 3: Middleware Route Protection

#### Step 11: Rewrite Middleware with Auth + Admin Protection
**File:** `frontend/src/middleware.ts`

Features:
- JWT verification using RS256 public key
- `PUBLIC_ROUTES`: `/`, `/login`, `/register`, `/auth/callback`
- `ADMIN_ROUTES`: `/admin/*`
- Redirect unauthenticated users to `/login?callbackUrl=...`
- Redirect non-admins from admin routes to `/dashboard`
- Redirect authenticated users away from login/register pages
- Combine with existing i18n middleware

---

### Phase 4: Automatic Token Refresh

#### Step 12: Add 401 Interceptor with Retry
**File:** `frontend/src/lib/api-client.ts`
- On 401 response, call `/api/auth/refresh`
- Retry the original request once
- If refresh fails, clear auth state and redirect to `/login`

#### Step 13: Add Proactive JWT-Based Refresh
**File:** `frontend/src/hooks/use-auth.ts`
- Schedule refresh ~5 minutes before token expiry (55 mins)
- Use setTimeout with automatic rescheduling
- Clear timer on logout

#### Step 14: Validate Persisted State on Mount
**File:** `frontend/src/hooks/use-auth.ts`
- On mount, call `/api/auth/me`
- If 401, call `useAuthStore.persist.clearStorage()` to clear stale localStorage

---

### Phase 5: Cleanup & Polish

#### Step 15: Handle Callback URL After Login
**File:** `frontend/src/hooks/use-auth.ts`
- After successful login, check for `callbackUrl` query param
- Redirect there instead of hardcoded `/dashboard`

#### Step 16: Remove Redundant Client-Side Admin Checks
**Files:**
- `frontend/src/app/[locale]/(dashboard)/admin/users/page.tsx`
- `frontend/src/app/[locale]/(dashboard)/admin/settings/page.tsx`
- Delete `useEffect` admin redirect logic (middleware handles this now)

---

### Phase 6: Testing & Documentation

#### Step 17: Add Comprehensive Tests
**Backend tests:**
- Test RS256 token generation and verification
- Test role claim inclusion in JWT payload
- Test session invalidation on role change

**Frontend tests:**
- Test middleware redirects (authenticated, unauthenticated, admin, non-admin)
- Test 401 retry logic
- Test proactive refresh timing

#### Step 18: Update Environment Documentation
- Document required env vars in README or `.env.example`:
  - `JWT_PRIVATE_KEY` (backend only)
  - `JWT_PUBLIC_KEY` (backend + frontend)
  - `JWT_ALGORITHM=RS256`
- Include key generation commands

#### Step 19: Session Storage Confirmation
Sessions are stored in **PostgreSQL** (not Redis) in the `sessions` table:
- `refresh_token_hash` - bcrypt hashed refresh token
- `user_id` - foreign key to users table
- `is_active` - for soft-delete/logout
- `expires_at` - token expiration
- `last_used_at` - activity tracking
- `device_name`, `ip_address`, `user_agent` - audit info

The existing `deactivate_all_user_sessions(db, user_id)` function in `session_repo` handles session invalidation for Step 6.

---

## File Change Summary

| File | Action |
|------|--------|
| `backend/pyproject.toml` | Add `cryptography>=42.0.0` |
| `backend/app/core/config.py` | Add JWT keys, change algorithm, increase expiry |
| `backend/app/core/security.py` | EdDSA signing, add role claims |
| `backend/app/api/routes/v1/auth.py` | Pass role to token creation |
| `backend/app/services/user.py` | Invalidate sessions on role change |
| `frontend/package.json` | Add `jose` |
| `frontend/src/lib/jwt.ts` | New file - JWT verification utility |
| `frontend/src/middleware.ts` | Rewrite with auth + admin protection |
| `frontend/src/lib/api-client.ts` | Add 401 retry logic |
| `frontend/src/app/api/auth/login/route.ts` | Update cookie maxAge |
| `frontend/src/app/api/auth/refresh/route.ts` | Update cookie maxAge |
| `frontend/src/hooks/use-auth.ts` | Proactive refresh, callback URL, validate on mount |
| `frontend/src/app/[locale]/(dashboard)/admin/*/page.tsx` | Remove redundant checks |

---

## Environment Variables

### Backend (.env)
```bash
# JWT Ed25519 Keys (generate with openssl commands above)
# Convert to single-line: awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}' private_key.pem
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMC4CAQAw...\n-----END PRIVATE KEY-----"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMCowBQYD...\n-----END PUBLIC KEY-----"

# Algorithm (EdDSA for Ed25519, HS256 for fallback)
ALGORITHM="EdDSA"

# Token expiry
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

### Frontend (.env.local)
```bash
# JWT Public Key for middleware verification (server-only)
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMCowBQYD...\n-----END PUBLIC KEY-----"
```

---

## Testing Checklist

- [ ] Generate Ed25519 key pair and configure env vars
- [ ] Login creates tokens with role claims
- [ ] Token refresh creates new tokens with role claims
- [ ] Middleware blocks unauthenticated access to protected routes
- [ ] Middleware blocks non-admin access to admin routes
- [ ] 401 responses trigger automatic refresh and retry
- [ ] Proactive refresh occurs before token expiry
- [ ] Role change invalidates all user sessions
- [ ] Callback URL preserved through login redirect
- [ ] Persisted auth state cleared when cookies expire
