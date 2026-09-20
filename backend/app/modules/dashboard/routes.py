from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from .repository import (
    get_custom_values,
    get_overview,
    get_timeseries,
    list_filters,
)

router = APIRouter()


@router.get("/filters")
def dashboard_filters(db: Session = Depends(get_db)):
    return list_filters(db)


@router.get("/overview")
def dashboard_overview(
    date_situation: date,
    agence_code: str | None = None,
    barrage_code: str | None = None,
    db: Session = Depends(get_db),
):
    return get_overview(
        db=db,
        date_situation=date_situation,
        agence_code=agence_code,
        barrage_code=barrage_code,
    )


@router.get("/timeseries")
def dashboard_timeseries(
    start_date: date,
    end_date: date,
    agence_code: str | None = None,
    barrage_code: str | None = None,
    db: Session = Depends(get_db),
):
    return get_timeseries(
        db=db,
        start_date=start_date,
        end_date=end_date,
        agence_code=agence_code,
        barrage_code=barrage_code,
    )


@router.get("/custom-values")
def dashboard_custom_values(
    start_date: date,
    end_date: date,
    agence_code: str | None = None,
    barrage_codes: Annotated[list[str] | None, Query()] = None,
    variables: Annotated[list[str] | None, Query()] = None,
    db: Session = Depends(get_db),
):
    return get_custom_values(
        db=db,
        start_date=start_date,
        end_date=end_date,
        agence_code=agence_code,
        barrage_codes=barrage_codes,
        variables=variables,
    )
