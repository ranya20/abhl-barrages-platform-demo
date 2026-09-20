from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.annonce.excel_generator import generate_annonce_excel
from app.modules.annonce.service import build_annonce_check, build_annonce_preview


router = APIRouter()


# === ABHL V25 ANNONCE DOWNLOAD NAME ===
def _abhl_v25_download_filename(date_situation: date) -> str:
    interval = date_situation - timedelta(days=1)
    return f"Annonce barrages - {interval.year}-{interval.month:02d}.xlsx"


@router.get("/check")
def check_annonce(
    date_situation: date = Query(..., description="Nouvelle cote à 7h, exemple 2026-06-09"),
    db: Session = Depends(get_db),
):
    return build_annonce_check(db, date_situation)


@router.get("/preview")
def preview_annonce(
    date_situation: date = Query(..., description="Nouvelle cote à 7h, exemple 2026-06-09"),
    db: Session = Depends(get_db),
):
    return build_annonce_preview(db, date_situation)


@router.get("/export")
def export_annonce(
    date_situation: date = Query(..., description="Nouvelle cote à 7h, exemple 2026-06-09"),
    db: Session = Depends(get_db),
):
    output_path = generate_annonce_excel(db, date_situation)

    return FileResponse(
        path=output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=_abhl_v25_download_filename(date_situation),
    )
