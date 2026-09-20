from __future__ import annotations

import hashlib
import json
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.auth.dependencies import AuthPrincipal
from app.modules.bilan.schemas import BilanComputeRequest, BilanDailyInput, BilanRestitutionInput
from app.modules.bilan.service import compute_bilan, safe_rate, zero
from app.modules.calculs.repository import (
    ensure_journee_situation,
    fetch_active_barrages,
    lookup_bareme_exact,
    upsert_bilan,
    upsert_bilan_variable,
    upsert_restitution,
)
from app.modules.calculs.schemas import BarrageCalculationInput, CalculsComputeRequest, RestitutionInput
from app.modules.calculs.service import compute_calculs
from app.modules.imports.constants import (
    ALLOWED_MODES,
    ALLOWED_MODULES,
    MAX_FILE_SIZE_BYTES,
    MODE_ADD_ONLY,
    MODE_FILL_EMPTY,
    MODE_REPLACE_SELECTED,
    MODULE_ANNONCE,
    MODULE_BILAN,
    ROW_APPLIED,
    ROW_COMPLEMENT,
    ROW_CONFLICT,
    ROW_IDENTICAL,
    ROW_INVALID,
    ROW_NEW,
    ROW_SKIPPED,
    STATUS_APPLIED,
    STATUS_FAILED,
    STATUS_PENDING_VALIDATION,
    STATUS_PREVIEW,
    STATUS_REJECTED,
    STATUS_ROLLED_BACK,
    SUPPORTED_EXTENSIONS,
)
from app.modules.imports.parser import as_date, normalize_code, normalize_text, parse_import_file
from app.modules.imports.snapshots import (
    changed_fields,
    json_dumps,
    restore_aggregate,
    snapshot_aggregate,
    snapshots_equal,
)


INPUT_FIELDS = ("cote_interval_ngm", "cote_7h_ngm", "cote_suivante_ngm", "hauteur_bac_mm", "pluie_mm", "observation")


def _uid() -> str:
    return f"IMP-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(4).upper()}"


def _json(value: Any) -> str:
    return json_dumps(value)


def _event(
    db: Session,
    *,
    batch_id: int,
    event_type: str,
    user_id: int | None,
    details: dict | None = None,
    reason: str | None = None,
    status: str = "SUCCESS",
):
    db.execute(
        text(
            """
            INSERT INTO public.data_import_events(
                batch_id, event_type, event_status, user_id, details, reason
            ) VALUES (
                :batch_id, :event_type, :event_status, :user_id,
                CAST(:details AS jsonb), :reason
            );
            """
        ),
        {
            "batch_id": batch_id,
            "event_type": event_type,
            "event_status": status,
            "user_id": user_id,
            "details": _json(details or {}),
            "reason": reason,
        },
    )


