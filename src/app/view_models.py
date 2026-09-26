"""Pure presentation helpers for the Streamlit decision-support UI."""
from __future__ import annotations

import json
import re
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

STAGE_DISPLAY = {"우선점검": "우선점검 후보", "추가확인": "추가확인", "관찰": "관찰"}

WORK24_BASIS = {
    "LIST": "업종 매핑된 Work24 목록 전체",
    "ACTIVE_CONFIRMED": "FactoryOn 확인 공고 중 저장된 목록 마감일 기준 유효",
    "DETAIL_VERIFIED": "상세 페이지까지 확인한 공고 · 현재 유효 여부와 별개",
    "DETAIL_COMPANY": "상세 검증 공고의 기업 수",
    "KEYWORD": "공고 제목 기준 빈도 · 공고당 1회 · 모집인원 아님",
}


# 화면 표시용 분기 표기: '2026Q2' → '2026년 2분기'. 저장·조회·위젯 key·파일명은 '2026Q2' 그대로 둔다.
_QUARTER_RE = re.compile(r"(?<![0-9A-Za-z_])(\d{4})Q([1-4])(?![0-9A-Za-z_])")


def quarter_text(text):
    """문장 안의 분기 코드(2026Q2)를 모두 '2026년 2분기'로 바꾼다(backend 문장·AI 답변 표시용). 문자열이 아니면 그대로."""
    return _QUARTER_RE.sub(lambda m: f"{m.group(1)}년 {m.group(2)}분기", text) if isinstance(text, str) else text


def next_quarters(quarter: str, count: int = 8) -> list[str]:
    """quarter 다음 분기부터 count개(저장 형식 '2026Q3'). 다음 검토 분기 선택 목록용."""
    year, _, number = str(quarter).partition("Q")
    y, n, out = int(year), int(number), []
    for _ in range(count):
        y, n = (y + 1, 1) if n == 4 else (y, n + 1)
        out.append(f"{y}Q{n}")
    return out


# KPI 칸에 한 줄로 들어가도록 줄인 Q1 상태 설명(표시만 — 저장된 상태 코드·설명은 그대로)
Q1_KPI_SHORT = {"N": "N · 증감 0 포함", "INVALID": "분류 불가"}


def q1_kpi_value(state: str | None, label: str | None) -> str:
    """'S4 · 생산↓·고용↓'처럼 짧은 것은 그대로, 긴 설명(N·INVALID)은 짧은 표기로."""
    if state in Q1_KPI_SHORT:
        return Q1_KPI_SHORT[state]
    return " · ".join(x for x in (state, label) if x) or "자료 없음"


# Q1 상태의 사용자 언어(README 부록 B의 S1~S4 설명). 화면은 이 표현을 먼저, S코드를 보조로 쓴다(저장값은 그대로).
Q1_PLAIN = {"S1": "생산·고용 동반확대", "S2": "생산확대·고용감소", "S3": "생산감소·고용증가",
            "S4": "생산·고용 동반감소", "N": "증감 0 포함", "INVALID": "분류 불가"}


def q1_plain(state: str | None) -> str:
    return Q1_PLAIN.get(state or "", state or "자료 없음")


# 생산지표 정의(표시용). Triage의 P·Q1 생산 방향은 KICOX 명목 생산액 YoY다(가격 보정 전).
PRODUCTION_LABEL = "명목 생산액 YoY"
YOY_NOTE = "YoY는 전년 동분기 대비 증감률입니다."
NOMINAL_NOTE = ("현재 점검단계에는 명목 생산액 증감률을 사용합니다. 가격변동 효과가 포함될 수 있으므로 "
                "실제 생산물량 변화는 추가 확인이 필요합니다.")


def quarter_label(quarter: str | None) -> str:
    """분기 값 하나의 표시명. 없으면 '—'."""
    return "—" if quarter in (None, "") else quarter_text(str(quarter))


def stage_display(stage: str | None) -> str:
    """Triage 단계 표시명. 등록되지 않은 값은 원문을 그대로, None이면 '판정 없음'."""
    if stage is None:
        return "판정 없음"
    return STAGE_DISPLAY.get(stage, stage)


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
        return "자료 없음" if v != v else f"{v:,.{digits}f}{suffix}"  # NaN은 화면에 노출하지 않는다
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


def _fact_employment(rec: dict) -> str:
    q2 = rec["q2"]
    return (f"고용 {_num(q2.get('employment'), suffix='명')} (전년동기 {_num(q2.get('employment_lag4'), suffix='명')} · "
            f"증감 {_num(q2.get('emp_delta'), suffix='명')} · YoY {_num(q2.get('employment_yoy'), 2, '%')})")


def _fact_production_yoy(rec: dict) -> str:
    return f"생산 YoY {_num(rec['activity'].get('production_yoy'), 1, '%')}"


def _fact_op_rate(rec: dict) -> str:
    act = rec["activity"]
    if act.get("op_rate_official") is not None:
        op_rate = f"{_num(act['op_rate_official'], 1, '%')}"
    else:
        op_rate = f"{_num(act.get('op_rate_approx'), 1, '%')} (근사)"
    return f"가동률 {op_rate}"


def _fact_firms(rec: dict) -> str:
    act = rec["activity"]
    return f"입주/가동 기업 {_num(act.get('firms_in'))} / {_num(act.get('firms_op'))}개"


def _fact_contribution(rec: dict) -> str:
    return f"산단 제조업 순감소 기여율 {_num(rec['q2'].get('contribution_pct'), 2, '%')}"


def _fact_entry_signals(rec: dict) -> str:
    sg = rec["signals"]
    return f"진입신호 개수 · 진입 {_num(sg.get('n_entry'))}건 · 상위 {_num(sg.get('n_up'))}건"


def _fact_q1_state(rec: dict) -> str:
    q1, q3 = rec["q1"], rec["q3"]
    return (f"Q1 상태 {q1.get('state_label') or q1.get('state') or '자료 없음'} · 현재 상태 지속 "
            f"{_num(q3.get('state_run_length'))}분기" + (f" · 전이 {q3['transition']}" if q3.get("transition") else ""))


def fact_items(rec: dict) -> list[str]:
    """등록 Snapshot 값만으로 만든 사실 목록(원인 해석 없음)."""
    return [_fact_employment(rec), _fact_production_yoy(rec), _fact_op_rate(rec), _fact_firms(rec),
            _fact_contribution(rec), _fact_entry_signals(rec), _fact_q1_state(rec)]


def supporting_fact_items(rec: dict) -> list[str]:
    """업종 진단 화면용 축약판 Fact(가동률·입주기업·순감소 기여율) — fact_items와 같은 포맷터를 쓴다.

    생산 YoY는 Q1 카드 sub에, 진입신호 개수는 '왜 ...인가?' 요약 줄에 이미 표시되므로 여기서는 뺀다.
    """
    return [_fact_op_rate(rec), _fact_firms(rec), _fact_contribution(rec)]


# review_required = 생산 YoY ±40% 또는 고용 YoY ±15% 초과, 또는 업종분류 비교 위험(core 전처리 경고 플래그)
REVIEW_REQUIRED_LABEL = "원자료 확인 필요(생산·고용 YoY 급변 또는 업종분류 비교 위험 표시)"


def data_quality_flags(rec: dict) -> list[str]:
    """자료 품질 표시(caveat_items의 자료 품질 부분만) — 원인 미판정 문구·범위·재구성 메모는 제외."""
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
        items.append(REVIEW_REQUIRED_LABEL)
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
    return items


def caveat_items(rec: dict, provenance: dict | None, scope: str | None) -> list[str]:
    """기존 '미확인·확인 필요' 탭 로직을 그대로 옮긴 한계 목록."""
    items = list(data_quality_flags(rec))
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


COPILOT_STAGE_QUESTION = {"우선점검": "왜 우선점검 후보인가요?", "추가확인": "왜 추가확인 상태인가요?",
                         "관찰": "왜 관찰 상태인가요?"}


# 추천 질문 버튼의 짧은 표시명(버튼 한 줄에 맞춤). 누르면 보내는 질문은 원문 그대로 — 라우팅·답변은 바뀌지 않는다.
CHIP_LABELS = {
    "왜 우선점검 후보인가요?": "우선점검 이유", "왜 추가확인 상태인가요?": "추가확인 이유", "왜 관찰 상태인가요?": "관찰 판정 이유",
    "이 업종의 판정 근거는?": "판정 근거", "현장에서 무엇을 확인해야 하나요?": "현장 확인 사항",
    "최근 채용 신호는 어떤가요?": "최근 채용 신호", "연결 가능한 공식 지원은?": "지원제도 검토",
    "현재 신청 가능한 지원사업은?": "모집 중 공고", "직전 분기 대비 최근 판정 변화는?": "분기 대비 변화",
    "검토 가능한 지원 기능 후보는?": "지원 기능 후보", "이 판정의 한계는?": "판정의 한계",
    "공모전 팀 제안에는 어떤 내용이 있어?": "팀 제안 요약", "조기경보 제안은 어떻게 작동해?": "조기경보 작동",
    "기업 조기진단의 기대효과는?": "조기진단 효과", "정책 성과는 어떤 지표로 확인해?": "정책 성과 지표",
    "공식 지원사업과 팀 제안은 뭐가 달라?": "공식 vs 팀 제안",
    "현재 남은 점검 절차는?": "남은 점검 절차", "현장확인 결과를 요약해줘": "현장확인 요약",
    "인계 전에 확인할 사항은?": "인계 전 확인", "이 점검 건의 판정 근거는?": "판정 근거",
}
# 점검 건 상세에서의 추천 질문 — 앞의 셋은 저장된 점검 기록 요약(입력·선택·결정을 대신하지 않음), 마지막은 등록 진단 경로
CASE_SUGGESTIONS = ("현재 남은 점검 절차는?", "현장확인 결과를 요약해줘", "인계 전에 확인할 사항은?", "이 점검 건의 판정 근거는?")


def chip_label(question: str) -> str:
    return CHIP_LABELS.get(question, question)


