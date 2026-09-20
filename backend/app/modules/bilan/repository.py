from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.calculs.repository import (
    fetch_active_barrages,
    fetch_bilans_by_dates,
    fetch_restitutions_for_bilan_ids,
    read_table_columns,
    table_exists,
)


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def fetch_supported_barrages(db: Session, supported_codes: list[str] | tuple[str, ...]) -> dict[str, dict]:
    active = fetch_active_barrages(db)
    return {code: active[code] for code in supported_codes if code in active}


def fetch_month_bilans(
    db: Session,
    *,
    barrage_code: str,
    dates: list[date],
) -> dict[str, dict]:
    rows = fetch_bilans_by_dates(db, dates, [barrage_code])
    return {
        day: row
        for (code, day), row in rows.items()
        if code == barrage_code
    }


def fetch_month_restitutions(
    db: Session,
    bilans_by_date: dict[str, dict],
) -> dict[str, dict[str, float]]:
    ids = [int(row["id"]) for row in bilans_by_date.values() if row.get("id") is not None]
    by_id = fetch_restitutions_for_bilan_ids(db, ids)
    result: dict[str, dict[str, float]] = {}

    for day, bilan in bilans_by_date.items():
        if bilan.get("id") is None:
            result[day] = {}
            continue
        result[day] = by_id.get(int(bilan["id"]), {})

    return result


def fetch_boem_transfers_by_dates(db: Session, dates: list[date]) -> dict[str, float]:
    if not dates:
        return {}

    rows = db.execute(
        text("""
            SELECT
                bj.date_bilan,
                COALESCE(SUM(rj.valeur_m3), 0) AS valeur
            FROM public.bilans_journaliers bj
            JOIN public.barrages b
              ON b.id = bj.barrage_id
            JOIN public.restitutions_journalieres rj
              ON rj.bilan_journalier_id = bj.id
            JOIN public.types_restitution tr
              ON tr.id = rj.type_restitution_id
            WHERE b.code = 'BOEM'
              AND bj.date_bilan = ANY(:dates)
              AND tr.code IN ('TRANSFERT_DAR_KHROFA', 'TRANSFERT')
            GROUP BY bj.date_bilan;
        """),
        {"dates": dates},
    ).mappings().all()

    return {row["date_bilan"].isoformat(): float(row["valeur"] or 0.0) for row in rows}


def existing_bilan_id(db: Session, barrage_id: int, date_bilan: date) -> int | None:
    row = db.execute(
        text("""
            SELECT id
            FROM public.bilans_journaliers
            WHERE barrage_id = :barrage_id
              AND date_bilan = :date_bilan
              AND heure_reference = '07:00'
            LIMIT 1;
        """),
        {"barrage_id": barrage_id, "date_bilan": date_bilan},
    ).mappings().first()
    return int(row["id"]) if row else None


def register_bilan_export(
    db: Session,
    *,
    barrage_code: str,
    year: int,
    month: int,
    filename: str,
    output_path: Path,
) -> int | None:
    if not table_exists(db, "exports"):
        return None

    export_columns = set(read_table_columns(db, "exports"))
    payload = {
        "type_export": "BILAN",
        "mois": month,
        "annee": year,
        "nom_fichier": filename,
        "chemin_fichier": str(output_path),
        "statut": "SUCCESS",
        "is_final": False,
        "raison_regeneration": f"Barrage {barrage_code}",
    }
    payload = {key: value for key, value in payload.items() if key in export_columns}

    columns = ", ".join(payload.keys())
    values = ", ".join(f":{key}" for key in payload.keys())

    row = db.execute(
        text(f"""
            INSERT INTO public.exports ({columns})
            VALUES ({values})
            RETURNING id;
        """),
        payload,
    ).mappings().first()

    return int(row["id"]) if row else None

# ============================================================
# Gestion dynamique BILAN pour les nouveaux barrages
# ============================================================

