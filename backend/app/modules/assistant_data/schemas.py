from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class AssistantFilters(BaseModel):
    barrage_code: str | None = None
    agence_code: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    metrics: list[str] = Field(default_factory=list)
    limit: int = 500


class AssistantQueryRequest(BaseModel):
    question: str | None = None
    filters: AssistantFilters | None = None
    use_llm: bool = True
    conversation_id: str | None = None



class GuidedQueryRequest(BaseModel):
    barrage_code: str | None = None
    agence_code: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    metric: str = "volume"
    restitution_type_code: str | None = None
    limit: int = 500
