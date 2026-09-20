from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.assistant_data.business_shortcuts import try_business_shortcut
from app.modules.assistant_data.answer_generator import (
    build_chart,
    build_columns,
    deterministic_answer,
    generate_final_answer,
)
from app.modules.assistant_data.catalog_reader import read_agences, read_available_dates, read_barrages, read_catalog
from app.modules.assistant_data.llm_client import llm_enabled, llm_status, test_llm_connection
from app.modules.assistant_data.schemas import AssistantFilters, AssistantQueryRequest
from app.modules.assistant_data.semantic_dictionary import METRICS, compact_metric_catalog
from app.modules.assistant_data.sql_generator import generate_sql_with_llm
from app.modules.assistant_data.sql_repair import execute_with_repair
from app.modules.assistant_data.utils import jsonable, limit_value, row_to_dict


def get_llm_status() -> dict[str, Any]:
    return llm_status()


def _simple_filter_sql(filters: AssistantFilters) -> tuple[str, dict[str, Any]]:
    latest_dates = {"max": None}
    params: dict[str, Any] = {
        "start_date": filters.start_date,
        "end_date": filters.end_date,
        "limit": limit_value(filters.limit),
    }

    metrics = [metric for metric in (filters.metrics or ["volume", "taux_remplissage"]) if metric in METRICS]
    if not metrics:
        metrics = ["volume", "taux_remplissage"]

    select_parts = [
        "bj.date_bilan",
        "b.code AS barrage_code",
        "COALESCE(b.nom_court, b.nom) AS barrage",
        "b.nom AS barrage_nom",
    ]

    # agence_id peut exister selon migration. Laisser le LEFT JOIN fonctionner si table existe.
    select_parts.extend(["a.code AS agence_code", "a.nom AS agence"])

    for metric in metrics:
        meta = METRICS[metric]
        expr = meta["expression"]
        if metric == "transfert":
            expr = (
                "COALESCE((SELECT SUM(tj.valeur_m3) FROM public.transferts_journaliers tj "
                "WHERE tj.date_bilan = bj.date_bilan "
                "AND (tj.barrage_source_id = b.id OR tj.barrage_destination_id = b.id)), 0)"
            )
        select_parts.append(f"{expr} AS {metric}")

    where = ["bj.date_bilan BETWEEN :start_date AND :end_date"]

    if filters.barrage_code:
        where.append("b.code = :barrage_code")
        params["barrage_code"] = filters.barrage_code

    if filters.agence_code:
        where.append("a.code = :agence_code")
        params["agence_code"] = filters.agence_code

    sql = f"""
SELECT
    {", ".join(select_parts)}
FROM public.bilans_journaliers bj
JOIN public.barrages b ON b.id = bj.barrage_id
LEFT JOIN public.agences_territoriales a ON a.id = b.agence_id
WHERE {" AND ".join(where)}
ORDER BY bj.date_bilan ASC, COALESCE(b.ordre_situation, b.ordre_affichage, 9999), b.code
LIMIT :limit
"""

    return sql, params


def _execute_filters(db: Session, filters: AssistantFilters) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    dates = read_available_dates(db)

    if not filters.start_date:
        filters.start_date = dates.get("max")
    if not filters.end_date:
        filters.end_date = filters.start_date or dates.get("max")

    sql, params = _simple_filter_sql(filters)

    try:
        db.execute(text("SET LOCAL transaction_read_only = on"))
        result = db.execute(text(sql), params)
        rows = [row_to_dict(row) for row in result.mappings().all()]
        db.rollback()
        return sql, params, rows
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Recherche par filtres impossible : {exc}") from exc


