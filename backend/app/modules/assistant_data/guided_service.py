
from __future__ import annotations

import decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.assistant_data.schemas import GuidedQueryRequest
from app.modules.assistant_data.utils import jsonable, row_to_dict


SIMPLE_METRICS: dict[str, dict[str, Any]] = {
    "volume": {"label": "Volume / réserve", "unit": "Mm³", "digits": 3, "expr": "bj.volume_mm3"},
    "taux_remplissage": {"label": "Taux de remplissage", "unit": "%", "digits": 1, "expr": "bj.taux_remplissage"},
    "cote_7h": {"label": "Cote à 7h", "unit": "mNGM", "digits": 2, "expr": "bj.cote_7h_ngm"},
    "hauteur_bac": {"label": "Hauteur Bac", "unit": "mm", "digits": 2, "expr": "bj.hauteur_bac_mm"},
    "pluie": {"label": "Pluie", "unit": "mm", "digits": 1, "expr": "bj.pluie_mm"},
    "surface": {"label": "Surface", "unit": "km²", "digits": 3, "expr": "bj.surface_km2"},
    "surface_moyenne": {"label": "Surface moyenne", "unit": "km²", "digits": 3, "expr": "bj.surface_moyenne_km2"},
    "volume_jour_suivant": {"label": "Volume jour suivant", "unit": "Mm³", "digits": 3, "expr": "bj.volume_jour_suivant_mm3"},
    "variation_reserve": {"label": "Variation de réserve", "unit": "Mm³", "digits": 3, "expr": "bj.variation_reserve_mm3"},
    "evaporation": {"label": "Évaporation", "unit": "m³", "digits": 0, "expr": "bj.evaporation_m3"},
    "apports": {"label": "Apports", "unit": "m³", "digits": 0, "expr": "bj.apports_m3"},
    "debit": {"label": "Débit moyen", "unit": "m³/s", "digits": 3, "expr": "bj.debit_m3s"},
    "capacite": {"label": "Capacité normale", "unit": "Mm³", "digits": 3, "expr": "b.capacite_normale_mm3"},
    "cote_normale": {"label": "Cote normale", "unit": "mNGM", "digits": 2, "expr": "b.cote_normale_ngm"},
}

METRIC_GROUPS = [
    {
        "code": "hydraulique",
        "label": "Situation hydraulique",
        "metrics": [
            "volume",
            "taux_remplissage",
            "cote_7h",
            "hauteur_bac",
            "variation_reserve",
            "capacite",
            "cote_normale",
        ],
    },
    {
        "code": "climat",
        "label": "Climat / pertes",
        "metrics": [
            "pluie",
            "evaporation",
            "surface",
            "surface_moyenne",
            "volume_jour_suivant",
        ],
    },
    {
        "code": "apports",
        "label": "Apports / débit",
        "metrics": ["apports", "debit"],
    },
]

LABELS = {
    "date": "Date",
    "date_bilan": "Date",
    "barrage_code": "Code barrage",
    "barrage": "Barrage",
    "barrage_nom": "Nom barrage",
    "agence_code": "Code agence",
    "agence": "Agence",
    "type_code": "Type code",
    "type_libelle": "Type restitution",
    "valeur_m3": "Valeur",
    "total_restitutions_m3": "Total restitutions",
    "irrigation_m3": "Irrigation",
    "transfert_m3": "Transfert",
    "prise_agricole_rd_m3": "Prise agricole RD",
    "prise_agricole_rg_m3": "Prise agricole RG",
    "aepi_tanger_m3": "AEPI Tanger",
    "source_code": "Source code",
    "source_barrage": "Source barrage",
    "destination_code": "Destination code",
    "destination_barrage": "Destination barrage",
    "source_table": "Source table",
}

UNITS = {
    "valeur_m3": "m³",
    "total_restitutions_m3": "m³",
    "irrigation_m3": "m³",
    "transfert_m3": "m³",
    "prise_agricole_rd_m3": "m³",
    "prise_agricole_rg_m3": "m³",
    "aepi_tanger_m3": "m³",
}


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, decimal.Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return 0.0


