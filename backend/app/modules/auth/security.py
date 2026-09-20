from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.config import settings


password_hash = PasswordHash.recommended()


class TokenValidationError(ValueError):
    """Jeton absent, invalide ou expiré."""


def validate_password_strength(password: str) -> None:
    errors: list[str] = []

    if len(password) < 10:
        errors.append("au moins 10 caractères")
    if not re.search(r"[a-z]", password):
        errors.append("une lettre minuscule")
    if not re.search(r"[A-Z]", password):
        errors.append("une lettre majuscule")
    if not re.search(r"\d", password):
        errors.append("un chiffre")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("un caractère spécial")

    if errors:
        raise ValueError("Le mot de passe doit contenir " + ", ".join(errors) + ".")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    if not hashed_password:
        return False
    try:
        return password_hash.verify(password, hashed_password)
    except Exception:
        return False


def create_access_token(*, user_id: int, username: str, role_code: str) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES)
    jti = uuid4().hex

    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role_code,
        "type": "access",
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, jti, expires_at


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except InvalidTokenError as exc:
        raise TokenValidationError("Session invalide ou expirée.") from exc

    if payload.get("type") != "access":
        raise TokenValidationError("Type de jeton invalide.")

    return payload
