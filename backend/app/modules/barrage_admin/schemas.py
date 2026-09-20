from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class BarrageCreateRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=80)
    nom: str = Field(..., min_length=2, max_length=250)
    nom_court: Optional[str] = None

    agence_id: Optional[int] = None
    bassin_id: Optional[int] = None
    province_id: Optional[int] = None

    capacite_normale_mm3: Optional[float] = None
    cote_normale_ngm: Optional[float] = None
    cote_min_ngm: Optional[float] = None
    cote_max_ngm: Optional[float] = None

    feuille_annonce: Optional[str] = None
    feuille_djbarrage: Optional[str] = None
    fichier_bm: Optional[str] = None

    ordre_affichage: Optional[int] = None
    ordre_annonce: Optional[int] = None
    ordre_bilan: Optional[int] = None
    ordre_situation: Optional[int] = None

    date_mise_service: Optional[date] = None

    actif: bool = True
    inclure_calculs: bool = True
    inclure_annonce: bool = True
    inclure_bilan: bool = True
    inclure_situation: bool = True

    restitution_type_ids: list[int] = Field(default_factory=list)
    observation: Optional[str] = None


class BarrageUpdateRequest(BaseModel):
    nom: Optional[str] = None
    nom_court: Optional[str] = None

    agence_id: Optional[int] = None
    bassin_id: Optional[int] = None
    province_id: Optional[int] = None

    capacite_normale_mm3: Optional[float] = None
    cote_normale_ngm: Optional[float] = None
    cote_min_ngm: Optional[float] = None
    cote_max_ngm: Optional[float] = None

    feuille_annonce: Optional[str] = None
    feuille_djbarrage: Optional[str] = None
    fichier_bm: Optional[str] = None

    ordre_affichage: Optional[int] = None
    ordre_annonce: Optional[int] = None
    ordre_bilan: Optional[int] = None
    ordre_situation: Optional[int] = None

    date_mise_service: Optional[date] = None

    actif: Optional[bool] = None
    inclure_calculs: Optional[bool] = None
    inclure_annonce: Optional[bool] = None
    inclure_bilan: Optional[bool] = None
    inclure_situation: Optional[bool] = None

    restitution_type_ids: Optional[list[int]] = None
    observation: Optional[str] = None


class BaremePointInput(BaseModel):
    cote_ngm: float
    volume_mm3: Optional[float] = None
    surface_km2: Optional[float] = None


class BaremeImportRequest(BaseModel):
    nom: str = "Barème plateforme"
    annee_bareme: Optional[int] = None
    date_debut_validite: Optional[date] = None
    source_fichier: Optional[str] = None
    source_feuille: Optional[str] = None
    observation: Optional[str] = None
    points: list[BaremePointInput]


class InitialBilanRequest(BaseModel):
    date_bilan: date
    cote_7h_ngm: float
    observation: Optional[str] = "Initialisation du premier bilan journalier"
    statut: str = "BROUILLON"
