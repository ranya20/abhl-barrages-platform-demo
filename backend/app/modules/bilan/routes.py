from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.dependencies import AuthPrincipal, require_roles
from app.modules.bilan.excel_generator import generate_bilan_excel
from app.modules.bilan.schemas import BilanComputeRequest, BilanSaveRequest
from app.modules.bilan.service import (
    build_bilan_catalog,
    build_bilan_check,
    build_bilan_month_form,
    build_bilan_preview,
    compute_bilan,
    save_bilan,
)


router = APIRouter()


def _handle_value_error(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog")
def get_bilan_catalog(db: Session = Depends(get_db)):
    return build_bilan_catalog(db)


@router.get("/month")
def get_bilan_month(
    barrage_code: str = Query(...),
    year: int = Query(..., ge=1900, le=2200),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return _handle_value_error(build_bilan_month_form, db, barrage_code, year, month)


@router.post("/compute")
def compute_bilan_route(payload: BilanComputeRequest, db: Session = Depends(get_db)):
    return _handle_value_error(compute_bilan, db, payload)


@router.post("/save")
def save_bilan_route(
    payload: BilanSaveRequest,
    _: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    result = _handle_value_error(save_bilan, db, payload)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/check")
def check_bilan(
    barrage_code: str = Query(...),
    year: int = Query(..., ge=1900, le=2200),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return _handle_value_error(build_bilan_check, db, barrage_code, year, month)


@router.get("/preview")
def preview_bilan(
    barrage_code: str = Query(...),
    year: int = Query(..., ge=1900, le=2200),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return _handle_value_error(build_bilan_preview, db, barrage_code, year, month)


@router.get("/export")
def export_bilan(
    barrage_code: str = Query(...),
    year: int = Query(..., ge=1900, le=2200),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    output_path = _handle_value_error(generate_bilan_excel, db, barrage_code, year, month)
    return FileResponse(
        path=output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=output_path.name,
    )
