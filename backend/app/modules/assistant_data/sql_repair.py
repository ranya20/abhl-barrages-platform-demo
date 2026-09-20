from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.assistant_data.catalog_reader import catalog_for_prompt
from app.modules.assistant_data.llm_client import chat_completion, extract_json
from app.modules.assistant_data.sql_executor import execute_readonly


REPAIR_RULES = """
Tu es un expert PostgreSQL. Corrige uniquement une requête SQL SELECT pour la plateforme ABHL Barrages.

Réponds uniquement en JSON strict :
{
  "sql": "SELECT ...",
  "explanation": "correction courte"
}

Règles :
- SELECT ou WITH SELECT uniquement.
- Pas de modification de données.
- Utilise seulement le schéma et les catalogues fournis.
- Pour les barrages, utilise les codes exacts fournis dans le catalogue.
- Si 0 ligne est probablement dû à un mauvais filtre b.code, remplace par le vrai code.
- Si une colonne n'existe pas, utilise la colonne correcte visible dans le schéma.
- Garde LIMIT 500.
"""


def repair_sql(
    *,
    question: str,
    previous_sql: str,
    error_or_reason: str,
    catalog: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    prompt = (
        REPAIR_RULES
        + "\n\nCATALOGUE RÉEL LU DE POSTGRESQL :\n"
        + catalog_for_prompt(catalog)
        + "\n\nQUESTION UTILISATEUR :\n"
        + question
        + "\n\nSQL À CORRIGER :\n"
        + previous_sql
        + "\n\nERREUR OU RAISON DE CORRECTION :\n"
        + error_or_reason
    )

    content, meta = chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Corrige le SQL en JSON strict."},
        ],
        force_json=False,
    )

    parsed = extract_json(content)

    if not parsed:
        content, meta = chat_completion(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Corrige le SQL en JSON strict."},
            ],
            force_json=True,
        )
        parsed = extract_json(content)

    if not parsed or not parsed.get("sql"):
        raise RuntimeError(f"Le LLM n'a pas corrigé le SQL. Réponse brute : {content[:700]}")

    return parsed["sql"], parsed.get("explanation") or "SQL corrigé par le LLM.", meta


def execute_with_repair(
    db: Session,
    *,
    question: str,
    initial_sql: str,
    catalog: dict[str, Any],
    max_attempts: int = 2,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    current_sql = initial_sql

    for attempt_index in range(max_attempts + 1):
        try:
            safe_sql, rows = execute_readonly(db, current_sql)
            attempts.append({"attempt": attempt_index + 1, "status": "executed", "rows": len(rows), "sql": safe_sql})

            if rows:
                return safe_sql, rows, attempts

            # 0 ligne peut être normal, mais dans ce projet c'est souvent un mauvais mapping barrage/date.
            if attempt_index < max_attempts:
                reason = (
                    "La requête s'exécute mais retourne 0 ligne. "
                    "Vérifie surtout le filtre barrage/date avec la liste réelle des codes barrages et la période disponible."
                )
                repaired_sql, explanation, meta = repair_sql(
                    question=question,
                    previous_sql=safe_sql,
                    error_or_reason=reason,
                    catalog=catalog,
                )
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "status": "repair_after_zero_rows",
                        "reason": reason,
                        "explanation": explanation,
                        "meta": meta,
                    }
                )
                current_sql = repaired_sql
                continue

            return safe_sql, rows, attempts

        except Exception as exc:
            attempts.append({"attempt": attempt_index + 1, "status": "error", "error": str(exc), "sql": current_sql})

            if attempt_index >= max_attempts:
                raise

            repaired_sql, explanation, meta = repair_sql(
                question=question,
                previous_sql=current_sql,
                error_or_reason=str(exc),
                catalog=catalog,
            )
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "status": "repair_after_error",
                    "explanation": explanation,
                    "meta": meta,
                }
            )
            current_sql = repaired_sql

    raise RuntimeError("La boucle de réparation SQL a échoué.")