def _batch_row(db: Session, import_uid: str, *, lock: bool = False) -> dict:
    suffix = " FOR UPDATE OF b" if lock else ""
    row = db.execute(
        text(
            f"""
            SELECT
                b.*,
                creator.username AS created_by_username,
                validator.username AS validated_by_username,
                rollback_user.username AS rolled_back_by_username
            FROM public.data_import_batches b
            LEFT JOIN public.users creator ON creator.id=b.created_by
            LEFT JOIN public.users validator ON validator.id=b.validated_by
            LEFT JOIN public.users rollback_user ON rollback_user.id=b.rolled_back_by
            WHERE b.import_uid=:uid
            LIMIT 1{suffix};
            """
        ),
        {"uid": import_uid},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Import introuvable.")
    return dict(row)


def _serialize_batch(row: dict) -> dict:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    return result


def _fetch_rows(db: Session, batch_id: int) -> list[dict]:
    return [
        dict(row)
        for row in db.execute(
            text(
                """
                SELECT *
                FROM public.data_import_rows
                WHERE batch_id=:batch_id
                ORDER BY row_number, id;
                """
            ),
            {"batch_id": batch_id},
        ).mappings().all()
    ]


def _barrages(db: Session) -> dict[str, dict]:
    rows = db.execute(
        text(
            """
            SELECT id, code, nom, capacite_normale_mm3, actif,
                   inclure_annonce, inclure_bilan
            FROM public.barrages
            WHERE COALESCE(actif, TRUE)=TRUE;
            """
        )
    ).mappings().all()
    return {str(row["code"]).upper(): dict(row) for row in rows}


def _restitution_types(db: Session) -> set[str]:
    return {
        str(value).upper()
        for value in db.execute(
            text("SELECT code FROM public.types_restitution WHERE COALESCE(actif, TRUE)=TRUE;")
        ).scalars().all()
    }


def _parser_context(db: Session, context: dict) -> dict:
    """Enrichit le contexte du parseur avec les référentiels dynamiques PostgreSQL."""
    result = dict(context or {})
    barrage_rows = db.execute(
        text(
            """
            SELECT code, nom, nom_court
            FROM public.barrages
            WHERE COALESCE(actif, TRUE)=TRUE;
            """
        )
    ).mappings().all()
    barrage_aliases: dict[str, str] = {}
    barrage_codes: list[str] = []
    for row in barrage_rows:
        code = normalize_code(row["code"])
        barrage_codes.append(code)
        for value in (row.get("code"), row.get("nom"), row.get("nom_court")):
            if value:
                barrage_aliases[normalize_text(value)] = code

    restitution_rows = db.execute(
        text(
            """
            SELECT code, libelle
            FROM public.types_restitution
            WHERE COALESCE(actif, TRUE)=TRUE;
            """
        )
    ).mappings().all()
    restitution_aliases: dict[str, str] = {}
    restitution_codes: list[str] = []
    for row in restitution_rows:
        code = normalize_code(row["code"])
        restitution_codes.append(code)
        for value in (row.get("code"), row.get("libelle")):
            if value:
                restitution_aliases[normalize_text(value)] = code

    result.update(
        {
            "barrage_aliases": barrage_aliases,
            "barrage_codes": sorted(set(barrage_codes)),
            "restitution_aliases": restitution_aliases,
            "restitution_codes": sorted(set(restitution_codes)),
        }
    )
    return result


def _snapshot_inputs(snapshot: dict) -> dict:
    if not snapshot.get("exists"):
        return {"bilan": {}, "restitutions": {}}
    bilan = dict(snapshot.get("bilan") or {})
    restitutions: dict[str, float] = {}
    for item in snapshot.get("restitutions") or []:
        code = item.get("type_code")
        if not code and item.get("type_restitution_id") is not None:
            # Le code est enrichi sÃ©parÃ©ment lorsque nÃ©cessaire.
            continue
        if code:
            restitutions[str(code).upper()] = float(item.get("valeur_m3") or 0)
    return {"bilan": bilan, "restitutions": restitutions}


def _aggregate_with_codes(db: Session, barrage_id: int, day: date) -> dict:
    snapshot = snapshot_aggregate(db, barrage_id, day)
    if snapshot.get("exists"):
        ids = [item.get("type_restitution_id") for item in snapshot.get("restitutions") or []]
        if ids:
            rows = db.execute(
                text("SELECT id, code FROM public.types_restitution WHERE id=ANY(:ids);"),
                {"ids": ids},
            ).mappings().all()
            by_id = {int(row["id"]): str(row["code"]).upper() for row in rows}
            for item in snapshot.get("restitutions") or []:
                item["type_code"] = by_id.get(int(item["type_restitution_id"]))
    return snapshot


def _same(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return abs(float(left) - float(right)) <= 1e-9
        except (TypeError, ValueError):
            return False
    return str(left or "").strip() == str(right or "").strip()


def _compare_field(field: str, old: Any, new: Any) -> dict | None:
    if new is None or new == "":
        return None
    if old is None or old == "":
        kind = "NEW"
    elif _same(old, new):
        kind = "IDENTICAL"
    else:
        kind = "CONFLICT"
    return {"field": field, "old": old, "new": new, "kind": kind}


ANNONCE_REQUIRED_FOR_CALCULATION = {
    "cote_interval_ngm": "cote du jour précédent",
    "cote_7h_ngm": "cote du jour",
    "hauteur_bac_mm": "hauteur du bac",
    "pluie_mm": "pluie",
}


def _annonce_missing_fields(data: dict[str, Any]) -> list[str]:
    """Champs absents qui empêchent un calcul complet, sans empêcher le stockage."""
    return [
        label
        for field, label in ANNONCE_REQUIRED_FOR_CALCULATION.items()
        if data.get(field) is None or data.get(field) == ""
    ]


def _append_import_row_warnings(db: Session, row_id: int, messages: list[str]) -> None:
    clean = [str(message).strip() for message in messages if str(message).strip()]
    if not clean:
        return
    db.execute(
        text(
            """
            UPDATE public.data_import_rows
            SET warnings = COALESCE(warnings, '[]'::jsonb) || CAST(:warnings AS jsonb)
            WHERE id=:row_id;
            """
        ),
        {"warnings": _json(clean), "row_id": row_id},
    )


def _existing_for_row(db: Session, module_code: str, barrage_id: int, row_data: dict, context: dict) -> dict:
    if module_code == MODULE_ANNONCE:
        date_situation = as_date(row_data.get("date_situation")) or as_date(context.get("date_situation"))
        if not date_situation:
            return {"date_situation": None, "interval": {}, "current": {}}
        date_interval = date_situation - timedelta(days=1)
        interval = _aggregate_with_codes(db, barrage_id, date_interval)
        current = _aggregate_with_codes(db, barrage_id, date_situation)
        interval_inputs = _snapshot_inputs(interval)
        current_inputs = _snapshot_inputs(current)
        return {
            "date_situation": date_situation,
            "date_interval": date_interval,
            "interval_snapshot": interval,
            "current_snapshot": current,
            "cote_interval_ngm": interval_inputs["bilan"].get("cote_7h_ngm"),
            "cote_7h_ngm": current_inputs["bilan"].get("cote_7h_ngm"),
            "hauteur_bac_mm": interval_inputs["bilan"].get("hauteur_bac_mm"),
            "pluie_mm": interval_inputs["bilan"].get("pluie_mm"),
            "observation": interval_inputs["bilan"].get("observation"),
            "restitutions": interval_inputs["restitutions"],
            "has_existing": bool(interval.get("exists") or current.get("exists")),
        }

    day = as_date(row_data.get("date_bilan"))
    if not day:
        return {"date_bilan": None, "current": {}, "next": {}}
    current = _aggregate_with_codes(db, barrage_id, day)
    next_snapshot = _aggregate_with_codes(db, barrage_id, day + timedelta(days=1))
    current_inputs = _snapshot_inputs(current)
    next_inputs = _snapshot_inputs(next_snapshot)
    return {
        "date_bilan": day,
        "current_snapshot": current,
        "next_snapshot": next_snapshot,
        "cote_7h_ngm": current_inputs["bilan"].get("cote_7h_ngm"),
        "cote_suivante_ngm": next_inputs["bilan"].get("cote_7h_ngm"),
        "hauteur_bac_mm": current_inputs["bilan"].get("hauteur_bac_mm"),
        "pluie_mm": current_inputs["bilan"].get("pluie_mm"),
        "observation": current_inputs["bilan"].get("observation"),
        "restitutions": current_inputs["restitutions"],
        "has_existing": bool(current.get("exists")),
    }


def _validate_and_compare(
    db: Session,
    *,
    module_code: str,
    parsed: dict,
    context: dict,
    barrages: dict[str, dict],
    valid_rest_codes: set[str],
) -> dict:
    code = normalize_code(parsed.get("barrage_code"))
    data = dict(parsed.get("data") or {})
    data["restitutions"] = {
        normalize_code(key): value
        for key, value in dict(data.get("restitutions") or {}).items()
    }
    errors = list(parsed.get("errors") or [])
    warnings = list(parsed.get("warnings") or [])

    barrage = barrages.get(code)
    if not code or not barrage:
        errors.append("Barrage inconnu ou inactif.")
    elif module_code == MODULE_ANNONCE and barrage.get("inclure_annonce") is False:
        errors.append("Ce barrage n'est pas inclus dans le module Annonce.")
    elif module_code == MODULE_BILAN and barrage.get("inclure_bilan") is False:
        errors.append("Ce barrage n'est pas inclus dans le module BILAN.")

    if module_code == MODULE_ANNONCE:
        date_situation = as_date(data.get("date_situation")) or as_date(context.get("date_situation"))
        data["date_situation"] = date_situation
        parsed["date_bilan"] = date_situation - timedelta(days=1) if date_situation else None
        if not date_situation:
            errors.append("Date de situation absente.")
    else:
        day = as_date(parsed.get("date_bilan"))
        parsed["date_bilan"] = day
        if not day:
            errors.append("Date BILAN absente ou invalide.")
        year = int(context.get("year") or 0)
        month = int(context.get("month") or 0)
        if day and year and month and (day.year != year or day.month != month):
            errors.append("La date est hors de la pÃ©riode sÃ©lectionnÃ©e.")

    if module_code == MODULE_ANNONCE and data.get("date_situation"):
        incomplete_fields = _annonce_missing_fields(data)
        data["incomplete_fields"] = incomplete_fields
        if incomplete_fields:
            warnings.append(
                "Données incomplètes : "
                + ", ".join(incomplete_fields)
                + ". La ligne sera stockée avec les valeurs disponibles; seuls les calculs impossibles resteront vides."
            )

    for field in ("pluie_mm",):
        value = data.get(field)
        if value is not None and float(value) < 0:
            errors.append(f"{field} ne peut pas Ãªtre nÃ©gatif.")
    if data.get("hauteur_bac_mm") is not None and float(data["hauteur_bac_mm"]) < 0:
        warnings.append("La hauteur de bac est nÃ©gative; elle sera conservÃ©e avec avertissement.")

    unknown_rest = sorted(code for code in data["restitutions"] if code not in valid_rest_codes)
    if unknown_rest:
        errors.append("Types de restitution inconnus : " + ", ".join(unknown_rest))
    for rest_code, value in data["restitutions"].items():
        if value is not None and float(value) < 0:
            errors.append(f"La restitution {rest_code} ne peut pas Ãªtre nÃ©gative.")

    if not any(data.get(field) is not None for field in INPUT_FIELDS[:-1]) and not data["restitutions"]:
        errors.append("La ligne ne contient aucune donnÃ©e importable.")

    comparison: list[dict] = []
    existing: dict = {}
    if barrage:
        existing = _existing_for_row(db, module_code, int(barrage["id"]), {**data, "date_bilan": parsed.get("date_bilan")}, context)
        for field in INPUT_FIELDS:
            item = _compare_field(field, existing.get(field), data.get(field))
            if item:
                comparison.append(item)
        old_rest = existing.get("restitutions") or {}
        for rest_code, new_value in sorted(data["restitutions"].items()):
            item = _compare_field(f"restitution:{rest_code}", old_rest.get(rest_code), new_value)
            if item:
                comparison.append(item)

        imported_interval_cote = data.get("cote_interval_ngm")
        if imported_interval_cote is not None:
            if lookup_bareme_exact(db, int(barrage["id"]), float(imported_interval_cote)) is None:
                errors.append(f"La cote initiale {imported_interval_cote} est absente du barème actif de {code}.")

        imported_cote = data.get("cote_7h_ngm")
        if imported_cote is not None:
            if lookup_bareme_exact(db, int(barrage["id"]), float(imported_cote)) is None:
                errors.append(f"La cote {imported_cote} est absente du barème actif de {code}.")

    kinds = {item["kind"] for item in comparison}
    if errors:
        row_status = ROW_INVALID
    elif "CONFLICT" in kinds:
        row_status = ROW_CONFLICT
    elif kinds == {"IDENTICAL"} or not comparison:
        row_status = ROW_IDENTICAL
    elif existing.get("has_existing"):
        row_status = ROW_COMPLEMENT
    else:
        row_status = ROW_NEW

    return {
        **parsed,
        "barrage_code": code,
        "data": data,
        "errors": errors,
        "warnings": warnings,
        "existing": _json_safe_existing(existing),
        "comparison": comparison,
        "row_status": row_status,
    }


def _json_safe_existing(existing: dict) -> dict:
    result = {}
    for key, value in existing.items():
        if key.endswith("_snapshot"):
            continue
        if isinstance(value, date):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def create_preview(
    db: Session,
    *,
    principal: AuthPrincipal,
    module_code: str,
    filename: str,
    content: bytes,
    context: dict,
) -> dict:
    module_code = str(module_code or "").upper().strip()
    if module_code not in ALLOWED_MODULES:
        raise HTTPException(status_code=400, detail="Module d'import invalide.")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Format non acceptÃ©. Utilisez .xlsx, .xlsm ou .csv.",
        )
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Le fichier dÃ©passe la limite de 20 Mo.")
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier est vide.")

    parser_context = _parser_context(db, context)

    try:
        parsed_rows, source_format = parse_import_file(
            module_code=module_code,
            filename=filename,
            content=content,
            context=parser_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Lecture du fichier impossible : {exc}") from exc

    if not parsed_rows:
        raise HTTPException(
            status_code=400,
            detail="Aucune ligne reconnue. VÃ©rifiez le type du fichier et les colonnes.",
        )

    barrages = _barrages(db)
    valid_rest_codes = _restitution_types(db)
    analyzed = [
        _validate_and_compare(
            db,
            module_code=module_code,
            parsed=item,
            context=parser_context,
            barrages=barrages,
            valid_rest_codes=valid_rest_codes,
        )
        for item in parsed_rows
    ]

    # Un même barrage à une même date ne doit apparaître qu'une seule fois.
    seen_keys: dict[tuple[str, date | None], dict] = {}
    for item in analyzed:
        key_date = (
            as_date((item.get("data") or {}).get("date_situation"))
            if module_code == MODULE_ANNONCE
            else as_date(item.get("date_bilan"))
        )
        key = (normalize_code(item.get("barrage_code")), key_date)
        previous = seen_keys.get(key)
        if previous and key[0] and key_date:
            message = f"Doublon dans le fichier pour {key[0]} à la date {key_date.isoformat()}."
            item["errors"].append(message)
            item["row_status"] = ROW_INVALID
            if message not in previous["errors"]:
                previous["errors"].append(message)
                previous["row_status"] = ROW_INVALID
        else:
            seen_keys[key] = item

    counts = defaultdict(int)
    for item in analyzed:
        counts[item["row_status"]] += 1

    detected_dates = sorted(
        {
            value
            for item in analyzed
            for value in [as_date(item.get("date_bilan"))]
            if value is not None
        }
    )
    detected_barrages = sorted(
        {normalize_code(item.get("barrage_code")) for item in analyzed if item.get("barrage_code")}
    )
    detected_sheets = sorted({str(item.get("sheet_name")) for item in analyzed if item.get("sheet_name")})

    summary = {
        "total": len(analyzed),
        "new": counts[ROW_NEW],
        "complement": counts[ROW_COMPLEMENT],
        "identical": counts[ROW_IDENTICAL],
        "conflict": counts[ROW_CONFLICT],
        "invalid": counts[ROW_INVALID],
        "incomplete": sum(
            1
            for item in analyzed
            if (item.get("data") or {}).get("incomplete_fields")
        ),
        "warnings": sum(len(item["warnings"]) for item in analyzed),
        "date_min": detected_dates[0].isoformat() if detected_dates else None,
        "date_max": detected_dates[-1].isoformat() if detected_dates else None,
        "dates_count": len(detected_dates),
        "barrages_count": len(detected_barrages),
        "sheets_count": len(detected_sheets),
        "barrages": detected_barrages,
        "sheets": detected_sheets,
    }

    import_uid = _uid()
    sha256 = hashlib.sha256(content).hexdigest()
    batch = db.execute(
        text(
            """
            INSERT INTO public.data_import_batches(
                import_uid, module_code, status, original_filename,
                file_sha256, file_size_bytes, source_format,
                import_context, summary, created_by
            ) VALUES (
                :uid, :module_code, :status, :filename,
                :sha256, :size, :source_format,
                CAST(:context AS jsonb), CAST(:summary AS jsonb), :created_by
            ) RETURNING id;
            """
        ),
        {
            "uid": import_uid,
            "module_code": module_code,
            "status": STATUS_PREVIEW,
            "filename": Path(filename).name,
            "sha256": sha256,
            "size": len(content),
            "source_format": source_format,
            "context": _json(context),
            "summary": _json(summary),
            "created_by": principal.id,
        },
    ).mappings().first()
    batch_id = int(batch["id"])

    for item in analyzed:
        data_for_json = dict(item["data"])
        for key in ("date_situation",):
            if isinstance(data_for_json.get(key), date):
                data_for_json[key] = data_for_json[key].isoformat()
        row = db.execute(
            text(
                """
                INSERT INTO public.data_import_rows(
                    batch_id, row_number, sheet_name, barrage_code, date_bilan,
                    row_status, raw_data, normalized_data, existing_data,
                    comparison, errors, warnings
                ) VALUES (
                    :batch_id, :row_number, :sheet_name, :barrage_code, :date_bilan,
                    :row_status, CAST(:raw AS jsonb), CAST(:normalized AS jsonb),
                    CAST(:existing AS jsonb), CAST(:comparison AS jsonb),
                    CAST(:errors AS jsonb), CAST(:warnings AS jsonb)
                ) RETURNING id;
                """
            ),
            {
                "batch_id": batch_id,
                "row_number": int(item["row_number"]),
                "sheet_name": item.get("sheet_name"),
                "barrage_code": item.get("barrage_code"),
                "date_bilan": item.get("date_bilan"),
                "row_status": item["row_status"],
                "raw": _json(item.get("raw") or {}),
                "normalized": _json(data_for_json),
                "existing": _json(item.get("existing") or {}),
                "comparison": _json(item.get("comparison") or []),
                "errors": _json(item.get("errors") or []),
                "warnings": _json(item.get("warnings") or []),
            },
        ).mappings().first()
        item["id"] = int(row["id"])

    _event(
        db,
        batch_id=batch_id,
        event_type="PREVIEW_CREATED",
        user_id=principal.id,
        details={"summary": summary, "source_format": source_format},
    )
    db.commit()

    return {
        "status": "ok",
        "batch": {
            "import_uid": import_uid,
            "module_code": module_code,
            "status": STATUS_PREVIEW,
            "original_filename": Path(filename).name,
            "source_format": source_format,
            "context": context,
            "summary": summary,
        },
        "rows": [_public_preview_row(item) for item in analyzed],
    }


def _public_preview_row(item: dict) -> dict:
    data = dict(item.get("data") or {})
    if isinstance(data.get("date_situation"), date):
        data["date_situation"] = data["date_situation"].isoformat()
    return {
        "id": item.get("id"),
        "row_number": item.get("row_number"),
        "sheet_name": item.get("sheet_name"),
        "barrage_code": item.get("barrage_code"),
        "date_bilan": item.get("date_bilan").isoformat() if isinstance(item.get("date_bilan"), date) else item.get("date_bilan"),
        "row_status": item.get("row_status"),
        "normalized_data": data,
        "comparison": item.get("comparison") or [],
        "errors": item.get("errors") or [],
        "warnings": item.get("warnings") or [],
    }


def submit_for_validation(
    db: Session,
    *,
    principal: AuthPrincipal,
    import_uid: str,
    mode: str,
    reason: str | None,
) -> dict:
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=400, detail="Mode d'import invalide.")
    batch = _batch_row(db, import_uid, lock=True)
    if batch["status"] != STATUS_PREVIEW:
        raise HTTPException(status_code=409, detail="Cet import ne peut plus Ãªtre soumis.")

    db.execute(
        text(
            """
            UPDATE public.data_import_batches
            SET status=:status,
                selected_mode=:mode,
                submitted_by=:user_id,
                submitted_at=now(),
                validation_reason=:reason
            WHERE id=:id;
            """
        ),
        {
            "status": STATUS_PENDING_VALIDATION,
            "mode": mode,
            "user_id": principal.id,
            "reason": reason,
            "id": int(batch["id"]),
        },
    )
    _event(
        db,
        batch_id=int(batch["id"]),
        event_type="SUBMITTED_FOR_VALIDATION",
        user_id=principal.id,
        details={"mode": mode},
        reason=reason,
    )
    db.commit()
    return {"status": "ok", "message": "Import envoyÃ© pour validation.", "import_uid": import_uid}


def reject_import(
    db: Session,
    *,
    principal: AuthPrincipal,
    import_uid: str,
    reason: str,
) -> dict:
    batch = _batch_row(db, import_uid, lock=True)
    if batch["status"] not in {STATUS_PREVIEW, STATUS_PENDING_VALIDATION}:
        raise HTTPException(status_code=409, detail="Cet import ne peut pas Ãªtre rejetÃ©.")
    db.execute(
        text(
            """
            UPDATE public.data_import_batches
            SET status=:status, validated_by=:user_id, validated_at=now(),
                validation_reason=:reason, can_rollback=FALSE
            WHERE id=:id;
            """
        ),
        {"status": STATUS_REJECTED, "user_id": principal.id, "reason": reason, "id": batch["id"]},
    )
    _event(db, batch_id=int(batch["id"]), event_type="REJECTED", user_id=principal.id, reason=reason)
    db.commit()
    return {"status": "ok", "message": "Import rejetÃ©.", "import_uid": import_uid}


def _merge_value(old: Any, new: Any, *, mode: str, replace: bool) -> Any:
    if new is None or new == "":
        return old
    if mode == MODE_REPLACE_SELECTED and replace:
        return new
    if old is None or old == "":
        return new
    return old


def _fresh_merged_rows(
    db: Session,
    *,
    batch: dict,
    rows: list[dict],
    mode: str,
    replace_row_ids: set[int],
) -> tuple[list[dict], list[int]]:
    module_code = batch["module_code"]
    context = dict(batch.get("import_context") or {})
    barrages = _barrages(db)
    merged: list[dict] = []
    skipped: list[int] = []

    for row in rows:
        if row["row_status"] == ROW_INVALID:
            skipped.append(int(row["id"]))
            continue
        code = normalize_code(row["barrage_code"])
        barrage = barrages.get(code)
        if not barrage:
            skipped.append(int(row["id"]))
            continue
        imported = dict(row["normalized_data"] or {})
        imported["restitutions"] = dict(imported.get("restitutions") or {})
        if imported.get("date_situation"):
            imported["date_situation"] = as_date(imported["date_situation"])
        imported["date_bilan"] = row["date_bilan"]
        existing = _existing_for_row(db, module_code, int(barrage["id"]), imported, context)

        if mode == MODE_ADD_ONLY and existing.get("has_existing"):
            skipped.append(int(row["id"]))
            continue

        replace = int(row["id"]) in replace_row_ids
        final = {
            "barrage_code": code,
            "barrage_id": int(barrage["id"]),
            "date_bilan": row["date_bilan"],
            "date_situation": as_date(imported.get("date_situation")) or as_date(context.get("date_situation")),
            "restitutions": {},
            "sheet_name": row.get("sheet_name"),
            "source_row_id": int(row["id"]),
        }
        for field in INPUT_FIELDS:
            final[field] = _merge_value(existing.get(field), imported.get(field), mode=mode, replace=replace)

        old_rest = dict(existing.get("restitutions") or {})
        final_rest = dict(old_rest)
        for rest_code, new_value in imported["restitutions"].items():
            old_value = old_rest.get(rest_code)
            final_rest[rest_code] = _merge_value(old_value, new_value, mode=mode, replace=replace)
        final["restitutions"] = final_rest

        changed = any(
            not _same(existing.get(field), final.get(field))
            for field in INPUT_FIELDS
        ) or any(
            not _same(old_rest.get(code), final_rest.get(code))
            for code in set(old_rest) | set(final_rest)
        )
        if not changed:
            skipped.append(int(row["id"]))
            continue
        merged.append(final)

    return merged, skipped


def _snapshot_targets_for_rows(module_code: str, merged: list[dict]) -> set[tuple[int, date]]:
    targets: set[tuple[int, date]] = set()
    for item in merged:
        barrage_id = int(item["barrage_id"])
        if module_code == MODULE_ANNONCE:
            date_situation = item["date_situation"]
            targets.add((barrage_id, date_situation - timedelta(days=1)))
            targets.add((barrage_id, date_situation))
        else:
            day = item["date_bilan"]
            targets.add((barrage_id, day))
            targets.add((barrage_id, day + timedelta(days=1)))
    return targets


def _write_annonce(db: Session, merged: list[dict], filename: str, principal: AuthPrincipal) -> dict:
    """Stocke toutes les lignes Annonce.

    Une ligne avec date + barrage est conservée même si le calcul hydraulique est
    impossible. Les valeurs disponibles sont écrites, le statut métier devient
    INCOMPLET et les contrôles bloquants sont conservés comme avertissements d'import.
    """
    if not merged:
        return {"saved_count": 0, "incomplete_count": 0, "warning_count": 0}

    grouped: dict[date, list[dict]] = defaultdict(list)
    for item in merged:
        date_situation = as_date(item.get("date_situation"))
        if not date_situation:
            # La date reste la seule donnée métier réellement obligatoire avec le barrage.
            continue
        grouped[date_situation].append(item)

    active = fetch_active_barrages(db)
    saved = 0
    incomplete_count = 0
    warning_count = 0

    # Traitement chronologique : les cotes importées d'un jour peuvent servir au suivant.
    for date_situation in sorted(grouped):
        items = grouped[date_situation]
        date_interval = date_situation - timedelta(days=1)
        journee_id = ensure_journee_situation(db, date_situation)

        # Précharger les cotes du jour précédent disponibles dans le fichier complet.
        for item in items:
            code = item["barrage_code"]
            barrage = active.get(code)
            if not barrage:
                continue
            interval_cote = item.get("cote_interval_ngm")
            if interval_cote is not None:
                upsert_bilan(
                    db,
                    barrage_id=int(barrage["id"]),
                    date_bilan=date_interval,
                    values={
                        "cote_7h_ngm": interval_cote,
                        "statut": "VALIDE",
                        "is_from_import": True,
                        "source_fichier": filename,
                        "source_feuille": item.get("sheet_name") or "IMPORT_ANNONCE",
                        "updated_by": principal.id,
                    },
                )

        request = CalculsComputeRequest(
            date_situation=date_situation,
            barrages=[
                BarrageCalculationInput(
                    barrage_code=item["barrage_code"],
                    cote_7h_ngm=item.get("cote_7h_ngm"),
                    hauteur_bac_mm=item.get("hauteur_bac_mm"),
                    pluie_mm=item.get("pluie_mm"),
                    restitutions=[
                        RestitutionInput(type_code=code, valeur_m3=value)
                        for code, value in sorted(item.get("restitutions", {}).items())
                    ],
                    transfert_dar_khrofa_m3=item.get("restitutions", {}).get("TRANSFERT_DAR_KHROFA"),
                    observation=item.get("observation"),
                )
                for item in items
            ],
        )

        try:
            computed_payload = compute_calculs(db, request)
            results_by_code = {
                result.get("barrage_code"): result
                for result in computed_payload.get("results", [])
            }
        except Exception as exc:
            # Une panne du calcul ne doit pas faire perdre les données brutes du fichier.
            results_by_code = {
                item["barrage_code"]: {
                    "barrage_code": item["barrage_code"],
                    "can_save": False,
                    "computed": None,
                    "checks": [
                        {
                            "niveau": "BLOQUANT",
                            "message": f"Calcul hydraulique non exécuté : {exc}",
                        }
                    ],
                }
                for item in items
            }

        for item in items:
            code = item["barrage_code"]
            barrage = active.get(code)
            if not barrage:
                # Les barrages inconnus ont déjà été classés INVALID et normalement filtrés.
                continue

            barrage_id = int(barrage["id"])
            source_sheet = item.get("sheet_name") or "IMPORT_ANNONCE"
            result = results_by_code.get(code) or {}
            computed = result.get("computed")
            can_compute = result.get("can_save") is True and computed is not None

            if can_compute:
                interval_values = {
                    "journee_situation_id": journee_id,
                    "cote_7h_ngm": item.get("cote_interval_ngm"),
                    "hauteur_bac_mm": item.get("hauteur_bac_mm"),
                    "pluie_mm": item.get("pluie_mm"),
                    "surface_moyenne_km2": computed["surface_moyenne_km2"],
                    "volume_jour_suivant_mm3": computed["volume_next_mm3"],
                    "variation_reserve_mm3": computed["variation_reserve_mm3"],
                    "hauteur_evaporee_mm": computed["hauteur_evaporee_mm"],
                    "hauteur_corrigee_mm": computed["hauteur_corrigee_mm"],
                    "evaporation_m3": computed["evaporation_m3"],
                    "evaporation_1000m3": computed["evaporation_1000m3"],
                    "debit_evaporation_1000m3s": computed["debit_evaporation_1000m3s"],
                    "total_restitutions_m3": computed["total_restitutions_m3"],
                    "transfert_dar_khrofa_m3": computed["transfert_dar_khrofa_m3"],
                    "apports_raw_m3": computed["apports_raw_m3"],
                    "apports_m3": computed["apports_m3"],
                    "debit_m3s": computed["debit_m3s"],
                    "statut": "VALIDE",
                    "observation": item.get("observation"),
                    "is_from_import": True,
                    "source_fichier": filename,
                    "source_feuille": source_sheet,
                    "updated_by": principal.id,
                }
                current_values = {
                    "journee_situation_id": journee_id,
                    "cote_7h_ngm": item.get("cote_7h_ngm"),
                    "volume_mm3": computed["volume_next_mm3"],
                    "surface_km2": computed["surface_next_km2"],
                    "taux_remplissage": computed["taux_remplissage"],
                    "statut": "VALIDE",
                    "observation": item.get("observation"),
                    "is_from_import": True,
                    "source_fichier": filename,
                    "source_feuille": source_sheet,
                    "updated_by": principal.id,
                }
            else:
                blocking_messages = [
                    str(check.get("message") or "").strip()
                    for check in result.get("checks", [])
                    if check.get("niveau") == "BLOQUANT" and check.get("message")
                ]
                missing_fields = _annonce_missing_fields(item)
                warning_messages = []
                if missing_fields:
                    warning_messages.append("Champs manquants : " + ", ".join(missing_fields) + ".")
                warning_messages.extend(blocking_messages)
                if not warning_messages:
                    warning_messages.append("Calcul hydraulique incomplet; les données disponibles ont été conservées.")

                auto_note = "Import incomplet : " + " | ".join(warning_messages[:8])
                original_note = str(item.get("observation") or "").strip()
                observation = f"{original_note} — {auto_note}" if original_note else auto_note

                interval_values = {
                    "journee_situation_id": journee_id,
                    "cote_7h_ngm": item.get("cote_interval_ngm"),
                    "hauteur_bac_mm": item.get("hauteur_bac_mm"),
                    "pluie_mm": item.get("pluie_mm"),
                    "statut": "INCOMPLET",
                    "observation": observation,
                    "is_from_import": True,
                    "source_fichier": filename,
                    "source_feuille": source_sheet,
                    "updated_by": principal.id,
                }
                restitutions = item.get("restitutions", {})
                if restitutions:
                    interval_values["total_restitutions_m3"] = sum(zero(value) for value in restitutions.values())
                if restitutions.get("TRANSFERT_DAR_KHROFA") is not None:
                    interval_values["transfert_dar_khrofa_m3"] = restitutions.get("TRANSFERT_DAR_KHROFA")

                current_values = {
                    "journee_situation_id": journee_id,
                    "cote_7h_ngm": item.get("cote_7h_ngm"),
                    "statut": "INCOMPLET",
                    "observation": observation,
                    "is_from_import": True,
                    "source_fichier": filename,
                    "source_feuille": source_sheet,
                    "updated_by": principal.id,
                }

                current_cote = item.get("cote_7h_ngm")
                if current_cote is not None:
                    bareme = lookup_bareme_exact(db, barrage_id, float(current_cote))
                    if bareme:
                        current_values["volume_mm3"] = bareme.get("volume_mm3")
                        current_values["surface_km2"] = bareme.get("surface_km2")
                        current_values["taux_remplissage"] = safe_rate(
                            bareme.get("volume_mm3"), barrage.get("capacite_normale_mm3")
                        )

                _append_import_row_warnings(
                    db,
                    int(item["source_row_id"]),
                    [
                        "La ligne a été stockée avec des données manquantes.",
                        *warning_messages,
                    ],
                )
                incomplete_count += 1
                warning_count += len(warning_messages)

            interval_id = upsert_bilan(
                db,
                barrage_id=barrage_id,
                date_bilan=date_interval,
                values=interval_values,
            )
            upsert_bilan(
                db,
                barrage_id=barrage_id,
                date_bilan=date_situation,
                values=current_values,
            )

            for rest_code, value in item.get("restitutions", {}).items():
                upsert_restitution(
                    db,
                    bilan_id=interval_id,
                    type_code=rest_code,
                    valeur_m3=zero(value),
                    observation=f"Import validé {filename}",
                )

            if can_compute:
                variables = [
                    ("HAUTEUR_EVAPOREE_MM", "Hauteur évaporée", computed["hauteur_evaporee_mm"], "mm"),
                    ("HAUTEUR_CORRIGEE_MM", "Hauteur corrigée", computed["hauteur_corrigee_mm"], "mm"),
                    ("EVAPORATION_1000M3", "Evaporation en milliers de m3", computed["evaporation_1000m3"], "1000 m3"),
                    ("DEBIT_EVAPORATION_1000M3S", "Débit évaporation auxiliaire", computed["debit_evaporation_1000m3s"], "1000 m3/s"),
                    ("APPORTS_RAW_M3", "Apports bruts avant max(0)", computed["apports_raw_m3"], "m3"),
                    ("TRANSFERT_DAR_KHROFA_M3", "Transfert Dar Khrofa", computed["transfert_dar_khrofa_m3"], "m3"),
                ]
                for var_code, label, value, unit in variables:
                    upsert_bilan_variable(
                        db,
                        bilan_id=interval_id,
                        code_variable=var_code,
                        libelle_variable=label,
                        valeur_numeric=value,
                        unite=unit,
                        source_type="IMPORT_ANNONCE",
                    )

            saved += 1

    return {
        "saved_count": saved,
        "incomplete_count": incomplete_count,
        "warning_count": warning_count,
    }

def _write_bilan(db: Session, merged: list[dict], filename: str, principal: AuthPrincipal) -> int:
    if not merged:
        return 0
    grouped: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    by_code_date: dict[tuple[str, date], dict] = {}
    for item in merged:
        day = item["date_bilan"]
        grouped[(item["barrage_code"], day.year, day.month)].append(item)
        by_code_date[(item["barrage_code"], day)] = item

    active = fetch_active_barrages(db)
    saved = 0
    for (code, year, month), items in grouped.items():
        items.sort(key=lambda value: value["date_bilan"])
        rows: list[BilanDailyInput] = []
        for item in items:
            day = item["date_bilan"]
            next_imported = by_code_date.get((code, day + timedelta(days=1)))
            next_cote = item.get("cote_suivante_ngm")
            if next_imported and next_imported.get("cote_7h_ngm") is not None:
                next_cote = next_imported.get("cote_7h_ngm")
            rows.append(
                BilanDailyInput(
                    date_bilan=day,
                    cote_7h_ngm=item.get("cote_7h_ngm"),
                    cote_suivante_ngm=next_cote,
                    hauteur_bac_mm=item.get("hauteur_bac_mm"),
                    pluie_mm=item.get("pluie_mm"),
                    restitutions=[
                        BilanRestitutionInput(type_code=rest_code, valeur_m3=value)
                        for rest_code, value in sorted(item.get("restitutions", {}).items())
                    ],
                    observation=item.get("observation"),
                )
            )
        request = BilanComputeRequest(barrage_code=code, year=year, month=month, rows=rows)
        computed_payload = compute_bilan(db, request)
        if not computed_payload.get("can_save"):
            messages = []
            for result in computed_payload.get("results", []):
                for check in result.get("checks", []):
                    if check.get("niveau") == "BLOQUANT":
                        messages.append(f"{result.get('date_bilan')}: {check.get('message')}")
            raise ValueError(f"Validation BILAN impossible pour {code}. " + " | ".join(messages[:10]))

        barrage = active.get(code)
        if not barrage:
            raise ValueError(f"Barrage actif introuvable : {code}")
        barrage_id = int(barrage["id"])
        capacity = float(barrage["capacite_normale_mm3"]) if barrage.get("capacite_normale_mm3") is not None else None
        item_by_date = {item["date_bilan"].isoformat(): item for item in items}

        for result in computed_payload["results"]:
            day = date.fromisoformat(result["date_bilan"])
            next_day = date.fromisoformat(result["date_suivante"])
            computed = result["computed"]
            inputs = result["inputs"]
            source_item = item_by_date[day.isoformat()]
            journee_id = ensure_journee_situation(db, next_day)
            current_values = {
                "journee_situation_id": journee_id,
                "cote_7h_ngm": inputs["cote_7h_ngm"],
                "hauteur_bac_mm": inputs["hauteur_bac_mm"],
                "pluie_mm": inputs["pluie_mm"],
                "surface_km2": computed["surface_interval_km2"],
                "surface_moyenne_km2": computed["surface_moyenne_km2"],
                "volume_mm3": computed["volume_interval_mm3"],
                "volume_jour_suivant_mm3": computed["volume_next_mm3"],
                "variation_reserve_mm3": computed["variation_reserve_mm3"],
                "hauteur_evaporee_mm": computed["hauteur_evaporee_mm"],
                "hauteur_corrigee_mm": computed["hauteur_corrigee_mm"],
                "evaporation_m3": computed["evaporation_m3"],
                "evaporation_1000m3": computed["evaporation_1000m3"],
                "debit_evaporation_1000m3s": computed["debit_evaporation_1000m3s"],
                "total_restitutions_m3": computed["total_restitutions_m3"],
                "transfert_dar_khrofa_m3": computed["transfert_dar_khrofa_m3"],
                "apports_raw_m3": computed["apports_raw_m3"],
                "apports_m3": computed["apports_m3"],
                "debit_m3s": computed["debit_m3s"],
                "taux_remplissage": safe_rate(computed["volume_interval_mm3"], capacity),
                "statut": "VALIDE",
                "observation": inputs.get("observation"),
                "is_from_import": True,
                "source_fichier": filename,
                "source_feuille": "IMPORT_BILAN",
                "updated_by": principal.id,
                "validated_by": principal.id,
                "validated_at": datetime.now(),
            }
            current_id = upsert_bilan(db, barrage_id=barrage_id, date_bilan=day, values=current_values)
            next_values = {
                "journee_situation_id": journee_id,
                "cote_7h_ngm": inputs["cote_suivante_ngm"],
                "surface_km2": computed["surface_next_km2"],
                "volume_mm3": computed["volume_next_mm3"],
                "taux_remplissage": safe_rate(computed["volume_next_mm3"], capacity),
                "statut": "VALIDE",
                "is_from_import": True,
                "source_fichier": filename,
                "source_feuille": "IMPORT_BILAN",
                "updated_by": principal.id,
            }
            upsert_bilan(db, barrage_id=barrage_id, date_bilan=next_day, values=next_values)
            for rest_code, value in computed["input_values"].items():
                upsert_restitution(
                    db,
                    bilan_id=current_id,
                    type_code=rest_code,
                    valeur_m3=zero(value),
                    observation=f"Import validÃ© {filename}",
                )
            variables = [
                ("HAUTEUR_EVAPOREE_MM", "Hauteur Ã©vaporÃ©e", computed["hauteur_evaporee_mm"], "mm"),
                ("HAUTEUR_CORRIGEE_MM", "Hauteur corrigÃ©e", computed["hauteur_corrigee_mm"], "mm"),
                ("EVAPORATION_1000M3", "Evaporation en milliers de m3", computed["evaporation_1000m3"], "1000 m3"),
                ("DEBIT_EVAPORATION_1000M3S", "DÃ©bit Ã©vaporation auxiliaire", computed["debit_evaporation_1000m3s"], "1000 m3/s"),
                ("APPORTS_RAW_M3", "Apports bruts avant max(0)", computed["apports_raw_m3"], "m3"),
                ("TRANSFERT_DAR_KHROFA_M3", "Transfert Dar Khrofa", computed["transfert_dar_khrofa_m3"], "m3"),
                ("IRRIGATION_CALCULEE_M3", "Irrigation calculÃ©e Dar Khrofa", computed.get("irrigation_m3"), "m3"),
            ]
            for var_code, label, value, unit in variables:
                upsert_bilan_variable(
                    db,
                    bilan_id=current_id,
                    code_variable=var_code,
                    libelle_variable=label,
                    valeur_numeric=value,
                    unite=unit,
                    source_type="IMPORT_BILAN",
                )
            saved += 1
    return saved


def apply_import(
    db: Session,
    *,
    principal: AuthPrincipal,
    import_uid: str,
    mode: str,
    replace_row_ids: list[int],
    validation_reason: str | None,
) -> dict:
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=400, detail="Mode d'import invalide.")
    batch = _batch_row(db, import_uid, lock=True)
    if batch["status"] not in {STATUS_PREVIEW, STATUS_PENDING_VALIDATION}:
        raise HTTPException(status_code=409, detail="Cet import ne peut plus Ãªtre appliquÃ©.")
    if mode == MODE_REPLACE_SELECTED and not replace_row_ids:
        raise HTTPException(status_code=400, detail="SÃ©lectionnez au moins une ligne conflictuelle Ã  remplacer.")

    rows = _fetch_rows(db, int(batch["id"]))
    merged, skipped_ids = _fresh_merged_rows(
        db,
        batch=batch,
        rows=rows,
        mode=mode,
        replace_row_ids=set(replace_row_ids),
    )
    if not merged:
        raise HTTPException(status_code=400, detail="Aucune nouvelle valeur ne doit Ãªtre appliquÃ©e.")

    targets = _snapshot_targets_for_rows(batch["module_code"], merged)
    before = {(barrage_id, day): _aggregate_with_codes(db, barrage_id, day) for barrage_id, day in targets}

    try:
        if batch["module_code"] == MODULE_ANNONCE:
            write_result = _write_annonce(db, merged, batch["original_filename"], principal)
            saved_count = int(write_result.get("saved_count") or 0)
            incomplete_count = int(write_result.get("incomplete_count") or 0)
            warning_count = int(write_result.get("warning_count") or 0)
        else:
            saved_count = _write_bilan(db, merged, batch["original_filename"], principal)
            incomplete_count = 0
            warning_count = 0

        after = {(barrage_id, day): _aggregate_with_codes(db, barrage_id, day) for barrage_id, day in targets}
        sequence = 1
        for barrage_id, day in sorted(targets, key=lambda item: (item[0], item[1])):
            old = before[(barrage_id, day)]
            new = after[(barrage_id, day)]
            if snapshots_equal(old, new):
                continue
            db.execute(
                text(
                    """
                    INSERT INTO public.data_import_changes(
                        batch_id, sequence_no, barrage_id, date_bilan,
                        before_state, after_state, changed_fields
                    ) VALUES (
                        :batch_id, :sequence_no, :barrage_id, :date_bilan,
                        CAST(:before_state AS jsonb), CAST(:after_state AS jsonb),
                        CAST(:changed_fields AS jsonb)
                    );
                    """
                ),
                {
                    "batch_id": int(batch["id"]),
                    "sequence_no": sequence,
                    "barrage_id": barrage_id,
                    "date_bilan": day,
                    "before_state": _json(old),
                    "after_state": _json(new),
                    "changed_fields": _json(changed_fields(old, new)),
                },
            )
            sequence += 1

        applied_ids = [int(item["source_row_id"]) for item in merged]
        if applied_ids:
            db.execute(
                text("UPDATE public.data_import_rows SET row_status=:status WHERE id=ANY(:ids);"),
                {"status": ROW_APPLIED, "ids": applied_ids},
            )
        if skipped_ids:
            db.execute(
                text("UPDATE public.data_import_rows SET row_status=:status WHERE id=ANY(:ids) AND row_status<>:invalid;"),
                {"status": ROW_SKIPPED, "ids": skipped_ids, "invalid": ROW_INVALID},
            )

        db.execute(
            text(
                """
                UPDATE public.data_import_batches
                SET status=:status,
                    selected_mode=:mode,
                    validated_by=:user_id,
                    validated_at=now(),
                    applied_by=:user_id,
                    applied_at=now(),
                    validation_reason=:reason,
                    can_rollback=TRUE,
                    summary=summary || CAST(:applied_summary AS jsonb)
                WHERE id=:id;
                """
            ),
            {
                "status": STATUS_APPLIED,
                "mode": mode,
                "user_id": principal.id,
                "reason": validation_reason,
                "applied_summary": _json({
                    "applied_rows": saved_count,
                    "skipped_rows": len(skipped_ids),
                    "changed_aggregates": sequence - 1,
                    "incomplete_rows": incomplete_count,
                    "application_warnings": warning_count,
                }),
                "id": int(batch["id"]),
            },
        )
        _event(
            db,
            batch_id=int(batch["id"]),
            event_type="VALIDATED_AND_APPLIED",
            user_id=principal.id,
            details={
                "mode": mode,
                "applied_rows": saved_count,
                "skipped_rows": len(skipped_ids),
                "replace_row_ids": replace_row_ids,
                "changed_aggregates": sequence - 1,
                "incomplete_rows": incomplete_count,
                "application_warnings": warning_count,
            },
            reason=validation_reason,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        db.execute(
            text("UPDATE public.data_import_batches SET status=:status, error_message=:error WHERE id=:id;"),
            {"status": STATUS_FAILED, "error": str(exc), "id": int(batch["id"])},
        )
        _event(
            db,
            batch_id=int(batch["id"]),
            event_type="APPLY_FAILED",
            user_id=principal.id,
            details={"error": str(exc)},
            status="ERROR",
        )
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    message = "Import validé et appliqué. Un retour arrière complet reste disponible."
    if incomplete_count:
        message = (
            f"Import appliqué avec avertissements : {incomplete_count} ligne(s) ont été "
            "stockée(s) avec des champs manquants. Les calculs impossibles sont restés vides."
        )

    return {
        "status": "ok",
        "message": message,
        "import_uid": import_uid,
        "applied_rows": saved_count,
        "skipped_rows": len(skipped_ids),
        "incomplete_rows": incomplete_count,
        "warning_count": warning_count,
        "can_rollback": True,
    }


def rollback_import(
    db: Session,
    *,
    principal: AuthPrincipal,
    import_uid: str,
    reason: str,
    force: bool,
) -> dict:
    batch = _batch_row(db, import_uid, lock=True)
    if batch["status"] != STATUS_APPLIED or not batch.get("can_rollback"):
        raise HTTPException(status_code=409, detail="Cet import ne peut pas Ãªtre annulÃ©.")
    if force and principal.role_code != "ADMIN":
        raise HTTPException(status_code=403, detail="Seul un administrateur peut forcer un retour arriÃ¨re.")

    changes = [
        dict(row)
        for row in db.execute(
            text(
                """
                SELECT * FROM public.data_import_changes
                WHERE batch_id=:batch_id
                ORDER BY sequence_no DESC
                FOR UPDATE;
                """
            ),
            {"batch_id": int(batch["id"])},
        ).mappings().all()
    ]
    if not changes:
        raise HTTPException(status_code=409, detail="Aucun Ã©tat antÃ©rieur n'a Ã©tÃ© enregistrÃ© pour cet import.")

    drift: list[dict] = []
    for change in changes:
        current = _aggregate_with_codes(db, int(change["barrage_id"]), change["date_bilan"])
        expected_after = dict(change["after_state"])
        if not snapshots_equal(current, expected_after):
            drift.append({
                "barrage_id": int(change["barrage_id"]),
                "date_bilan": change["date_bilan"].isoformat(),
            })

    if drift and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ROLLBACK_DATA_CHANGED_AFTER_IMPORT",
                "message": (
                    "Certaines donnÃ©es ont Ã©tÃ© modifiÃ©es aprÃ¨s cet import. "
                    "Le retour arriÃ¨re normal est bloquÃ© pour ne pas Ã©craser ces changements."
                ),
                "changed_targets": drift,
            },
        )

    try:
        for change in changes:
            restore_aggregate(db, dict(change["before_state"]))
            db.execute(
                text("UPDATE public.data_import_changes SET rolled_back_at=now() WHERE id=:id;"),
                {"id": int(change["id"])},
            )

        db.execute(
            text(
                """
                UPDATE public.data_import_batches
                SET status=:status,
                    rolled_back_by=:user_id,
                    rolled_back_at=now(),
                    rollback_reason=:reason,
                    can_rollback=FALSE
                WHERE id=:id;
                """
            ),
            {
                "status": STATUS_ROLLED_BACK,
                "user_id": principal.id,
                "reason": reason,
                "id": int(batch["id"]),
            },
        )
        _event(
            db,
            batch_id=int(batch["id"]),
            event_type="ROLLED_BACK",
            user_id=principal.id,
            details={"force": force, "restored_aggregates": len(changes), "drift": drift},
            reason=reason,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Retour arriÃ¨re impossible : {exc}") from exc

    return {
        "status": "ok",
        "message": "L'import a Ã©tÃ© annulÃ© et les donnÃ©es antÃ©rieures ont Ã©tÃ© restaurÃ©es.",
        "import_uid": import_uid,
        "restored_aggregates": len(changes),
        "forced": force,
    }


def get_import_details(db: Session, *, import_uid: str) -> dict:
    batch = _batch_row(db, import_uid)
    rows = _fetch_rows(db, int(batch["id"]))
    events = [
        dict(row)
        for row in db.execute(
            text(
                """
                SELECT e.*, u.username
                FROM public.data_import_events e
                LEFT JOIN public.users u ON u.id=e.user_id
                WHERE e.batch_id=:batch_id
                ORDER BY e.created_at;
                """
            ),
            {"batch_id": int(batch["id"])},
        ).mappings().all()
    ]
    return {
        "status": "ok",
        "batch": _serialize_batch(batch),
        "rows": [_serialize_row(row) for row in rows],
        "events": [_serialize_batch(row) for row in events],
    }


def _serialize_row(row: dict) -> dict:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
    return result


def list_import_history(
    db: Session,
    *,
    module_code: str | None,
    limit: int,
) -> dict:
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    where = ""
    if module_code:
        module_code = module_code.upper().strip()
        where = "WHERE b.module_code=:module_code"
        params["module_code"] = module_code
    rows = db.execute(
        text(
            f"""
            SELECT
                b.*,
                creator.username AS created_by_username,
                validator.username AS validated_by_username,
                rollback_user.username AS rolled_back_by_username
            FROM public.data_import_batches b
            LEFT JOIN public.users creator ON creator.id=b.created_by
            LEFT JOIN public.users validator ON validator.id=b.validated_by
            LEFT JOIN public.users rollback_user ON rollback_user.id=b.rolled_back_by
            {where}
            ORDER BY b.created_at DESC
            LIMIT :limit;
            """
        ),
        params,
    ).mappings().all()
    return {
        "status": "ok",
        "count": len(rows),
        "imports": [_serialize_batch(dict(row)) for row in rows],
    }


def generate_template_csv(db: Session, *, module_code: str, context: dict) -> tuple[str, bytes]:
    module_code = module_code.upper().strip()
    if module_code == MODULE_ANNONCE:
        rest_codes = [
            str(value)
            for value in db.execute(
                text("SELECT code FROM public.types_restitution WHERE COALESCE(actif, TRUE)=TRUE ORDER BY code;")
            ).scalars().all()
        ]
        headers = [
            "barrage_code",
            "date_situation",
            "cote_interval_ngm",
            "cote_7h_ngm",
            "hauteur_bac_mm",
            "pluie_mm",
            *[f"restitution_{item}" for item in rest_codes],
            "observation",
        ]
        barrage_codes = [
            str(value)
            for value in db.execute(
                text(
                    """
                    SELECT code
                    FROM public.barrages
                    WHERE COALESCE(actif, TRUE)=TRUE
                      AND COALESCE(inclure_annonce, TRUE)=TRUE
                    ORDER BY COALESCE(ordre_annonce, ordre_affichage, id), id;
                    """
                )
            ).scalars().all()
        ]
        sample_rows = []
        sample_date = str(context.get("date_situation") or date.today().isoformat())
        for code in barrage_codes:
            sample_rows.append([code, sample_date, "", "", "", "", *([""] * len(rest_codes)), ""])
        filename = "modele_import_annonce_complet.csv"
    else:
        code = normalize_code(context.get("barrage_code")) or "NAKHLA"
        rest_codes = [
            str(row["code"])
            for row in db.execute(
                text(
                    """
                    SELECT tr.code
                    FROM public.barrage_types_restitution btr
                    JOIN public.barrages b ON b.id=btr.barrage_id
                    JOIN public.types_restitution tr ON tr.id=btr.type_restitution_id
                    WHERE b.code=:code AND COALESCE(btr.actif, TRUE)=TRUE
                    ORDER BY COALESCE(btr.ordre_affichage, tr.id);
                    """
                ),
                {"code": code},
            ).mappings().all()
        ]
        headers = [
            "barrage_code",
            "date_bilan",
            "cote_7h_ngm",
            "cote_suivante_ngm",
            "hauteur_bac_mm",
            "pluie_mm",
            *[f"restitution_{item}" for item in rest_codes],
            "observation",
        ]
        sample = [code, "", "", "", "", "", *([""] * len(rest_codes)), ""]
        filename = f"modele_import_bilan_{code}.csv"

    if module_code == MODULE_ANNONCE:
        lines = [";".join(headers), *[";".join(row) for row in sample_rows]]
    else:
        lines = [";".join(headers), ";".join(sample)]
    content = "\r\n".join(lines) + "\r\n"
    return filename, content.encode("utf-8-sig")