def copilot_suggestions(stage: str | None) -> tuple[list[str], list[str]]:
    """Copilot 제안 질문 — (기본 4개, 더보기 3개). 라우팅 키워드는 quick_prompts와 같은 의도를 유지한다."""
    primary = [COPILOT_STAGE_QUESTION.get(stage, "이 업종의 판정 근거는?"), "현장에서 무엇을 확인해야 하나요?",
              "최근 채용 신호는 어떤가요?", "연결 가능한 공식 지원은?"]
    more = ["현재 신청 가능한 지원사업은?", "직전 분기 대비 최근 판정 변화는?", "검토 가능한 지원 기능 후보는?",
            "이 판정의 한계는?"]
    return primary, more


# ------------------------------------------------------------------ 신규 헬퍼(UI 리스트럭처)
SIGNAL_EXPLANATION_TITLE = {"E": "고용 감소율", "R": "산단평균 대비 열위", "A": "산단 대비 감소규모"}


def signal_explanation(rows: list[dict], signals: dict, p_title: str = "생산 감소 (보강)") -> dict:
    """"왜 {단계}인가?" 카드용 근거. rule_evidence_rows() 값만 재구성하고 새로 계산하지 않는다.

    E/R/A는 판정과 무관하게 항상 표시하고(모든 단계에서 같은 구조), P·반복 진입신호는 보강 기준을
    충족했을 때만 덧붙인다. summary는 등록된 n_entry/n_up 신호 개수를 그대로 옮긴다.
    p_title = P 카드 제목(화면은 '명목 생산 감소 (보강)'으로 생산지표 정의를 드러낸다).
    """
    items: list[dict] = []
    for code in ("E", "R", "A"):
        row = next((r for r in rows if (r.get("signal") or "").startswith(code)), None)
        if row is None:
            continue
        verdict = row.get("verdict")
        if verdict == "상위":
            rule, tone = f"상위경계 {row.get('upper_threshold')} 통과", "rose"
        elif verdict == "진입":
            rule, tone = f"진입경계 {row.get('entry_threshold')} 통과", "amber"
        elif verdict == "미달":
            rule, tone = f"진입경계 {row.get('entry_threshold')} 미달", "muted"
        else:
            rule, tone = "판정 자료 미확인", "muted"
        items.append({"title": SIGNAL_EXPLANATION_TITLE[code], "value": row.get("current"),
                      "rule": rule, "tone": tone})
    p_row = next((r for r in rows if (r.get("signal") or "").startswith("P ")), None)
    if p_row and p_row.get("verdict") == "충족":
        items.append({"title": p_title, "value": p_row.get("current"),
                      "rule": f"보강 기준 {p_row.get('entry_threshold')} 충족", "tone": "amber"})
    rep_row = next((r for r in rows if (r.get("signal") or "").startswith("반복 진입신호")), None)
    if rep_row and rep_row.get("verdict") == "충족":
        items.append({"title": "지속성 (보강)", "value": "연속 진입신호",
                      "rule": "반복 진입신호 충족", "tone": "amber"})
    summary = f"진입신호 {_num(signals.get('n_entry'))}건 · 상위신호 {_num(signals.get('n_up'))}건"
    return {"items": items[:5], "summary": summary}


# 현장 확인 질문 표시용 어미 통일(원문은 backend·Snapshot 그대로, 화면에서만 '~ 확인' 체크리스트 문체로 바꾼다)
_CHECK_ENDINGS = (
    ("확인했습니까?", "확인"), ("했습니까?", "했는지 확인"), ("였습니까?", "였는지 확인"), ("입니까?", "인지 확인"), ("있습니까?", "있는지 확인"),
    ("없습니까?", "없는지 확인"), ("합니까?", "한지 확인"), ("습니까?", "는지 확인"),
    ("확인할 필요가 있다", "확인"), ("할 필요가 있다", ""), ("확인한다", "확인"), ("할 수 없다", "할 수 없음"),
    ("아니다", "아님"), ("않는다", "않음"), ("나타난다", "나타남"), ("다르다", "다름"),
    ("이다", "임"), ("있다", "있음"), ("없다", "없음"), ("한다", "함"),
)
_TRAILING_NOTE = re.compile(r"^(.*?)(\s*\([^()]*\))?$")


def checklist_text(text: str | None) -> str:
    """'…발생했습니까?' / '…확인할 필요가 있다.'처럼 섞인 어미를 '…발생했는지 확인' 형태로 맞춘다. 내용·수치는 그대로."""
    out = []
    for sentence in re.split(r"(?<=[.?])\s+", (text or "").strip()):
        body, note = _TRAILING_NOTE.match(sentence.rstrip(".").strip()).groups()
        body = body.rstrip(".").strip()
        for ending, repl in _CHECK_ENDINGS:
            if body.endswith(ending):
                body = body[: -len(ending)] + repl
                break
        else:
            if body.endswith("?"):
                body = body[:-1] + " 확인"
        out.append(body.rstrip() + (note or ""))
    return ". ".join(x for x in out if x)


def top_questions(questions: list[dict], n: int = 3) -> list[dict]:
    """앞의 n개만 잘라 보여준다. backend 순서(Q1→Q3→WORK24→SNAPSHOT)를 그대로 쓰며 재정렬하지 않는다."""
    return questions[:n]


# ------------------------------------------------------------------ 업종 진단 상단 점검 대기열 · 5초 요약
# 정렬은 등록 판정 단계와 등록 단계 내 순위(rank_in_stage)만 쓴다 — 새 순위 계산식 없음.
QUEUE_GROUP = {"우선점검": 0, "추가확인": 1}  # 2 = 진행 중인 점검이 있는 관찰 업종, 3 = 나머지 관찰
_STAGE_TO = {"우선점검": "우선점검 후보로", "추가확인": "추가확인으로", "관찰": "관찰로"}
_SIGNAL_SHORT = {"E": "고용 감소율", "R": "산단평균 대비 열위", "A": "산단 대비 감소규모"}
OBSERVATION_RANK_HELP = "동일 점검단계 안에서의 비교 순위이며 우선점검 대상 순위를 의미하지 않습니다."
# 진단 → 지원 연계 흐름(업종 진단 지원체계 검토 경로·정책 화면 공용 안내 — 새 라우팅 아님)
LINK_FLOW = ("진단 신호", "현장 확인질문", "검토 지원기능", "정책 원문 RAG", "현재 지원사업·공고", "담당기관·접수 경로")
HANDOVER_NOTICE = "본 문서는 담당자 검토와 인계를 위한 요약자료이며 공식 행정처분 또는 지원대상 확정 문서가 아닙니다."


def pick_case(cases: list[dict], industry: str, quarter: str) -> dict | None:
    """그 업종·분기의 점검 건 — 진행 중(모니터링 포함)을 먼저, 없으면 가장 최근 종결 건(list_cases는 최신순)."""
    mine = [c for c in cases if c.get("industry") == industry and c.get("quarter") == quarter]
    active = [c for c in mine if c.get("status") != "종결"]
    return (active or mine or [None])[0]


def case_status_label(candidate: dict | None, case: dict | None) -> str:
    """점검상태 표시(기록된 값만): 미개설 · 검토 중 · 진행 중 · 인계 · 모니터링 · 종결(점검 건 번호는 표시하지 않음)."""
    if case:
        if case.get("status") == "종결":
            return "종결"
        if case.get("decision") == "인계":
            return "인계"
        return case.get("status") or "진행 중"
    review = (candidate or {}).get("review") or {}
    if review.get("status") == "점검 불필요":
        return "검토 종료(점검 불필요)"
    return review.get("status") or "미개설"


def run_text(q3: dict) -> str:
    n = q3.get("state_run_length")
    return "지속기간 자료 없음" if n is None or n != n else f"{int(n)}분기 연속"


def reason_sentence(rec: dict, rows: list[dict]) -> str:
    """판정 이유 한 문장 — rule_evidence_rows()의 등록 판정(상위·진입·충족)만 옮긴다. 원인 해석 없음."""
    t = rec["triage"]
    stage = t.get("stage")
    parts = []
    for code in ("E", "R", "A"):
        row = next((r for r in rows if (r.get("signal") or "").startswith(code)), None)
        if row and row.get("verdict") in ("상위", "진입"):
            edge, bound = (("상위경계", row.get("upper_threshold")) if row["verdict"] == "상위"
                           else ("진입경계", row.get("entry_threshold")))
            parts.append(f"{_SIGNAL_SHORT[code]} {row.get('current')}({edge} {bound} 통과)")
    extra = []
    p_row = next((r for r in rows if (r.get("signal") or "").startswith("P ")), None)
    if p_row and p_row.get("verdict") == "충족":
        extra.append(f"명목 생산액 감소 {p_row.get('current')}")
    rep_row = next((r for r in rows if (r.get("signal") or "").startswith("반복 진입신호")), None)
    if rep_row and rep_row.get("verdict") == "충족":
        extra.append("직전 분기 반복 진입신호")
    if not parts:
        if stage != "관찰":
            return f"등록 판정 사유: {t.get('stage_reason') or '자료 없음'}"
        text = "점검단계 진입기준을 충족한 고용 신호가 없어 관찰로 분류됐습니다."
        if t.get("prod_only_decline") or (p_row and p_row.get("verdict") == "충족"):
            text += " 명목 생산액 단독 감소는 현장 확인질문에만 반영됐습니다."
        return text
    if stage not in ("우선점검", "추가확인"):
        return f"등록 판정 사유: {t.get('stage_reason') or '자료 없음'}"
    head = " · ".join(parts)
    text = (f"{head}에 보강 신호({' · '.join(extra)})가 더해져 {_STAGE_TO[stage]} 분류됐습니다." if extra
            else f"{head} 신호가 확인되어 {_STAGE_TO[stage]} 분류됐습니다.")
    if t.get("scale_flag"):
        text += f" 규모 기준: {t['scale_flag']}."
    if t.get("data_quality_minimum_only"):
        text += " 확인 가능한 신호에 따른 최소판정입니다."
    return text


_SIGNAL_PLAIN = {"E": "고용 감소율", "R": "산단 평균 대비 감소", "A": "고용 감소 규모"}
_STAGE_IS = {"우선점검": "우선점검 후보입니다", "추가확인": "추가확인 단계입니다", "관찰": "관찰 단계입니다"}


