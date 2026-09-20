from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class RestitutionInput(BaseModel):
    type_code: str = Field(..., description="Code du type de restitution, exemple AEPI, VDF, EVAC")
    valeur_m3: Optional[float] = Field(0, description="Valeur en m3")


class BarrageCalculationInput(BaseModel):
    barrage_code: str
    cote_7h_ngm: Optional[float] = None

    hauteur_bac_mm: Optional[float] = None
    pluie_mm: Optional[float] = None

    restitutions: list[RestitutionInput] = Field(default_factory=list)

    # Utilisé surtout pour Dar Khrofa si la valeur est saisie directement.
    transfert_dar_khrofa_m3: Optional[float] = None

    observation: Optional[str] = None


class CalculsComputeRequest(BaseModel):
    date_situation: date
    barrages: list[BarrageCalculationInput]


class CalculsSaveRequest(CalculsComputeRequest):
    statut: str = Field("CALCULE", description="BROUILLON, INCOMPLET, CALCULE, VALIDE")
    overwrite: bool = True