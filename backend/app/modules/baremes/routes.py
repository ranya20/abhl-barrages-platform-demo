from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.dependencies import AuthPrincipal, require_roles
from app.modules.baremes.excel_io import build_blank_template, parse_bareme_excel
from app.modules.baremes.schemas import (
    BaremeArchiveRequest,
    BaremeCloneRequest,
    BaremeDraftCreateRequest,
    BaremeDraftUpdateRequest,
    BaremePeriodRequest,
    BaremePublishRequest,
)
from app.modules.baremes.service import (
    BaremeResolutionError,
    archive_version,
    clone_version,
    create_draft_version,
    delete_draft_version,
    get_bareme_by_barrage_code,
    get_bareme_status,
    get_version,
    get_volume_surface_by_cote,
    list_audit,
    list_management_barrages,
    list_versions,
    preview_period_change,
    publish_version,
    resolve_bareme_version,
    update_draft_version,
    update_published_period,
)


router = APIRouter()


def _bad_request(exc: Exception):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
def baremes_status(db: Session = Depends(get_db)):
    data = get_bareme_status(db)
    return {"status": "ok", "count": len(data), "data": data}


@router.get("/management/barrages")
def management_barrages(db: Session = Depends(get_db)):
    data = list_management_barrages(db)
    return {"status": "ok", "count": len(data), "data": data}