def reason_summary(rec: dict, rows: list[dict]) -> str:
    """대기열용 짧은 판정 이유 — 어떤 신호가 기준을 넘었는지만(수치·경계값은 진단카드 판정 근거에서 본다)."""
    stage = rec["triage"].get("stage")
    met = [_SIGNAL_PLAIN[c] for c in ("E", "R", "A")
           if any((r.get("signal") or "").startswith(c) and r.get("verdict") in ("상위", "진입") for r in rows)]
    extra = [name for prefix, name in (("P ", "생산 감소"), ("반복 진입신호", "2분기 연속 신호"))
             if any((r.get("signal") or "").startswith(prefix) and r.get("verdict") == "충족" for r in rows)]
    tail = _STAGE_IS.get(stage, f"{stage_display(stage)}입니다")
    if rec["triage"].get("scale_flag"):  # 규모 gate로 우선점검이 아닌 경우를 문장에 드러낸다
        tail = tail.removesuffix("입니다") + f"입니다({rec['triage']['scale_flag']})"
    if not met:
        return f"고용 신호가 기준에 못 미쳐 {tail}." if stage == "관찰" else reason_sentence(rec, rows)
    last = met[-1][-1]
    josa = "이" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "가"  # 받침 있으면 '이', 없으면 '가'
    subject = f"{'·'.join(met)}{josa}"
    return (f"{subject} 기준을 넘고 {'·'.join(extra)}도 확인돼 {tail}." if extra
            else f"{subject} 기준을 넘어 {tail}.")


def next_action(stage: str | None, status: str, next_review: str | None) -> str:
    """다음 조치 한 줄 — 등록 단계와 기록된 점검상태만으로 정한다(새 판단 없음)."""
    if status in ("진행 중", "인계", "모니터링"):
        return "진행 중인 점검 건 확인" + ("" if status == "진행 중" else f" · {status}")
    if status == "종결":
        return f"종결된 점검 건 기록 확인 · 다음 검토 {quarter_label(next_review)}"
    if stage in ("우선점검", "추가확인"):
        return "점검 개설 · 현재 점검 미개설" if status == "미개설" else f"점검 후보 검토 · {status}"
    return f"정기 모니터링 · 다음 검토 {quarter_label(next_review)}"


def queue_rows(records: list[dict], candidates: list[dict], cases: list[dict], rules: dict[str, dict]) -> list[dict]:
    """선택 분기의 점검 대기열: 우선점검 후보 → 추가확인 → 진행 중인 점검(관찰) → 관찰, 같은 묶음은 등록 단계 내 순위."""
    cand = {c["industry"]: c for c in candidates}
    out = []
    for r in records:
        t, q1, q2, q3 = r["triage"], r["q1"], r["q2"], r["q3"]
        case = pick_case(cases, r["industry"], r["quarter"])
        status = case_status_label(cand.get(r["industry"]), case)
        active = case is not None and case.get("status") != "종결"
        stage = t.get("stage")
        out.append({
            "industry": r["industry"], "quarter": r["quarter"], "stage": stage, "display": stage_display(stage),
            "group": QUEUE_GROUP.get(stage, 2 if active else 3), "rank": t.get("rank_in_stage"),
            "state": q1.get("state"), "state_plain": q1_plain(q1.get("state")),
            "emp_delta": _num(q2.get("emp_delta"), suffix="명"), "emp_yoy": _num(q2.get("employment_yoy"), 2, "%"),
            "share": _num(q2.get("employment_share_pct"), 2, "%"), "run": run_text(q3),
            "transition": q3.get("transition") or "전환 자료 없음",
            "reason": reason_sentence(r, rule_evidence_rows(r, rules)),
            "summary": reason_summary(r, rule_evidence_rows(r, rules)), "status": status,
            "case_id": case["id"] if active else None,
            "next_review": t.get("next_review_quarter"),
        })
    return sorted(out, key=lambda x: (x["group"], x["rank"] if isinstance(x["rank"], int) else 999, x["industry"]))


def rank_text(stage: str | None, rank) -> str:
    """단계 내 순위 표시 — 관찰은 우선점검 순위로 읽히지 않게 '참고 순위'로 쓴다."""
    if not isinstance(rank, int):
        return "단계 내 순위 자료 없음"
    if stage == "관찰":
        return f"관찰 단계 내 참고 순위 {rank}위"
    return f"{stage_display(stage)} 단계 내 {rank}순위"


# ------------------------------------------------------------------ 점검 관리 · 진행 중 점검 상세(저장된 기록만 읽는 진행 요약)
CASE_SUBVIEWS = ("점검 요약", "현장 확인", "지원 검토·결정", "인계·재점검")
CHECK_RESULT_ORDER = ("확인", "부분 확인", "미확인", "반대증거")
# 현장확인 결과 표시명(저장값은 그대로) — '반대증거'는 뜻이 바로 읽히지 않아 화면에서만 풀어 쓴다
CHECK_RESULT_DISPLAY = {"반대증거": "반대 사실 확인"}
CHECK_RESULT_HELP = ("확인: 질문 내용이 사실로 확인됨 · 부분 확인: 일부만 사실로 확인됨 · 미확인: 확인하지 못함 · "
                     "반대 사실 확인: 질문과 반대되는 사실이 확인됨(예: 감원·휴업이 실제로는 없었음)")


def check_result_label(code: str | None) -> str:
    return CHECK_RESULT_DISPLAY.get(code or "", code or "—")


def case_progress(case: dict, label_of=None) -> dict:
    """진행 요약·다음 할 일 — get_case() 결과만 읽어 계산한다(DB에 진행률을 따로 저장하지 않음, 상태를 바꾸지 않음).

    next = (다음 할 일 문장, 이동할 하위 화면, 버튼 이름). 버튼은 화면 이동만 하며 저장·상태변경을 하지 않는다.
    """
    label_of = label_of or (lambda tag: tag)
    closed = case.get("status") == "종결"
    cur = case.get("current_scope") or {}
    checks = cur.get("checks") or []
    done = [i for i in checks if i.get("latest")]
    counts = {code: 0 for code in CHECK_RESULT_ORDER}
    for item in done:
        code = item["latest"].get("result_code")
        counts[code] = counts.get(code, 0) + 1
    need = cur.get("support_needs")
    if need is None:
        support = "미선택"
    else:
        support = ", ".join(label_of(t) for t in need.get("function_tags") or []) or "선택 없음(기록됨)"
    decisions = cur.get("decisions") or []
    decision = decisions[-1]["decision"] if decisions else None
    referrals = case.get("referrals") or []
    active = [r for r in referrals if r.get("status") != "종결"]
    nrq = case.get("next_review_quarter")
    if closed:
        nxt = ("종결된 점검 건입니다. 기록은 읽기 전용으로 확인할 수 있습니다.", "점검 요약", "점검 요약 보기")
    elif not done:
        nxt = ("첫 번째 현장확인 결과를 기록하세요.", "현장 확인", "현장 확인 계속")
    elif len(done) < len(checks):
        nxt = (f"남은 현장확인 {len(checks) - len(done)}건을 기록하세요.", "현장 확인", "현장 확인 계속")
    elif need is None:
        nxt = ("현장확인 결과를 검토하고 필요한 지원기능을 선택하세요.", "지원 검토·결정", "지원기능 검토")
    elif not decisions:
        nxt = ("점검 결과와 지원 필요성을 바탕으로 결정을 기록하세요.", "지원 검토·결정", "결정 기록")
    elif decision == "인계" and active:
        nxt = ("인계 발송·접수·회신 상태를 기록하세요.", "인계·재점검", "인계 상태 기록")
    elif nrq:
        nxt = (f"{quarter_label(nrq)} 재점검을 준비하세요.", "인계·재점검", "재점검 확인")
    else:
        nxt = ("기록된 결정을 확인하세요.", "지원 검토·결정", "결정 확인")
    return {
        "closed": closed, "total": len(checks), "done": len(done), "counts": counts,
        "unrecorded": len(checks) - len(done), "support": support, "support_recorded": need is not None,
        "decision": decision or "미기록", "referrals": len(referrals), "active_referrals": len(active),
        "referral_text": (f"{len(referrals)}건 · 진행 중 {len(active)}건" if referrals else "없음"),
        "next_review": quarter_label(nrq) if nrq else "미정",
        "next": nxt,
    }


# 종결 점검 건 — 하위 화면은 안정적인 ID로 두고 표시 이름만 바꾼다(예전 case_tab 이름도 받아들인다)
CLOSED_SUBVIEWS = {"closed_summary": "종결 요약", "closed_checks": "현장확인 기록",
                   "closed_support_decisions": "지원·결정 기록", "closed_referrals_history": "인계·변경 기록"}
CLOSED_TAB_ALIAS = {"점검 요약": "closed_summary", "현장 확인": "closed_checks", "지원 검토·결정": "closed_support_decisions",
                    "인계·재점검": "closed_referrals_history", **{v: k for k, v in CLOSED_SUBVIEWS.items()}}


def closed_subview_id(value: str | None) -> str:
    """URL·세션의 case_tab 값을 종결 하위 화면 ID로(ID·표시 이름·예전 이름 모두 허용, 그 밖은 종결 요약)."""
    if value in CLOSED_SUBVIEWS:
        return value
    return CLOSED_TAB_ALIAS.get(value or "", "closed_summary")


