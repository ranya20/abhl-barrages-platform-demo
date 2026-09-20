
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.assistant_data.schemas import AssistantQueryRequest, GuidedQueryRequest
from app.modules.assistant_data.service import (
    get_llm_status,
    get_metadata,
    run_assistant_query,
    test_llm_connection,
)
from app.modules.assistant_data.guided_service import get_guided_profile, run_guided_query

router = APIRouter()


@router.get("/metadata")
def metadata(db: Session = Depends(get_db)):
    return get_metadata(db)


@router.get("/llm-status")
def llm_status():
    return get_llm_status()


@router.post("/llm-test")
def llm_test():
    return test_llm_connection()


@router.get("/guided/profile")
def guided_profile(barrage_code: str | None = Query(default=None), db: Session = Depends(get_db)):
    return get_guided_profile(db, barrage_code=barrage_code)


@router.post("/guided/query")
def guided_query(payload: GuidedQueryRequest, db: Session = Depends(get_db)):
    return run_guided_query(db, payload)


@router.post("/query")
def query(payload: AssistantQueryRequest, db: Session = Depends(get_db)):
    return run_assistant_query(db, payload)