def fetch_bilan_enabled_barrages(db: Session) -> list[dict]:
    """
    Retourne tous les barrages actifs inclus dans le module BILAN.
    Les barrages officiels et les barrages ajoutés dynamiquement sont inclus.
    """
    rows = db.execute(
        text("""
            SELECT
                b.id,
                b.code,
                b.nom,
                b.nom_court,
                b.capacite_normale_mm3,
                b.cote_normale_ngm,
                b.ordre_affichage,
                COALESCE(b.ordre_bilan, b.ordre_affichage, b.id) AS ordre_bilan,
                COALESCE(b.actif, TRUE) AS actif,
                COALESCE(b.inclure_bilan, TRUE) AS inclure_bilan,
                COUNT(DISTINCT btr.type_restitution_id) AS nb_restitutions,
                COUNT(DISTINCT bp.id) AS nb_points_bareme
            FROM public.barrages b
            LEFT JOIN public.barrage_types_restitution btr
              ON btr.barrage_id = b.id
             AND COALESCE(btr.actif, TRUE) = TRUE
            LEFT JOIN public.bareme_versions bv
              ON bv.barrage_id = b.id
             AND COALESCE(bv.actif, TRUE) = TRUE
             AND COALESCE(bv.is_default, TRUE) = TRUE
            LEFT JOIN public.bareme_points bp
              ON bp.bareme_version_id = bv.id
            WHERE COALESCE(b.actif, TRUE) = TRUE
              AND COALESCE(b.inclure_bilan, TRUE) = TRUE
            GROUP BY
                b.id,
                b.code,
                b.nom,
                b.nom_court,
                b.capacite_normale_mm3,
                b.cote_normale_ngm,
                b.ordre_affichage,
                b.ordre_bilan,
                b.actif,
                b.inclure_bilan
            ORDER BY COALESCE(b.ordre_bilan, b.ordre_affichage, b.id), b.id;
        """)
    ).mappings().all()

    result = []
    for row in rows:
        item = dict(row)
        item["capacite_normale_mm3"] = to_float(item.get("capacite_normale_mm3"))
        item["cote_normale_ngm"] = to_float(item.get("cote_normale_ngm"))
        item["nb_restitutions"] = int(item.get("nb_restitutions") or 0)
        item["nb_points_bareme"] = int(item.get("nb_points_bareme") or 0)
        result.append(item)
    return result


def fetch_dynamic_bilan_input_fields(db: Session, barrage_code: str) -> list[dict]:
    """
    Construit dynamiquement les champs de restitution d'un barrage ajouté.
    Le nombre de colonnes du BILAN dépend exactement de ces champs.
    """
    rows = db.execute(
        text("""
            SELECT
                tr.code AS type_code,
                COALESCE(btr.libelle_affichage, tr.libelle, tr.code) AS label,
                COALESCE(tr.unite, 'm3') AS unite,
                COALESCE(btr.ordre_affichage, tr.id) AS ordre_affichage
            FROM public.barrage_types_restitution btr
            JOIN public.barrages b
              ON b.id = btr.barrage_id
            JOIN public.types_restitution tr
              ON tr.id = btr.type_restitution_id
            WHERE b.code = :code
              AND COALESCE(b.actif, TRUE) = TRUE
              AND COALESCE(b.inclure_bilan, TRUE) = TRUE
              AND COALESCE(btr.actif, TRUE) = TRUE
              AND COALESCE(tr.actif, TRUE) = TRUE
            ORDER BY COALESCE(btr.ordre_affichage, tr.id), tr.id;
        """),
        {"code": barrage_code},
    ).mappings().all()

    def col_name(index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    fields: list[dict] = []
    first_restitution_col = 6  # F dans APPORT, après A-E fixes.

    for offset, row in enumerate(rows):
        type_code = str(row["type_code"] or "").strip().upper()
        if not type_code:
            continue
        fields.append(
            {
                "code": type_code,
                "label": row["label"] or type_code,
                "column": col_name(first_restitution_col + offset),
                "included_in_total": True,
                "role": "restitution",
                "editable": True,
                "unit": row.get("unite") or "m3",
            }
        )

    return fields


def fetch_default_bareme_points_for_barrage(db: Session, barrage_code: str) -> list[dict]:
    """Points du barème par défaut pour l'onglet BAREME du BILAN dynamique."""
    rows = db.execute(
        text("""
            SELECT
                bp.cote_ngm,
                bp.surface_km2,
                bp.volume_mm3
            FROM public.barrages b
            JOIN public.bareme_versions bv
              ON bv.barrage_id = b.id
            JOIN public.bareme_points bp
              ON bp.bareme_version_id = bv.id
            WHERE b.code = :code
              AND COALESCE(bv.actif, TRUE) = TRUE
              AND COALESCE(bv.is_default, TRUE) = TRUE
            ORDER BY bp.cote_ngm;
        """),
        {"code": barrage_code},
    ).mappings().all()

    return [
        {
            "cote_ngm": to_float(row["cote_ngm"]),
            "surface_km2": to_float(row["surface_km2"]),
            "volume_mm3": to_float(row["volume_mm3"]),
        }
        for row in rows
    ]