def closed_case_vm(case: dict, label_of=None) -> dict:
    """종결 점검 건 표시값 — get_case() 결과만 읽는다. 최종 결정/이전 결정 구분, 후속 검토는 저장값만(없으면 '해당 없음 · 종결').

    '기록된 지원 필요 기능'은 담당자의 검토 기록이며 지원 완료·인계를 뜻하지 않는다. 인계 기록이 없으면 '인계 기록 없음'으로만 쓴다.
    """
    label_of = label_of or (lambda tag: tag)
    scopes = case.get("scopes") or []
    last = scopes[-1] if scopes else {}
    decisions = list(case.get("decisions") or [])
    final = next((d for d in reversed(decisions) if d.get("decision") == "종결"), decisions[-1] if decisions else None)
    previous = [d for d in decisions if d is not final]
    checks = last.get("checks") or []
    done = [i for i in checks if i.get("latest")]
    counts = {code: 0 for code in CHECK_RESULT_ORDER}
    for item in done:
        code = item["latest"].get("result_code")
        counts[code] = counts.get(code, 0) + 1
    need = last.get("support_needs")
    tags = list((need or {}).get("function_tags") or [])
    referrals = case.get("referrals") or []
    reason = str(case.get("closing_note") or "").strip() or "기록 없음"
    return {
        "final": final, "previous": previous, "decision_count": len(decisions),
        "final_decision": (final or {}).get("decision") or "기록 없음", "closing_note": reason,
        "closed_by": case.get("closed_by") or "미지정", "closed_at": case.get("closed_at"),
        "assignee": case.get("assignee") or "미지정",
        "done": len(done), "total": len(checks), "counts": counts,
        "counts_text": " · ".join(f"{check_result_label(k)} {v}건" for k, v in counts.items()),
        "support": ", ".join(label_of(t) for t in tags) or ("선택 없음(기록됨)" if need else "기록 없음"),
        "support_count": len(tags),
        "referral_text": f"{len(referrals)}건" if referrals else "인계 기록 없음",
        "followup": quarter_label(case["next_review_quarter"]) if case.get("next_review_quarter") else "해당 없음 · 종결",
        "rounds": len(scopes),
    }


def closed_case_timeline(case: dict) -> list[tuple[str, str, str]]:
    """처리 흐름 — 저장된 이벤트만(개설 · 재점검 시작 · 현장확인 기록 · 결정). (시각 ISO, 단계, 내용), 시간순. 누락 단계를 추정하지 않는다."""
    events = [(case.get("opened_at") or "", "점검 개설", f"{case.get('origin') or ''}에서 개설".strip())]
    for sc in case.get("scopes") or []:
        title = f"{quarter_label(sc.get('quarter'))} {sc.get('review_kind') or ''}".strip()
        if sc.get("review_kind") == "재점검":
            events.append((sc.get("started_at") or "", "재점검 시작", title))
        latest = [i["latest"] for i in sc.get("checks") or [] if i.get("latest")]
        if latest:
            events.append((max(str(r.get("recorded_at") or "") for r in latest), "현장확인 기록",
                           f"{len(latest)}/{len(sc.get('checks') or [])}건 · {title}"))
    for d in case.get("decisions") or []:
        detail = (f"다음 검토 {quarter_label(d['next_review_quarter'])} (결정 당시)"
                  if d.get("next_review_quarter") else ("점검 건 종결" if d.get("decision") == "종결" else ""))
        events.append((d.get("decided_at") or "", f"{d.get('decision')} 결정", detail))
    return sorted((e for e in events if e[0]), key=lambda e: str(e[0]))


def default_check_position(checks: list[dict]) -> int | None:
    """기록할 문항 기본값: 첫 번째 미기록 문항 → 모두 기록됐으면 가장 최근에 기록한 문항."""
    if not checks:
        return None
    pending = [i for i in checks if not i.get("latest")]
    if pending:
        return pending[0]["position"]
    return max(checks, key=lambda i: str(i["latest"].get("recorded_at") or ""))["position"]


# ------------------------------------------------------------------ 담당자 인계용 진단 요약(진단서) ViewModel
REPORT_TYPES = ("요약본 · 1페이지", "상세본 · 요약 + 근거 부록")
REPORT_NOTICE = "담당자 검토·인계용 자료이며 행정처분 또는 지원대상 확정 문서가 아닙니다."
_RULE_ROLE = {"상위": "상위신호", "진입": "진입신호", "미달": "미충족", "미확인": "미확인"}


def _evidence_role(row: dict) -> str:
    sig, verdict = row.get("signal") or "", row.get("verdict")
    if sig.startswith(("P ", "반복")):
        return "보강근거" if verdict == "충족" else ("미확인" if verdict == "미확인" else "보강 미충족")
    if sig.startswith("규모"):
        return "규모 기준 " + ("통과" if verdict == "통과" else verdict or "미확인")
    return _RULE_ROLE.get(verdict, verdict or "미확인")


def build_report_vm(payload: dict, rec: dict | None, rows: list[dict], *, fn_label, case: dict | None = None,
                    institutions: dict[str, list[dict]] | None = None, doc_titles: dict | None = None,
                    snapshot_label: str = "", nature: str = "", population_note: str = "") -> dict:
    """진단서 표시용 값 — payload·등록 Snapshot·점검 건 기록(get_case 결과)만 읽는다. 판정·상태를 다시 계산하거나 저장하지 않는다.

    구분: 지원기능 '검토 후보'(채용 키워드·확인 신호) vs '담당자 선택'(점검 건 support_needs) / 담당기관 확인(verified) vs
    접수경로 확인 / '다음 검토'(점검 건에 저장된 값) vs '권고 검토분기'(등록 판정 규칙 값) / 판정근거 vs 보조자료.
    """
    institutions = institutions or {}
    t = (rec or {}).get("triage") or {}
    q1, q2, q3 = ((rec or {}).get(k) or {} for k in ("q1", "q2", "q3"))
    stage = t.get("stage") or (payload.get("triage") or {}).get("stage")
    questions = (payload.get("field_checks") or {}).get("questions") or []

    # 현장확인 — 점검 건이 있으면 그 기록, 없으면 이 세션의 체크·입력(영구 저장 아님)
    cur = None
    if case:
        cur = case["current_scope"] if case.get("status") != "종결" else case["scopes"][-1]
    case_results = {i["question_text"]: i["latest"] for i in (cur or {}).get("checks") or [] if i.get("latest")}
    session = {r["question"]: r for r in ((payload.get("field_checks") or {}).get("session_context") or {}).get("responses", [])
               if r.get("checked") or r.get("answer")}
    if cur is not None:
        total, done, basis = len(cur.get("checks") or []), len(case_results), "점검 건 기록"
    else:
        total, done, basis = len(questions), len(session), "현재 세션 입력"
    field_text = f"{done}/{total}건" + (" · 입력 없음" if not done else f" · {basis}")

    # 지원 검토 — 후보(payload)와 담당자 선택(점검 건) 구분, 담당기관은 verified 후보만
    candidates = [f["function_tag"] for f in payload.get("support_functions") or []]
    need = (cur or {}).get("support_needs")
    selected = list(need.get("function_tags") or []) if need else []
    cards = payload.get("requirement_cards") or []
    card_count = {tag: sum(1 for c in cards if c.get("function_tag") == tag) for tag in candidates}
    referrals = (case or {}).get("referrals") or []
    fn_rows = []
    for tag in list(dict.fromkeys([*selected, *candidates])):
        cands = institutions.get(tag) or []
        ref = [r for r in referrals if r.get("function_tag") == tag]
        fn_rows.append({
            "label": fn_label(tag), "status": "담당자 선택" if tag in selected else "후보",
            "cards": card_count.get(tag), "institutions": ", ".join(dict.fromkeys(c["institution"] for c in cands)),
            "intake": ("접수경로 확인" if cands and all(c.get("intake_route_verified") for c in cands)
                       else ("접수경로 미확인" if cands else "—")),
            "referral": (f"인계 기록 · {ref[-1]['status']}" if ref else "인계 없음"),
            "confirmed": bool(cands),
        })
    confirmed = [f"{r['label']} — {r['institutions']}" for r in fn_rows if r["confirmed"]]
    unmapped = [r["label"] for r in fn_rows if not r["confirmed"]]
    need_check = []
    if any(r["confirmed"] and r["intake"] == "접수경로 미확인" for r in fn_rows):
        need_check.append("실제 접수경로")
    if unmapped:
        need_check.append(f"담당기관 미확정 기능({'·'.join(unmapped)})의 담당기관")

    # 다음 검토 — 저장값과 규칙상 권고값 구분
    if case and case.get("next_review_quarter"):
        review = ("다음 검토", quarter_label(case["next_review_quarter"]))
    elif t.get("next_review_quarter"):
        review = ("권고 검토분기", f"{quarter_label(t['next_review_quarter'])} (등록 판정 규칙)")
    else:
        review = ("다음 검토", "미정")

    priority = checklist_text(((rec or {}).get("questions") or {}).get("check_question")) or None
    if case:
        next_text = case_progress(case, fn_label)["next"][0]
    elif priority:
        next_text = f"점검 개설 검토 · 우선 확인: {priority}"
    else:
        next_text = "점검 개설 검토"

    jobs = payload.get("recruitment_snapshot") or {}
    levels = {lv.get("key"): lv for lv in jobs.get("evidence_levels") or []}
    keywords = [(k["term"], k["count"]) for k in (payload.get("recruitment_keywords") or {}).get("keywords") or []]

    def level(key, field="count"):
        return (levels.get(key) or {}).get(field)

    production = q1.get("production_yoy")
    kpis = [
        ("산업·고용 상태", q1_plain(q1.get("state")), q1.get("state") or "—"),
        ("고용 영향", _num(q2.get("emp_delta"), suffix="명"), f"전년 동분기 대비 {_num(q2.get('employment_yoy'), 2, '%')}"),
        ("산단 고용 비중", _num(q2.get("employment_share_pct"), 2, "%"), f"고용 {_num(q2.get('employment'), suffix='명')}"),
        ("지속·전환", run_text(q3) if rec else "자료 없음", (q3.get("transition") or "전환 자료 없음").replace(" → ", "→")),
    ]

    # 부록 B — 현장 확인문항 원문 전체(출처 메타데이터만 사용)
    question_rows = []
    for i, item in enumerate(questions, 1):
        latest = case_results.get(item["question"])
        sess = session.get(item["question"])
        if latest:
            result = f"{check_result_label(latest.get('result_code'))} · {latest.get('method') or ''}".strip(" ·")
        elif sess:
            result = sess.get("answer") or "확인 표시(세션)"
        else:
            result = ""
        question_rows.append({"no": i, "text": item["question"], "source": item.get("source") or "", "result": result})

    sources = []
    for s in payload.get("official_sources") or []:
        title = (doc_titles or {}).get(s.get("document_id")) or s.get("document_id")
        if title and s.get("source_url"):
            sources.append((f"{title} (확인 {s.get('verified_at') or '—'})", s["source_url"]))
    limits = [x for x in [
        f"자료 기준일 {payload.get('basis_date')}" if payload.get("basis_date") else "",
        f"분석본 {snapshot_label}" if snapshot_label else "", nature,
        "생산지표는 가격변동 효과가 포함될 수 있는 명목 생산액입니다. 실제 생산물량 변화는 추가 확인이 필요합니다.",
        YOY_NOTE, population_note,
        *[quarter_text(c) for c in payload.get("caveat") or []],
    ] if x and str(x).strip()]

    return {
        "industry": payload["industry"], "quarter": quarter_label(payload["quarter"]),
        "stage": stage, "stage_display": stage_display(stage),
        "case_status": (case or {}).get("status") or "점검 미개설", "assignee": (case or {}).get("assignee") or "미배정",
        "field_text": field_text, "field_done": done, "field_total": total,
        "reason": reason_summary(rec, rows) if rec else "등록 진단 없음",
        "production": ("명목 생산액 미확인" if production is None else f"명목 생산액 전년 동분기 대비 {_num(production, 1, '%')}"),
        "kpis": kpis, "review": review,
        "decision": ((cur or {}).get("decisions") or [{}])[-1].get("decision") or "미결정",
        "referral_text": (f"{len(referrals)}건" if referrals else "없음"),
        "next_action": next_text,
        "priority": priority, "question_total": len(questions),
        "more_questions": max(len(questions) - (1 if priority else 0), 0),
        "candidates": [fn_label(tg) for tg in candidates], "selected": [fn_label(tg) for tg in selected],
        "confirmed": confirmed, "need_check": need_check, "fn_rows": fn_rows,
        "jobs_found": jobs.get("status") == "FOUND", "jobs_quarter": quarter_label(jobs.get("quarter")),
        "jobs_counts": {"목록": level("LIST"), "현재 유효": level("ACTIVE_CONFIRMED"),
                        "상세 검증": level("DETAIL_VERIFIED"), "확인 기업": level("DETAIL_VERIFIED", "company_count")},
        "keywords_top": keywords[:3], "keywords_all": keywords,
        "rule_rows": [{**r, "role": _evidence_role(r)} for r in rows],
        "rule_summary": (f"진입신호 {_num((rec or {}).get('signals', {}).get('n_entry'))}건 · "
                         f"상위신호 {_num((rec or {}).get('signals', {}).get('n_up'))}건 → 등록 판정 {stage_display(stage)}"),
        "question_rows": question_rows, "any_results": any(r["result"] for r in question_rows),
        "cards": cards, "sources": sources, "limits": list(dict.fromkeys(limits)),
        "basis": [x for x in (f"자료 기준일 {payload.get('basis_date')}" if payload.get("basis_date") else "",
                              nature) if x],
    }


