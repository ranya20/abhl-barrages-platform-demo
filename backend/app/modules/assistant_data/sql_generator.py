from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.modules.assistant_data.catalog_reader import catalog_for_prompt, read_catalog
from app.modules.assistant_data.llm_client import chat_completion, extract_json


SYSTEM_RULES = """
Tu es un expert PostgreSQL et data engineer pour la plateforme ABHL Barrages.

Tu dois transformer une question en SQL PostgreSQL SELECT fiable.

RÈGLES ABSOLUES :
1) Réponds uniquement en JSON strict.
2) Format obligatoire :
{
  "needs_clarification": false,
  "clarification_message": null,
  "confidence": 0.0,
  "intent": "point|series|aggregate|compare|ranking|threshold|table|explain",
  "sql": "SELECT ...",
  "chart_type": "none|bar|line",
  "explanation": "..."
}
3) Si la question est ambiguë ou manque une variable/date/barrage indispensable, mets needs_clarification=true, sql=null et explique la question à poser.
4) SQL autorisé : SELECT ou WITH ... SELECT seulement.
5) Interdit : INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, COPY, GRANT, REVOKE, CALL, EXECUTE.
6) N'utilise jamais les tables users, roles, auth_sessions, auth_audit_log, data_import_*.
7) Utilise uniquement les tables/colonnes visibles dans le schéma fourni.
8) Ajoute toujours LIMIT 500 sauf pour les agrégations très petites.
9) Les valeurs doivent venir de PostgreSQL. N'invente aucune valeur.
10) Pour les noms de barrages, compare la question avec la liste de barrages fournie, puis utilise toujours b.code = 'CODE_EXACT'.
11) Ne fais jamais b.code ILIKE '%nom utilisateur%' si tu peux résoudre un code exact.
12) Pour Dar Khrofa mal écrit (dar khroufa, dar khorfa, dar khrofa), utilise le code réel DAR_KHROFA si ce code est dans la liste.
13) Pour 9 avril / barrage 9 avril, utilise le code réel 9_AVRIL si ce code est dans la liste.
14) Pour les dates françaises :
    - 01/06/2026, 1/6/2026, 1er juin 2026, 1er mois 6 année 2026 => DATE '2026-06-01'
    - juin 2026 => BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'
15) Les comparaisons doivent retourner les deux valeurs et si possible l'écart.
16) Pour les questions "pourquoi", utilise les colonnes disponibles : apports, restitutions, évaporation, variation, pluie. N'invente pas des causes externes.
"""


def build_prompt(question: str, catalog: dict[str, Any]) -> str:
    return (
        SYSTEM_RULES
        + "\n\nCATALOGUE RÉEL LU DE POSTGRESQL :\n"
        + catalog_for_prompt(catalog)
        + "\n\nQUESTION UTILISATEUR :\n"
        + question
    )


def generate_sql_with_llm(db: Session, question: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    catalog = read_catalog(db)
    prompt = build_prompt(question, catalog)

    content, meta = chat_completion(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
        force_json=False,
    )

    parsed = extract_json(content)

    if not parsed:
        content, meta = chat_completion(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            force_json=True,
        )
        parsed = extract_json(content)

    if not parsed:
        raise RuntimeError(f"Le LLM n'a pas retourné un JSON exploitable. Réponse brute : {content[:700]}")

    # Certains modèles renvoient "false" / "true" sous forme texte.
    needs_clarification = parsed.get("needs_clarification")
    if isinstance(needs_clarification, str):
        parsed["needs_clarification"] = needs_clarification.strip().lower() in {"1", "true", "yes", "oui"}
    else:
        parsed["needs_clarification"] = bool(needs_clarification)

    if parsed.get("needs_clarification"):
        return parsed, meta, catalog

    if not parsed.get("sql"):
        raise RuntimeError("Le JSON du LLM ne contient pas de champ sql.")

    return parsed, meta, catalog
