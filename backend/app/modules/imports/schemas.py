from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ImportMode = Literal["ADD_ONLY", "FILL_EMPTY", "REPLACE_SELECTED"]


class SubmitImportRequest(BaseModel):
    mode: ImportMode = "FILL_EMPTY"
    reason: str | None = Field(default=None, max_length=1000)


class ApplyImportRequest(BaseModel):
    mode: ImportMode = "FILL_EMPTY"
    replace_row_ids: list[int] = Field(default_factory=list)
    validation_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("replace_row_ids")
    @classmethod
    def unique_ids(cls, value: list[int]) -> list[int]:
        return sorted({int(item) for item in value if int(item) > 0})


class RejectImportRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RollbackImportRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    force: bool = False
