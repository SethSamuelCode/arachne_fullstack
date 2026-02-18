# Registration Security Fixes — Design

**Date:** 2026-02-19
**Branch:** `fix/auth`
**Status:** Approved

## Problem

Seven security issues in the signup/registration flow ranging from a critical privilege escalation to minor information leakage.

## Issues and Fixes

### Fix 1 (CRITICAL): Privilege Escalation

**Problem:** `UserCreate` has a `role` field. `POST /auth/register` uses `UserCreate` directly, so any user can send `{"role": "ADMIN"}` and become an admin. `user.py:75` trusts `user_in.role.value` for non-first users.

**Fix:** Create `UserRegister` schema (no `role` field). Use it in the register endpoint and `register()` service method. Role is always hardcoded to `UserRole.USER` for public registration. Keep `UserCreate` (with `role`) for admin-only flows.

### Fix 2: `name` Field Never Saved

**Problem:** Frontend sends `{"name": "John Doe"}` but backend expects `full_name`. Pydantic silently drops the unknown field.

**Fix:** `UserRegister.full_name` uses `validation_alias=AliasChoices("name", "full_name")` — handles both keys. Resolved by Fix 1 with no additional changes needed.

### Fix 3: No Rate Limiting on Registration

**Problem:** Login has `@limiter.limit("5/minute")`. Register has none — enables mass account creation and bcrypt CPU exhaustion.

**Fix:** Add `@limiter.limit("3/minute")` and `request: Request` parameter to the register endpoint.

### Fix 4: Race Condition on First-User Admin Promotion

**Problem:** `register()` checks `user_count == 0` then creates the user. Two concurrent requests on a fresh DB can both see count=0 and both become admin.

**Fix:** PostgreSQL advisory lock before the count check: `SELECT pg_advisory_xact_lock(1001)`. Lock is transaction-scoped, auto-released on commit/rollback. Lock ID `1001` is an arbitrary constant.

### Fix 5: Email Enumeration

**Problem:** Duplicate email error says `"Email already registered"` and includes the email in details — lets attackers enumerate registered emails.

**Fix:** Change error in `register()` only to generic `"Registration failed"` with no details. `create_by_admin()` keeps specific errors (admins need them).

### Fix 6: Error Information Leakage in Frontend Proxy

**Problem:** `register/route.ts` catch-all returns `` `Internal server error: ${error}` `` — can leak stack traces or internal details.

**Fix:** Return static `{ detail: "Internal server error" }` and log the error server-side only.

### Fix 7: Registration Form Defaults to Enabled on Failure

**Problem:** If the backend is unreachable, the registration status check fails and `setRegistrationEnabled(true)` is called — the form renders but any submit will fail with a confusing error.

**Fix:** Leave `registrationEnabled` as `null` in the catch block. Add a "Service Unavailable" card for the `null` state (only shown after loading completes).

## Files Changed (9 total)

| File | Change |
|------|--------|
| `backend/app/schemas/user.py` | Add `UserRegister` class |
| `backend/app/schemas/__init__.py` | Export `UserRegister` |
| `backend/app/services/user.py` | New signature, hardcoded role, advisory lock, generic error |
| `backend/app/api/routes/v1/auth.py` | Use `UserRegister`, add rate limit + `request` param |
| `backend/cli/commands.py` | Switch CLI user creation to `create_by_admin()` |
| `frontend/src/app/api/auth/register/route.ts` | Generic 500 error |
| `frontend/src/components/auth/register-form.tsx` | `null` error state UI |
| `backend/tests/test_services.py` | Switch to `UserRegister` |
| `backend/tests/api/test_auth.py` | Add privilege escalation test |

## Implementation Order

1. `backend/app/schemas/user.py` — add `UserRegister`
2. `backend/app/schemas/__init__.py` — export it
3. `backend/app/services/user.py` — new signature, hardcoded role, advisory lock, generic error
4. `backend/app/api/routes/v1/auth.py` — use `UserRegister`, rate limit, `request` param
5. `backend/cli/commands.py` — switch to `create_by_admin()`
6. `frontend/src/app/api/auth/register/route.ts` — generic error
7. `frontend/src/components/auth/register-form.tsx` — error state UI
8. `backend/tests/test_services.py` — use `UserRegister`
9. `backend/tests/api/test_auth.py` — add privilege escalation test

## Testing

After all changes: `cd backend && source .venv/bin/activate && pytest`

Key assertions:
- `test_register_role_field_ignored`: POSTing `{"role": "ADMIN"}` returns 201 but user is `USER` role
- `test_register_duplicate_email`: error message is generic (no email in details)
- Existing auth tests continue to pass