# ------------------------------------------------------------------ 정책 근거 위치 · 담당기관 검증상태(등록 값만)
_GENERIC_SECTION = re.compile(r"^(section-\d+|p\.\s*\d+|본문|첨부파일|회원로그인|로그인)$", re.I)
PROVENANCE_MISSING = "공식 근거 위치 상세 미등록"


def provenance_lines(card: dict, doc_title: str | None = None) -> list[str]:
    """요건 카드의 근거 위치 — 등록된 쪽·절만 문서명과 함께. 의미 없는 추출 머리글은 쓰지 않고, 없으면 '미등록'."""
    head = doc_title or (f"공식문서 {card['document_id']}" if card.get("document_id") else "공식문서")
    lines = []
    for p in card.get("provenance") or []:
        section = str(p.get("section") or "").strip()
        if p.get("page"):
            lines.append(f"{head} {p['page']}쪽")
        elif section and not _GENERIC_SECTION.match(section):
            lines.append(f"{head} · {section}")
    return list(dict.fromkeys(lines)) or [PROVENANCE_MISSING]


def institution_status_text(candidates: list[dict]) -> str:
    """지원 기능 1개의 담당기관 검증상태. 카탈로그·등록부의 verified 후보만 담당기관으로 적는다(기관을 새로 확정하지 않음)."""
    if not candidates:
        return "담당기관 미확정 · 실제 인계 전 담당기관 확인 필요"
    names = ", ".join(dict.fromkeys(c["institution"] for c in candidates))
    route = ("접수경로 확인됨" if all(c.get("intake_route_verified") for c in candidates)
             else "실제 접수경로 미확인")
    return f"담당기관 확인 · {names} ({route})"


INSTITUTION_AUDIT_LABEL = {
    "verified": "담당기관 확인 · 기관 기능 확인, 실제 접수경로 미확인",
    "proposed": "관련기관 · 담당기관 추가 확인 필요",
    "rejected": "관련기관 참고 · 인계 대상 아님",
}


def institution_audit_label(entry: dict | None) -> str:
    if not entry:
        return "관련기관 참고 · 실제 인계 전 담당기관 확인 필요"
    label = INSTITUTION_AUDIT_LABEL.get(entry.get("status"), "관련기관 참고 · 실제 인계 전 담당기관 확인 필요")
    if entry.get("status") == "verified" and entry.get("intake_route_verified"):
        label = "담당기관 확인 · 기관 기능·접수경로 확인"
    return label


# ------------------------------------------------------------------ AI 패널 이름(설정 상태와 일치)
def assistant_labels(llm_available: bool) -> tuple[str, str]:
    """(패널 이름, 응답 방식). Gemini가 설정되지 않으면 생성형 AI처럼 보이지 않게 '규칙 기반'으로 표시한다."""
    if llm_available:
        return "행정 AI 비서", ""  # 설정된 경우는 이름만(응답 방식 표시 없음)
    return "진단 근거 도우미", "규칙 기반 응답"


def function_card_counts(functions: list[dict], cards: list[dict]) -> dict[str, int]:
    """기능별 등록된 공식 요건 카드 개수(카드 자체는 재계산하지 않고 세기만 한다)."""
    counts = {f["function_tag"]: 0 for f in functions}
    for card in cards:
        tag = card.get("function_tag")
        if tag in counts:
            counts[tag] += 1
    return counts


def recruitment_observations(jobs: dict, keywords: list[dict]) -> list[str]:
    """'관찰된 표현' 목록 — 등록된 키워드·경력분포 값만으로 만들고 해석하지 않는다."""
    obs: list[str] = []
    if len(keywords) >= 2:
        obs.append(f"공고 제목에서 {keywords[0]['term']}·{keywords[1]['term']} 표현이 반복적으로 확인됨")
    career_n = (jobs.get("career_distribution") or {}).get("경력")
    if career_n:
        obs.append(f"경력 요구 공고 {career_n}건 관찰 (목록 기준)")
    obs.append("실제 인력부족 여부는 현장 확인 필요")
    return obs


def evidence_level(jobs: dict, key: str) -> dict | None:
    """evidence_levels 목록에서 key(ACTIVE_CONFIRMED/DETAIL_VERIFIED 등)로 하나 찾는다."""
    for lv in jobs.get("evidence_levels") or []:
        if lv.get("key") == key:
            return lv
    return None


# ------------------------------------------------------------------ 행정 AI 비서 답변 표시(내용·수치는 바꾸지 않음)
COPILOT_ICONS = ("🔎", "📋", "💼", "🏛")  # 기본 추천 질문 4개의 버튼 라벨에만 붙인다(보내는 질문은 원문)
_NEXT_HINTS = ("현장 확인", "확인이 필요", "확인하세요", "확인해야")
_SENTENCE_END = re.compile(r"(?<=[다요])\.\s+|(?<=[.?!])\s+(?=[가-힣A-Za-z0-9‘'\"(])")


def structure_answer(text: str) -> dict:
    """backend 답변 문자열을 결론 → 근거 → 다음 확인으로 '나눠' 보여주기 위한 구조. 문장·수치는 그대로다.

    줄바꿈이 있는 답변(목록·공고 등)은 첫 줄을 결론, 나머지 줄을 근거로 쓰고, 한 문단 답변은 문장 단위로 나눈다.
    """
    text = (text or "").replace("**", "").strip()  # LLM 답변의 markdown 굵게 표시만 걷어낸다(문장·수치는 그대로)
    if not text:
        return {"conclusion": "", "points": [], "next": []}
    if "\n" in text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        conclusion, rest = lines[0], [re.sub(r"^[-*•]\s*", "", ln) for ln in lines[1:]]
        return {"conclusion": conclusion, "points": rest, "next": []}
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    sentences = [s if s.endswith((".", "?", "!")) else s + "." for s in sentences]
    conclusion, rest = sentences[0], sentences[1:]
    points = [s for s in rest if not any(h in s for h in _NEXT_HINTS)]
    nxt = [s for s in rest if any(h in s for h in _NEXT_HINTS)]
    return {"conclusion": conclusion, "points": points[:4], "next": nxt}


COMPARE_SHORT = {"E": "감소율", "R": "산단평균 대비 열위", "A": "감소 규모", "P": "생산 감소", "반복": "반복성"}


def _triggered(rows: list[dict]) -> list[tuple[str, dict]]:
    """판정 근거 행 중 기준을 넘은 신호(상위·진입·충족)만 (코드, 행)으로. 규모 gate는 제외."""
    out = []
    for row in rows:
        sig = row.get("signal") or ""
        code = "반복" if sig.startswith("반복") else sig[:1]
        if code in COMPARE_SHORT and row.get("verdict") in ("상위", "진입", "충족"):
            out.append((code, row))
    return out


