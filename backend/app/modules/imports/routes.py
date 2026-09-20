from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.dependencies import AuthPrincipal, get_current_ready_user, require_roles
from app.modules.imports.schemas import (
    ApplyImportRequest,
    RejectImportRequest,
    RollbackImportRequest,
    SubmitImportRequest,
)
from app.modules.imports.service import (
    apply_import,
    create_preview,
    generate_template_csv,
    get_import_details,
    list_import_history,
    reject_import,
    rollback_import,
    submit_for_validation,
)


router = APIRouter()


@router.post("/preview")
async def preview_import(
    module_code: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    context_json: Annotated[str, Form()] = "{}",
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    try:
        context = json.loads(context_json or "{}")
        if not isinstance(context, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        context = {}

    content = await file.read()
    return create_preview(
        db,
        principal=principal,
        module_code=module_code,
        filename=file.filename or "import.xlsx",
        content=content,
        context=context,
    )


@router.post("/{import_uid}/submit")
def submit_import(
    import_uid: str,
    payload: SubmitImportRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "SAISIE", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    return submit_for_validation(
        db,
        principal=principal,
        import_uid=import_uid,
        mode=payload.mode,
        reason=payload.reason,
    )


@router.post("/{import_uid}/apply")
def validate_and_apply_import(
    import_uid: str,
    payload: ApplyImportRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    return apply_import(
        db,
        principal=principal,
        import_uid=import_uid,
        mode=payload.mode,
        replace_row_ids=payload.replace_row_ids,
        validation_reason=payload.validation_reason,
    )


@router.post("/{import_uid}/reject")
def reject_import_route(
    import_uid: str,
    payload: RejectImportRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    return reject_import(
        db,
        principal=principal,
        import_uid=import_uid,
        reason=payload.reason,
    )


@router.post("/{import_uid}/rollback")
def rollback_import_route(
    import_uid: str,
    payload: RollbackImportRequest,
    principal: AuthPrincipal = Depends(require_roles("ADMIN", "VALIDATEUR")),
    db: Session = Depends(get_db),
):
    return rollback_import(
        db,
        principal=principal,
        import_uid=import_uid,
        reason=payload.reason,
        force=payload.force,
    )


@router.get("/history")
def import_history(
    module_code: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    _: AuthPrincipal = Depends(get_current_ready_user),
    db: Session = Depends(get_db),
):
    return list_import_history(db, module_code=module_code, limit=limit)


@router.get("/template")
def import_template(
    module_code: str = Query(...),
    context_json: str = Query(default="{}"),
    _: AuthPrincipal = Depends(get_current_ready_user),
    db: Session = Depends(get_db),
):
    try:
        context = json.loads(context_json or "{}")
    except json.JSONDecodeError:
        context = {}
    filename, content = generate_template_csv(db, module_code=module_code, context=context)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{import_uid}")
def import_details(
    import_uid: str,
    _: AuthPrincipal = Depends(get_current_ready_user),
    db: Session = Depends(get_db),
):
    return get_import_details(db, import_uid=import_uid)
