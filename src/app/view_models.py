"""Pure presentation helpers for the Streamlit decision-support UI."""
from __future__ import annotations

import json
from typing import Any


STAGE_CODE = {"우선점검": "priority", "추가확인": "check", "관찰": "watch"}
SOURCE_CATEGORY_LABEL = {"PRINCIPLE_ADAPTED": "원칙 차용", "PROJECT_OPERATIONAL": "운영규칙"}
QUICK_PROMPTS_TAIL = (
    "현장 확인 질문 만들어줘",
    "직전 분기 대비 최근 판정 변화는?",
    "채용신호·직무 키워드로 확인되는 것은?",
    "검토 가능한 지원 기능 후보는?",
    "연결 가능한 공식 지원은?",
    "이 판정의 한계는?",
)

RELEVANCE_LABELS = {
    "CORE_INDUSTRIAL": "핵심 산업직무",
    "INDUSTRIAL_SUPPORT": "산업 지원직무",
    "GENERAL_NONCORE": "일반 비핵심직무",
    "UNKNOWN": "상세 미확인",
}


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


def with_session_context(base: dict[str, Any], field_ctx: dict | None, generated_at: str) -> dict[str, Any]:
    """세션과 무관한(캐시된) 진단 payload에 이번 실행의 현장 입력·생성 시각만 얹는다.

    DecisionSupportService.report_payload(q, ind, field_context=ctx)에서 field_context가 바꾸는 값은
    field_checks.session_context 하나뿐이다(test로 동일성 확인). 캐시 원본은 수정하지 않는다.
    """
    payload = dict(base)
    payload["generated_at"] = generated_at
    payload["field_checks"] = {**base["field_checks"], "session_context": field_ctx or {}}
    return payload


def stage_code(stage: str | None) -> str:
    """CSS class suffix for a Triage stage. 등록되지 않은 값은 'hold'로 묶는다."""
    return STAGE_CODE.get(stage or "", "hold")


def _num(v, digits: int = 1, suffix: str = "") -> str:
    if v is None:
        return "자료 없음"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, int):
        return f"{v:,}{suffix}"
    if isinstance(v, float):
        return f"{v:,.{digits}f}{suffix}"
    return str(v)


def split_threshold(text: str | None) -> tuple[str | None, str | None]:
    """규칙 threshold 문자열을 (진입경계, 상위경계)로 나눈다.

    "5% / 10%" -> ("5%", "10%"), "5%p" -> ("5%p", None). 숫자를 다시 계산하지 않고
    등록된 threshold 문자열만 그대로 나눠 보여준다.
    """
    if not text:
        return None, None
    parts = [p.strip() for p in text.split("/")]
    if len(parts) == 1:
        return (parts[0] or None), None
    return (parts[0] or None), (parts[1] or None)


def _rule(rules: dict[str, dict], name: str) -> dict:
    return rules.get(name, {}) or {}


def _basis_label(rule: dict) -> str:
    return SOURCE_CATEGORY_LABEL.get(rule.get("source_category"), rule.get("source_category") or "—")


def _bucket_verdict(entry: bool | None, up: bool | None) -> str:
    if entry is None:
        return "미확인"
    if up:
        return "상위"
    if entry:
        return "진입"
    return "미달"


def _bool_verdict(value: bool | None, yes: str, no: str) -> str:
    if value is None:
        return "미확인"
    return yes if value else no


def rule_evidence_rows(rec: dict, rules: dict[str, dict]) -> list[dict]:
    """판정근거 표 행. 판정은 snapshot boolean(E_entry/E_up 등)만으로 정하며 재계산하지 않는다."""
    sg, q3, t, q2 = rec["signals"], rec["q3"], rec["triage"], rec["q2"]
    rows = []
    # R은 진입(R_entry)·상위(R_up) 경계가 규칙 두 개로 나뉘어 등록되어 있다.
    for signal, name, rule_name, upper_rule_name, unit in (
            ("E", "E 고용감소율", "E", None, "%"),
            ("R", "R 산단평균 대비 열위", "R_entry", "R_up", "%p"),
            ("A", "A 산단 고용 대비 감소규모", "A", None, "%")):
        rule = _rule(rules, rule_name)
        entry_th, upper_th = split_threshold(rule.get("threshold"))
        if upper_rule_name:
            upper_th = split_threshold(_rule(rules, upper_rule_name).get("threshold"))[0]
        rows.append({
            "signal": name, "current": _num(sg.get(signal), 2, unit),
            "entry_threshold": entry_th, "upper_threshold": upper_th,
            "verdict": _bucket_verdict(sg.get(f"{signal}_entry"), sg.get(f"{signal}_up")),
            "basis": _basis_label(rule), "definition": rule.get("definition", ""),
        })
    p_rule = _rule(rules, "P")
    p_entry, _ = split_threshold(p_rule.get("threshold"))
    rows.append({
        "signal": "P 생산감소(상위 보강)", "current": _num(sg.get("P"), 2, "%"),
        "entry_threshold": p_entry, "upper_threshold": None,
        "verdict": _bool_verdict(sg.get("P_support"), "충족", "미달"),
        "basis": _basis_label(p_rule), "definition": p_rule.get("definition", ""),
    })
    rep_rule = _rule(rules, "repeated_employment_entry_signal")
    rep_entry, _ = split_threshold(rep_rule.get("threshold"))
    rows.append({
        "signal": "반복 진입신호(상위 보강)", "current": _num(q3.get("repeated_signal")),
        "entry_threshold": rep_entry, "upper_threshold": None,
        "verdict": _bool_verdict(q3.get("repeated_signal"), "충족", "미달"),
        "basis": _basis_label(rep_rule), "definition": rep_rule.get("definition", ""),
    })
    scale_rule = _rule(rules, "scale_gate")
    scale_entry, _ = split_threshold(scale_rule.get("threshold"))
    rows.append({
        "signal": "규모 gate(우선점검)", "current": _num(q2.get("employment"), suffix="명"),
        "entry_threshold": scale_entry, "upper_threshold": None,
        "verdict": _bool_verdict(t.get("scale_ok"), "통과", "미달"),
        "basis": _basis_label(scale_rule), "definition": scale_rule.get("definition", ""),
    })
    return rows