def comparison_view(a: str, rec_a: dict, b: str, rec_b: dict, rules: dict[str, dict]) -> dict:
    """두 업종 비교 표시용 구조 — 등록 Snapshot 값과 판정 행(rule_evidence_rows)만 쓴다. 새 해석·점수 없음."""
    def side(name: str, rec: dict) -> dict:
        rows = rule_evidence_rows(rec, rules)
        q2, sg = rec["q2"], rec["signals"]
        trig = _triggered(rows)
        metrics = [("고용 증감", _num(q2.get("emp_delta"), suffix="명")),
                   ("YoY", _num(q2.get("employment_yoy"), 2, "%")),
                   ("산단 고용 비중", _num(q2.get("employment_share_pct"), 2, "%")),
                   ("E 고용 감소율", _num(sg.get("E"), 2, "%")),
                   ("R 산단평균 대비 열위", _num(sg.get("R"), 2, "%p")),
                   ("A 산단 대비 감소규모", _num(sg.get("A"), 2, "%")),
                   ("P 생산 감소", _num(sg.get("P"), 2, "%"))]
        strong = {"E 고용 감소율": "E", "R 산단평균 대비 열위": "R", "A 산단 대비 감소규모": "A", "P 생산 감소": "P"}
        hit = {c for c, _ in trig}
        notes = []
        for code, row in trig:
            if code == "P":
                notes.append("생산 감소가 보강 신호로 작용")
            elif code == "반복":
                notes.append("직전 분기에도 진입신호가 반복됨")
            else:
                bound = row["upper_threshold"] if row["verdict"] == "상위" else row["entry_threshold"]
                edge = "상위경계" if row["verdict"] == "상위" else "진입경계"
                notes.append(f"{SIGNAL_EXPLANATION_TITLE[code]} {row['current']} · {edge} {bound} 통과")
        return {"name": name, "stage": rec["triage"]["stage"], "display": stage_display(rec["triage"]["stage"]),
                "metrics": [(k, v, strong.get(k) in hit) for k, v in metrics], "notes": notes or ["기준을 넘은 신호 없음"],
                "up": [COMPARE_SHORT[c] for c, r in trig if r["verdict"] == "상위"],
                "short": [COMPARE_SHORT[c] for c, _ in trig]}

    sa, sb = side(a, rec_a), side(b, rec_b)
    if sa["stage"] == sb["stage"]:
        conclusion = (f"둘 다 {sa['display']}입니다. 상위경계를 넘은 신호: {a} {'·'.join(sa['up']) or '없음'} · "
                      f"{b} {'·'.join(sb['up']) or '없음'}.")
    else:
        conclusion = f"{a}는 {sa['display']}, {b}는 {sb['display']}입니다."
    diff = [f"{s['name']} = {' · '.join(s['short']) + ' 신호' if s['short'] else '기준을 넘은 신호 없음'}" for s in (sa, sb)]
    return {"conclusion": conclusion, "sides": [sa, sb], "diff": diff,
            "caveat": "같은 단계라도 신호 구성은 다를 수 있으며, 원인은 이 자료만으로 단정하지 않습니다."}


CONTEXT_HINTS = ("상태", "지금", "채용", "지원", "현장", "판정", "왜", "진단", "점검", "업종")
SCOPE_TEXT = "현재 도우미는 등록된 진단 결과, 현장 확인사항, 채용시장 보조근거와 지원 연계 근거만 설명할 수 있습니다."


def clarification(prompt: str, industry: str, stage: str | None, mentioned: tuple[str, ...]) -> dict:
    """backend가 '지원 범위 밖'(UNSUPPORTED)으로 답한 질문의 화면 표시.

    현재 업종·분기 맥락과 관련된 짧은 질문이면 되묻고(clarify), 무관한 질문이면 짧은 범위 안내(scope)만 한다.
    backend 호출·라우팅은 그대로이며, 표시 문장과 바로가기 질문만 정한다.
    """
    primary, _ = copilot_suggestions(stage)
    actions = [(f"왜 {stage_display(stage)}인가요?" if stage else "판정 근거", primary[0]),
               ("최근 채용 신호", primary[2]), ("현장 확인사항", primary[1]), ("공식 지원", primary[3])]
    if mentioned or any(h in prompt for h in CONTEXT_HINTS):
        target = mentioned[0] if mentioned else industry
        text = (f"현재 선택된 업종은 {industry}입니다. {target} 업종의 진단 결과, 최근 채용 신호, 현장 확인사항, "
                "연결 가능한 공식 지원 중 무엇을 확인할까요?")
        return {"kind": "clarify", "text": text, "actions": actions}
    return {"kind": "scope", "text": SCOPE_TEXT, "actions": actions}


# ------------------------------------------------------------------ 공모전 팀 제안 — 정본 자료 기준
# 정본: changwon_policy_revised.html(2026.09, 팀 정책 제안 최종안). 요약은 팀이 정본에서 정리한 문장, 상세는 정본 원문 그대로.
# 정본에 없는 사업비·지원액·대상요건·기관·성과수치는 넣지 않는다. DB의 team_proposals(JSON payload용)는 건드리지 않는다.
TEAM_PROPOSALS = (
    {"no": 1, "title": "산업·고용 조기경보 정례협의체", "kind": "운영체계 개선",
     "summary": "분기별 산업·고용 신호를 정례 검토하고, 위험업종 발생 시 관계기관 현장확인과 기존 지원사업 연계까지 이어지는 "
                "협업체계를 제안합니다. 모델 결과는 지원대상 확정이 아니라 점검 후보 선별에 활용합니다.",
     "details": (("운영", "분기 1회 지표 점검 → 위험 업종 발생 시 임시회의 → 노동청·고용센터·경남TP·상의 등 현장확인 → 지원사업 연결"),
                 ("데이터 활용", "모형의 우선점검·추가확인 결과는 후보군 발굴용으로만 활용. 고용·생산·매출·수주 등 객관지표와 현장확인을 함께 사용."),
                 ("핵심 기대효과", "산업위기 신호를 행정적으로 놓치지 않고, 부서별로 따로 대응하던 정보를 공동 대응으로 연결."),
                 ("KPI", "분기 점검 횟수 / 위험업종 현장확인 비율 / 위험신호→지원 연계 소요기간 / 기관 공동 대응 건수"))},
    {"no": 2, "title": "경남형 버팀이음 다음 회차 재설계", "kind": "기존사업 고도화",
     "summary": "기존 사업을 새로 대체하기보다 대상 업종·지급구조·접수방식·소진율을 다음 회차에 개선합니다. "
                "신청률·미신청 사유·고용유지 성과를 후속 설계에 반영합니다.",
     "details": (("대상", "모형 결과를 자동 선정기준으로 쓰지 않고, 기존 대상과 실제 고용·생산 감소 업종을 비교하여 후보군을 재검토."),
                 ("지급", "숙련 유지가 목적이라면 근속기간 등 객관적 기준에 따른 차등 지급을 검토하되, 재원과 중앙정부 지침을 함께 확인."),
                 ("접수", "온라인 폼 + 방문/전화 안내를 병행하고 상의·산단공 등 현장기관을 통한 아웃리치 강화."),
                 ("필수 조사", "1차 사업의 신청률·소진율·미신청 사유·근속 유지 여부를 평가하여 다음 회차에 반영."),
                 ("KPI", "신청률 / 예산 소진율 / 지원자 6·12개월 고용유지율 / 미신청 사유별 비중"))},
    {"no": 3, "title": "산업전환 직무전환·재취업 패키지", "kind": "기존 제도 고도화",
     "summary": "제조 숙련인력의 직무훈련 → 전직 → 지역 내 재취업 과정을 연결합니다. 실제 채용수요를 확인해 "
                "스마트팩토리·자동화·로봇·제조AI 등 전환 직무와 연계합니다.",
     "details": (("대상", "산업전환으로 고용감소가 확인된 업종의 재직·이직·퇴직 근로자 중 전환 필요성이 확인된 사람."),
                 ("지원", "직무훈련, 자격증·교육비, 취업상담, 채용기업 매칭, 필요 시 취업 후 일정 기간 유지 인센티브를 결합."),
                 ("직무 예시", "기계가공·생산관리 → 품질데이터·스마트팩토리·자동화·로봇·제조AI 관련 직무 등. 실제 채용수요를 확인해 과정 개설."),
                 ("재원", "창원 자체사업으로 한정하지 않고 고용노동부·경남도·고용센터 사업과 연계."),
                 ("KPI", "훈련 수료율 / 취업률 / 6개월 고용유지율 / 전환 직무 수 / 지역 내 재취업 비율"))},
    {"no": 4, "title": "산업전환 기업 조기진단 프로그램", "kind": "신규 제안",
     "summary": "산업위기 신호를 기업 단위 현장진단과 지원연계로 연결합니다. 매출·고용·수주·생산·수출·원청 의존도·기술전환 수준·"
                "인력구조 등을 확인한 뒤 자금·DX/AX·사업전환·재교육·고용유지 등 필요한 지원영역을 검토합니다.",
     "details": (("진단항목", "매출·고용·수주·생산·수출·원청 의존도·기술전환 수준·인력구조·자금상황 등."),
                 ("운영", "위험업종 후보 → 간이진단 → 심층진단 필요 여부 결정 → 기업별 처방 → 중앙·지역 사업 연계."),
                 ("처방 예시", "A 자금 / B DX·AX / C 사업전환 / D 인력 재교육 / E 고용유지 등으로 유형화."),
                 ("중요 원칙", "모형 점수로 기업을 자동 탈락·선정하지 않는다. 기업진단과 객관적 재무·고용자료를 통해 최종 판단."),
                 ("KPI", "진단기업 수 / 진단→지원 연계율 / 기업별 맞춤처방 비율 / 지원 후 고용·매출·수주 변화"))},
    {"no": 5, "title": "원청-협력사 공동 산업전환 프로그램", "kind": "신규 제안",
     "summary": "원청의 미래 직무·기술 수요와 협력사의 인력·기술전환을 연결합니다. 원청 수요 제시 → 협력사 진단 → 공동교육 → "
                "전환 프로젝트·채용·납품역량 강화 구조입니다.",
     "details": (("구조", "원청이 미래 직무·기술 수요 제시 → 협력사 인력 진단 → 공동 교육 → 전환 프로젝트·채용·납품역량 강화."),
                 ("창원 적용", "기존 제조 AX 사업의 참여기업 및 협력사 네트워크를 활용하여 단계적으로 시범 운영."),
                 ("지원", "교육비·컨설팅·공정개선 비용 일부 지원. 원청은 교육과정 설계·현장실습·수요정보 제공 등에 참여."),
                 ("KPI", "참여 원청 수 / 참여 협력사 수 / 전환교육 이수자 / 공정개선 건수 / 신규 수주·채용 등 후속성과"))},
    {"no": 6, "title": "위기기업 고용유지·근로환경 개선 패키지", "kind": "기존사업 연계·확장",
     "summary": "고용유지 또는 신규채용 계획이 있는 영세·중소 협력사에 근로환경 개선·직무교육 등을 선택형으로 연결합니다. "
                "산업위기 모델은 후보군 발굴에만 사용합니다.",
     "details": (("대상", "매출·고용 감소 등 위기 신호가 확인되면서도 고용유지 또는 신규채용 계획이 있는 영세·중소 협력사."),
                 ("지원", "안전시설, 휴게시설, 건강·복지, 직무교육, 작업환경 개선 등 기업 상황에 맞는 선택형 지원."),
                 ("선정", "산업위기 모델은 후보군 발굴에만 사용하고, 최종 선정은 매출 하락률·고용유지 계획 등 객관지표로 판단."),
                 ("KPI", "고용유지 인원 / 신규채용 인원 / 개선기업 수 / 이직률 변화 / 지원 후 6개월 유지율"))},
    {"no": 7, "title": "방산·항공 협력사 패키지의 단계적 확대", "kind": "기존사업 확대",
     "summary": "기존 방산·항공 지원을 전체 제조업에 즉시 확대하지 않고, 위험신호가 확인된 비방산 기계·소재 협력사부터 "
                "단계적으로 적용 범위를 검토합니다.",
     "details": (("확대 대상", "공작기계·발전설비·소재 등 분석에서 위험신호가 확인된 협력사를 우선 검토."),
                 ("지원내용", "근로환경 개선, 숙련인력 유지, 직무교육, 공정개선 등 기존 패키지의 검증된 수단을 우선 활용."),
                 ("추진 조건", "현재 방산·항공 패키지의 대상 업종·기업 범위를 담당부서와 확인한 뒤 중복지원 여부를 점검."),
                 ("KPI", "확대 기업 수 / 고용유지율 / 참여기업의 사업전환·공정개선 성과"))},
    {"no": 8, "title": "산업전환 직무전환 바우처", "kind": "조건부 검토",
     "summary": "추가 예산 확보 시 교육비·자격증·훈련비를 묶어 기존 제조인력의 직무 이동을 지원하는 보조수단입니다. "
                "독립 신규사업보다는 직무전환·재취업 패키지의 세부수단으로 우선 시범 적용하는 방향입니다.",
     "details": (("전환 예시", "기계가공 → 자동화·로봇·스마트팩토리·품질데이터 / 생산관리 → 제조데이터·품질관리·공정분석 / "
                              "기존 숙련직 → 원청·협력사 공동 전환직무"),
                 ("비고", "독립된 신규 현금지원사업으로 만들기보다 3순위 직무전환·재취업 패키지의 세부 수단으로 먼저 시범 적용하는 편이 "
                         "사업 중복을 줄일 수 있다."))},
)

