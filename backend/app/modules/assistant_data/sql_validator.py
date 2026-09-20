from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.assistant_data.catalog_reader import SENSITIVE_TABLES, read_schema


BLOCKED_WORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "copy",
    "execute",
    "call",
    "do",
    "merge",
    "vacuum",
    "analyze",
    "refresh",
    "reindex",
    "lock",
}

DEFAULT_LIMIT = 500


def clean_sql(sql: str) -> str:
    sql = str(sql or "").strip()
    sql = re.sub(r"^```(?:sql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = re.sub(r"```$", "", sql).strip()
    sql = re.sub(r";+\s*$", "", sql)
    return sql.strip()


def allowed_tables(db: Session) -> set[str]:
    return set(read_schema(db).keys()) - SENSITIVE_TABLES


def _cte_names(lowered_sql: str) -> set[str]:
    if not re.match(r"^\s*with\b", lowered_sql):
        return set()

    return set(re.findall(r"(?:with|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", lowered_sql))


def validate_sql(db: Session, sql: str, *, add_limit: bool = True) -> str:
    sql = clean_sql(sql)
    lowered = sql.lower()

    if not sql:
        raise HTTPException(status_code=400, detail="Le LLM n'a pas généré de SQL.")

    if not re.match(r"^\s*(select|with)\b", lowered):
        raise HTTPException(status_code=400, detail="Requête refusée : seulement SELECT ou WITH ... SELECT est autorisé.")

    if ";" in lowered:
        raise HTTPException(status_code=400, detail="Requête refusée : une seule instruction SQL est autorisée.")

    if "--" in lowered or "/*" in lowered or "*/" in lowered:
        raise HTTPException(status_code=400, detail="Requête refusée : commentaires SQL interdits.")

    for word in BLOCKED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            raise HTTPException(status_code=400, detail=f"Requête refusée : mot-clé interdit '{word}'.")

    ctes = _cte_names(lowered)
    allowed = allowed_tables(db)

    table_refs = re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_\.\"']+)", lowered)

    for raw in table_refs:
        table = raw.replace('"', "").replace("'", "").strip()

        if not table or table.startswith("("):
            continue

        if table.startswith("information_schema.") or table.startswith("pg_catalog."):
            raise HTTPException(status_code=400, detail="Requête refusée : catalogues système interdits.")

        unqualified = table.split(".")[-1]
        schema_name = table.split(".")[0] if "." in table else "public"

        if unqualified in ctes:
            continue

        if schema_name != "public":
            raise HTTPException(status_code=400, detail=f"Requête refusée : schéma non autorisé '{schema_name}'.")

        if unqualified in SENSITIVE_TABLES:
            raise HTTPException(status_code=400, detail=f"Requête refusée : table sensible interdite '{unqualified}'.")

        if unqualified not in allowed:
            raise HTTPException(status_code=400, detail=f"Requête refusée : table inexistante ou non autorisée '{unqualified}'.")

    if add_limit and not re.search(r"\blimit\s+(\d+|:\w+|%\(\w+\)s|\$\d+)\b", lowered):
        sql = f"{sql}\nLIMIT {DEFAULT_LIMIT}"

    return sql


def explain_sql_validation(db: Session, sql: str) -> dict[str, str]:
    safe_sql = validate_sql(db, sql)
    return {"status": "ok", "sql": safe_sql}
