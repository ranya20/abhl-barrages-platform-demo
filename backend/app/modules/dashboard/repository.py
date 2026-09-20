from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

try:
    from app.modules.situation.mappings import SITUATION_ROWS
except Exception:
    SITUATION_ROWS = {}


VARIABLES: dict[str, dict[str, Any]] = {
    "cote": {"label": "Cote à 7h", "unit": "m NGM", "digits": 2},
    "volume": {"label": "Volume", "unit": "Mm³", "digits": 3},
    "taux": {"label": "Taux de remplissage", "unit": "%", "digits": 1},
    "surface": {"label": "Surface", "unit": "km²", "digits": 3},
    "pluie": {"label": "Pluie", "unit": "mm", "digits": 2},
    "hauteur_bac": {"label": "Hauteur bac", "unit": "mm", "digits": 2},
    "evaporation": {"label": "Évaporation", "unit": "m³", "digits": 0},
    "apports": {"label": "Apports", "unit": "m³", "digits": 0},
    "restitutions": {"label": "Restitutions", "unit": "m³", "digits": 0},
    "debit": {"label": "Débit moyen", "unit": "m³/s", "digits": 3},
    "volume_n1": {"label": "Volume N-1", "unit": "Mm³", "digits": 3},
    "variation": {"label": "Variation volume", "unit": "Mm³", "digits": 3},
}


FALLBACK_OFFICIAL_CAPACITIES: dict[str, float] = {
    "BOEM": 695.8,
    "DAR_KHROFA": 474.7,
    "BIB": 29.2,
    "9_AVRIL": 305.6,
    "KHARROUB": 188.7,
    "TANGER_MED": 22.6,
    "NAKHLA": 4.209826352083337,
    "SMIR": 45.0,
    "MHB_MEHDI": 29.6,
    "CAI": 133.4,
    "CHEFCHAOUEN": 11.68398062083334,
    "KHATTABI": 10.5,
    "JOUMOUA": 5.4,
}


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


OFFICIAL_CAPACITIES: dict[str, float] = {}
for _code, _row in (SITUATION_ROWS or {}).items():
    _cap = _float(_row.get("volume_normal_current"))
    if _cap is not None:
        OFFICIAL_CAPACITIES[_code] = _cap

if not OFFICIAL_CAPACITIES:
    OFFICIAL_CAPACITIES = FALLBACK_OFFICIAL_CAPACITIES.copy()


def _zero(value: Any) -> float:
    value = _float(value)
    return 0.0 if value is None else value


def _date_iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _rate(volume: float | None, capacity: float | None) -> float | None:
    if volume is None or capacity in (None, 0):
        return None
    return min(float(volume) / float(capacity) * 100.0, 100.0)


def _effective_capacity(barrage_code: str | None, db_capacity: Any) -> float | None:
    """Capacité utilisée seulement par le dashboard.

    Les barrages officiels gardent les volumes normaux officiels de la Situation
    quotidienne. Les barrages ajoutés utilisent barrages.capacite_normale_mm3.
    On ne modifie jamais PostgreSQL ici.
    """
    if barrage_code in OFFICIAL_CAPACITIES:
        return OFFICIAL_CAPACITIES[barrage_code]
    return _float(db_capacity)


def _fix_text(value: Any) -> Any:
    """Corrige l'affichage mojibake dans le dashboard sans modifier la base."""
    if not isinstance(value, str):
        return value

    fixed = value

    if any(token in fixed for token in ("Ã", "Â", "â€")):
        try:
            fixed = fixed.encode("latin1").decode("utf-8")
        except Exception:
            pass

    replacements = {
        "TÃ©touan": "Tétouan",
        "TÃ©tuan": "Tétouan",
        "MÃ©diterranÃ©e": "Méditerranée",
        "MÃ©diterrannÃ©e": "Méditerrannée",
        "Â": "",
    }
    for bad, good in replacements.items():
        fixed = fixed.replace(bad, good)

    return fixed


