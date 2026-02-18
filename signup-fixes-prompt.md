# Task: Fix 7 Signup/Registration Security Issues and Bugs

Implement all the fixes below, commit, and run tests. Each fix is described with the exact file, the problem, and what to change.

---

## Fix 1 (CRITICAL): Privilege Escalation — Anyone Can Register as Admin

**Problem:** `UserCreate` schema has a `role` field. The `POST /auth/register` endpoint uses `UserCreate` directly, so a user can send `{"role": "ADMIN"}` in the registration payload and become an admin. In `backend/app/services/user.py` line 75, non-first users get `user_in.role.value` which trusts attacker input.

**Fix:** Create a new `UserRegister` schema without a `role` field. Use it in the register endpoint and service method. Keep `UserCreate` (with `role`) for admin-only flows.

### `backend/app/schemas/user.py`
Add a new class after `UserCreate`:
```python
from pydantic import AliasChoices

class UserRegister(BaseSchema):
    """Schema for public user registration. No role field — always USER."""

    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(
        default=None,
        max_length=255,
        validation_alias=AliasChoices("name", "full_name"),
    )
```

The `validation_alias` also fixes Fix 2 (see below). `BaseSchema` already has `populate_by_name=True` so both `name` and `full_name` work on input.

### `backend/app/schemas/__init__.py`
- Add `UserRegister` to the import on line 5: `from app.schemas.user import UserCreate, UserRead, UserRegister, UserUpdate`
- Add `"UserRegister"` to the `__all__` list

### `backend/app/services/user.py`
- Add `UserRegister` to the import from `app.schemas.user`
- Add `from sqlalchemy import text` to imports
- Change `register()` method signature from `user_in: UserCreate` to `user_in: UserRegister`
- On line 75, change `user_in.role.value` to `UserRole.USER.value` so the role is always hardcoded to USER for public registration:
  ```python
  role=UserRole.ADMIN.value if is_first_user else UserRole.USER.value,
  ```

### `backend/app/api/routes/v1/auth.py`
- Change import from `UserCreate, UserRead` to `UserRead, UserRegister`
- Change the `register()` endpoint parameter from `user_in: UserCreate` to `user_in: UserRegister`

### `backend/cli/commands.py`
The CLI `user_create` (line 222) and `user_create_admin` (line 263) both call `user_service.register()` with a `UserCreate` that has a role. Since `register()` now takes `UserRegister` (no role), switch these to use `user_service.create_by_admin()` instead — which is semantically correct since CLI-created users are operator-created, not self-registering:
- Line 222: `user = await user_service.register(user_in)` → `user = await user_service.create_by_admin(user_in)`
- Line 263: same change

---

## Fix 2: `name` Field Never Saved (Frontend/Backend Mismatch)

**Problem:** Frontend sends `{"name": "John Doe"}` but backend expects `full_name`. Pydantic silently drops the unknown `name` field, so the user's name is never persisted.

**Fix:** Already handled in Fix 1 above via `validation_alias=AliasChoices("name", "full_name")` on the new `UserRegister` schema. No additional changes needed.

---

## Fix 3: No Rate Limiting on Registration Endpoint

**Problem:** Login has `@limiter.limit("5/minute")` but registration has none. Enables mass account creation and bcrypt CPU exhaustion.

**Fix in `backend/app/api/routes/v1/auth.py`:**
- Add `@limiter.limit("3/minute")` decorator to the `register()` function (between the `@router.post(...)` decorator and the function def)
- Add `request: Request` as the first parameter of `register()` (required by slowapi to extract client IP). `Request` is already imported in this file.

The function signature should become:
```python
@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    user_in: UserRegister,
    user_service: UserSvc,
    settings_service: RuntimeSettingsSvc,
):
```

---

## Fix 4: Race Condition on First-User Admin Promotion

**Problem:** In `backend/app/services/user.py`, `register()` checks `user_count == 0` then creates the user. Two concurrent requests on a fresh DB can both see count=0 and both become admin.

**Fix in `backend/app/services/user.py`:**
Add a PostgreSQL advisory lock before the count check in `register()`. Insert this right before the `user_count = await user_repo.count(self.db)` line:

```python
# Acquire advisory lock to prevent race on first-user admin promotion.
# Lock is transaction-scoped and auto-released on commit/rollback.
await self.db.execute(text("SELECT pg_advisory_xact_lock(1001)"))
```

The lock ID `1001` is an arbitrary constant. This serializes the critical section.

---

## Fix 5: Email Enumeration via Error Response

