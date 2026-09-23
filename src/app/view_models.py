"""Pure presentation helpers for the Streamlit decision-support UI."""
from __future__ import annotations

import json
from typing import Any


RELEVANCE_LABELS = {
    "CORE_INDUSTRIAL": "핵심 산업직무",
    "INDUSTRIAL_SUPPORT": "산업 지원직무",
    "GENERAL_NONCORE": "일반 비핵심직무",
    "UNKNOWN": "상세 미확인",
}


def industry_option_label(industry: str, latest_stage: str | None) -> str:
    return f"{industry} · 우선점검" if latest_stage == "우선점검" else industry


def session_scope(industry: str, quarter: str) -> str:
    return f"{industry}::{quarter}"


def field_context(questions: list[dict], responses: dict[str, dict], note: str = "") -> dict:
    rows = []
    for item in questions:
        saved = responses.get(item["question_id"], {})
        rows.append({
            "question_id": item["question_id"],
            "question": item["question"],
            "checked": bool(saved.get("checked")),
            "answer": str(saved.get("answer") or "").strip() or None,
            "source": item.get("source"),
        })
    return {"responses": rows, "note": note.strip() or None}


def report_download(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def evidence_level_value(level: dict) -> str:
    value = level.get("count")
    return "상세 미확인" if value is None else f"{int(value):,}건"
