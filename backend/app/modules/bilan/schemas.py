from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class BilanRestitutionInput(BaseModel):
    type_code: str
    valeur_m3: Optional[float] = 0


class BilanDailyInput(BaseModel):
    date_bilan: date
    cote_7h_ngm: Optional[float] = None
    cote_suivante_ngm: Optional[float] = None
    hauteur_bac_mm: Optional[float] = None
    pluie_mm: Optional[float] = None
    restitutions: list[BilanRestitutionInput] = Field(default_factory=list)
    observation: Optional[str] = None


class BilanComputeRequest(BaseModel):
    barrage_code: str
    year: int = Field(..., ge=1900, le=2200)
    month: int = Field(..., ge=1, le=12)
    rows: list[BilanDailyInput] = Field(default_factory=list)


class BilanSaveRequest(BilanComputeRequest):
    statut: str = Field("CALCULE", description="BROUILLON, INCOMPLET, CALCULE ou VALIDE")
    overwrite: bool = True
