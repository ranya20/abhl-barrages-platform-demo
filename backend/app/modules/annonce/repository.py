from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.annonce.mappings import DATA_ROW_COUNT, TARGET_BARRAGE_CODES


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def date_key(value: date) -> str:
    return value.isoformat()


def table_exists(db: Session, table_name: str) -> bool:
    return bool(
        db.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                );
            """),
            {"table_name": table_name},
        ).scalar()
    )


def month_context(date_situation: date) -> dict:
    # La cote de date_situation termine les calculs de la veille.
    date_interval = date_situation - timedelta(days=1)
    month_start = date(date_interval.year, date_interval.month, 1)
    data_end = month_start + timedelta(days=DATA_ROW_COUNT - 1)

    if date_interval.month == 12:
        next_month_start = date(date_interval.year + 1, 1, 1)
    else:
        next_month_start = date(date_interval.year, date_interval.month + 1, 1)

    return {
        "date_situation": date_situation,
        "date_interval": date_interval,
        "month_start": month_start,
        "next_month_start": next_month_start,
        "data_end": data_end,
        "month": date_interval.month,
        "year": date_interval.year,
    }


def fetch_annonce_barrages(db: Session) -> dict[str, dict]:
    """Charge tous les barrages actifs inclus dans le module Annonce.

    Les anciens barrages officiels gardent leurs feuilles fixes.
    Les barrages ajoutés dynamiquement seront exportés dans des feuilles créées automatiquement.
    """

    rows = db.execute(
        text("""
            SELECT
                b.id,
                b.code,
                b.nom,
                b.capacite_normale_mm3,
                b.ordre_affichage,
                b.ordre_annonce,
                b.mode_creation,
                COALESCE(a.code, '') AS agence_code,
                COALESCE(a.nom, '') AS agence_nom
            FROM public.barrages b
            LEFT JOIN public.agences_territoriales a
              ON a.id = b.agence_id
            WHERE COALESCE(b.actif, TRUE) = TRUE
              AND COALESCE(b.inclure_annonce, TRUE) = TRUE
            ORDER BY
                COALESCE(b.ordre_annonce, b.ordre_affichage, 9999),
                b.code;
        """),
    ).mappings().all()

    return {row["code"]: dict(row) for row in rows}


def fetch_barrage_restitution_config(
    db: Session,
    codes: list[str],
) -> dict[str, list[dict]]:
    if not codes:
        return {}

    rows = db.execute(
        text("""
            SELECT
                b.code AS barrage_code,
                tr.code AS type_code,
                COALESCE(btr.libelle_affichage, tr.libelle, tr.code) AS libelle,
                COALESCE(btr.ordre_affichage, 9999) AS ordre_affichage,
                COALESCE(btr.obligatoire, FALSE) AS obligatoire
            FROM public.barrage_types_restitution btr
            JOIN public.barrages b
              ON b.id = btr.barrage_id
            JOIN public.types_restitution tr
              ON tr.id = btr.type_restitution_id
            WHERE b.code = ANY(:codes)
              AND COALESCE(btr.actif, TRUE) = TRUE
              AND COALESCE(tr.actif, TRUE) = TRUE
            ORDER BY b.code, COALESCE(btr.ordre_affichage, 9999), tr.code;
        """),
        {"codes": codes},
    ).mappings().all()

    data: dict[str, list[dict]] = {code: [] for code in codes}
    for row in rows:
        data.setdefault(row["barrage_code"], []).append(
            {
                "type_code": row["type_code"],
                "libelle": row["libelle"],
                "ordre_affichage": int(row["ordre_affichage"] or 9999),
                "obligatoire": bool(row["obligatoire"]),
            }
        )

    return data


def fetch_bilans(
    db: Session,
    start_date: date,
    end_date: date,
    codes: list[str],
) -> dict[tuple[str, str], dict]:
    if not codes:
        return {}

    rows = db.execute(
        text("""
            SELECT DISTINCT ON (b.code, bj.date_bilan)
                bj.id,
                b.code AS barrage_code,
                b.nom AS barrage_nom,
                bj.date_bilan,
                bj.cote_7h_ngm,
                bj.volume_mm3,
                bj.surface_km2,
                bj.taux_remplissage,
                bj.hauteur_bac_mm,
                bj.pluie_mm,
                bj.evaporation_m3,
                bj.total_restitutions_m3,
                bj.apports_raw_m3,
                bj.apports_m3,
                bj.debit_m3s,
                bj.transfert_dar_khrofa_m3,
                bj.statut,
                bj.observation
            FROM public.bilans_journaliers bj
            JOIN public.barrages b
              ON b.id = bj.barrage_id
            WHERE b.code = ANY(:codes)
              AND bj.date_bilan BETWEEN :start_date AND :end_date
              AND bj.heure_reference = '07:00'
            ORDER BY b.code, bj.date_bilan, bj.id DESC;
        """),
        {
            "codes": codes,
            "start_date": start_date,
            "end_date": end_date,
        },
    ).mappings().all()

    data: dict[tuple[str, str], dict] = {}

    for row in rows:
        item = dict(row)
        for key in (
            "cote_7h_ngm",
            "volume_mm3",
            "surface_km2",
            "taux_remplissage",
            "hauteur_bac_mm",
            "pluie_mm",
            "evaporation_m3",
            "total_restitutions_m3",
            "apports_raw_m3",
            "apports_m3",
            "debit_m3s",
            "transfert_dar_khrofa_m3",
        ):
            item[key] = to_float(item.get(key))

        key = (item["barrage_code"], date_key(item["date_bilan"]))
        data[key] = item

    return data


def fetch_restitutions(
    db: Session,
    bilan_ids: list[int],
) -> dict[tuple[int, str], float]:
    if not bilan_ids:
        return {}

    rows = db.execute(
        text("""
            SELECT
                rj.bilan_journalier_id,
                tr.code AS type_code,
                rj.valeur_m3
            FROM public.restitutions_journalieres rj
            JOIN public.types_restitution tr
              ON tr.id = rj.type_restitution_id
            WHERE rj.bilan_journalier_id = ANY(:bilan_ids);
        """),
        {"bilan_ids": bilan_ids},
    ).mappings().all()

    return {
        (int(row["bilan_journalier_id"]), row["type_code"]): to_float(row["valeur_m3"]) or 0.0
        for row in rows
    }


def fetch_specials(
    db: Session,
    bilan_ids: list[int],
) -> dict[tuple[int, str], float]:
    if not bilan_ids or not table_exists(db, "djbarrage_mesures_speciales"):
        return {}

    rows = db.execute(
        text("""
            SELECT
                bilan_journalier_id,
                mesure_code,
                valeur
            FROM public.djbarrage_mesures_speciales
            WHERE bilan_journalier_id = ANY(:bilan_ids);
        """),
        {"bilan_ids": bilan_ids},
    ).mappings().all()

    return {
        (int(row["bilan_journalier_id"]), row["mesure_code"]): to_float(row["valeur"]) or 0.0
        for row in rows
    }


def fetch_default_bareme_points_for_codes(
    db: Session,
    codes: list[str],
) -> dict[str, list[dict]]:
    if not codes:
        return {}

    rows = db.execute(
        text("""
            SELECT
                b.code AS barrage_code,
                bp.cote_ngm,
                bp.surface_km2,
                bp.volume_mm3
            FROM public.barrages b
            JOIN public.bareme_versions bv
              ON bv.barrage_id = b.id
            JOIN public.bareme_points bp
              ON bp.bareme_version_id = bv.id
            WHERE b.code = ANY(:codes)
              AND COALESCE(bv.actif, TRUE) = TRUE
              AND COALESCE(bv.is_default, TRUE) = TRUE
            ORDER BY b.code, bp.cote_ngm;
        """),
        {"codes": codes},
    ).mappings().all()

    data: dict[str, list[dict]] = {code: [] for code in codes}

    for row in rows:
        data.setdefault(row["barrage_code"], []).append(
            {
                "cote_ngm": to_float(row["cote_ngm"]),
                "surface_km2": to_float(row["surface_km2"]),
                "volume_mm3": to_float(row["volume_mm3"]),
            }
        )

    return data


def load_annonce_data(db: Session, date_situation: date) -> dict:
    context = month_context(date_situation)

    barrages = fetch_annonce_barrages(db)
    codes = list(barrages.keys())

    official_codes = [code for code in TARGET_BARRAGE_CODES if code in barrages]
    dynamic_codes = [code for code in codes if code not in TARGET_BARRAGE_CODES]

    bilans = fetch_bilans(db, context["month_start"], context["data_end"], codes)
    bilan_ids = [int(row["id"]) for row in bilans.values()]

    restitutions_by_id = fetch_restitutions(db, bilan_ids)
    specials_by_id = fetch_specials(db, bilan_ids)
    barrage_restitutions = fetch_barrage_restitution_config(db, codes)
    bareme_points = fetch_default_bareme_points_for_codes(db, codes)

    restitutions: dict[tuple[str, str], dict[str, float]] = {}
    specials: dict[tuple[str, str], dict[str, float]] = {}

    for (code, day), bilan in bilans.items():
        bilan_id = int(bilan["id"])
        restitutions[(code, day)] = {
            type_code: value
            for (candidate_id, type_code), value in restitutions_by_id.items()
            if candidate_id == bilan_id
        }
        specials[(code, day)] = {
            special_code: value
            for (candidate_id, special_code), value in specials_by_id.items()
            if candidate_id == bilan_id
        }

    return {
        "context": context,
        "barrages": barrages,
        "target_codes": codes,
        "official_codes": official_codes,
        "dynamic_codes": dynamic_codes,
        "barrage_restitutions": barrage_restitutions,
        "bareme_points": bareme_points,
        "bilans": bilans,
        "restitutions": restitutions,
        "specials": specials,
    }


def register_export(
    db: Session,
    *,
    date_situation: date,
    month: int,
    year: int,
    filename: str,
    output_path: Path,
) -> int | None:
    if not table_exists(db, "exports"):
        return None

    row = db.execute(
        text("""
            INSERT INTO public.exports (
                type_export,
                date_situation,
                mois,
                annee,
                nom_fichier,
                chemin_fichier,
                statut,
                is_final
            )
            VALUES (
                'ANNONCE',
                :date_situation,
                :month,
                :year,
                :filename,
                :output_path,
                'SUCCESS',
                FALSE
            )
            RETURNING id;
        """),
        {
            "date_situation": date_situation,
            "month": month,
            "year": year,
            "filename": filename,
            "output_path": str(output_path),
        },
    ).mappings().first()

    return int(row["id"]) if row else None

# === ABHL BAREMES V27 ANNONCE DATE RESOLUTION START ===
_abhl_v27_load_annonce_data_legacy = load_annonce_data

def load_annonce_data(db: Session, date_situation: date) -> dict:
    raw = _abhl_v27_load_annonce_data_legacy(db, date_situation)
    from app.modules.baremes.service import resolve_bareme_versions_for_dates, fetch_points_by_versions
    context = raw["context"]
    day = context["month_start"]
    dates = []
    while day <= context["data_end"]:
        dates.append(day)
        day += timedelta(days=1)
    codes = list(raw.get("target_codes") or [])
    resolutions = resolve_bareme_versions_for_dates(db, codes, dates, strict=True)
    version_ids = {v["id"] for v in resolutions.values() if v}
    raw["_abhl_v27_bareme_versions_by_date"] = resolutions
    raw["_abhl_v27_bareme_points_by_version"] = fetch_points_by_versions(db, version_ids)
    return raw
# === ABHL BAREMES V27 ANNONCE DATE RESOLUTION END ===