def _format_number(value: Any, digits: int = 0) -> str:
    if value is None:
        return "-"
    if isinstance(value, decimal.Decimal):
        value = float(value)
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return str(value)


def _limit(value: int | None) -> int:
    try:
        raw = int(value or 500)
    except Exception:
        raw = 500
    return max(1, min(raw, 1000))


def _columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    output = []

    for key in rows[0].keys():
        meta = SIMPLE_METRICS.get(key)
        output.append(
            {
                "key": key,
                "label": meta["label"] if meta else LABELS.get(key, key.replace("_", " ").title()),
                "unit": meta["unit"] if meta else UNITS.get(key, ""),
                "digits": meta["digits"] if meta else (0 if key.endswith("_m3") or key == "valeur_m3" else 3),
            }
        )

    return output


def _chart(rows: list[dict[str, Any]], metric_key: str | None = None) -> dict[str, Any] | None:
    if not rows:
        return None

    keys = list(rows[0].keys())
    numeric = [k for k in keys if any(isinstance(row.get(k), (int, float)) for row in rows)]

    if metric_key and metric_key in numeric:
        numeric = [metric_key] + [k for k in numeric if k != metric_key]

    if not numeric:
        return None

    x_key = (
        "date"
        if "date" in keys
        else "date_bilan"
        if "date_bilan" in keys
        else "type_libelle"
        if "type_libelle" in keys
        else "barrage"
        if "barrage" in keys
        else keys[0]
    )

    chart_type = "line" if x_key in {"date", "date_bilan"} and len(rows) > 1 else "bar"

    return {"type": chart_type, "x_key": x_key, "y_keys": numeric[:3]}


def _execute(db: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        db.execute(text("SET LOCAL transaction_read_only = on"))
        db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
        rows = [row_to_dict(row) for row in db.execute(text(sql), params).mappings().all()]
        db.rollback()
        return rows
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Recherche guidée impossible : {exc}") from exc


def _payload(
    answer: str,
    explanation: str,
    rows: list[dict[str, Any]],
    sql: str,
    params: dict[str, Any],
    metric_key: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "guided_slicers",
        "llm": {"attempted": False, "used": False, "error": None},
        "answer": answer,
        "explanation": explanation,
        "rows": rows,
        "columns": _columns(rows),
        "chart": _chart(rows, metric_key),
        "sql_used": sql,
        "sql_params": {key: jsonable(value) for key, value in params.items()},
        "safety": {"read_only": True, "select_only": True, "llm_used": False},
    }


def _available_dates(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT MIN(date_bilan) AS min_date, MAX(date_bilan) AS max_date FROM public.bilans_journaliers"
        )
    ).mappings().first()

    return {"min": row["min_date"] if row else None, "max": row["max_date"] if row else None}


def _types_for_barrage(db: Session, barrage_code: str | None) -> list[dict[str, Any]]:
    if not barrage_code:
        return []

    sql = """
SELECT DISTINCT tr.code, tr.libelle, tr.unite
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
WHERE b.code = :barrage_code
ORDER BY tr.code
"""

    return [
        row_to_dict(row)
        for row in db.execute(text(sql), {"barrage_code": barrage_code}).mappings().all()
    ]


