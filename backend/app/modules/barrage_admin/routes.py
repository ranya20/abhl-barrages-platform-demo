from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.dependencies import AuthPrincipal, require_roles
from app.modules.baremes.schemas import BaremeDraftCreateRequest as VersionedBaremeDraftCreateRequest
from app.modules.baremes.service import create_draft_version
from app.modules.barrage_admin.schemas import (
    BarrageCreateRequest,
    BarrageUpdateRequest,
    BaremeImportRequest,
    InitialBilanRequest,
)
from app.modules.barrage_admin.service import (
    create_barrage_full,
    get_admin_barrage,
    get_barrage_readiness,
    import_bareme_points,
    initialize_initial_bilan,
    list_admin_barrages,
    list_reference_data,
    update_barrage_configuration,
)

router = APIRouter()


@router.get("/reference-data")
def reference_data(db: Session = Depends(get_db)):
    return list_reference_data(db)


@router.get("/barrages")
def admin_list_barrages(db: Session = Depends(get_db)):
    return list_admin_barrages(db)


@router.get("/barrages/{code}")
def admin_get_barrage(code: str, db: Session = Depends(get_db)):
    barrage = get_admin_barrage(db, code)
    if not barrage:
        raise HTTPException(status_code=404, detail=f"Barrage introuvable : {code}")
    return {"status": "ok", "data": barrage}


@router.get("/barrages/{code}/readiness")
def admin_barrage_readiness(code: str, db: Session = Depends(get_db)):
    try:
        return get_barrage_readiness(db, code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/barrages")
def admin_create_barrage(payload: BarrageCreateRequest, db: Session = Depends(get_db)):
    try:
        return create_barrage_full(db, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/barrages/{code}/configuration")
def admin_update_barrage(code: str, payload: BarrageUpdateRequest, db: Session = Depends(get_db)):
    try:
        return update_barrage_configuration(db, code, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# === ABHL BAREMES V27 SAFE LEGACY IMPORT ===
@router.post("/barrages/{code}/bareme-points")
def admin_import_bareme(
    code: str,
    payload: BaremeImportRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        draft = VersionedBaremeDraftCreateRequest(
            barrage_code=code, nom=payload.nom, annee_bareme=payload.annee_bareme,
            date_debut_validite=payload.date_debut_validite, source_type="MANUEL",
            source_fichier=payload.source_fichier, source_feuille=payload.source_feuille,
            observation=payload.observation,
            points=[{"cote_ngm":p.cote_ngm,"volume_mm3":p.volume_mm3,"surface_km2":p.surface_km2} for p in payload.points],
        )
        result=create_draft_version(db,draft,user_id=principal.id)
        result["message"]="Barème créé en BROUILLON. Publiez-le depuis la page Barèmes pour l'appliquer."
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
# === ABHL BAREMES V27 SAFE LEGACY IMPORT END ===


@router.post("/barrages/{code}/initial-bilan")
def admin_initialize_initial_bilan(code: str, payload: InitialBilanRequest, db: Session = Depends(get_db)):
    try:
        return initialize_initial_bilan(db, code, payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