# 화면용 분류·설명(정본 내용은 그대로). stages = 이 앱의 UI 분류(공식 정책 분류 아님).
# why·effect_detail = 정본 '정책 우선순위' 표의 '우선 추진 이유'·'기대효과' 열 원문(8번은 정본 5절 본문).
# effect = 팀이 정리한 한 줄 기대효과(정량값 없음). flow = 정본의 운영·구조 흐름(없으면 정본 항목을 순서대로 옮긴 것).
# linkage = 이 앱의 화면 흐름과의 연결.
_TEAM_EXTRA = {
    1: {"stages": ("조기경보",), "effect": "산업위기 신호 조기 포착 · 기관 공동 대응 강화 · 지원 연계 지연 감소",
        "why": "신규 대규모 예산보다 회의체·업무 프로토콜 정비 중심이라 실행 부담이 낮고 전체 정책의 출발점이 됨.",
        "effect_detail": "위기 신호의 조기 포착, 부서·기관 간 대응속도 향상, 지원사업의 적시성 강화",
        "flow": ("분기 지표 점검", "위험업종 식별·임시회의", "관계기관 현장확인(노동청·고용센터·경남TP·상의 등)", "지원사업 연결",
                 "다음 분기 재점검"),
        "linkage": ("업종 진단(분기 신호)", "점검 관리(점검 후보·현장 확인)", "정책·지원 연계")},
    2: {"stages": ("고용유지", "재점검"), "effect": "숙련인력 이탈 완화 · 사업 참여율 개선 · 지원대상 정합성 향상",
        "why": "이미 시행된 사업의 다음 회차 설계에 바로 반영 가능. 대상·접수·소진율 데이터를 활용할 수 있음.",
        "effect_detail": "숙련인력 이탈 방지, 사업 참여율 개선, 실제 위기 업종과 지원대상의 정합성 향상",
        "flow": ("기존 사업 성과 확인", "신청률·소진율·미신청 사유 분석", "대상·지급구조·접수방식 재설계", "다음 회차 운영",
                 "고용유지 성과 확인"),
        "linkage": ("업종 진단(고용·생산 감소 업종)", "정책·지원 연계(고용유지)", "분기 재점검")},
    3: {"stages": ("노동전환",), "effect": "제조인력 이탈 완화 · 직무이동 촉진 · 지역 내 숙련인력 재배치",
        "why": "창원이 과거 운영한 전직·재취업·훈련 경험을 현재 AX 전환과 연결할 수 있음.",
        "effect_detail": "기존 제조인력의 이탈 완화, 지역 내 직무이동, 숙련인력의 재배치",
        "flow": ("기존 제조 숙련 확인", "실제 채용수요 확인", "전환 직무 설계", "직무훈련", "전직", "지역 내 재취업"),
        "linkage": ("업종 진단(채용시장 보조 신호)", "현장 확인", "정책·지원 연계(직업훈련·전직·재취업)")},
    4: {"stages": ("현장진단",), "effect": "기업별 맞춤 지원연계 · 지원 중복 감소 · 지원 시점 개선",
        "why": "모델의 산업 신호를 실제 기업지원으로 연결하는 핵심 브릿지. 중앙정부 구조혁신·고용서비스 사업과 결합 가능.",
        "effect_detail": "기업별 맞춤형 처방, 지원 중복 감소, 사업전환·DX 지원의 타이밍 개선",
        "flow": ("위험업종 후보", "기업 간이진단", "심층진단 필요 여부 결정", "기업별 지원영역 분류(처방)", "중앙·지역 사업 연계"),
        "linkage": ("업종 진단", "점검 관리", "현장 확인", "기업 조기진단", "기존 지원체계 연계")},
    5: {"stages": ("기업전환",), "effect": "협력사 기술·인력 전환 촉진 · 수요 기반 교육 강화 · 지역 제조생태계 안정",
        "why": "창원의 대기업-협력사 제조생태계를 활용한다는 지역 특화성이 높음.",
        "effect_detail": "협력사의 기술·인력 전환, 원청 수요 기반 교육, 산업생태계 안정",
        "flow": ("원청 미래 직무·기술 수요 제시", "협력사 인력·기술 진단", "공동 교육", "전환 프로젝트", "채용·납품역량 강화"),
        "linkage": ("업종 진단", "현장 확인(원청·협력사 수요)", "정책·지원 연계(기술전환·직업훈련)")},
    6: {"stages": ("고용유지",), "effect": "근로환경 개선 · 이직요인 완화 · 고용유지 및 신규채용 지원",
        "why": "단순 기업지원금이 아니라 고용유지·채용과 연계할 때 정책 목적이 명확해짐.",
        "effect_detail": "근로환경 개선, 이직요인 완화, 고용유지 및 신규채용 유도",
        "flow": ("위기신호 확인", "고용유지·채용계획 확인", "지원 필요영역 확인", "근로환경·직무교육 등 선택형 연계",
                 "고용유지 성과 확인"),
        "linkage": ("업종 진단", "점검 관리(현장 확인)", "정책·지원 연계(고용유지)")},
    7: {"stages": ("기업전환", "고용유지"), "effect": "지원 사각지대 축소 · 비방산 협력사 전환역량 강화 · 고용 안정",
        "why": "기존 패키지의 대상 범위를 먼저 확인한 뒤 위기 신호가 확인된 비방산 기계·소재 협력사로 단계적으로 확대.",
        "effect_detail": "지원 사각지대 축소, 협력사 경쟁력·고용 안정",
        "flow": ("기존 지원대상 범위 확인", "위험신호 비방산 협력사 확인", "중복지원 검토", "단계적 적용",
                 "사업전환·고용성과 확인"),
        "linkage": ("업종 진단(위험 신호 업종)", "현장 확인(협력사 범위)", "정책·지원 연계")},
    8: {"stages": ("노동전환",), "effect": "직무전환 비용 부담 완화 · 지역 채용수요가 있는 직무로의 이동 지원(검토 시 기대)",
        "why": "위 7개 정책 중 예산을 추가 확보할 수 있을 때 별도 사업으로 검토할 수 있는 보조정책. 기존 제조인력이 실제 지역 "
               "채용수요가 있는 직무로 이동할 수 있도록 교육비·자격증·훈련 관련 비용을 묶어 지원.",
        "effect_detail": "조건부 검토안 — 정본 우선순위 표에 별도 기대효과·KPI가 없습니다. 위 한 줄은 검토 시 기대하는 방향이며 확정된 효과가 아닙니다.",
        "flow": ("직무전환 필요 확인", "실제 채용수요 확인", "교육·자격·훈련비 지원", "직무 이동", "후속 고용 확인"),
        "linkage": ("업종 진단(채용시장 직무 키워드)", "정책·지원 연계(직업훈련)")},
}
TEAM_PROPOSALS = tuple({**p, **_TEAM_EXTRA[p["no"]]} for p in TEAM_PROPOSALS)
TEAM_STAGE_FLOW = (("조기경보", "위험 신호 포착"), ("현장진단", "기업 현장 확인"), ("고용유지", "근로환경·고용 유지"),
                   ("노동전환", "직무전환·재취업"), ("기업전환", "사업전환·협력사 전환"), ("재점검", "성과 확인"))