def get_guided_profile(db: Session, barrage_code: str | None = None) -> dict[str, Any]:
    barrage = None

    if barrage_code:
        barrage = db.execute(
            text(
                """
SELECT b.code, b.nom, b.nom_court, b.capacite_normale_mm3, b.cote_normale_ngm, a.code AS agence_code, a.nom AS agence
FROM public.barrages b
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE b.code = :code
"""
            ),
            {"code": barrage_code},
        ).mappings().first()

        barrage = row_to_dict(barrage) if barrage else None

    dates = _available_dates(db)
    types = _types_for_barrage(db, barrage_code)

    groups = []

    for group in METRIC_GROUPS:
        groups.append(
            {
                "code": group["code"],
                "label": group["label"],
                "metrics": [
                    {
                        "code": code,
                        "label": SIMPLE_METRICS[code]["label"],
                        "unit": SIMPLE_METRICS[code]["unit"],
                        "kind": "simple",
                    }
                    for code in group["metrics"]
                ],
            }
        )

    restitutions = [
        {"code": "restitutions_total", "label": "Total restitutions", "kind": "restitution_total"},
        {"code": "restitutions_detail", "label": "Détail complet", "kind": "restitution_detail"},
    ]

    for item in types:
        restitutions.append(
            {
                "code": f"type::{item['code']}",
                "label": item.get("libelle") or item.get("code"),
                "kind": "restitution_type",
                "type_code": item.get("code"),
            }
        )

    special = []

    if barrage_code == "DAR_KHROFA":
        special.append(
            {
                "code": "irrigation",
                "label": "Irrigation",
                "kind": "usage",
                "rule": "PRISE_AGRICOLE_RD + PRISE_AGRICOLE_RG - AEPI_TANGER",
            }
        )
        special.append(
            {
                "code": "transfert",
                "label": "Transfert depuis Oued El Makhazine",
                "kind": "transfer",
                "rule": "transferts_journaliers puis fallback TRANSFERT_DAR_KHROFA",
            }
        )
    else:
        special.append(
            {
                "code": "irrigation",
                "label": "Irrigation",
                "kind": "usage",
                "rule": "types de restitution/utilisation liés à irrigation",
            }
        )
        special.append({"code": "transfert", "label": "Transferts", "kind": "transfer"})

    return {
        "status": "ok",
        "barrage": barrage,
        "dates": {"min": jsonable(dates.get("min")), "max": jsonable(dates.get("max"))},
        "metric_groups": groups,
        "restitutions": restitutions,
        "special_metrics": special,
        "types_restitution": types,
        "llm_used": False,
    }


