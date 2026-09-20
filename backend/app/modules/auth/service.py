from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.auth.dependencies import AuthPrincipal
from app.modules.auth.schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    ChangePasswordRequest,
    LoginRequest,
    SignUpRequest,
)
from app.modules.auth.security import (
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)


USER_SELECT = """
    SELECT
        u.id,
        u.username,
        u.full_name,
        u.email,
        u.password_hash,
        u.is_active,
        COALESCE(u.must_change_password, FALSE) AS must_change_password,
        COALESCE(u.failed_login_attempts, 0) AS failed_login_attempts,
        u.locked_until,
        u.last_login_at,
        u.created_at,
        r.id AS role_id,
        r.code AS role_code,
        r.libelle AS role_label
    FROM public.users u
    LEFT JOIN public.roles r ON r.id = u.role_id
"""


def _public_user(row: Any) -> dict:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role_code": row["role_code"] or "CONSULTATION",
        "role_label": row["role_label"],
        "is_active": bool(row["is_active"]),
        "must_change_password": bool(row["must_change_password"]),
        "last_login_at": row.get("last_login_at"),
        "created_at": row.get("created_at"),
    }


def _role_id(db: Session, role_code: str) -> int:
    role_id = db.execute(
        text("SELECT id FROM public.roles WHERE code = :code LIMIT 1;"),
        {"code": role_code.upper()},
    ).scalar()
    if role_id is None:
        raise ValueError(f"Rôle inconnu : {role_code}")
    return int(role_id)


