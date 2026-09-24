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


def copilot_suggestions(stage: str | None) -> tuple[list[str], list[str]]:
    """Copilot 제안 질문 — (기본 4개, 더보기 3개). 라우팅 키워드는 quick_prompts와 같은 의도를 유지한다."""
    primary = [COPILOT_STAGE_QUESTION.get(stage, "이 업종의 판정 근거는?"), "현장에서 무엇을 확인해야 하나요?",
              "최근 채용 신호는 어떤가요?", "연결 가능한 공식 지원은?"]
    more = ["현재 신청 가능한 지원사업은?", "직전 분기 대비 최근 판정 변화는?", "검토 가능한 지원 기능 후보는?",
            "이 판정의 한계는?"]
    return primary, more


# ------------------------------------------------------------------ 신규 헬퍼(UI 리스트럭처)
SIGNAL_EXPLANATION_TITLE = {"E": "고용 감소율", "R": "산단평균 대비 열위", "A": "산단 대비 감소규모"}


def signal_explanation(rows: list[dict], signals: dict) -> dict:
    """"왜 {단계}인가?" 카드용 근거. rule_evidence_rows() 값만 재구성하고 새로 계산하지 않는다.

    E/R/A는 판정과 무관하게 항상 표시하고(모든 단계에서 같은 구조), P·반복 진입신호는 보강 기준을
    충족했을 때만 덧붙인다. summary는 등록된 n_entry/n_up 신호 개수를 그대로 옮긴다.
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
        items.append({"title": "생산 감소 (보강)", "value": p_row.get("current"),
                      "rule": f"보강 기준 {p_row.get('entry_threshold')} 충족", "tone": "amber"})
    rep_row = next((r for r in rows if (r.get("signal") or "").startswith("반복 진입신호")), None)
    if rep_row and rep_row.get("verdict") == "충족":
        items.append({"title": "지속성 (보강)", "value": "직전 분기에도 진입신호",
                      "rule": "반복 진입신호 충족", "tone": "amber"})
    summary = f"진입신호 {_num(signals.get('n_entry'))}건 · 상위신호 {_num(signals.get('n_up'))}건"
    return {"items": items[:5], "summary": summary}


def top_questions(questions: list[dict], n: int = 3) -> list[dict]:
    """앞의 n개만 잘라 보여준다. backend 순서(Q1→Q3→WORK24→SNAPSHOT)를 그대로 쓰며 재정렬하지 않는다."""
    return questions[:n]


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
    return {"kind": "scope", "text": "이 비서는 창원국가산단의 산업·고용 진단과 정책 연계를 지원합니다.", "actions": actions}


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
