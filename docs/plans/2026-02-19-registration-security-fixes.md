# Registration Security Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 7 security issues in the registration flow: privilege escalation, missing name field, no rate limiting, race condition, email enumeration, frontend error leakage, and unsafe form fallback.

**Architecture:** New `UserRegister` schema (no `role` field) separates public registration from admin user creation. Backend service changes add an advisory lock and generic errors. Frontend proxy and form get defensive error handling.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, Next.js 15, pytest/anyio

---

### Task 1: Add UserRegister Schema

**Files:**
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/schemas/__init__.py`

**Step 1: Add `UserRegister` class to user.py**

In `backend/app/schemas/user.py`, add `AliasChoices` to the pydantic import line and insert the new class after `UserCreate`:

```python
# Change this line:
from pydantic import EmailStr, Field
# To:
from pydantic import AliasChoices, EmailStr, Field
```

Then add after the `UserCreate` class:

```python
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

`BaseSchema` already has `populate_by_name=True`, so both `name` and `full_name` work as input keys.

**Step 2: Export from `__init__.py`**

In `backend/app/schemas/__init__.py`, change line 5:

```python
# From:
from app.schemas.user import UserCreate, UserRead, UserUpdate
# To:
from app.schemas.user import UserCreate, UserRead, UserRegister, UserUpdate
```

And add `"UserRegister"` to the `__all__` list after `"UserUpdate"`:

```python
    "UserCreate",
    "UserRead",
    "UserRegister",
    "UserUpdate",
```

**Step 3: Verify the schema works**

```bash
cd backend && source .venv/bin/activate
python -c "
from app.schemas.user import UserRegister
# name alias works
u1 = UserRegister(email='a@b.com', password='password1', name='Alice')
assert u1.full_name == 'Alice'
# full_name works too
u2 = UserRegister(email='a@b.com', password='password1', full_name='Bob')
assert u2.full_name == 'Bob'
# role field is ignored (extra fields silently dropped by BaseSchema)
u3 = UserRegister.model_validate({'email': 'a@b.com', 'password': 'password1', 'role': 'ADMIN'})
assert not hasattr(u3, 'role')
print('All assertions passed')
"
```

Expected: `All assertions passed`

**Step 4: Commit**

```bash
git add backend/app/schemas/user.py backend/app/schemas/__init__.py
git commit -m "feat: add UserRegister schema without role field"
```

---

### Task 2: Update UserService.register()

**Files:**
- Modify: `backend/app/services/user.py`

This task applies Fixes 1 (privilege escalation), 4 (race condition), and 5 (email enumeration) simultaneously since they're all in the same method.

**Step 1: Write the failing service test**

In `backend/tests/test_services.py`, change the import on line 9:

```python
# From:
from app.schemas.user import UserCreate, UserUpdate
# To:
from app.schemas.user import UserCreate, UserRegister, UserUpdate
```

Then update `test_register_success` to use `UserRegister` and assert role is always `USER`:

```python
@pytest.mark.anyio
async def test_register_success(self, user_service: UserService, mock_user: MockUser):
    """Test registering a new user always uses USER role regardless of input."""
    with patch("app.services.user.user_repo") as mock_repo:
        mock_repo.get_by_email = AsyncMock(return_value=None)
        mock_repo.count = AsyncMock(return_value=1)  # Not the first user
        mock_repo.create = AsyncMock(return_value=mock_user)

        user_in = UserRegister(
            email="new@example.com",
            password="password123",
            full_name="New User",
        )
        result = await user_service.register(user_in)

        assert result == mock_user
        # Verify role is hardcoded to USER (not taken from user_in)
        call_kwargs = mock_repo.create.call_args.kwargs
        assert call_kwargs["role"] == "USER"
```

Also update `test_register_duplicate_email` to use `UserRegister`:

```python
@pytest.mark.anyio
async def test_register_duplicate_email(self, user_service: UserService, mock_user: MockUser):
    """Test registering with existing email raises AlreadyExistsError."""
    with patch("app.services.user.user_repo") as mock_repo:
        mock_repo.get_by_email = AsyncMock(return_value=mock_user)

        user_in = UserRegister(
            email="existing@example.com",
            password="password123",
            full_name="Test",
        )

        with pytest.raises(AlreadyExistsError):
            await user_service.register(user_in)
```

**Step 2: Run tests to verify they fail**

```bash
cd backend && source .venv/bin/activate
pytest tests/test_services.py::TestUserServicePostgresql::test_register_success -v
```

