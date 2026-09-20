from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.calculs.repository import read_table_columns
from app.modules.imports.constants import VOLATILE_SNAPSHOT_KEYS


def json_default(value: Any):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Type non sérialisable : {type(value)!r}")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default)


def snapshot_aggregate(db: Session, barrage_id: int, date_bilan: date) -> dict:
    row = db.execute(
        text(
            """
            SELECT to_jsonb(bj) AS bilan
            FROM public.bilans_journaliers bj
            WHERE bj.barrage_id = :barrage_id
              AND bj.date_bilan = :date_bilan
              AND bj.heure_reference = '07:00'
            LIMIT 1;
            """
        ),
        {"barrage_id": barrage_id, "date_bilan": date_bilan},
    ).mappings().first()

    if not row:
        return {
            "exists": False,
            "barrage_id": barrage_id,
            "date_bilan": date_bilan.isoformat(),
            "bilan": None,
            "restitutions": [],
            "variables": [],
        }

    bilan = dict(row["bilan"])
    bilan_id = int(bilan["id"])

    restitutions = [
        dict(item["payload"])
        for item in db.execute(
            text(
                """
                SELECT to_jsonb(rj) AS payload
                FROM public.restitutions_journalieres rj
                WHERE rj.bilan_journalier_id = :bilan_id
                ORDER BY rj.type_restitution_id, rj.id;
                """
            ),
            {"bilan_id": bilan_id},
        ).mappings().all()
    ]

    variables = []
    exists_variables = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name='bilan_variables_journalieres'
            );
            """
        )
    ).scalar()
    if exists_variables:
        variables = [
            dict(item["payload"])
            for item in db.execute(
                text(
                    """
                    SELECT to_jsonb(v) AS payload
                    FROM public.bilan_variables_journalieres v
                    WHERE v.bilan_journalier_id = :bilan_id
                    ORDER BY v.code_variable, v.id;
                    """
                ),
                {"bilan_id": bilan_id},
            ).mappings().all()
        ]

    return {
        "exists": True,
        "barrage_id": barrage_id,
        "date_bilan": date_bilan.isoformat(),
        "bilan": bilan,
        "restitutions": restitutions,
        "variables": variables,
    }


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_SNAPSHOT_KEYS and key != "id"
        }
    if isinstance(value, list):
        canonical_items = [_canonical(item) for item in value]
        return sorted(canonical_items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


def snapshots_equal(left: dict, right: dict) -> bool:
    return _canonical(left) == _canonical(right)


def changed_fields(before: dict, after: dict) -> list[str]:
    if not before.get("exists") and after.get("exists"):
        return ["__CREATED__"]
    if before.get("exists") and not after.get("exists"):
        return ["__DELETED__"]

    fields: list[str] = []
    before_bilan = _canonical(before.get("bilan") or {})
    after_bilan = _canonical(after.get("bilan") or {})
    for key in sorted(set(before_bilan) | set(after_bilan)):
        if before_bilan.get(key) != after_bilan.get(key):
            fields.append(key)

    if _canonical(before.get("restitutions") or []) != _canonical(after.get("restitutions") or []):
        fields.append("restitutions")
    if _canonical(before.get("variables") or []) != _canonical(after.get("variables") or []):
        fields.append("variables")
    return fields


def _coerce_for_column(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in {"date_bilan"} and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if column == "heure_reference" and isinstance(value, str):
        return value[:8]
    return value


def restore_aggregate(db: Session, snapshot: dict) -> None:
    barrage_id = int(snapshot["barrage_id"])
    date_bilan = date.fromisoformat(str(snapshot["date_bilan"])[:10])

    current = db.execute(
        text(
            """
            SELECT id
            FROM public.bilans_journaliers
            WHERE barrage_id=:barrage_id
              AND date_bilan=:date_bilan
              AND heure_reference='07:00'
            LIMIT 1;
            """
        ),
        {"barrage_id": barrage_id, "date_bilan": date_bilan},
    ).mappings().first()

    if not snapshot.get("exists"):
        if current:
            db.execute(
                text("DELETE FROM public.bilans_journaliers WHERE id=:id;"),
                {"id": int(current["id"])},
            )
        return

    original = dict(snapshot.get("bilan") or {})
    original_id = int(original["id"])
    columns = set(read_table_columns(db, "bilans_journaliers"))
    data = {
        key: _coerce_for_column(key, value)
        for key, value in original.items()
        if key in columns
    }

    if current and int(current["id"]) != original_id:
        db.execute(
            text("DELETE FROM public.bilans_journaliers WHERE id=:id;"),
            {"id": int(current["id"])},
        )
        current = None

    if current:
        update_data = {key: value for key, value in data.items() if key != "id"}
        set_sql = ", ".join(f"{key}=:{key}" for key in update_data)
        update_data["target_id"] = original_id
        db.execute(
            text(f"UPDATE public.bilans_journaliers SET {set_sql} WHERE id=:target_id;"),
            update_data,
        )
    else:
        col_sql = ", ".join(data)
        val_sql = ", ".join(f":{key}" for key in data)
        db.execute(
            text(f"INSERT INTO public.bilans_journaliers ({col_sql}) VALUES ({val_sql});"),
            data,
        )

    db.execute(
        text("DELETE FROM public.restitutions_journalieres WHERE bilan_journalier_id=:id;"),
        {"id": original_id},
    )
    restitution_columns = set(read_table_columns(db, "restitutions_journalieres"))
    for item in snapshot.get("restitutions") or []:
        child = {
            key: _coerce_for_column(key, value)
            for key, value in dict(item).items()
            if key in restitution_columns
        }
        child["bilan_journalier_id"] = original_id
        col_sql = ", ".join(child)
        val_sql = ", ".join(f":{key}" for key in child)
        db.execute(
            text(f"INSERT INTO public.restitutions_journalieres ({col_sql}) VALUES ({val_sql});"),
            child,
        )

    table_exists = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name='bilan_variables_journalieres'
            );
            """
        )
    ).scalar()
    if table_exists:
        db.execute(
            text("DELETE FROM public.bilan_variables_journalieres WHERE bilan_journalier_id=:id;"),
            {"id": original_id},
        )
        variable_columns = set(read_table_columns(db, "bilan_variables_journalieres"))
        for item in snapshot.get("variables") or []:
            child = {
                key: _coerce_for_column(key, value)
                for key, value in dict(item).items()
                if key in variable_columns
            }
            child["bilan_journalier_id"] = original_id
            col_sql = ", ".join(child)
            val_sql = ", ".join(f":{key}" for key in child)
            db.execute(
                text(f"INSERT INTO public.bilan_variables_journalieres ({col_sql}) VALUES ({val_sql});"),
                child,
            )

    for table_name in ("restitutions_journalieres", "bilan_variables_journalieres"):
        if table_name == "bilan_variables_journalieres" and not table_exists:
            continue
        sequence_name = db.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id');"),
            {"table_name": f"public.{table_name}"},
        ).scalar()
        if sequence_name:
            db.execute(
                text(
                    f"SELECT setval(:sequence_name, "
                    f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM public.{table_name}), 1), TRUE);"
                ),
                {"sequence_name": sequence_name},
            )

    db.execute(
        text(
            """
            SELECT setval(
                pg_get_serial_sequence('public.bilans_journaliers', 'id'),
                GREATEST((SELECT COALESCE(MAX(id), 1) FROM public.bilans_journaliers), 1),
                TRUE
            );
            """
        )
    )