def get_metadata(db: Session) -> dict[str, Any]:
    dates = read_available_dates(db)

    return {
        "status": "ok",
        "dates": {
            "min": dates.get("min"),
            "max": dates.get("max"),
        },
        "barrages": read_barrages(db),
        "agences": read_agences(db),
        "metrics": [
            {
                "code": item["metric_code"],
                "label": item["label"],
                "unit": item["unit"],
                "digits": METRICS[item["metric_code"]]["digits"],
                "description": item["description"],
                "synonyms": item["synonyms"],
            }
            for item in compact_metric_catalog()
        ],
        "llm": get_llm_status(),
        "examples": [
            "hauteur Bac de Dar Khrofa le 1er mois 6 année 2026",
            "Compare le volume de Dar Khrofa entre juin 2026 et juin 2025",
            "Quels barrages ont les restitutions les plus élevées en juin 2026 ?",
            "Quelle est la pluie moyenne par barrage en juin 2026 ?",
            "Quels barrages ont un taux inférieur à 50 % le 09/06/2026 ?",
            "Pourquoi le volume de Dar Khrofa a diminué en juin 2026 ?",
        ],
    }


def run_assistant_query(db: Session, payload: AssistantQueryRequest) -> dict[str, Any]:
    question = (payload.question or "").strip()

    if payload.filters and not question:
        sql, params, rows = _execute_filters(db, payload.filters)
        return {
            "status": "ok",
            "mode": "controlled_filters",
            "llm": {"attempted": False, "used": False, "error": None},
            "answer": deterministic_answer("filtres", rows),
            "explanation": "Résultat produit avec les filtres contrôlés.",
            "columns": build_columns(rows),
            "rows": rows,
            "chart": build_chart(rows),
            "sql_used": sql,
            "sql_params": {key: jsonable(value) for key, value in params.items()},
            "safety": {"read_only": True, "select_only": True},
        }

    if not question:
        raise HTTPException(status_code=400, detail="Écris une question ou utilise les filtres.")

    # Cas métier connus traités sans appel LLM : irrigation et transferts.
    # Cela évite les confusions sémantiques et permet de répondre même si le quota OpenRouter est atteint.
    business_shortcut = try_business_shortcut(db, question)
    if business_shortcut is not None:
        return business_shortcut

    if not payload.use_llm:
        raise HTTPException(
            status_code=400,
            detail="Le mode question libre nécessite le LLM. Utilise les filtres si tu veux éviter le LLM.",
        )

    if not llm_enabled():
        raise HTTPException(
            status_code=503,
            detail="LLM désactivé ou clé OpenRouter manquante dans backend/.env.",
        )

    try:
        llm_sql, llm_meta, catalog = generate_sql_with_llm(db, question)

        if llm_sql.get("needs_clarification"):
            return {
                "status": "needs_clarification",
                "mode": "llm_sql_secure",
                "llm": {"attempted": True, "used": True, "error": None, **llm_meta},
                "answer": llm_sql.get("clarification_message") or "La question est ambiguë. Peux-tu préciser ?",
                "explanation": llm_sql.get("explanation") or "Clarification demandée par le LLM.",
                "columns": [],
                "rows": [],
                "chart": None,
                "sql_used": None,
                "safety": {"read_only": True, "select_only": True},
            }

        sql_used, rows, repair_attempts = execute_with_repair(
            db,
            question=question,
            initial_sql=llm_sql["sql"],
            catalog=catalog,
            max_attempts=2,
        )

        answer = generate_final_answer(question, sql_used, rows, llm_meta)
        chart = build_chart(rows, preferred_type=llm_sql.get("chart_type"))

        return {
            "status": "ok",
            "mode": "llm_sql_secure",
            "llm": {
                "attempted": True,
                "used": True,
                "error": None,
                "model": llm_meta.get("model"),
                "endpoint": llm_meta.get("endpoint"),
            },
            "answer": answer,
            "explanation": llm_sql.get("explanation") or "SQL généré par LLM à partir du schéma et du catalogue PostgreSQL, puis sécurisé et exécuté en read-only.",
            "columns": build_columns(rows),
            "rows": rows,
            "chart": chart,
            "sql_used": sql_used,
            "llm_sql_initial": llm_sql.get("sql"),
            "repair_attempts": repair_attempts,
            "safety": {
                "read_only": True,
                "select_only": True,
                "llm_generated_sql": True,
                "validated_before_execution": True,
                "repair_loop": True,
                "catalog_used": {
                    "barrages_count": len(catalog.get("barrages", [])),
                    "agences_count": len(catalog.get("agences", [])),
                    "metrics_count": len(catalog.get("metrics", [])),
                },
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Assistant LLM SQL indisponible ou impossible à exécuter : {exc}",
        ) from exc