def fact_items(rec: dict) -> list[str]:
    """등록 Snapshot 값만으로 만든 사실 목록(원인 해석 없음)."""
    act, q1, q2, q3, sg = rec["activity"], rec["q1"], rec["q2"], rec["q3"], rec["signals"]
    if act.get("op_rate_official") is not None:
        op_rate = f"{_num(act['op_rate_official'], 1, '%')}"
    else:
        op_rate = f"{_num(act.get('op_rate_approx'), 1, '%')} (근사)"
    items = [
        f"고용 {_num(q2.get('employment'), suffix='명')} (전년동기 {_num(q2.get('employment_lag4'), suffix='명')} · "
        f"증감 {_num(q2.get('emp_delta'), suffix='명')} · YoY {_num(q2.get('employment_yoy'), 2, '%')})",
        f"생산 YoY {_num(act.get('production_yoy'), 1, '%')}",
        f"가동률 {op_rate}",
        f"입주/가동 기업 {_num(act.get('firms_in'))} / {_num(act.get('firms_op'))}개",
        f"산단 제조업 순감소 기여율 {_num(q2.get('contribution_pct'), 2, '%')}",
        f"진입신호 개수 · 진입 {_num(sg.get('n_entry'))}건 · 상위 {_num(sg.get('n_up'))}건",
        f"Q1 상태 {q1.get('state_label') or q1.get('state') or '자료 없음'} · 현재 상태 지속 {_num(q3.get('state_run_length'))}분기"
        + (f" · 전이 {q3['transition']}" if q3.get("transition") else ""),
    ]
    return items


def caveat_items(rec: dict, provenance: dict | None, scope: str | None) -> list[str]:
    """기존 '미확인·확인 필요' 탭 로직을 그대로 옮긴 한계 목록."""
    dq = rec["data_quality"]
    items: list[str] = []
    if dq.get("core_missing"):
        items.append("핵심 자료 누락")
    if dq.get("production_missing"):
        items.append("생산자료 미확인")
    if dq.get("previous_signal_unknown"):
        items.append("이전 분기 신호 미확인")
    if rec["triage"].get("data_quality_minimum_only"):
        items.append("확인 가능한 신호에 따른 최소판정")
    if dq.get("review_required"):
        items.append("원천 검토 필요 표시")
    masked = [f for f, v in dq.get("fields", {}).items() if v.get("masked")]
    if masked:
        items.append(f"비공개(마스킹) 항목: {', '.join(masked)}")
    missing_src = [s["label"] for s in rec.get("external_sources") or []
                   if not s.get("available") and not s.get("quality_only")]
    if missing_src:
        items.append(f"외부자료 해당 시점 자료 없음: {', '.join(missing_src)}")
    electre = rec.get("electre_smaa") or {}
    if electre.get("available") and len(electre.get("possible_stages_list") or []) > 1:
        items.append("파라미터에 따라 선택적 재검토 단계가 달라짐")
    items.append("고용 감소의 원인(수주·자동화·폐업·외주화 등)은 집계자료만으로 판단할 수 없습니다.")
    if scope:
        items.append(scope)
    if provenance and provenance.get("snapshot_type") == "reconstructed" and provenance.get("reconstruction_note"):
        items.append(provenance["reconstruction_note"])
    return items


def stage_counts(records: list[dict]) -> dict[str, int]:
    """분기 등록 판정 개수(재계산 아님) — 우선점검/추가확인/관찰 순."""
    counts = {"우선점검": 0, "추가확인": 0, "관찰": 0}
    for r in records:
        stage = (r.get("triage") or {}).get("stage")
        if stage in counts:
            counts[stage] += 1
    return counts


def quick_prompts(stage: str | None) -> list[str]:
    """Copilot 빠른 질문 칩. decision_support.answer()의 키워드 라우팅에 맞춘 문구만 사용한다."""
    return [f"이 업종이 왜 {stage}인가?" if stage else "이 업종의 판정 근거는?", *QUICK_PROMPTS_TAIL]