def _restitution_value_column(db: Session) -> str:
    rows = db.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'restitutions_journalieres';
    """)).scalars().all()

    columns = set(rows)
    for candidate in ("valeur_m3", "volume_m3", "quantite_m3", "valeur"):
        if candidate in columns:
            return candidate

    return "valeur_m3"


def _filters_sql(agence_code: str | None, barrage_code: str | None) -> tuple[str, dict[str, Any]]:
    clauses = [
        "COALESCE(b.actif, TRUE) = TRUE",
        "COALESCE(b.inclure_calculs, TRUE) = TRUE",
    ]
    params: dict[str, Any] = {}

    if agence_code:
        clauses.append("a.code = :agence_code")
        params["agence_code"] = agence_code

    if barrage_code:
        clauses.append("b.code = :barrage_code")
        params["barrage_code"] = barrage_code

    return " AND ".join(clauses), params


def list_filters(db: Session) -> dict:
    date_row = db.execute(text("""
        SELECT
            MIN(date_bilan) AS min_date,
            MAX(date_bilan) AS max_date
        FROM public.bilans_journaliers;
    """)).mappings().first()

    agences = db.execute(text("""
        SELECT
            a.code,
            a.nom
        FROM public.agences_territoriales a
        JOIN public.barrages b
          ON b.agence_id = a.id
        WHERE COALESCE(b.actif, TRUE) = TRUE
          AND COALESCE(b.inclure_calculs, TRUE) = TRUE
        GROUP BY a.code, a.nom
        ORDER BY
            MIN(COALESCE(b.ordre_situation, b.ordre_affichage, 9999)) NULLS LAST,
            a.nom;
    """)).mappings().all()

    barrages = db.execute(text("""
        SELECT
            b.code,
            b.nom,
            b.nom_court,
            a.code AS agence_code,
            a.nom AS agence_nom
        FROM public.barrages b
        LEFT JOIN public.agences_territoriales a
          ON a.id = b.agence_id
        WHERE COALESCE(b.actif, TRUE) = TRUE
          AND COALESCE(b.inclure_calculs, TRUE) = TRUE
        ORDER BY COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code;
    """)).mappings().all()

    return {
        "status": "ok",
        "dates": {
            "min": _date_iso(date_row["min_date"]) if date_row else None,
            "max": _date_iso(date_row["max_date"]) if date_row else None,
        },
        "agences": [
            {
                "code": row["code"],
                "nom": _fix_text(row["nom"]),
            }
            for row in agences
        ],
        "barrages": [
            {
                "code": row["code"],
                "nom": _fix_text(row["nom"]),
                "nom_court": _fix_text(row["nom_court"]),
                "agence_code": row["agence_code"],
                "agence_nom": _fix_text(row["agence_nom"]),
            }
            for row in barrages
        ],
        "variables": VARIABLES,
    }


def get_overview(
    db: Session,
    date_situation: date,
    agence_code: str | None = None,
    barrage_code: str | None = None,
) -> dict:
    value_col = _restitution_value_column(db)
    where_sql, params = _filters_sql(agence_code, barrage_code)

    rows = db.execute(text(f"""
        WITH rest AS (
            SELECT
                rj.bilan_journalier_id,
                COALESCE(SUM(rj.{value_col}), 0) AS total_restitutions_m3
            FROM public.restitutions_journalieres rj
            GROUP BY rj.bilan_journalier_id
        )
        SELECT
            b.id AS barrage_id,
            b.code AS barrage_code,
            b.nom AS barrage_nom,
            b.nom_court AS barrage_nom_court,
            a.code AS agence_code,
            a.nom AS agence_nom,
            b.capacite_normale_mm3 AS capacite_db_mm3,
            bj.id AS bilan_id,
            bj.date_bilan,
            bj.cote_7h_ngm,
            bj.volume_mm3,
            bj.surface_km2,
            bj.taux_remplissage,
            bj.hauteur_bac_mm,
            bj.pluie_mm,
            bj.evaporation_m3,
            bj.apports_m3,
            COALESCE(rest.total_restitutions_m3, 0) AS total_restitutions_m3,
            bj_n1.volume_mm3 AS volume_n1_mm3,
            bj_n1.taux_remplissage AS taux_n1
        FROM public.barrages b
        LEFT JOIN public.agences_territoriales a
          ON a.id = b.agence_id
        LEFT JOIN public.bilans_journaliers bj
          ON bj.barrage_id = b.id
         AND bj.date_bilan = :date_situation
        LEFT JOIN rest
          ON rest.bilan_journalier_id = bj.id
        LEFT JOIN public.bilans_journaliers bj_n1
          ON bj_n1.barrage_id = b.id
         AND bj_n1.date_bilan = (CAST(:date_situation AS date) - INTERVAL '1 year')::date
        WHERE {where_sql}
        ORDER BY COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code;
    """), {"date_situation": date_situation, **params}).mappings().all()

    barrages = []
    for row in rows:
        row_dict = dict(row)

        code = row_dict.get("barrage_code")
        capacity = _effective_capacity(code, row_dict.get("capacite_db_mm3"))
        volume = _float(row_dict.get("volume_mm3"))
        taux = _float(row_dict.get("taux_remplissage"))
        if taux is None:
            taux = _rate(volume, capacity)

        volume_n1 = _float(row_dict.get("volume_n1_mm3"))
        taux_n1 = _float(row_dict.get("taux_n1"))
        if taux_n1 is None:
            taux_n1 = _rate(volume_n1, capacity)

        if row_dict.get("bilan_id") is None:
            status = "Donnée manquante"
            severity = "danger"
        elif taux is not None and taux < 30:
            status = "Taux faible"
            severity = "warning"
        elif taux is not None and taux >= 95:
            status = "Très élevé"
            severity = "info"
        else:
            status = "OK"
            severity = "success"

        barrages.append({
            "barrage_id": row_dict.get("barrage_id"),
            "barrage_code": code,
            "barrage_nom": _fix_text(row_dict.get("barrage_nom")),
            "barrage_nom_court": _fix_text(row_dict.get("barrage_nom_court") or code),
            "agence_code": row_dict.get("agence_code"),
            "agence_nom": _fix_text(row_dict.get("agence_nom")),
            "capacite_normale_mm3": capacity,
            "date_bilan": _date_iso(row_dict.get("date_bilan")),
            "cote_7h_ngm": _float(row_dict.get("cote_7h_ngm")),
            "volume_mm3": volume,
            "surface_km2": _float(row_dict.get("surface_km2")),
            "taux_remplissage": taux,
            "hauteur_bac_mm": _float(row_dict.get("hauteur_bac_mm")),
            "pluie_mm": _float(row_dict.get("pluie_mm")),
            "evaporation_m3": _float(row_dict.get("evaporation_m3")),
            "apports_m3": _float(row_dict.get("apports_m3")),
            "total_restitutions_m3": _float(row_dict.get("total_restitutions_m3")) or 0.0,
            "volume_n1_mm3": volume_n1,
            "taux_n1": taux_n1,
            "status": status,
            "severity": severity,
        })

    capacity_total = sum(_zero(item["capacite_normale_mm3"]) for item in barrages)
    volume_total = sum(_zero(item["volume_mm3"]) for item in barrages)
    volume_n1_total = sum(_zero(item["volume_n1_mm3"]) for item in barrages)
    apports_total = sum(_zero(item["apports_m3"]) for item in barrages)
    rest_total = sum(_zero(item["total_restitutions_m3"]) for item in barrages)
    evaporation_total = sum(_zero(item["evaporation_m3"]) for item in barrages)
    pluie_total = sum(_zero(item["pluie_mm"]) for item in barrages)
    missing_count = sum(1 for item in barrages if item["date_bilan"] is None)

    agency_map: dict[str, dict[str, Any]] = {}
    for item in barrages:
        code = item["agence_code"] or "NON_CLASSE"
        record = agency_map.setdefault(code, {
            "agence_code": code,
            "agence_nom": item["agence_nom"] or "Non classé",
            "barrages_count": 0,
            "capacite_normale_mm3": 0.0,
            "volume_mm3": 0.0,
            "apports_m3": 0.0,
            "total_restitutions_m3": 0.0,
        })
        record["barrages_count"] += 1
        record["capacite_normale_mm3"] += _zero(item["capacite_normale_mm3"])
        record["volume_mm3"] += _zero(item["volume_mm3"])
        record["apports_m3"] += _zero(item["apports_m3"])
        record["total_restitutions_m3"] += _zero(item["total_restitutions_m3"])

    agency_summary = []
    for record in agency_map.values():
        record["taux_remplissage"] = _rate(record["volume_mm3"], record["capacite_normale_mm3"])
        agency_summary.append(record)

    agency_summary.sort(key=lambda item: item["volume_mm3"], reverse=True)

    return {
        "status": "ok",
        "date_situation": date_situation.isoformat(),
        "summary": {
            "barrages_count": len(barrages),
            "bilans_count": len(barrages) - missing_count,
            "missing_count": missing_count,
            "capacite_normale_mm3": capacity_total,
            "volume_mm3": volume_total,
            "taux_remplissage": _rate(volume_total, capacity_total),
            "volume_n1_mm3": volume_n1_total,
            "taux_n1": _rate(volume_n1_total, capacity_total),
            "apports_m3": apports_total,
            "total_restitutions_m3": rest_total,
            "evaporation_m3": evaporation_total,
            "pluie_mm": pluie_total,
        },
        "agency_summary": agency_summary,
        "barrages": barrages,
    }


def get_timeseries(
    db: Session,
    start_date: date,
    end_date: date,
    agence_code: str | None = None,
    barrage_code: str | None = None,
) -> dict:
    value_col = _restitution_value_column(db)
    where_sql, params = _filters_sql(agence_code, barrage_code)

    rows = db.execute(text(f"""
        WITH rest AS (
            SELECT
                rj.bilan_journalier_id,
                COALESCE(SUM(rj.{value_col}), 0) AS total_restitutions_m3
            FROM public.restitutions_journalieres rj
            GROUP BY rj.bilan_journalier_id
        )
        SELECT
            bj.date_bilan,
            b.code AS barrage_code,
            b.capacite_normale_mm3 AS capacite_db_mm3,
            bj.volume_mm3,
            bj.apports_m3,
            COALESCE(rest.total_restitutions_m3, 0) AS total_restitutions_m3,
            bj.evaporation_m3,
            bj.pluie_mm,
            bj.id AS bilan_id
        FROM public.bilans_journaliers bj
        JOIN public.barrages b
          ON b.id = bj.barrage_id
        LEFT JOIN public.agences_territoriales a
          ON a.id = b.agence_id
        LEFT JOIN rest
          ON rest.bilan_journalier_id = bj.id
        WHERE {where_sql}
          AND bj.date_bilan BETWEEN :start_date AND :end_date
        ORDER BY bj.date_bilan, COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code;
    """), {"start_date": start_date, "end_date": end_date, **params}).mappings().all()

    by_date: dict[Any, dict[str, Any]] = {}

    for row in rows:
        date_key = row["date_bilan"]
        point = by_date.setdefault(date_key, {
            "date": _date_iso(date_key),
            "capacite_normale_mm3": 0.0,
            "volume_mm3": 0.0,
            "apports_m3": 0.0,
            "total_restitutions_m3": 0.0,
            "evaporation_m3": 0.0,
            "pluie_mm": 0.0,
            "bilans_count": 0,
        })

        point["capacite_normale_mm3"] += _zero(_effective_capacity(row["barrage_code"], row["capacite_db_mm3"]))
        point["volume_mm3"] += _zero(row["volume_mm3"])
        point["apports_m3"] += _zero(row["apports_m3"])
        point["total_restitutions_m3"] += _zero(row["total_restitutions_m3"])
        point["evaporation_m3"] += _zero(row["evaporation_m3"])
        point["pluie_mm"] += _zero(row["pluie_mm"])
        point["bilans_count"] += 1

    points = []
    for date_key in sorted(by_date):
        point = by_date[date_key]
        point["taux_remplissage"] = _rate(point["volume_mm3"], point["capacite_normale_mm3"])
        points.append(point)

    return {
        "status": "ok",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "points": points,
    }


def get_custom_values(
    db: Session,
    start_date: date,
    end_date: date,
    agence_code: str | None = None,
    barrage_codes: list[str] | None = None,
    variables: list[str] | None = None,
) -> dict:
    value_col = _restitution_value_column(db)

    variables = [item for item in (variables or ["volume", "taux"]) if item in VARIABLES]
    if not variables:
        variables = ["volume", "taux"]

    clauses = [
        "COALESCE(b.actif, TRUE) = TRUE",
        "COALESCE(b.inclure_calculs, TRUE) = TRUE",
        "bj.date_bilan BETWEEN :start_date AND :end_date",
    ]
    params: dict[str, Any] = {"start_date": start_date, "end_date": end_date}

    if agence_code:
        clauses.append("a.code = :agence_code")
        params["agence_code"] = agence_code

    if barrage_codes:
        clauses.append("b.code = ANY(:barrage_codes)")
        params["barrage_codes"] = barrage_codes

    rows = db.execute(text(f"""
        WITH rest AS (
            SELECT
                rj.bilan_journalier_id,
                COALESCE(SUM(rj.{value_col}), 0) AS total_restitutions_m3
            FROM public.restitutions_journalieres rj
            GROUP BY rj.bilan_journalier_id
        ),
        prev AS (
            SELECT
                bj2.barrage_id,
                bj2.date_bilan + INTERVAL '1 day' AS date_bilan,
                bj2.volume_mm3 AS previous_volume_mm3
            FROM public.bilans_journaliers bj2
        )
        SELECT
            bj.date_bilan,
            b.code AS barrage_code,
            b.nom_court AS barrage_nom_court,
            b.capacite_normale_mm3 AS capacite_db_mm3,
            a.code AS agence_code,
            a.nom AS agence_nom,
            bj.cote_7h_ngm,
            bj.volume_mm3,
            bj.surface_km2,
            bj.taux_remplissage,
            bj.hauteur_bac_mm,
            bj.pluie_mm,
            bj.evaporation_m3,
            bj.apports_m3,
            COALESCE(rest.total_restitutions_m3, 0) AS total_restitutions_m3,
            CASE
                WHEN bj.apports_m3 IS NULL THEN NULL
                ELSE bj.apports_m3 / 86400.0
            END AS debit_m3s,
            bj_n1.volume_mm3 AS volume_n1_mm3,
            bj.volume_mm3 - prev.previous_volume_mm3 AS variation_mm3
        FROM public.bilans_journaliers bj
        JOIN public.barrages b
          ON b.id = bj.barrage_id
        LEFT JOIN public.agences_territoriales a
          ON a.id = b.agence_id
        LEFT JOIN rest
          ON rest.bilan_journalier_id = bj.id
        LEFT JOIN public.bilans_journaliers bj_n1
          ON bj_n1.barrage_id = b.id
         AND bj_n1.date_bilan = (bj.date_bilan - INTERVAL '1 year')::date
        LEFT JOIN prev
          ON prev.barrage_id = bj.barrage_id
         AND prev.date_bilan::date = bj.date_bilan
        WHERE {" AND ".join(clauses)}
        ORDER BY bj.date_bilan, COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code;
    """), params).mappings().all()

    field_map = {
        "cote": "cote_7h_ngm",
        "volume": "volume_mm3",
        "surface": "surface_km2",
        "pluie": "pluie_mm",
        "hauteur_bac": "hauteur_bac_mm",
        "evaporation": "evaporation_m3",
        "apports": "apports_m3",
        "restitutions": "total_restitutions_m3",
        "debit": "debit_m3s",
        "volume_n1": "volume_n1_mm3",
        "variation": "variation_mm3",
    }

    data_rows = []
    for row in rows:
        capacity = _effective_capacity(row["barrage_code"], row.get("capacite_db_mm3"))

        values: dict[str, float | None] = {}
        for variable in variables:
            if variable == "taux":
                taux = _float(row.get("taux_remplissage"))
                if taux is None:
                    taux = _rate(_float(row.get("volume_mm3")), capacity)
                values[variable] = taux
            else:
                values[variable] = _float(row.get(field_map[variable]))

        data_rows.append({
            "date": _date_iso(row["date_bilan"]),
            "barrage_code": row["barrage_code"],
            "barrage_nom_court": _fix_text(row["barrage_nom_court"] or row["barrage_code"]),
            "agence_code": row["agence_code"],
            "agence_nom": _fix_text(row["agence_nom"]),
            "values": values,
        })

    return {
        "status": "ok",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "variables": {key: VARIABLES[key] for key in variables},
        "rows": data_rows,
    }
