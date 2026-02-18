# Plan: Fix Signup/Registration Security and Bugs

## Overview

Fix 7 identified issues in the signup code path: a critical privilege escalation vulnerability, a field mapping bug, missing rate limiting, a race condition, email enumeration, error leakage, and a UX issue.

---

## Step 1: Create `UserRegister` schema (Issue #1 + #2)

**File:** `backend/app/schemas/user.py`

- Add a new `UserRegister` schema class that has only `email`, `password`, and `full_name` — no `role` field
- Use `validation_alias=AliasChoices("name", "full_name")` on `full_name` so the frontend's `name` field is accepted (fixes issue #2)
- `UserCreate` remains unchanged for admin use

**File:** `backend/app/schemas/__init__.py`

- Add `UserRegister` to the import from `app.schemas.user` (line 5)
- Add `"UserRegister"` to the `__all__` list

## Step 2: Update `register()` service method (Issues #1, #4, #5)

**File:** `backend/app/services/user.py`

- Change `register()` signature from `UserCreate` to `UserRegister`
- Import `UserRegister` and `text` from sqlalchemy
- Hardcode `role=UserRole.USER.value` instead of trusting `user_in.role.value` (fixes issue #1)
- Add `pg_advisory_xact_lock` before the first-user count check to prevent race conditions (fixes issue #4)
- Change the duplicate email error message to a generic `"Registration failed"` with no email in details (fixes issue #5)

## Step 3: Update registration route (Issues #1, #3)

**File:** `backend/app/api/routes/v1/auth.py`

- Import `UserRegister` instead of `UserCreate`
- Change the `register()` endpoint parameter from `UserCreate` to `UserRegister`
- Add `@limiter.limit("3/minute")` decorator (fixes issue #3)
- Add `request: Request` parameter (required by slowapi)

## Step 4: Update CLI commands (Impact of issue #1 fix)

**File:** `backend/cli/commands.py`

- In `user_create` (line 222): change `user_service.register(user_in)` to `user_service.create_by_admin(user_in)` since CLI users are operator-created, not self-registering
- In `user_create_admin` (line 263): same change — use `create_by_admin()` instead of `register()`

## Step 5: Fix frontend proxy error leakage (Issue #6)

**File:** `frontend/src/app/api/auth/register/route.ts`

- Change the catch-all 500 response to use a generic `"Internal server error"` message
- Add `console.error()` to log the actual error server-side

## Step 6: Fix registration status error handling (Issue #7)

**File:** `frontend/src/components/auth/register-form.tsx`

- Remove `setRegistrationEnabled(true)` from the catch block — leave `registrationEnabled` as `null`
- Add a new conditional render block for `registrationEnabled === null` (after `checkingStatus` and `registrationEnabled === false` checks) showing a "Service Unavailable" message

## Step 7: Update tests

**File:** `backend/tests/test_services.py`

- Change `UserCreate` to `UserRegister` in `test_register_success` (line 100) and `test_register_duplicate_email` (line 116)
- Update the import accordingly

**File:** `backend/tests/api/test_auth.py`

- Existing tests use `full_name` in JSON payloads — these will continue to work with the `AliasChoices` on `UserRegister`
- Add a new test `test_register_role_ignored` that sends `{"email": "...", "password": "...", "role": "ADMIN"}` and verifies the role field is ignored (user gets USER role)
- Update the duplicate email test to expect the generic `"Registration failed"` message

---

## Files Modified (8 total)

| File | Changes |
|------|---------|
| `backend/app/schemas/user.py` | Add `UserRegister` schema |
| `backend/app/schemas/__init__.py` | Export `UserRegister` |
| `backend/app/services/user.py` | New signature, hardcoded role, advisory lock, generic error |
| `backend/app/api/routes/v1/auth.py` | Use `UserRegister`, add rate limit |
| `backend/cli/commands.py` | Switch to `create_by_admin()` |
| `frontend/src/app/api/auth/register/route.ts` | Generic error message |
| `frontend/src/components/auth/register-form.tsx` | Error state UI |
| `backend/tests/test_services.py` | Use `UserRegister` in tests |
