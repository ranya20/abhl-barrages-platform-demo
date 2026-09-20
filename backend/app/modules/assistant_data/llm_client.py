from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ENV_PATH, override=True)


def _env(name: str) -> str:
    return os.getenv(name, "").strip().strip('"').strip("'")


def first_env(*names: str) -> str:
    for name in names:
        value = _env(name)
        if value:
            return value
    return ""


def as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def as_float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def llm_enabled() -> bool:
    explicit = _env("ASSISTANT_LLM_ENABLED").lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    return bool(first_env("ASSISTANT_LLM_API_KEY", "OPENROUTER_API_KEY"))


def strict_llm_mode() -> bool:
    return _env("ASSISTANT_STRICT_LLM").lower() in {"1", "true", "yes", "on"}


def llm_options() -> dict[str, Any]:
    return {
        "api_key": first_env("ASSISTANT_LLM_API_KEY", "OPENROUTER_API_KEY"),
        "temperature": as_float(first_env("ASSISTANT_LLM_TEMPERATURE", "OPENROUTER_TEMPERATURE"), 0.0),
        "max_tokens": as_int(first_env("ASSISTANT_LLM_MAX_TOKENS", "OPENROUTER_MAX_TOKENS"), 900),
        "timeout": as_int(first_env("ASSISTANT_LLM_TIMEOUT", "OPENROUTER_TIMEOUT"), 60),
    }


def model_candidates() -> list[str]:
    primary = first_env("ASSISTANT_LLM_MODEL", "OPENROUTER_MODEL")
    fallbacks = first_env("ASSISTANT_LLM_FALLBACK_MODELS", "OPENROUTER_FALLBACK_MODELS")

    candidates: list[str] = []
    if primary:
        candidates.append(primary)

    for item in fallbacks.split(","):
        item = item.strip()
        if item and item not in candidates:
            candidates.append(item)

    if not candidates:
        candidates = ["openrouter/free"]

    return candidates


def candidate_endpoints() -> list[str]:
    bases = [
        first_env("ASSISTANT_LLM_BASE_URL", "OPENROUTER_BASE_URL"),
        "https://openrouter.ai/api/v1",
    ]

    endpoints: list[str] = []

    for base in bases:
        base = (base or "").rstrip("/")
        if not base:
            continue
        if base.endswith("/chat/completions"):
            endpoints.append(base)
        else:
            endpoints.append(base + "/chat/completions")

    endpoints.append("https://openrouter.ai/api/v1/chat/completions")

    unique: list[str] = []
    for endpoint in endpoints:
        if endpoint not in unique:
            unique.append(endpoint)

    return unique


def llm_status() -> dict[str, Any]:
    opts = llm_options()
    return {
        "enabled": llm_enabled(),
        "strict_mode": strict_llm_mode(),
        "api_key_present": bool(opts["api_key"]),
        "models": model_candidates(),
        "endpoints": candidate_endpoints(),
        "temperature": opts["temperature"],
        "max_tokens": opts["max_tokens"],
        "timeout": opts["timeout"],
        "env_path": str(ENV_PATH),
    }


def extract_json(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None

    raw = str(content).strip()

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    raw = re.sub(r"^```(?:json|sql)?", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"```$", "", raw).strip()

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")

    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def chat_completion(
    messages: list[dict[str, str]],
    *,
    force_json: bool = False,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    opts = llm_options()

    if not opts["api_key"]:
        raise RuntimeError("Clé OpenRouter manquante dans backend/.env : OPENROUTER_API_KEY ou ASSISTANT_LLM_API_KEY.")

    errors: list[str] = []

    for model in model_candidates():
        for endpoint in candidate_endpoints():
            payload: dict[str, Any] = {
                "model": model,
                "temperature": opts["temperature"],
                "max_tokens": max_tokens or opts["max_tokens"],
                "messages": messages,
            }

            if force_json:
                payload["response_format"] = {"type": "json_object"}

            request = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {opts['api_key']}",
                    "HTTP-Referer": "http://localhost:5173",
                    "X-Title": "ABHL Barrages Platform",
                    "X-OpenRouter-Metadata": "enabled",
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(request, timeout=opts["timeout"]) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    data = json.loads(raw)

                content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""

                return content, {
                    "model": model,
                    "endpoint": endpoint,
                    "response_id": data.get("id"),
                }

            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                errors.append(f"{model} @ {endpoint} -> HTTP {exc.code}: {body[:1200]}")
            except Exception as exc:
                errors.append(f"{model} @ {endpoint} -> {type(exc).__name__}: {exc}")

    raise RuntimeError("Tous les appels OpenRouter ont échoué. " + " | ".join(errors[-6:]))


def test_llm_connection() -> dict[str, Any]:
    content, meta = chat_completion(
        [
            {"role": "system", "content": "Réponds uniquement en JSON strict."},
            {"role": "user", "content": "Retourne exactement {\"ok\": true, \"message\": \"connected\"}"},
        ],
        force_json=False,
        max_tokens=80,
    )

    parsed = extract_json(content)

    return {
        "ok": bool(parsed),
        "parsed": parsed,
        "raw_preview": content[:300],
        "meta": meta,
        "status": llm_status(),
    }
