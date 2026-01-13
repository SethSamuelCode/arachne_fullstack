"""User repository (PostgreSQL async).

Contains only database operations. Business logic (password hashing,
validation) is handled by UserService in app/services/user.py.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


async def get_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    """Get user by ID."""
    return await db.get(User, user_id)


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    """Get user by email."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    """Get multiple users with pagination."""
    result = await db.execute(select(User).offset(skip).limit(limit))
    return list(result.scalars().all())


async def count(db: AsyncSession) -> int:
    """Get total count of users."""
    from sqlalchemy import func

    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def create(
    db: AsyncSession,
    *,
    email: str,
    hashed_password: str | None,
    full_name: str | None = None,
    is_active: bool = True,
    is_superuser: bool = False,
    role: str = "user",
) -> User:
    """Create a new user.

    Note: Password should already be hashed by the service layer.
    """
    user = User(
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        is_active=is_active,
        is_superuser=is_superuser,
        role=role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def update(
    db: AsyncSession,
    *,
    db_user: User,
    update_data: dict,
) -> User:
    """Update a user.

    Note: If password needs updating, it should already be hashed.
    """
    for field, value in update_data.items():
        setattr(db_user, field, value)

    db.add(db_user)
    await db.flush()
    await db.refresh(db_user)
    return db_user


async def soft_delete(db: AsyncSession, user_id: UUID) -> User | None:
    """Soft delete a user by setting is_active=False.

    This is the preferred method for user deletion as it:
    - Preserves referential integrity
    - Allows for potential account recovery
    - Maintains audit trail
    """
    user = await get_by_id(db, user_id)
    if user:
        user.is_active = False
        db.add(user)
        await db.flush()
        await db.refresh(user)
    return user


async def hard_delete(db: AsyncSession, user_id: UUID) -> User | None:
    """Permanently delete a user from the database.

    WARNING: This is irreversible. Use soft_delete() for normal deletion.
    """
    user = await get_by_id(db, user_id)
    if user:
        await db.delete(user)
        await db.flush()
    return user


async def delete(db: AsyncSession, user_id: UUID) -> User | None:
    """Delete a user (soft delete).

    Alias for soft_delete() for backward compatibility.
    """
    return await soft_delete(db, user_id)