@router.get("/versions")
def versions(
    barrage_code: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    data = list_versions(db, barrage_code)
    return {"status": "ok", "count": len(data), "data": data}


@router.get("/versions/{version_id}")
def version_detail(version_id: int, db: Session = Depends(get_db)):
    try:
        return {"status": "ok", "data": get_version(db, version_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/audit")
def audit(
    version_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return {"status": "ok", "data": list_audit(db, version_id, limit)}


@router.get("/template.xlsx")
def blank_template():
    content = build_blank_template()
    headers = {
        "Content-Disposition": 'attachment; filename="Modele_Bareme_ABHL.xlsx"'
    }
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    _: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
):
    try:
        content = await file.read()
        report = parse_bareme_excel(content, file.filename)
        return {
            "status": "ok",
            "data": {
                **report,
                "points": [
                    {
                        "cote_ngm": format(p["cote_ngm"], "f"),
                        "volume_mm3": format(p["volume_mm3"], "f"),
                        "surface_km2": format(p["surface_km2"], "f"),
                        "ligne_source": p.get("ligne_source"),
                    }
                    for p in report["points"]
                ],
                "min_cote": float(report["min_cote"]),
                "max_cote": float(report["max_cote"]),
                "min_volume": float(report["min_volume"]),
                "max_volume": float(report["max_volume"]),
                "min_surface": float(report["min_surface"]),
                "max_surface": float(report["max_surface"]),
            },
        }
    except ValueError as exc:
        _bad_request(exc)


@router.post("/import/draft")
async def import_as_draft(
    barrage_code: str = Form(...),
    nom: str = Form(...),
    annee_bareme: int | None = Form(default=None),
    date_debut_validite: date | None = Form(default=None),
    date_fin_validite: date | None = Form(default=None),
    cote_normale_ngm: Decimal | None = Form(default=None),
    volume_normal_mm3: Decimal | None = Form(default=None),
    surface_normale_km2: Decimal | None = Form(default=None),
    observation: str | None = Form(default=None),
    file: UploadFile = File(...),
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        content = await file.read()
        report = parse_bareme_excel(content, file.filename)
        payload = BaremeDraftCreateRequest(
            barrage_code=barrage_code,
            nom=nom,
            annee_bareme=annee_bareme,
            date_debut_validite=date_debut_validite,
            date_fin_validite=date_fin_validite,
            cote_normale_ngm=cote_normale_ngm,
            volume_normal_mm3=volume_normal_mm3,
            surface_normale_km2=surface_normale_km2,
            observation=observation,
            source_type="EXCEL",
            source_fichier=file.filename,
            source_feuille=report["sheet_name"],
            source_sha256=report["source_sha256"],
            points=[
                {
                    "cote_ngm": p["cote_ngm"],
                    "volume_mm3": p["volume_mm3"],
                    "surface_km2": p["surface_km2"],
                }
                for p in report["points"]
            ],
        )
        result = create_draft_version(db, payload, user_id=principal.id)
        result["import_preview"] = {
            "source_sha256": report["source_sha256"],
            "points_count": report["points_count"],
            "warnings": report["warnings"],
        }
        return result
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.post("/versions")
def create_draft(
    payload: BaremeDraftCreateRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return create_draft_version(db, payload, user_id=principal.id)
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.put("/versions/{version_id}")
def update_draft(
    version_id: int,
    payload: BaremeDraftUpdateRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return update_draft_version(db, version_id, payload, user_id=principal.id)
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.delete("/versions/{version_id}")
def delete_draft(
    version_id: int,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return delete_draft_version(db, version_id, user_id=principal.id)
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.post("/versions/{version_id}/clone")
def clone(
    version_id: int,
    payload: BaremeCloneRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return clone_version(db, version_id, payload, user_id=principal.id)
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.post("/versions/{version_id}/period/preview")
def period_preview(
    version_id: int,
    payload: BaremePeriodRequest,
    _: AuthPrincipal = Depends(require_roles("ADMIN", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return {
            "status": "ok",
            "data": preview_period_change(
                db,
                version_id,
                payload.date_debut_validite,
                payload.date_fin_validite,
            ),
        }
    except ValueError as exc:
        _bad_request(exc)


@router.put("/versions/{version_id}/period")
def update_period(
    version_id: int,
    payload: BaremePeriodRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return update_published_period(
            db,
            version_id,
            start=payload.date_debut_validite,
            end=payload.date_fin_validite,
            user_id=principal.id,
            commentaire=payload.commentaire,
        )
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.post("/versions/{version_id}/publish")
def publish(
    version_id: int,
    payload: BaremePublishRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        return publish_version(
            db,
            version_id,
            user_id=principal.id,
            close_previous=payload.close_previous,
            commentaire=payload.commentaire,
        )
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.post("/versions/{version_id}/archive")
def archive(
    version_id: int,
    payload: BaremeArchiveRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return archive_version(
            db,
            version_id,
            user_id=principal.id,
            confirm=payload.confirm,
            commentaire=payload.commentaire,
        )
    except ValueError as exc:
        db.rollback()
        _bad_request(exc)


@router.get("/resolve")
def resolve(
    barrage_code: str = Query(...),
    date_reference: date = Query(...),
    db: Session = Depends(get_db),
):
    try:
        return {
            "status": "ok",
            "data": resolve_bareme_version(
                db,
                barrage_code=barrage_code,
                date_reference=date_reference,
                strict=True,
            ),
        }
    except BaremeResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        _bad_request(exc)


# ---------------------------------------------------------------------------
# Compatibilité des anciennes routes du module
# ---------------------------------------------------------------------------

@router.get("/{barrage_code}/lookup")
def lookup_volume_surface(
    barrage_code: str,
    cote_ngm: float = Query(..., description="Cote NGM à rechercher"),
    date_reference: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        data = get_volume_surface_by_cote(
            db,
            barrage_code,
            cote_ngm,
            date_reference=date_reference,
        )
    except BaremeResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Cote {cote_ngm} introuvable dans le barème de {barrage_code}",
        )
    return {"status": "ok", "data": data}


@router.get("/{barrage_code}")
def bareme_by_barrage(
    barrage_code: str,
    date_reference: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        data = get_bareme_by_barrage_code(
            db,
            barrage_code,
            date_reference=date_reference,
        )
    except BaremeResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun barème trouvé pour le barrage : {barrage_code}",
        )

    return {
        "status": "ok",
        "barrage_code": barrage_code.upper(),
        "count": len(data),
        "data": data,
    }
