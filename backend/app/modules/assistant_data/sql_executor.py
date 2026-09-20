from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.assistant_data.sql_validator import validate_sql
from app.modules.assistant_data.utils import row_to_dict


STATEMENT_TIMEOUT_MS = 15000


def execute_readonly(db: Session, sql: str) -> tuple[str, list[dict[str, Any]]]:
    safe_sql = validate_sql(db, sql)

    try:
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
        db.execute(text("SET LOCAL transaction_read_only = on"))
        result = db.execute(text(safe_sql))
        rows = [row_to_dict(row) for row in result.mappings().all()]
        db.rollback()
        return safe_sql, rows
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc
