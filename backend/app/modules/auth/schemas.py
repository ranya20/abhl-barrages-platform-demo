from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


RoleCode = Literal["ADMIN", "SAISIE", "VALIDATEUR", "CONSULTATION"]


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,50}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if not _USERNAME_RE.fullmatch(normalized):
        raise ValueError(
            "Le nom d'utilisateur doit contenir entre 3 et 50 caractères : "
            "lettres, chiffres, point, tiret ou underscore."
        )
    return normalized


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 250 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("Adresse e-mail invalide.")
    return normalized


class UserPublic(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    email: str | None = None
    role_code: str
    role_label: str | None = None
    is_active: bool
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class SignUpRequest(BaseModel):
    username: str
    full_name: str = Field(min_length=2, max_length=200)
    email: str
    password: str = Field(min_length=10, max_length=128)
    password_confirmation: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _normalize_username(value)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            raise ValueError("Le nom complet est obligatoire.")
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = _normalize_email(value)
        if normalized is None:
            raise ValueError("L'adresse e-mail est obligatoire.")
        return normalized

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError("Les mots de passe ne correspondent pas.")
        return self


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=250)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().lower()


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)
    new_password_confirmation: str = Field(min_length=10, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError("Les nouveaux mots de passe ne correspondent pas.")
        return self


class AdminCreateUserRequest(BaseModel):
    username: str
    full_name: str = Field(min_length=2, max_length=200)
    email: str | None = None
    role_code: RoleCode = "CONSULTATION"
    password: str = Field(min_length=10, max_length=128)
    is_active: bool = True
    must_change_password: bool = True

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _normalize_username(value)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _normalize_email(value)


class AdminUpdateUserRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: str | None = None
    role_code: RoleCode | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.strip().split())

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _normalize_email(value)


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=10, max_length=128)
    must_change_password: bool = True


class RolePublic(BaseModel):
    code: str
    libelle: str
    description: str | None = None
