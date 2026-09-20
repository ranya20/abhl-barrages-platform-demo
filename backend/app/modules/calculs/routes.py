from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.calculs.schemas import CalculsComputeRequest, CalculsSaveRequest
from app.modules.calculs.service import build_calculs_form, compute_calculs, save_calculs


router = APIRouter()


@router.get("/form")
def get_calculs_form(
    date_situation: date = Query(..., description="Date de situation, exemple 2026-06-09"),
    db: Session = Depends(get_db),
):
    return build_calculs_form(db, date_situation)


@router.post("/compute")
def compute_calculs_route(
    payload: CalculsComputeRequest,
    db: Session = Depends(get_db),
):
    return compute_calculs(db, payload)


@router.post("/save")
def save_calculs_route(
    payload: CalculsSaveRequest,
    db: Session = Depends(get_db),
):
    result = save_calculs(db, payload)

    if result["status"] != "ok":
        raise HTTPException(
            status_code=400,
            detail=result,
        )

    return result