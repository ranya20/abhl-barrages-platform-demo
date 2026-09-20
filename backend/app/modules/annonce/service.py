from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.modules.annonce.repository import load_annonce_data


def _has_value(value) -> bool:
    return value is not None


def build_annonce_check(db: Session, date_situation: date) -> dict:
    raw = load_annonce_data(db, date_situation)
    context = raw["context"]
    bilans = raw["bilans"]

    details = []

    for code in raw.get("target_codes", []):
        interval_key = (code, context["date_interval"].isoformat())
        current_key = (code, context["date_situation"].isoformat())
        interval_bilan = bilans.get(interval_key)
        current_bilan = bilans.get(current_key)
        barrage = raw.get("barrages", {}).get(code, {})

        missing = []

        if not interval_bilan:
            missing.append("bilan_ligne")
        else:
            for field in (
                "hauteur_bac_mm",
                "pluie_mm",
                "evaporation_m3",
                "total_restitutions_m3",
            ):
                if not _has_value(interval_bilan.get(field)):
                    missing.append(field)

            if not _has_value(interval_bilan.get("apports_raw_m3")) and not _has_value(
                interval_bilan.get("apports_m3")
            ):
                missing.append("apports")

        if not current_bilan:
            missing.append("bilan_cote_suivante")
        else:
            if not _has_value(current_bilan.get("cote_7h_ngm")):
                missing.append("cote_7h_ngm")
            if not _has_value(current_bilan.get("volume_mm3")):
                missing.append("volume_mm3")

        details.append(
            {
                "barrage_code": code,
                "barrage_nom": barrage.get("nom"),
                "dynamic": code in raw.get("dynamic_codes", []),
                "ready": not missing,
                "missing": missing,
            }
        )

    ready_count = sum(1 for row in details if row["ready"])
    expected_count = len(raw.get("target_codes", []))

    return {
        "status": "ok",
        "date_situation": context["date_situation"].isoformat(),
        "date_interval": context["date_interval"].isoformat(),
        "month": context["month"],
        "year": context["year"],
        "ready_count": ready_count,
        "expected_count": expected_count,
        "official_count": len(raw.get("official_codes", [])),
        "dynamic_count": len(raw.get("dynamic_codes", [])),
        "complete_for_selected_line": ready_count == expected_count,
        # L'export reste permis : les lignes absentes sont laissées vides dans le modèle.
        "can_export": True,
        "details": details,
    }


def build_annonce_preview(db: Session, date_situation: date) -> dict:
    raw = load_annonce_data(db, date_situation)
    context = raw["context"]
    bilans = raw["bilans"]
    restitutions = raw["restitutions"]

    rows = []

    for code in raw.get("target_codes", []):
        interval_key = (code, context["date_interval"].isoformat())
        current_key = (code, context["date_situation"].isoformat())
        interval_bilan = bilans.get(interval_key) or {}
        current_bilan = bilans.get(current_key) or {}
        barrage = raw.get("barrages", {}).get(code, {})

        rows.append(
            {
                "barrage_code": code,
                "barrage_nom": barrage.get("nom"),
                "dynamic": code in raw.get("dynamic_codes", []),
                "date_ligne": context["date_interval"].isoformat(),
                "cote_suivante_ngm": current_bilan.get("cote_7h_ngm"),
                "volume_suivant_mm3": current_bilan.get("volume_mm3"),
                "hauteur_bac_mm": interval_bilan.get("hauteur_bac_mm"),
                "pluie_mm": interval_bilan.get("pluie_mm"),
                "evaporation_m3": interval_bilan.get("evaporation_m3"),
                "total_restitutions_m3": interval_bilan.get("total_restitutions_m3"),
                "apports_m3": interval_bilan.get("apports_raw_m3")
                if interval_bilan.get("apports_raw_m3") is not None
                else interval_bilan.get("apports_m3"),
                "restitutions": restitutions.get(interval_key, {}),
            }
        )

    return {
        "status": "ok",
        "date_situation": context["date_situation"].isoformat(),
        "date_interval": context["date_interval"].isoformat(),
        "month": context["month"],
        "year": context["year"],
        "official_count": len(raw.get("official_codes", [])),
        "dynamic_count": len(raw.get("dynamic_codes", [])),
        "rows": rows,
    }