def _audit(
    db: Session,
    *,
    action: str,
    success: bool,
    user_id: int | None = None,
    username_attempted: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: str | None = None,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO public.auth_audit_log (
                user_id, username_attempted, action, success,
                ip_address, user_agent, details
            ) VALUES (
                :user_id, :username_attempted, :action, :success,
                :ip_address, :user_agent, :details
            );
            """
        ),
        {
            "user_id": user_id,
            "username_attempted": username_attempted,
            "action": action,
            "success": success,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "details": details,
        },
    )


def signup_user(
    db: Session,
    payload: SignUpRequest,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> dict:
    validate_password_strength(payload.password)
    role_id = _role_id(db, "CONSULTATION")

    existing = db.execute(
        text(
            """
            SELECT id
            FROM public.users
            WHERE LOWER(username) = LOWER(:username)
               OR LOWER(COALESCE(email, '')) = LOWER(:email)
            LIMIT 1;
            """
        ),
        {"username": payload.username, "email": payload.email},
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ce nom d'utilisateur ou cette adresse e-mail est déjà utilisé.",
        )

    try:
        row = db.execute(
            text(
                """
                INSERT INTO public.users (
                    username, full_name, email, password_hash, role_id,
                    is_active, must_change_password
                ) VALUES (
                    :username, :full_name, :email, :password_hash, :role_id,
                    FALSE, FALSE
                )
                RETURNING id;
                """
            ),
            {
                "username": payload.username,
                "full_name": payload.full_name,
                "email": payload.email,
                "password_hash": hash_password(payload.password),
                "role_id": role_id,
            },
        ).first()
        user_id = int(row[0])
        _audit(
            db,
            action="SIGNUP",
            success=True,
            user_id=user_id,
            username_attempted=payload.username,
            ip_address=ip_address,
            user_agent=user_agent,
            details="Compte créé en attente d'approbation.",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ce nom d'utilisateur ou cette adresse e-mail est déjà utilisé.",
        ) from exc

    return {
        "status": "pending_approval",
        "message": (
            "Votre demande de compte a été enregistrée. "
            "Un administrateur ABHL doit maintenant l'approuver."
        ),
    }


def login_user(
    db: Session,
    payload: LoginRequest,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> dict:
    row = db.execute(
        text(USER_SELECT + " WHERE LOWER(u.username) = LOWER(:identifier) OR LOWER(COALESCE(u.email, '')) = LOWER(:identifier) LIMIT 1;"),
        {"identifier": payload.identifier},
    ).mappings().first()

    generic_error = HTTPException(
        status_code=401,
        detail="Identifiant ou mot de passe incorrect.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not row:
        _audit(
            db,
            action="LOGIN_FAILURE",
            success=False,
            username_attempted=payload.identifier,
            ip_address=ip_address,
            user_agent=user_agent,
            details="Utilisateur introuvable.",
        )
        db.commit()
        raise generic_error

    now = datetime.now(timezone.utc)
    locked_until = row["locked_until"]
    if locked_until and locked_until > now:
        _audit(
            db,
            action="LOGIN_BLOCKED",
            success=False,
            user_id=int(row["id"]),
            username_attempted=payload.identifier,
            ip_address=ip_address,
            user_agent=user_agent,
            details="Compte temporairement verrouillé.",
        )
        db.commit()
        raise HTTPException(
            status_code=423,
            detail="Compte temporairement verrouillé après plusieurs échecs. Réessayez plus tard.",
        )

    if not verify_password(payload.password, row["password_hash"]):
        attempts = int(row["failed_login_attempts"] or 0) + 1
        lock_value = None
        if attempts >= settings.AUTH_MAX_FAILED_ATTEMPTS:
            lock_value = now + timedelta(minutes=settings.AUTH_LOCK_MINUTES)

        db.execute(
            text(
                """
                UPDATE public.users
                SET failed_login_attempts = :attempts,
                    locked_until = :locked_until
                WHERE id = :user_id;
                """
            ),
            {
                "attempts": attempts,
                "locked_until": lock_value,
                "user_id": int(row["id"]),
            },
        )
        _audit(
            db,
            action="LOGIN_FAILURE",
            success=False,
            user_id=int(row["id"]),
            username_attempted=payload.identifier,
            ip_address=ip_address,
            user_agent=user_agent,
            details=f"Mot de passe incorrect. Tentative {attempts}.",
        )
        db.commit()
        raise generic_error

    if not row["is_active"]:
        _audit(
            db,
            action="LOGIN_REJECTED_INACTIVE",
            success=False,
            user_id=int(row["id"]),
            username_attempted=payload.identifier,
            ip_address=ip_address,
            user_agent=user_agent,
            details="Compte désactivé ou en attente d'approbation.",
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Compte en attente d'approbation ou désactivé.",
        )

    if not row["role_code"]:
        raise HTTPException(status_code=500, detail="Aucun rôle n'est associé à ce compte.")

    token, jti, expires_at = create_access_token(
        user_id=int(row["id"]),
        username=row["username"],
        role_code=row["role_code"],
    )

    db.execute(
        text(
            """
            UPDATE public.users
            SET last_login_at = CURRENT_TIMESTAMP,
                failed_login_attempts = 0,
                locked_until = NULL
            WHERE id = :user_id;
            """
        ),
        {"user_id": int(row["id"])},
    )

    db.execute(
        text(
            """
            INSERT INTO public.auth_sessions (
                jti, user_id, expires_at, ip_address, user_agent
            ) VALUES (
                :jti, :user_id, :expires_at, :ip_address, :user_agent
            );
            """
        ),
        {
            "jti": jti,
            "user_id": int(row["id"]),
            "expires_at": expires_at,
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )

    _audit(
        db,
        action="LOGIN_SUCCESS",
        success=True,
        user_id=int(row["id"]),
        username_attempted=payload.identifier,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    refreshed = dict(row)
    refreshed["last_login_at"] = now
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_MINUTES * 60,
        "user": _public_user(refreshed),
    }


def logout_user(
    db: Session,
    principal: AuthPrincipal,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> dict:
    db.execute(
        text(
            """
            UPDATE public.auth_sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE jti = :jti AND revoked_at IS NULL;
            """
        ),
        {"jti": principal.jti},
    )
    _audit(
        db,
        action="LOGOUT",
        success=True,
        user_id=principal.id,
        username_attempted=principal.username,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return {"status": "ok", "message": "Déconnexion effectuée."}


def get_user_by_id(db: Session, user_id: int) -> dict:
    row = db.execute(
        text(USER_SELECT + " WHERE u.id = :user_id LIMIT 1;"),
        {"user_id": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return _public_user(row)


def change_password(
    db: Session,
    principal: AuthPrincipal,
    payload: ChangePasswordRequest,
) -> dict:
    row = db.execute(
        text("SELECT password_hash FROM public.users WHERE id = :user_id;"),
        {"user_id": principal.id},
    ).mappings().first()

    if not row or not verify_password(payload.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Le mot de passe actuel est incorrect.")

    validate_password_strength(payload.new_password)
    if verify_password(payload.new_password, row["password_hash"]):
        raise HTTPException(
            status_code=400,
            detail="Le nouveau mot de passe doit être différent de l'ancien.",
        )

    db.execute(
        text(
            """
            UPDATE public.users
            SET password_hash = :password_hash,
                must_change_password = FALSE,
                password_changed_at = CURRENT_TIMESTAMP
            WHERE id = :user_id;
            """
        ),
        {
            "password_hash": hash_password(payload.new_password),
            "user_id": principal.id,
        },
    )
    db.execute(
        text(
            """
            UPDATE public.auth_sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id
              AND jti <> :current_jti
              AND revoked_at IS NULL;
            """
        ),
        {"user_id": principal.id, "current_jti": principal.jti},
    )
    _audit(
        db,
        action="PASSWORD_CHANGED",
        success=True,
        user_id=principal.id,
        username_attempted=principal.username,
    )
    db.commit()
    return {
        "status": "ok",
        "message": "Mot de passe modifié avec succès.",
        "user": get_user_by_id(db, principal.id),
    }


def list_roles(db: Session) -> list[dict]:
    rows = db.execute(
        text("SELECT code, libelle, description FROM public.roles ORDER BY id;")
    ).mappings().all()
    return [dict(row) for row in rows]


def list_users(db: Session) -> list[dict]:
    rows = db.execute(
        text(USER_SELECT + " ORDER BY u.is_active DESC, u.created_at DESC, u.username;")
    ).mappings().all()
    return [_public_user(row) for row in rows]


def admin_create_user(
    db: Session,
    principal: AuthPrincipal,
    payload: AdminCreateUserRequest,
) -> dict:
    validate_password_strength(payload.password)
    role_id = _role_id(db, payload.role_code)

    try:
        user_id = int(
            db.execute(
                text(
                    """
                    INSERT INTO public.users (
                        username, full_name, email, password_hash, role_id,
                        is_active, must_change_password, approved_at, approved_by, created_by
                    ) VALUES (
                        :username, :full_name, :email, :password_hash, :role_id,
                        :is_active, :must_change_password,
                        CASE WHEN :is_active THEN CURRENT_TIMESTAMP ELSE NULL END,
                        CASE WHEN :is_active THEN :admin_id ELSE NULL END,
                        :admin_id
                    )
                    RETURNING id;
                    """
                ),
                {
                    "username": payload.username,
                    "full_name": payload.full_name,
                    "email": payload.email,
                    "password_hash": hash_password(payload.password),
                    "role_id": role_id,
                    "is_active": payload.is_active,
                    "must_change_password": payload.must_change_password,
                    "admin_id": principal.id,
                },
            ).scalar()
        )
        _audit(
            db,
            action="ADMIN_CREATE_USER",
            success=True,
            user_id=user_id,
            username_attempted=payload.username,
            details=f"Créé par {principal.username} avec rôle {payload.role_code}.",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ce nom d'utilisateur ou cette adresse e-mail est déjà utilisé.",
        ) from exc

    return {"status": "ok", "user": get_user_by_id(db, user_id)}


def admin_update_user(
    db: Session,
    principal: AuthPrincipal,
    user_id: int,
    payload: AdminUpdateUserRequest,
) -> dict:
    target = db.execute(
        text(USER_SELECT + " WHERE u.id = :user_id LIMIT 1;"),
        {"user_id": user_id},
    ).mappings().first()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

    updates: dict[str, Any] = {}
    if payload.full_name is not None:
        updates["full_name"] = payload.full_name
    if payload.email is not None:
        updates["email"] = payload.email
    if payload.role_code is not None:
        updates["role_id"] = _role_id(db, payload.role_code)
    if payload.is_active is not None:
        if user_id == principal.id and payload.is_active is False:
            raise HTTPException(status_code=400, detail="Vous ne pouvez pas désactiver votre propre compte.")
        updates["is_active"] = payload.is_active

    if user_id == principal.id and payload.role_code is not None and payload.role_code != "ADMIN":
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas retirer votre propre rôle administrateur.")

    if not updates:
        return {"status": "ok", "user": _public_user(target)}

    assignments = [f"{column} = :{column}" for column in updates]
    if payload.is_active is True:
        assignments.extend(["approved_at = CURRENT_TIMESTAMP", "approved_by = :admin_id"])
        updates["admin_id"] = principal.id
    if payload.is_active is False:
        assignments.append("approved_at = NULL")

    updates["user_id"] = user_id

    try:
        db.execute(
            text(f"UPDATE public.users SET {', '.join(assignments)} WHERE id = :user_id;"),
            updates,
        )
        if payload.is_active is False:
            db.execute(
                text(
                    """
                    UPDATE public.auth_sessions
                    SET revoked_at = CURRENT_TIMESTAMP
                    WHERE user_id = :user_id AND revoked_at IS NULL;
                    """
                ),
                {"user_id": user_id},
            )
        _audit(
            db,
            action="ADMIN_UPDATE_USER",
            success=True,
            user_id=user_id,
            username_attempted=target["username"],
            details=f"Modifié par {principal.username}: {sorted(updates.keys())}",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Adresse e-mail déjà utilisée.") from exc

    return {"status": "ok", "user": get_user_by_id(db, user_id)}


def admin_reset_password(
    db: Session,
    principal: AuthPrincipal,
    user_id: int,
    payload: AdminResetPasswordRequest,
) -> dict:
    target = db.execute(
        text("SELECT id, username FROM public.users WHERE id = :user_id;"),
        {"user_id": user_id},
    ).mappings().first()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

    validate_password_strength(payload.new_password)
    db.execute(
        text(
            """
            UPDATE public.users
            SET password_hash = :password_hash,
                must_change_password = :must_change_password,
                password_changed_at = CURRENT_TIMESTAMP,
                failed_login_attempts = 0,
                locked_until = NULL
            WHERE id = :user_id;
            """
        ),
        {
            "password_hash": hash_password(payload.new_password),
            "must_change_password": payload.must_change_password,
            "user_id": user_id,
        },
    )
    db.execute(
        text(
            """
            UPDATE public.auth_sessions
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id AND revoked_at IS NULL;
            """
        ),
        {"user_id": user_id},
    )
    _audit(
        db,
        action="ADMIN_RESET_PASSWORD",
        success=True,
        user_id=user_id,
        username_attempted=target["username"],
        details=f"Réinitialisé par {principal.username}.",
    )
    db.commit()
    return {"status": "ok", "message": "Mot de passe réinitialisé."}


def generate_temporary_password() -> str:
    return f"Abhl!{secrets.token_urlsafe(8)}9"
