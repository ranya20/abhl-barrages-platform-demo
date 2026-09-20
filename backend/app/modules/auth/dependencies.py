from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.security import TokenValidationError, decode_access_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


@dataclass(frozen=True)
class AuthPrincipal:
    id: int
    username: str
    full_name: str | None
    email: str | None
    role_code: str
    role_label: str | None
    is_active: bool
    must_change_password: bool
    jti: str

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "email": self.email,
            "role_code": self.role_code,
            "role_label": self.role_label,
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
        }


def _credentials_exception(detail: str = "Session invalide ou expirée.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_active_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> AuthPrincipal:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        jti = str(payload["jti"])
    except (TokenValidationError, KeyError, TypeError, ValueError) as exc:
        raise _credentials_exception() from exc

    row = db.execute(
        text(
            """
            SELECT
                u.id,
                u.username,
                u.full_name,
                u.email,
                u.is_active,
                COALESCE(u.must_change_password, FALSE) AS must_change_password,
                r.code AS role_code,
                r.libelle AS role_label,
                s.jti
            FROM public.auth_sessions s
            JOIN public.users u ON u.id = s.user_id
            JOIN public.roles r ON r.id = u.role_id
            WHERE s.jti = :jti
              AND s.user_id = :user_id
              AND s.revoked_at IS NULL
              AND s.expires_at > CURRENT_TIMESTAMP
            LIMIT 1;
            """
        ),
        {"jti": jti, "user_id": user_id},
    ).mappings().first()

    if not row:
        raise _credentials_exception()
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Compte désactivé ou en attente d'approbation.")

    return AuthPrincipal(
        id=int(row["id"]),
        username=row["username"],
        full_name=row["full_name"],
        email=row["email"],
        role_code=row["role_code"],
        role_label=row["role_label"],
        is_active=bool(row["is_active"]),
        must_change_password=bool(row["must_change_password"]),
        jti=row["jti"],
    )


def get_current_ready_user(
    principal: AuthPrincipal = Depends(get_current_active_user),
) -> AuthPrincipal:
    if principal.must_change_password:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PASSWORD_CHANGE_REQUIRED",
                "message": "Vous devez modifier votre mot de passe avant de continuer.",
            },
        )
    return principal


def require_roles(*allowed_roles: str):
    allowed = {role.upper() for role in allowed_roles}

    def dependency(
        principal: AuthPrincipal = Depends(get_current_ready_user),
    ) -> AuthPrincipal:
        if principal.role_code.upper() not in allowed:
            raise HTTPException(
                status_code=403,
                detail="Vous ne disposez pas des autorisations nécessaires.",
            )
        return principal

    return dependency
