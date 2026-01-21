"""Security utilities for JWT authentication with EdDSA (Ed25519)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

_ALGORITHM = "EdDSA"


def _get_signing_key() -> str:
    """Get the Ed25519 private key for signing JWTs.

    Raises:
        ValueError: If JWT_PRIVATE_KEY is not configured.
    """
    if not settings.JWT_PRIVATE_KEY:
        raise ValueError(
            "JWT_PRIVATE_KEY is required. Generate with: "
            "openssl genpkey -algorithm Ed25519 -out private_key.pem"
        )
    return settings.JWT_PRIVATE_KEY


def _get_verification_key() -> str:
    """Get the Ed25519 public key for verifying JWTs.

    Raises:
        ValueError: If JWT_PUBLIC_KEY is not configured.
    """
    if not settings.JWT_PUBLIC_KEY:
        raise ValueError(
            "JWT_PUBLIC_KEY is required. Generate with: "
            "openssl pkey -in private_key.pem -pubout -out public_key.pem"
        )
    return settings.JWT_PUBLIC_KEY


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
    *,
    role: str | None = None,
    is_superuser: bool = False,
) -> str:
    """Create a JWT access token with optional role claims.

    Args:
        subject: User ID or unique identifier.
        expires_delta: Custom expiration time delta.
        role: User role (e.g., "admin", "user") to embed in token.
        is_superuser: Whether user is a superuser, embedded in token.

    Returns:
        Encoded JWT access token string.
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: dict[str, Any] = {
        "exp": expire,
        "sub": str(subject),
        "type": "access",
    }

    # Add role claims for middleware authorization
    if role is not None:
        to_encode["role"] = role
    if is_superuser:
        to_encode["is_superuser"] = is_superuser

    return jwt.encode(to_encode, _get_signing_key(), algorithm=_ALGORITHM)


def create_refresh_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token.

    Note: Refresh tokens don't include role claims since they're only
    used to obtain new access tokens, which will have fresh claims.
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    return jwt.encode(to_encode, _get_signing_key(), algorithm=_ALGORITHM)


def verify_token(token: str) -> dict[str, Any] | None:
    """Verify a JWT token and return payload using EdDSA."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        payload = jwt.decode(
            token,
            _get_verification_key(),
            algorithms=[_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token verification failed: token has expired")
        return None
    except jwt.InvalidSignatureError:
        logger.warning("Token verification failed: invalid signature (key mismatch?)")
        return None
    except jwt.PyJWTError as e:
        logger.warning(f"Token verification failed: {type(e).__name__}: {e}")
        return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")
