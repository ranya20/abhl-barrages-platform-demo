from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.situation.calculations import add_months, build_situation_data
from app.modules.situation.excel_generator import generate_situation_excel
from app.modules.situation.pdf_export import convert_excel_to_pdf
from app.modules.situation.repository import load_situation_raw_data
from app.modules.situation.mappings import SELECTED_EXPORT_SHEETS


router = APIRouter()


@router.get("/check")
def check_situation(
    date_situation: date = Query(..., description="Date de situation, exemple : 2026-06-09"),
    db: Session = Depends(get_db),
):
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    raw = load_situation_raw_data(
        db,
        [date_situation, date_veille, date_annee_precedente],
    )

    data = build_situation_data(raw, date_situation)

    return {
        "status": "ok" if data["check"]["can_generate"] else "problem",
        "data": data["check"],
    }


@router.get("/preview")
def preview_situation(
    date_situation: date = Query(..., description="Date de situation, exemple : 2026-06-09"),
    db: Session = Depends(get_db),
):
    date_veille = date_situation - timedelta(days=1)
    date_annee_precedente = add_months(date_situation, -12)

    raw = load_situation_raw_data(
        db,
        [date_situation, date_veille, date_annee_precedente],
    )

    data = build_situation_data(raw, date_situation)

    if not data["check"]["can_generate"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Données insuffisantes pour générer la situation.",
                "check": data["check"],
            },
        )

    return {
        "status": "ok",
        "date_situation": data["dates"]["date_situation"],
        "date_veille": data["dates"]["date_veille"],
        "date_annee_precedente": data["dates"]["date_annee_precedente"],
        "normal_rows": data["normal_rows"],
        "normal_totals": data["normal_totals"],
        "transfer_rows": data["transfer_rows"],
        "transfer_totals": data["transfer_totals"],
        "specials": data["specials"],
    }


@router.get("/pdf-options")
def situation_pdf_options():
    """
    Source unique pour l'interface : exactement les feuilles Situation
    officiellement exportées par la plateforme.
    """
    return {
        "status": "ok",
        "data": {
            "allow_full": True,
            "sheets": list(SELECTED_EXPORT_SHEETS),
        },
    }


@router.get("/export")
def export_situation(
    date_situation: date = Query(..., description="Date de situation, exemple : 2026-06-09"),
    export_format: str = Query("xlsx", alias="format", description="Format de sortie : xlsx ou pdf"),
    sheet: str | None = Query(
        default=None,
        description="Pour un PDF : nom exact de la feuille à exporter. Vide = PDF complet.",
    ),
    db: Session = Depends(get_db),
):
    output_path = generate_situation_excel(db, date_situation)

    requested_format = (export_format or "xlsx").strip().lower()
    if requested_format not in {"xlsx", "pdf"}:
        raise HTTPException(
            status_code=400,
            detail="Format invalide. Utilisez format=xlsx ou format=pdf.",
        )

    if requested_format == "pdf":
        selected_sheet = (sheet or "").strip() or None
        if selected_sheet is not None and selected_sheet not in SELECTED_EXPORT_SHEETS:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Feuille PDF invalide.",
                    "allowed_sheets": list(SELECTED_EXPORT_SHEETS),
                },
            )

        pdf_path = convert_excel_to_pdf(
            output_path,
            sheet_name=selected_sheet,
        )
        suffix = f" - {selected_sheet}" if selected_sheet else ""
        filename = (
            f"Situation quotidienne des barrages - "
            f"{date_situation.isoformat()}{suffix}.pdf"
        )

        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=filename,
        )

    if sheet:
        raise HTTPException(
            status_code=400,
            detail="Le choix d'une feuille est disponible uniquement pour l'export PDF.",
        )

    filename = f"Situation quotidienne des barrages - {date_situation.isoformat()}.xlsx"

    return FileResponse(
        path=output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )