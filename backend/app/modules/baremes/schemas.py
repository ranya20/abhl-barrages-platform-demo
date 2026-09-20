from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


BaremeStatus = Literal["BROUILLON", "PUBLIE", "ARCHIVE"]


class BaremePointInput(BaseModel):
    cote_ngm: Decimal
    volume_mm3: Decimal
    surface_km2: Decimal


class BaremeDraftCreateRequest(BaseModel):
    barrage_code: str = Field(..., min_length=2, max_length=80)
    nom: str = Field(..., min_length=2, max_length=250)
    annee_bareme: int | None = Field(default=None, ge=1900, le=2200)
    date_debut_validite: date | None = None
    date_fin_validite: date | None = None
    cote_normale_ngm: Decimal | None = None
    volume_normal_mm3: Decimal | None = None
    surface_normale_km2: Decimal | None = None
    observation: str | None = None
    source_type: Literal["MANUEL", "EXCEL", "COPIE"] = "MANUEL"
    source_fichier: str | None = None
    source_feuille: str | None = None
    source_sha256: str | None = None
    points: list[BaremePointInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_period(self):
        if (
            self.date_debut_validite
            and self.date_fin_validite
            and self.date_fin_validite < self.date_debut_validite
        ):
            raise ValueError("La date de fin ne peut pas précéder la date de début.")
        return self


class BaremeDraftUpdateRequest(BaseModel):
    nom: str | None = Field(default=None, min_length=2, max_length=250)
    annee_bareme: int | None = Field(default=None, ge=1900, le=2200)
    date_debut_validite: date | None = None
    date_fin_validite: date | None = None
    cote_normale_ngm: Decimal | None = None
    volume_normal_mm3: Decimal | None = None
    surface_normale_km2: Decimal | None = None
    observation: str | None = None
    points: list[BaremePointInput] | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if (
            self.date_debut_validite
            and self.date_fin_validite
            and self.date_fin_validite < self.date_debut_validite
        ):
            raise ValueError("La date de fin ne peut pas précéder la date de début.")
        return self


class BaremePeriodRequest(BaseModel):
    date_debut_validite: date
    date_fin_validite: date | None = None
    commentaire: str | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if self.date_fin_validite and self.date_fin_validite < self.date_debut_validite:
            raise ValueError("La date de fin ne peut pas précéder la date de début.")
        return self


class BaremePublishRequest(BaseModel):
    close_previous: bool = True
    commentaire: str | None = None


class BaremeArchiveRequest(BaseModel):
    confirm: bool = False
    commentaire: str | None = None


class BaremeCloneRequest(BaseModel):
    nom: str | None = None
    annee_bareme: int | None = Field(default=None, ge=1900, le=2200)
    date_debut_validite: date | None = None
    date_fin_validite: date | None = None
