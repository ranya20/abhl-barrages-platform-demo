from __future__ import annotations

import json
from typing import Any

from app.modules.assistant_data.llm_client import chat_completion, llm_enabled
from app.modules.assistant_data.semantic_dictionary import METRICS


def build_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    labels = {
        "date_bilan": "Date",
        "date": "Date",
        "annee": "Année",
        "mois": "Mois",
        "barrage_code": "Code barrage",
        "code": "Code",
        "barrage": "Barrage",
        "barrage_nom": "Nom barrage",
        "nom": "Nom",
        "nom_court": "Barrage",
        "agence": "Agence",
        "agence_code": "Code agence",
        "agence_nom": "Agence",
        "periode": "Période",
        "ecart": "Écart",
        "difference": "Différence",
        "evolution": "Évolution",
        "pourcentage": "Pourcentage",
    }

    columns = []

    for key in rows[0].keys():
        metric = METRICS.get(key)
        columns.append(
            {
                "key": key,
                "label": metric["label"] if metric else labels.get(key, key.replace("_", " ").title()),
                "unit": metric["unit"] if metric else "",
                "digits": metric["digits"] if metric else 3,
            }
        )

    return columns


def build_chart(rows: list[dict[str, Any]], preferred_type: str | None = None) -> dict[str, Any] | None:
    if not rows:
        return None

    keys = list(rows[0].keys())
    numeric_keys = [
        key
        for key in keys
        if any(isinstance(row.get(key), (int, float)) for row in rows)
    ]

    numeric_keys = [key for key in numeric_keys if key not in {"annee"}]

    if not numeric_keys:
        return None

    date_key = next((key for key in keys if "date" in key.lower()), None)
    month_key = "mois" if "mois" in keys else None
    barrage_key = next((key for key in keys if key in {"barrage", "barrage_nom", "nom_court", "nom"}), None)
    x_key = date_key or month_key or barrage_key or keys[0]

    chart_type = preferred_type if preferred_type in {"line", "bar"} else None
    if not chart_type:
        chart_type = "line" if date_key or month_key else "bar"

    return {"type": chart_type, "x_key": x_key, "y_keys": numeric_keys[:4]}


def deterministic_answer(question: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Aucune donnée n’a été trouvée dans PostgreSQL pour cette question."

    if len(rows) == 1:
        row = rows[0]
        parts = []
        for key, value in row.items():
            if key in {"date_bilan", "date", "barrage", "barrage_nom", "barrage_code", "code", "nom", "nom_court"}:
                continue
            if isinstance(value, (int, float)):
                parts.append(f"{key.replace('_', ' ')} = {value:,.3f}".replace(",", " ").replace(".", ","))
            elif value is not None:
                parts.append(f"{key.replace('_', ' ')} = {value}")

        prefix = "Résultat"
        barrage = row.get("barrage") or row.get("barrage_nom") or row.get("nom_court") or row.get("nom")
        date = row.get("date_bilan") or row.get("date")
        if barrage:
            prefix = f"Pour {barrage}"
        if date:
            prefix += f", le {date}"

        return f"{prefix} : " + "; ".join(parts[:8]) + ". Source : PostgreSQL."

    return f"J’ai trouvé {len(rows)} ligne(s) dans PostgreSQL. Consulte le tableau pour les détails."


def generate_final_answer(question: str, sql: str, rows: list[dict[str, Any]], llm_meta: dict[str, Any] | None = None) -> str:
    if not rows:
        return deterministic_answer(question, rows)

    if not llm_enabled():
        return deterministic_answer(question, rows)

    payload = {
        "question": question,
        "sql_execute": sql,
        "nombre_lignes": len(rows),
        "colonnes": list(rows[0].keys()) if rows else [],
        "lignes": rows[:80],
    }

    system = (
        "Tu es l'assistant métier ABHL. Réponds en français clair. "
        "Tu dois utiliser uniquement les lignes JSON fournies et le SQL exécuté. "
        "N'invente jamais une valeur. Si une information n'est pas dans les lignes, dis qu'elle n'est pas disponible. "
        "Donne une réponse directe, puis indique que la source est PostgreSQL."
    )

    try:
        content, _meta = chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            force_json=False,
            max_tokens=700,
        )
        return content.strip()
    except Exception:
        return deterministic_answer(question, rows)