TEAM_STAGE_FILTERS = ("조기경보", "현장진단", "고용유지", "노동전환", "기업전환")


def team_kpis(p: dict) -> tuple[str, ...]:
    """정본 KPI 행만(없으면 빈 값 — 지어내지 않는다)."""
    row = next((v for k, v in p["details"] if k == "KPI"), "")
    return tuple(x.strip() for x in row.split("/") if x.strip())


def team_principles(p: dict) -> tuple[tuple[str, str], ...]:
    """정본 상세 행 중 KPI를 뺀 나머지 = 추진 전 확인사항·원칙·대상 등(원문 그대로)."""
    return tuple((k, v) for k, v in p["details"] if k != "KPI")


def team_proposals_text() -> str:
    """행정 AI 비서가 '공모전 팀 제안' 탭에서 근거로 쓰는 정본 텍스트(화면과 같은 내용)."""
    lines = ["[공모전 팀 제안 정본] 아래 8건은 현재 시행 중인 공식 지원사업이 아니라, 기존 사업·제도와 분석 결과를 바탕으로 "
             "팀이 구성한 정책 개선·신규 제안이며 전 업종 공통입니다(특정 업종 추천 아님).",
             "공식 지원 연계 = 지금 활용 가능한 기존 제도와 기관 / 공모전 팀 제안 = 분석 결과를 기반으로 제안하는 개선·신규 정책.",
             "정책체계 흐름: " + " → ".join(s for s, _ in TEAM_STAGE_FLOW)]
    for p in TEAM_PROPOSALS:
        lines.append(f"{p['no']}. {p['title']} · 성격 {p['kind']} · 연계 단계 {'·'.join(p['stages'])}")
        lines.append(f"   제안: {p['summary']}")
        lines.append(f"   추진 이유: {p['why']}")
        lines.append(f"   작동 방식: {' → '.join(p['flow'])}")
        lines.append(f"   기대효과: {p['effect']} (정본: {p['effect_detail']})")
        kpis = team_kpis(p)
        lines.append(f"   성과 확인 지표(KPI): {' / '.join(kpis) if kpis else '정본에 별도 KPI 없음'}")
        for k, v in team_principles(p):
            lines.append(f"   {k}: {v}")
    return "\n".join(lines)


TEAM_SUGGESTIONS = ("공모전 팀 제안에는 어떤 내용이 있어?", "조기경보 제안은 어떻게 작동해?", "기업 조기진단의 기대효과는?",
                    "정책 성과는 어떤 지표로 확인해?")
TEAM_SUGGESTIONS_MORE = ("공식 지원사업과 팀 제안은 뭐가 달라?",)

# 지원 기능 화면 라벨(표시용 어휘만 정리 — 저장·조회는 backend 기능 태그 그대로)
FUNCTION_UI = {
    "employment_retention": ("🛡", "고용유지"), "vocational_training": ("🎓", "직업훈련"),
    "reemployment": ("🔁", "재취업"), "recruitment_matching": ("🤝", "채용매칭"),
    "business_difficulty": ("🏭", "경영·기술 지원"), "technology_transition": ("⚙", "기술전환"),
    "crisis_response": ("🚨", "위기대응"), "further_observation": ("👁", "추가관찰"),
}
INTAKE_UI = {"OPEN": "접수 중", "UNKNOWN": "접수 상태 확인 필요"}


def function_name(tag: str, fallback: str | None = None) -> str:
    """지원 기능 화면 표시명(아이콘 없음) — 업종 진단·진단서·점검 관리·정책 화면 공통. 저장값(tag)은 그대로."""
    return FUNCTION_UI.get(tag, ("", fallback or tag))[1]


def function_ui_label(tag: str, fallback: str | None = None) -> str:
    icon, label = FUNCTION_UI.get(tag, ("", fallback or tag))
    return f"{icon} {label}".strip()


def filter_official_cards(cards: list[dict], function_tag: str | None, intake: str | None) -> list[dict]:
    """공식 요건 카드 필터(화면 필터만 — 카드 자체·순서는 backend 그대로)."""
    return [c for c in cards if (not function_tag or c.get("function_tag") == function_tag)
            and (not intake or c.get("current_intake_status") == intake)]


# ------------------------------------------------------------------ 현재 모집 중인 관련 공고(출처: 기업마당)
# 지원 기능별로 공고 개요·제목·대상에 이 표현이 있으면 '관련 가능 공고'로 본다(표현 일치만 — 지원대상·적격은 판정하지 않음).
NOTICE_TERMS = {
    "employment_retention": ("고용유지", "고용안정", "고용 유지", "근로환경"),
    "vocational_training": ("직업훈련", "교육훈련", "인력양성", "재직자 교육", "훈련"),
    "reemployment": ("재취업", "전직", "구직"),
    "recruitment_matching": ("채용", "구인", "인력 매칭", "일자리 매칭"),
    "business_difficulty": ("경영안정", "경영개선", "경영 애로", "컨설팅", "자금"),
    "technology_transition": ("스마트공장", "스마트제조", "자동화", "디지털 전환", "공정개선", "기술개발"),
    "crisis_response": ("위기", "긴급", "재도약"),
}
# 기업이 아니라 사업을 운영할 기관을 뽑는 공고(공고명 표현 기준)
OPERATOR_CALL_WORDS = ("주관기관 모집", "운영기관 모집", "수행기관 모집", "전문기관 모집", "위탁기관 모집", "주관기관 공모",
                       "운영기관 공모", "수행기관 공모")
_NOTICE_INDUSTRY_RANK = {"DIRECT": 0, "MANUFACTURING": 1, "BUSINESS_TYPE_ONLY": 2, "NOT_STATED": 3}
_NOTICE_REGION_RANK = {"CHANGWON": 0, "GYEONGNAM": 1, "NATIONWIDE": 2, "NOT_STATED": 3}


def rank_notices(items: list[dict]) -> list[dict]:
    """관련 가능 공고 정렬: ① 업종 표현(업종명 > 제조 > 무관) ② 지원 기능 표현 있음 ③ 지역(창원 > 경남 > 전국) ④ 최근 접수 시작.

    접수 중 여부·다른 지역 제외는 provider가 이미 걸렀다. 지원대상 적합성은 판정하지 않는다(항상 '추가 확인 필요').
    """
    newest_first = sorted(items, key=lambda it: it.get("start") or "", reverse=True)
    return sorted(newest_first, key=lambda it: (
        _NOTICE_INDUSTRY_RANK.get((it.get("industry_match") or {}).get("level"), 9),
        0 if it.get("function_tags") else 1,
        _NOTICE_REGION_RANK.get((it.get("region_match") or {}).get("level"), 9)))


def collect_related_notices(api, industry: str, fn_tags, today) -> list[dict]:
    """접수 중 공고(provider가 OPEN·지역 조건을 이미 적용) 중 '관련 가능 공고'만 모아 정렬한다.

    - 선택 업종의 지원 기능별 표현(NOTICE_TERMS)이 공고에 있으면 그 기능을 연결 사유로 붙인다.
    - 기능 표현이 없어도 업종명이 공고에 직접 적힌 것(DIRECT)은 포함한다.
    - 조회 장애는 RuntimeError로 올려 호출부가 로그로 남기게 한다(화면에는 개발용 메시지를 띄우지 않음).
    - 여러 시도 태그로 '전국'이 된 공고라도 공고명·소관기관이 경남 밖 시도를 가리키면(예: '전북 …', 전북특별자치도) 뺀다.
    - 공고명이 사업을 운영할 기관을 모집하는 공고(주관기관·운영기관 모집 등)면 기업 대상이 아니므로 뺀다.
    - 남는 공고는 업종명·'제조'가 적혀 있거나 창원·경남 공고여야 한다.
    """
    from copilot.providers.official import SIDO
    found: dict[str, dict] = {}

    def not_for_changwon_firms(item: dict) -> bool:
        title, agency = item.get("title") or "", item.get("agency") or ""
        other_sido = any(s != "경남" and (s in title or agency.startswith(s)) for s in SIDO)
        return other_sido or any(w in title for w in OPERATOR_CALL_WORDS)

    def collect(result, tag: str | None):
        if not result.ok and result.error not in ("NO_MATCHING_OPEN_ITEMS", "EMPTY"):
            raise RuntimeError(result.error or "UNAVAILABLE")
        for item in (result.meta or {}).get("items") or []:
            if not_for_changwon_firms(item):
                continue
            if tag is None and (item.get("industry_match") or {}).get("level") != "DIRECT":
                continue
            entry = found.setdefault(item["detail_url"], {**item, "function_tags": []})
            if tag and tag not in entry["function_tags"]:
                entry["function_tags"].append(tag)

    for tag in fn_tags:
        if NOTICE_TERMS.get(tag):
            collect(api.search(f"{industry} {function_name(tag)} 공고", terms=list(NOTICE_TERMS[tag]), today=today,
                               max_results=100, industry_terms=(industry,)), tag)
    collect(api.search(f"{industry} 공고", terms=[], today=today, max_results=100, industry_terms=(industry,)), None)
    # 업종명·'제조' 언급도 없고 지역도 전국(또는 미표기)인 공고는 연결이 약해 뺀다(표현 한 단어만 겹친 경우)
    kept = [it for it in found.values()
            if (it.get("industry_match") or {}).get("level") in ("DIRECT", "MANUFACTURING")
            or (it.get("region_match") or {}).get("level") in ("CHANGWON", "GYEONGNAM")]
    return rank_notices(kept)


def notice_reasons(item: dict) -> list[str]:
    """'현재 진단과의 연결 사유' — 공고문 표현이 실제로 일치한 근거만 적는다."""
    reasons = [f"{function_name(tag)} 관련 표현이 공고에 있음" for tag in item.get("function_tags") or []]
    level = (item.get("industry_match") or {}).get("level")
    if level in ("DIRECT", "MANUFACTURING"):
        reasons.append(item["industry_match"]["evidence"])
    region = item.get("region_match") or {}
    if region.get("level") in ("CHANGWON", "GYEONGNAM", "NATIONWIDE"):
        reasons.append(region["evidence"])
    return reasons
