from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.dependencies import (
    AuthPrincipal,
    get_current_active_user,
    require_roles,
)
from app.modules.auth.schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    ChangePasswordRequest,
    LoginRequest,
    SignUpRequest,
)
from app.modules.auth.service import (
    admin_create_user,
    admin_reset_password,
    admin_update_user,
    change_password,
    get_user_by_id,
    list_roles,
    list_users,
    login_user,
    logout_user,
    signup_user,
)


router = APIRouter()


def _request_context(request: Request) -> tuple[str | None, str | None]:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent


@router.post("/signup", status_code=201)
def signup(
    payload: SignUpRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip_address, user_agent = _request_context(request)
    return signup_user(
        db,
        payload,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip_address, user_agent = _request_context(request)
    return login_user(
        db,
        payload,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post("/token")
def oauth2_token(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Point d'entrée OAuth2 utilisé par Swagger/OpenAPI."""
    ip_address, user_agent = _request_context(request)
    return login_user(
        db,
        LoginRequest(identifier=form.username, password=form.password),
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.get("/me")
def me(
    principal: AuthPrincipal = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "user": get_user_by_id(db, principal.id)}


@router.post("/logout")
def logout(
    request: Request,
    principal: AuthPrincipal = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    ip_address, user_agent = _request_context(request)
    return logout_user(
        db,
        principal,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@router.post("/change-password")
def update_password(
    payload: ChangePasswordRequest,
    principal: AuthPrincipal = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    return change_password(db, principal, payload)


@router.get("/admin/roles")
def admin_roles(
    _: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "roles": list_roles(db)}


@router.get("/admin/users")
def admin_users(
    _: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    users = list_users(db)
    return {"status": "ok", "count": len(users), "users": users}


@router.post("/admin/users", status_code=201)
def admin_add_user(
    payload: AdminCreateUserRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    return admin_create_user(db, principal, payload)


@router.patch("/admin/users/{user_id}")
def admin_edit_user(
    user_id: int,
    payload: AdminUpdateUserRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    return admin_update_user(db, principal, user_id, payload)


@router.post("/admin/users/{user_id}/reset-password")
def admin_password_reset(
    user_id: int,
    payload: AdminResetPasswordRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    return admin_reset_password(db, principal, user_id, payload)
