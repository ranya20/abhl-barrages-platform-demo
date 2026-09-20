from __future__ import annotations

import datetime as dt
import decimal
import re
import unicodedata
from typing import Any


def fix_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    replacements = {
        "TÃ©touan": "Tétouan",
        "MÃ©diterrannÃ©e": "Méditerranée",
        "MÃ©diterrannée": "Méditerranée",
        "Ã©": "é",
        "Ã¨": "è",
        "Ã ": "à",
        "Ã¢": "â",
        "Ãª": "ê",
        "Ã´": "ô",
        "Ã»": "û",
        "Ã§": "ç",
    }

    result = value
    for bad, good in replacements.items():
        result = result.replace(bad, good)

    return result


def jsonable(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, str):
        return fix_text(value)
    return value


def row_to_dict(row: Any) -> dict[str, Any]:
    return {key: jsonable(value) for key, value in dict(row).items()}


def normalize(value: str | None) -> str:
    if not value:
        return ""

    value = fix_text(value)
    value = unicodedata.normalize("NFD", str(value))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def limit_value(value: int | None, *, default: int = 500, maximum: int = 1000) -> int:
    try:
        raw = int(value or default)
    except Exception:
        raw = default

    return max(1, min(raw, maximum))