**Problem:** In `backend/app/services/user.py` line 60-63, the duplicate email error says `"Email already registered"` and includes the email in `details`. This lets attackers enumerate which emails are registered.

**Fix in `backend/app/services/user.py`:**
Change the error in `register()` only (leave `create_by_admin()` as-is since admins should see specific errors):

```python
raise AlreadyExistsError(
    message="Registration failed",
)
```

Remove the `details={"email": user_in.email}` argument entirely.

---

## Fix 6: Error Information Leakage in Frontend Proxy

**Problem:** `frontend/src/app/api/auth/register/route.ts` line 21-24 interpolates the raw error object into the 500 response: `` `Internal server error: ${error}` ``. This can leak stack traces or internal details.

**Fix in `frontend/src/app/api/auth/register/route.ts`:**
Change the catch-all block to:
```typescript
console.error("Registration proxy error:", error);
return NextResponse.json(
  { detail: "Internal server error" },
  { status: 500 }
);
```

---

## Fix 7: Registration Status Defaults to Enabled on Failure

**Problem:** `frontend/src/components/auth/register-form.tsx` line 32-33 catches errors from the registration status check and sets `setRegistrationEnabled(true)`. If the backend is down, the form renders and the user fills it out only to get a confusing error on submit.

**Fix in `frontend/src/components/auth/register-form.tsx`:**

1. Change the catch block (around line 32) — remove `setRegistrationEnabled(true)`, leaving `registrationEnabled` as its initial `null`:
```typescript
} catch {
  // Cannot determine registration status — will show error UI
}
```

2. Add a new conditional render block between the `registrationEnabled === false` block and the main form return (after the "Registration Unavailable" card, before the "Create Account" card):
```tsx
// Error state — couldn't determine registration status
if (registrationEnabled === null) {
  return (
    <Card className="w-full max-w-md mx-auto">
      <CardHeader>
        <CardTitle className="text-2xl text-center">Service Unavailable</CardTitle>
      </CardHeader>
      <CardContent className="text-center space-y-4">
        <p className="text-muted-foreground">
          Unable to verify registration availability. Please try again later.
        </p>
      </CardContent>
      <CardFooter className="justify-center">
        <p className="text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href={ROUTES.LOGIN} className="text-primary hover:underline">
            Login
          </Link>
        </p>
      </CardFooter>
    </Card>
  );
}
```

---

## Fix 8: Update Tests

### `backend/tests/test_services.py`
- Change `from app.schemas.user import UserCreate` to also import `UserRegister`
- In `test_register_success` (~line 100): change `UserCreate(...)` to `UserRegister(...)` (remove `role` if present, keep `email`, `password`, `full_name`)
- In `test_register_duplicate_email` (~line 116): same change

### `backend/tests/api/test_auth.py`
- Existing tests already send `full_name` (not `role`) in JSON payloads — they should continue to pass
- Add a new test to verify privilege escalation is blocked:

```python
@pytest.mark.anyio
async def test_register_role_field_ignored(client_with_mock_service: AsyncClient):
    """Test that role field in registration payload is ignored."""
    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "email": "attacker@example.com",
            "password": "password123",
            "role": "ADMIN",
        },
    )
    # Should succeed (role field is silently ignored by UserRegister schema)
    assert response.status_code == 201
```

---

## Implementation Order

1. `backend/app/schemas/user.py` — add `UserRegister`
2. `backend/app/schemas/__init__.py` — export it
3. `backend/app/services/user.py` — new signature, hardcoded role, advisory lock, generic error
4. `backend/app/api/routes/v1/auth.py` — use `UserRegister`, add rate limit + `request` param
5. `backend/cli/commands.py` — switch to `create_by_admin()`
6. `frontend/src/app/api/auth/register/route.ts` — generic error
7. `frontend/src/components/auth/register-form.tsx` — error state UI
8. `backend/tests/test_services.py` — use `UserRegister`
9. `backend/tests/api/test_auth.py` — add privilege escalation test

After all changes, run `make test` (or `cd backend && pytest`) to verify.

## Files Modified (9 total)

- `backend/app/schemas/user.py`
- `backend/app/schemas/__init__.py`
- `backend/app/services/user.py`
- `backend/app/api/routes/v1/auth.py`
- `backend/cli/commands.py`
- `frontend/src/app/api/auth/register/route.ts`
- `frontend/src/components/auth/register-form.tsx`
- `backend/tests/test_services.py`
- `backend/tests/api/test_auth.py`