def _simple_metric(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    metric = payload.metric if payload.metric in SIMPLE_METRICS else "volume"
    meta = SIMPLE_METRICS[metric]

    sql = f"""
SELECT bj.date_bilan AS date, b.code AS barrage_code, COALESCE(b.nom_court, b.nom) AS barrage, b.nom AS barrage_nom,
       a.code AS agence_code, a.nom AS agence, {meta['expr']} AS {metric}
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE (:barrage_code IS NULL OR b.code = :barrage_code)
  AND (:agence_code IS NULL OR a.code = :agence_code)
  AND bj.date_bilan BETWEEN :start_date AND :end_date
ORDER BY bj.date_bilan ASC, COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code
LIMIT :limit
"""

    params = {
        "barrage_code": payload.barrage_code,
        "agence_code": payload.agence_code,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)

    answer = f"J’ai trouvé {len(rows)} ligne(s) dans PostgreSQL pour {meta['label']}. Consulte le tableau pour les détails."

    return _payload(answer, "Résultat produit par les slicers contrôlés, sans LLM.", rows, sql, params, metric)


def _restitutions_total(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    sql = """
SELECT bj.date_bilan AS date, b.code AS barrage_code, COALESCE(b.nom_court, b.nom) AS barrage, b.nom AS barrage_nom,
       a.code AS agence_code, a.nom AS agence, bj.total_restitutions_m3 AS total_restitutions_m3
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE (:barrage_code IS NULL OR b.code = :barrage_code)
  AND (:agence_code IS NULL OR a.code = :agence_code)
  AND bj.date_bilan BETWEEN :start_date AND :end_date
ORDER BY bj.date_bilan ASC, COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code
LIMIT :limit
"""

    params = {
        "barrage_code": payload.barrage_code,
        "agence_code": payload.agence_code,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)

    total = sum(_to_float(row.get("total_restitutions_m3")) for row in rows)

    answer = f"Total des restitutions sur la sélection : {_format_number(total, 0)} m³. {len(rows)} ligne(s) trouvée(s). Source : PostgreSQL."

    return _payload(
        answer,
        "Restitutions totales depuis bilans_journaliers.total_restitutions_m3, sans LLM.",
        rows,
        sql,
        params,
        "total_restitutions_m3",
    )


def _restitutions_detail(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    sql = """
SELECT bj.date_bilan AS date, b.code AS barrage_code, COALESCE(b.nom_court, b.nom) AS barrage,
       tr.code AS type_code, tr.libelle AS type_libelle, rj.valeur_m3 AS valeur_m3
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE (:barrage_code IS NULL OR b.code = :barrage_code)
  AND (:agence_code IS NULL OR a.code = :agence_code)
  AND bj.date_bilan BETWEEN :start_date AND :end_date
ORDER BY bj.date_bilan ASC, tr.code
LIMIT :limit
"""

    params = {
        "barrage_code": payload.barrage_code,
        "agence_code": payload.agence_code,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)

    answer = f"J’ai trouvé {len(rows)} ligne(s) de restitutions détaillées. Source : PostgreSQL."

    return _payload(
        answer,
        "Détail par type de restitution depuis restitutions_journalieres + types_restitution, sans LLM.",
        rows,
        sql,
        params,
        "valeur_m3",
    )


def _restitution_type(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    type_code = payload.restitution_type_code or ""

    if payload.metric.startswith("type::"):
        type_code = payload.metric.split("::", 1)[1]

    if not type_code:
        raise HTTPException(status_code=400, detail="Type de restitution manquant.")

    sql = """
SELECT bj.date_bilan AS date, b.code AS barrage_code, COALESCE(b.nom_court, b.nom) AS barrage,
       tr.code AS type_code, tr.libelle AS type_libelle, rj.valeur_m3 AS valeur_m3
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE (:barrage_code IS NULL OR b.code = :barrage_code)
  AND (:agence_code IS NULL OR a.code = :agence_code)
  AND bj.date_bilan BETWEEN :start_date AND :end_date
  AND tr.code = :type_code
ORDER BY bj.date_bilan ASC, b.code
LIMIT :limit
"""

    params = {
        "barrage_code": payload.barrage_code,
        "agence_code": payload.agence_code,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "type_code": type_code,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)

    total = sum(_to_float(row.get("valeur_m3")) for row in rows)

    answer = f"{type_code} sur la sélection : {_format_number(total, 0)} m³. Source : PostgreSQL."

    return _payload(
        answer,
        f"Valeur du type de restitution {type_code}, sans LLM.",
        rows,
        sql,
        params,
        "valeur_m3",
    )


def _irrigation(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    if payload.barrage_code == "DAR_KHROFA":
        sql = """
WITH details AS (
    SELECT bj.date_bilan, b.code AS barrage_code, COALESCE(b.nom_court, b.nom) AS barrage,
           UPPER(COALESCE(tr.code, '')) AS code, LOWER(COALESCE(tr.libelle, '')) AS libelle, COALESCE(rj.valeur_m3,0) AS valeur_m3
    FROM public.bilans_journaliers bj
    JOIN public.barrages b ON b.id = bj.barrage_id
    LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
    LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
    WHERE b.code = 'DAR_KHROFA' AND bj.date_bilan BETWEEN :start_date AND :end_date
)
SELECT date_bilan AS date, barrage_code, barrage,
       SUM(CASE WHEN code LIKE '%PRISE%AGRICOLE%RD%' OR (libelle LIKE '%prise%' AND libelle LIKE '%agricole%' AND (libelle LIKE '%rd%' OR libelle LIKE '%droite%')) THEN valeur_m3 ELSE 0 END) AS prise_agricole_rd_m3,
       SUM(CASE WHEN code LIKE '%PRISE%AGRICOLE%RG%' OR (libelle LIKE '%prise%' AND libelle LIKE '%agricole%' AND (libelle LIKE '%rg%' OR libelle LIKE '%gauche%')) THEN valeur_m3 ELSE 0 END) AS prise_agricole_rg_m3,
       SUM(CASE WHEN code LIKE '%AEPI%TANGER%' OR (libelle LIKE '%aepi%' AND libelle LIKE '%tanger%') THEN valeur_m3 ELSE 0 END) AS aepi_tanger_m3,
       SUM(CASE WHEN code LIKE '%PRISE%AGRICOLE%RD%' OR (libelle LIKE '%prise%' AND libelle LIKE '%agricole%' AND (libelle LIKE '%rd%' OR libelle LIKE '%droite%')) THEN valeur_m3 ELSE 0 END)
       + SUM(CASE WHEN code LIKE '%PRISE%AGRICOLE%RG%' OR (libelle LIKE '%prise%' AND libelle LIKE '%agricole%' AND (libelle LIKE '%rg%' OR libelle LIKE '%gauche%')) THEN valeur_m3 ELSE 0 END)
       - SUM(CASE WHEN code LIKE '%AEPI%TANGER%' OR (libelle LIKE '%aepi%' AND libelle LIKE '%tanger%') THEN valeur_m3 ELSE 0 END) AS irrigation_m3
FROM details
GROUP BY date_bilan, barrage_code, barrage
ORDER BY date_bilan
LIMIT :limit
"""

        params = {
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "limit": _limit(payload.limit),
        }

        rows = _execute(db, sql, params)

        answer = f"Irrigation Dar Khrofa : {len(rows)} ligne(s). Source : PostgreSQL."

        return _payload(
            answer,
            "Règle Dar Khrofa : Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger, sans LLM.",
            rows,
            sql,
            params,
            "irrigation_m3",
        )

    sql = """
SELECT bj.date_bilan AS date, b.code AS barrage_code, COALESCE(b.nom_court, b.nom) AS barrage,
       COALESCE(SUM(CASE
           WHEN UPPER(COALESCE(tr.code,'')) LIKE '%IRRIG%'
             OR LOWER(COALESCE(tr.libelle,'')) LIKE '%irrig%'
             OR LOWER(COALESCE(tr.libelle,'')) LIKE '%agricole%'
             OR LOWER(COALESCE(tr.libelle,'')) LIKE '%siphon%'
           THEN rj.valeur_m3 ELSE 0 END),0) AS irrigation_m3
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE (:barrage_code IS NULL OR b.code = :barrage_code)
  AND (:agence_code IS NULL OR a.code = :agence_code)
  AND bj.date_bilan BETWEEN :start_date AND :end_date
GROUP BY bj.date_bilan, b.code, COALESCE(b.nom_court, b.nom)
ORDER BY bj.date_bilan ASC, b.code
LIMIT :limit
"""

    params = {
        "barrage_code": payload.barrage_code,
        "agence_code": payload.agence_code,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)

    return _payload(
        f"Irrigation : {len(rows)} ligne(s) trouvée(s). Source : PostgreSQL.",
        "Irrigation lue dans les types de restitution/utilisation du barrage, sans LLM.",
        rows,
        sql,
        params,
        "irrigation_m3",
    )


def _transfer(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    sql = """
SELECT tj.date_bilan AS date, s.code AS source_code, COALESCE(s.nom_court, s.nom) AS source_barrage,
       d.code AS destination_code, COALESCE(d.nom_court, d.nom) AS destination_barrage, tj.valeur_m3 AS transfert_m3,
       'transferts_journaliers' AS source_table
FROM public.transferts_journaliers tj
JOIN public.barrages s ON s.id = tj.barrage_source_id
JOIN public.barrages d ON d.id = tj.barrage_destination_id
WHERE (:barrage_code IS NULL OR s.code = :barrage_code OR d.code = :barrage_code)
  AND tj.date_bilan BETWEEN :start_date AND :end_date
ORDER BY tj.date_bilan ASC, tj.valeur_m3 DESC
LIMIT :limit
"""

    params = {
        "barrage_code": payload.barrage_code,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)

    if rows:
        total = sum(_to_float(row.get("transfert_m3")) for row in rows)
        return _payload(
            f"Transfert total sur la sélection : {_format_number(total, 0)} m³. Source : PostgreSQL.",
            "Transferts depuis transferts_journaliers, sans LLM.",
            rows,
            sql,
            params,
            "transfert_m3",
        )

    if payload.barrage_code == "DAR_KHROFA":
        sql_fb = """
WITH bj0 AS (
    SELECT bj.id, bj.date_bilan, b.code AS destination_code, COALESCE(b.nom_court, b.nom) AS destination_barrage
    FROM public.bilans_journaliers bj JOIN public.barrages b ON b.id = bj.barrage_id
    WHERE b.code = 'DAR_KHROFA' AND bj.date_bilan BETWEEN :start_date AND :end_date
)
SELECT bj0.date_bilan AS date, 'BOEM' AS source_code, 'Oued El Makhazine' AS source_barrage,
       bj0.destination_code, bj0.destination_barrage,
       COALESCE(SUM(CASE WHEN UPPER(COALESCE(tr.code,'')) LIKE '%TRANSFERT%DAR%KHROFA%' OR LOWER(COALESCE(tr.libelle,'')) LIKE '%transfert%dar khrofa%' THEN rj.valeur_m3 ELSE 0 END),0) AS transfert_m3,
       'restitutions_journalieres/types_restitution' AS source_table
FROM bj0
LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj0.id
LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
GROUP BY bj0.date_bilan, bj0.destination_code, bj0.destination_barrage
ORDER BY bj0.date_bilan
LIMIT :limit
"""

        params_fb = {
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "limit": _limit(payload.limit),
        }

        rows = _execute(db, sql_fb, params_fb)
        total = sum(_to_float(row.get("transfert_m3")) for row in rows)

        return _payload(
            f"Transfert depuis Oued El Makhazine vers Dar Khrofa : {_format_number(total, 0)} m³ sur la sélection. Source : PostgreSQL.",
            "Fallback Dar Khrofa : type TRANSFERT_DAR_KHROFA, sans LLM.",
            rows,
            sql_fb,
            params_fb,
            "transfert_m3",
        )

    return _payload(
        "Aucun transfert trouvé pour cette sélection.",
        "Recherche effectuée dans transferts_journaliers, sans LLM.",
        [],
        sql,
        params,
        "transfert_m3",
    )


def run_guided_query(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    dates = _available_dates(db)

    if not payload.start_date:
        payload.start_date = dates.get("max")

    if not payload.end_date:
        payload.end_date = payload.start_date or dates.get("max")

    metric = payload.metric or "volume"

    # Correction ciblée V14 : dans la recherche guidée, le bouton "Irrigation"
    # peut arriver comme metric="type::IRRIGATION" parce qu'il existe aussi
    # dans les restitutions détaillées. Pour DAR_KHROFA, on force la règle Excel :
    # Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger.
    if payload.barrage_code == "DAR_KHROFA" and str(metric or "").strip().lower() in {"irrigation", "type::irrigation"}:
        return _dar_khrofa_irrigation_guided_v15(db, payload)

    if metric == "restitutions_total":
        return _restitutions_total(db, payload)

    if metric == "restitutions_detail":
        return _restitutions_detail(db, payload)

    if metric == "irrigation":
        return _irrigation(db, payload)

    if metric == "transfert":
        return _transfer(db, payload)

    if metric.startswith("type::") or payload.restitution_type_code:
        return _restitution_type(db, payload)

    return _simple_metric(db, payload)


def _dar_khrofa_irrigation_guided_v14(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    """Correction ciblée Recherche guidée.

    Cas métier Dar Khrofa :
    Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger.
    """

    sql = """
WITH details AS (
    SELECT
        bj.date_bilan,
        b.code AS barrage_code,
        COALESCE(b.nom_court, b.nom) AS barrage,
        UPPER(COALESCE(tr.code, '')) AS type_code_upper,
        LOWER(COALESCE(tr.libelle, '')) AS type_libelle_lower,
        COALESCE(rj.valeur_m3, 0) AS valeur_m3
    FROM public.bilans_journaliers bj
    JOIN public.barrages b ON b.id = bj.barrage_id
    LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
    LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
    WHERE b.code = 'DAR_KHROFA'
      AND bj.date_bilan BETWEEN :start_date AND :end_date
),
calc AS (
    SELECT
        date_bilan,
        barrage_code,
        barrage,

        SUM(
            CASE
                WHEN
                    (
                        type_code_upper LIKE '%PRISE%'
                        AND type_code_upper LIKE '%AGRICOLE%'
                        AND type_code_upper LIKE '%RD%'
                    )
                    OR
                    (
                        type_libelle_lower LIKE '%prise%'
                        AND type_libelle_lower LIKE '%agricole%'
                        AND (
                            type_libelle_lower LIKE '% rd%'
                            OR type_libelle_lower LIKE '%rd %'
                            OR type_libelle_lower LIKE '%droite%'
                            OR type_libelle_lower LIKE '%digue b%'
                        )
                    )
                THEN valeur_m3
                ELSE 0
            END
        ) AS prise_agricole_rd_m3,

        SUM(
            CASE
                WHEN
                    (
                        type_code_upper LIKE '%PRISE%'
                        AND type_code_upper LIKE '%AGRICOLE%'
                        AND type_code_upper LIKE '%RG%'
                    )
                    OR
                    (
                        type_libelle_lower LIKE '%prise%'
                        AND type_libelle_lower LIKE '%agricole%'
                        AND (
                            type_libelle_lower LIKE '% rg%'
                            OR type_libelle_lower LIKE '%rg %'
                            OR type_libelle_lower LIKE '%gauche%'
                            OR type_libelle_lower LIKE '%digue a%'
                        )
                    )
                THEN valeur_m3
                ELSE 0
            END
        ) AS prise_agricole_rg_m3,

        SUM(
            CASE
                WHEN
                    (
                        type_code_upper LIKE '%AEPI%'
                        AND type_code_upper LIKE '%TANGER%'
                    )
                    OR
                    (
                        type_libelle_lower LIKE '%aepi%'
                        AND type_libelle_lower LIKE '%tanger%'
                    )
                THEN valeur_m3
                ELSE 0
            END
        ) AS aepi_tanger_m3

    FROM details
    GROUP BY date_bilan, barrage_code, barrage
)
SELECT
    date_bilan AS date,
    barrage_code,
    barrage,
    prise_agricole_rd_m3,
    prise_agricole_rg_m3,
    aepi_tanger_m3,
    (prise_agricole_rd_m3 + prise_agricole_rg_m3 - aepi_tanger_m3) AS irrigation_m3
FROM calc
ORDER BY date_bilan ASC
LIMIT :limit
"""

    params = {
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)
    total = sum(_to_float(row.get("irrigation_m3")) for row in rows)

    answer = (
        "Irrigation Dar Khrofa sur la sélection : "
        f"{_format_number(total, 0)} m³. Source : PostgreSQL."
    )

    return _payload(
        answer,
        "Règle spéciale Dar Khrofa : Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger. Recherche guidée sans LLM.",
        rows,
        sql,
        params,
        "irrigation_m3",
    )


def _dar_khrofa_irrigation_guided_v15(db: Session, payload: GuidedQueryRequest) -> dict[str, Any]:
    """Correction ciblée Recherche guidée V15.

    Dar Khrofa :
    - règle normale Excel : Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger
    - fallback uniquement si les composants RD/RG/AEPI Tanger sont absents dans la base :
      utiliser la ligne directe IRRIGATION si elle existe.
    """

    sql = """
WITH details AS (
    SELECT
        bj.date_bilan,
        b.code AS barrage_code,
        COALESCE(b.nom_court, b.nom) AS barrage,
        UPPER(COALESCE(tr.code, '')) AS type_code_upper,
        LOWER(COALESCE(tr.libelle, '')) AS type_libelle_lower,
        COALESCE(rj.valeur_m3, 0) AS valeur_m3
    FROM public.bilans_journaliers bj
    JOIN public.barrages b ON b.id = bj.barrage_id
    LEFT JOIN public.restitutions_journalieres rj ON rj.bilan_journalier_id = bj.id
    LEFT JOIN public.types_restitution tr ON tr.id = rj.type_restitution_id
    WHERE b.code = 'DAR_KHROFA'
      AND bj.date_bilan BETWEEN :start_date AND :end_date
),
calc AS (
    SELECT
        date_bilan,
        barrage_code,
        barrage,

        SUM(
            CASE
                WHEN
                    (
                        type_code_upper LIKE '%PRISE%'
                        AND type_code_upper LIKE '%AGRICOLE%'
                        AND type_code_upper LIKE '%RD%'
                    )
                    OR
                    (
                        type_libelle_lower LIKE '%prise%'
                        AND type_libelle_lower LIKE '%agricole%'
                        AND (
                            type_libelle_lower LIKE '% rd%'
                            OR type_libelle_lower LIKE '%rd %'
                            OR type_libelle_lower LIKE '%droite%'
                            OR type_libelle_lower LIKE '%digue b%'
                        )
                    )
                THEN valeur_m3
                ELSE 0
            END
        ) AS prise_agricole_rd_m3,

        SUM(
            CASE
                WHEN
                    (
                        type_code_upper LIKE '%PRISE%'
                        AND type_code_upper LIKE '%AGRICOLE%'
                        AND type_code_upper LIKE '%RG%'
                    )
                    OR
                    (
                        type_libelle_lower LIKE '%prise%'
                        AND type_libelle_lower LIKE '%agricole%'
                        AND (
                            type_libelle_lower LIKE '% rg%'
                            OR type_libelle_lower LIKE '%rg %'
                            OR type_libelle_lower LIKE '%gauche%'
                            OR type_libelle_lower LIKE '%digue a%'
                        )
                    )
                THEN valeur_m3
                ELSE 0
            END
        ) AS prise_agricole_rg_m3,

        SUM(
            CASE
                WHEN
                    (
                        type_code_upper LIKE '%AEPI%'
                        AND type_code_upper LIKE '%TANGER%'
                    )
                    OR
                    (
                        type_libelle_lower LIKE '%aepi%'
                        AND type_libelle_lower LIKE '%tanger%'
                    )
                THEN valeur_m3
                ELSE 0
            END
        ) AS aepi_tanger_m3,

        SUM(
            CASE
                WHEN
                    type_code_upper = 'IRRIGATION'
                    OR type_code_upper LIKE '%IRRIGATION%'
                    OR type_libelle_lower = 'irrigation'
                    OR type_libelle_lower LIKE '%irrigation%'
                THEN valeur_m3
                ELSE 0
            END
        ) AS irrigation_directe_m3

    FROM details
    GROUP BY date_bilan, barrage_code, barrage
)
SELECT
    date_bilan AS date,
    barrage_code,
    barrage,
    prise_agricole_rd_m3,
    prise_agricole_rg_m3,
    aepi_tanger_m3,
    irrigation_directe_m3,
    CASE
        WHEN
            COALESCE(prise_agricole_rd_m3, 0) <> 0
            OR COALESCE(prise_agricole_rg_m3, 0) <> 0
            OR COALESCE(aepi_tanger_m3, 0) <> 0
        THEN
            COALESCE(prise_agricole_rd_m3, 0)
            + COALESCE(prise_agricole_rg_m3, 0)
            - COALESCE(aepi_tanger_m3, 0)
        ELSE
            COALESCE(irrigation_directe_m3, 0)
    END AS irrigation_m3
FROM calc
ORDER BY date_bilan ASC
LIMIT :limit
"""

    params = {
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "limit": _limit(payload.limit),
    }

    rows = _execute(db, sql, params)
    total = sum(_to_float(row.get("irrigation_m3")) for row in rows)

    answer = (
        "Irrigation Dar Khrofa sur la sélection : "
        f"{_format_number(total, 0)} m³. Source : PostgreSQL."
    )

    return _payload(
        answer,
        "Règle spéciale Dar Khrofa : Irrigation = Prise Agricole RD + Prise Agricole RG - AEPI Tanger. Si ces composants sont absents pour une date, fallback sur la valeur IRRIGATION directe. Recherche guidée sans LLM.",
        rows,
        sql,
        params,
        "irrigation_m3",
    )