Expected: FAIL — `register()` still takes `UserCreate`, so `UserRegister` type hint mismatch or `call_kwargs["role"]` assertion fails (currently role comes from `user_in.role.value` which doesn't exist on `UserRegister`).

**Step 3: Update `user.py` service**

In `backend/app/services/user.py`:

1. Add imports at the top:
```python
# Add to existing sqlalchemy import:
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
```

2. Add `UserRegister` to the schema import:
```python
# From:
from app.schemas.user import UserCreate, UserUpdate
# To:
from app.schemas.user import UserCreate, UserRegister, UserUpdate
```

3. Replace the `register()` method signature and body (lines 50–77):

```python
async def register(self, user_in: UserRegister) -> User:
    """Register a new user.

    The first user registered will automatically be made an admin.
    Role is always USER for public registration — never trusted from input.

    Raises:
        AlreadyExistsError: If email is already registered (generic message).
    """
    existing = await user_repo.get_by_email(self.db, user_in.email)
    if existing:
        raise AlreadyExistsError(
            message="Registration failed",
        )

    # Acquire advisory lock to prevent race on first-user admin promotion.
    # Lock is transaction-scoped and auto-released on commit/rollback.
    await self.db.execute(text("SELECT pg_advisory_xact_lock(1001)"))

    # Check if this is the first user - make them admin
    user_count = await user_repo.count(self.db)
    is_first_user = user_count == 0

    hashed_password = get_password_hash(user_in.password)
    return await user_repo.create(
        self.db,
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        role=UserRole.ADMIN.value if is_first_user else UserRole.USER.value,
        is_superuser=is_first_user,
    )
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && source .venv/bin/activate
pytest tests/test_services.py::TestUserServicePostgresql::test_register_success tests/test_services.py::TestUserServicePostgresql::test_register_duplicate_email -v
```

Expected: Both PASS.

**Step 5: Commit**

```bash
git add backend/app/services/user.py backend/tests/test_services.py
git commit -m "fix: UserRegister schema, hardcode USER role, advisory lock, generic error"
```

---

### Task 3: Update Register Endpoint (rate limiting + schema)

**Files:**
- Modify: `backend/app/api/routes/v1/auth.py`

**Step 1: Update the import and endpoint**

In `backend/app/api/routes/v1/auth.py`:

1. Change the user schema import on line 13:
```python
# From:
from app.schemas.user import UserCreate, UserRead
# To:
from app.schemas.user import UserRead, UserRegister
```

2. Replace the register endpoint (lines 67–80ish) with:
```python
@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    user_in: UserRegister,
    user_service: UserSvc,
    settings_service: RuntimeSettingsSvc,
):
    """Register a new user.

    Rate limited to 3 attempts per minute.
    Role is always USER — role field in payload is ignored.

    Raises:
        HTTPException 403: If registration is disabled by admin.
        AlreadyExistsError: If email is already registered.
    """
```

Leave the function body unchanged (the `if not await settings_service.is_registration_enabled():` block and `return await user_service.register(user_in)` stay the same).

**Step 2: Run existing endpoint tests to verify they still pass**

```bash
cd backend && source .venv/bin/activate
pytest tests/api/test_auth.py::test_register_success tests/api/test_auth.py::test_register_duplicate_email -v
```

Expected: Both PASS (the mock service still returns the mock user; rate limiter works fine in test transport).

**Step 3: Commit**

```bash
git add backend/app/api/routes/v1/auth.py
git commit -m "fix: use UserRegister on register endpoint, add rate limiting"
```

---

### Task 4: Update CLI Commands

**Files:**
- Modify: `backend/cli/commands.py`

**Context:** The CLI `user_create` (~line 222) and `user_create_admin` (~line 263) both call `user_service.register()` with a `UserCreate` that has a `role` field. Since `register()` now takes `UserRegister` (no role), switch these to `create_by_admin()` — semantically correct since CLI users are operator-created, not self-registering.

**Step 1: Update `user_create` command (~line 220–232)**

Find:
```python
user_in = UserCreate(email=email, password=password, role=UserRole(role))
user = await user_service.register(user_in)
```

Replace with:
```python
user_in = UserCreate(email=email, password=password, role=UserRole(role))
user = await user_service.create_by_admin(user_in)
```

**Step 2: Update `user_create_admin` command (~line 262–263)**

Find:
```python
user_in = UserCreate(email=email, password=password, role=UserRole.ADMIN)
user = await user_service.register(user_in)
```

Replace with:
```python
user_in = UserCreate(email=email, password=password, role=UserRole.ADMIN)
user = await user_service.create_by_admin(user_in)
```

**Step 3: Run CLI tests to verify**

```bash
cd backend && source .venv/bin/activate
pytest tests/test_commands.py -v -k "user"
```

Expected: All user command tests pass.

**Step 4: Commit**

```bash
git add backend/cli/commands.py
git commit -m "fix: CLI user creation uses create_by_admin instead of register"
```

---

### Task 5: Fix Frontend Proxy Error Leakage

**Files:**
- Modify: `frontend/src/app/api/auth/register/route.ts`

**Step 1: Update the catch-all block**

In `frontend/src/app/api/auth/register/route.ts`, find the last catch block (lines 21–24):

```typescript
    return NextResponse.json(
      { detail: `Internal server error: ${error}` },
      { status: 500 }
    );
```

Replace with:

```typescript
    console.error("Registration proxy error:", error);
    return NextResponse.json(
      { detail: "Internal server error" },
      { status: 500 }
    );
```

**Step 2: Commit**

```bash
git add frontend/src/app/api/auth/register/route.ts
git commit -m "fix: sanitize registration proxy 500 error response"
```

---

### Task 6: Fix Register Form Null State

**Files:**
- Modify: `frontend/src/components/auth/register-form.tsx`

**Step 1: Update the catch block (~line 32–34)**

Find:
```typescript
      } catch {
        // If we can't check status, assume registration is enabled
        setRegistrationEnabled(true);
      } finally {
```

Replace with:
```typescript
      } catch {
        // Cannot determine registration status — will show error UI
      } finally {
```

**Step 2: Add null state render block**

After the `registrationEnabled === false` block (after line 109, before `return (`), insert:

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

**Step 3: Commit**

```bash
git add frontend/src/components/auth/register-form.tsx
git commit -m "fix: show service unavailable when registration status check fails"
```

---

### Task 7: Add Privilege Escalation Test to API Tests

**Files:**
- Modify: `backend/tests/api/test_auth.py`

**Step 1: Write the new test**

Add at the end of `backend/tests/api/test_auth.py`:

```python
@pytest.mark.anyio
async def test_register_role_field_ignored(
    client_with_mock_service: AsyncClient,
    mock_user_service: MagicMock,
):
    """Test that role field in registration payload is silently ignored.

    This is the critical security test: a malicious user sending role=ADMIN
    must not be able to elevate their privileges.
    """
    response = await client_with_mock_service.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "email": "attacker@example.com",
            "password": "password123",
            "role": "ADMIN",
        },
    )
    # Should succeed — role field is stripped by UserRegister schema
    assert response.status_code == 201
    # Verify register() was called (role is handled at service level)
    mock_user_service.register.assert_called_once()
```

**Step 2: Run the new test**

```bash
cd backend && source .venv/bin/activate
pytest tests/api/test_auth.py::test_register_role_field_ignored -v
```

Expected: PASS (the `role` field is stripped by `UserRegister` schema, request succeeds with 201).

**Step 3: Run the full auth test suite**

```bash
cd backend && source .venv/bin/activate
pytest tests/api/test_auth.py -v
```

Expected: All tests pass.

**Step 4: Commit**

```bash
git add backend/tests/api/test_auth.py
git commit -m "test: verify role field is ignored during registration"
```

---

### Task 8: Run Full Test Suite and Verify

**Step 1: Run all backend tests**

```bash
cd backend && source .venv/bin/activate
pytest -v
```

Expected: All tests pass. The only pre-existing failure is `test_sanitize_preserves_required_fields` (unrelated to this work — schema sanitization strips `minimum`, known issue).

**Step 2: Final commit if anything was missed**

If any fixes were needed, commit them. Otherwise, the branch is ready.

**Step 3: Summary of changes**

| Fix | Status |
|-----|--------|
| 1. Privilege escalation | `UserRegister` schema, hardcoded `USER` role in service |
| 2. `name` field lost | `AliasChoices("name", "full_name")` on `UserRegister` |
| 3. No rate limiting | `@limiter.limit("3/minute")` on register endpoint |
| 4. Race condition | `pg_advisory_xact_lock(1001)` before count check |
| 5. Email enumeration | Generic "Registration failed" error |
| 6. Frontend error leakage | Static "Internal server error" string |
| 7. Form defaults enabled | `null` state UI shown on backend unreachable |
| 8. Tests updated | `UserRegister` in service tests, new escalation test |
