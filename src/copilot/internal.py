"""INTERNAL_DIAGNOSTIC 답변 — 기존 backend 결과만 쓰는 결정론적 문구.

- 기존 의도(판정 근거·판정 변화·채용·현장·한계·업종 비교·지원 기능)는 DecisionSupportService.answer()에
  고정 질의문(CANONICAL)으로 위임한다. 사용자 문장을 그대로 넘기면 answer() 내부 키워드 분기가 엇갈릴 수 있어서다.
- E/R/A/P·Q1~Q3는 등록 Snapshot 값과 등록 규칙 경계 문자열을 그대로 옮긴다(재계산 없음).
"""
from __future__ import annotations

from dataclasses import replace

from app.view_models import rule_evidence_rows

from . import router as R
from .contracts import INTERNAL_DIAGNOSTIC, INTERNAL_RAG, SYSTEM, TEMPLATE, Citation, CopilotAnswer

# 의도 → (answer()가 해당 분기로 가는 고정 질의문, 기대 answer_type). 테스트로 분기 일치를 확인한다.
CANONICAL = {
    R.STAGE: ("판정 근거 설명", "DIAGNOSTIC_EXPLANATION"),
    R.CHANGE: ("최근 판정 변화", "RECENT_DIAGNOSTIC_CHANGE"),
    R.RECRUITMENT: ("채용신호", "RECRUITMENT_CONTEXT"),
    R.FIELD: ("현장 체크리스트", "FIELD_CHECKLIST"),
    R.GAPS: ("데이터 한계", "EVIDENCE_GAPS"),
    R.COMPARE: ("업종 비교", "INDUSTRY_COMPARISON"),
    R.SUPPORT_FUNCTIONS: ("지원기능 후보", "SUPPORT_FUNCTION_CANDIDATES"),
}
SIGNAL_ROW = {"E": 0, "R": 1, "A": 2, "P": 3}
NUMERIC = (R.SIGNAL, R.Q1, R.Q2, R.Q3)
NO_RECALC = "값은 등록 분석본 그대로이며 이 답변에서 다시 계산하지 않았습니다."


def _f(value, digits: int = 1, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        return "자료 없음"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, int):
        return f"{value:+,}{suffix}" if signed else f"{value:,}{suffix}"
    if isinstance(value, float):
        return f"{value:+,.{digits}f}{suffix}" if signed else f"{value:,.{digits}f}{suffix}"
    return str(value)


class InternalDiagnostics:
    def __init__(self, service):
        self.service = service  # DecisionSupportService(읽기 전용 사용)

    @property
    def snapshot(self):
        return self.service.snapshot

    def _rules(self) -> dict:
        return {r["rule_name"]: r for r in self.snapshot.reference["triage_rules"]}

    # ------------------------------------------------------------ 기존 answer() 위임
    def delegated(self, intent: str, quarter: str, industry: str, *, comparison_industry: str | None = None,
                  field_context: dict | None = None) -> dict:
        prompt, _ = CANONICAL[intent]
        return self.service.answer(prompt, quarter, industry, comparison_industry=comparison_industry,
                                   field_context=field_context)

    def answer(self, decision: R.RouteDecision, quarter: str, industry: str, *,
               comparison_industry: str | None = None, field_context: dict | None = None) -> CopilotAnswer:
        target = {"industry": industry, "quarter": quarter,
                  "snapshot": f"{self.snapshot.quarter} {self.snapshot.version}"}
        rec = self.snapshot.get(industry, quarter)
        if rec is None:
            return CopilotAnswer(
                answer=f"{industry} · {quarter}의 등록 진단이 이 분석본에 없습니다. 다른 분기·업종 값을 대신 쓰지 않습니다.",
                source_type=SYSTEM, route=decision.route, intent=decision.intent, answer_type="NOT_FOUND",
                target=target)
        intent = decision.intent
        if intent in NUMERIC:
            asked = set(decision.subintents or (intent,)) | {intent}
            parts = [p for p in NUMERIC if p in asked]  # 표시 순서 고정: 신호 → Q1 → Q2 → Q3
            text = "\n\n".join(self._numeric(p, rec, decision) for p in parts)
            return CopilotAnswer(answer=f"{text}\n\n{NO_RECALC}", source_type=INTERNAL_DIAGNOSTIC,
                                 route=decision.route, intent=intent, answer_type=f"REGISTERED_{intent}",
                                 evidence=[{"industry": industry, "quarter": quarter}], target=target)
        if intent == R.REPHRASE:
            # 무엇을 쉽게 설명할지: 함께 물은 진단 의도(예: 'E값을 쉽게') → 없으면 판정 근거
            base_intent = next((s for s in decision.subintents if s != R.REPHRASE), R.STAGE)
            base = self.answer(replace(decision, intent=base_intent), quarter, industry,
                               comparison_industry=comparison_industry, field_context=field_context)
            return replace(base, intent=intent)
        result = self.delegated(intent, quarter, industry, comparison_industry=comparison_industry,
                                field_context=field_context)
        text = result["answer"]
        if intent == R.FIELD:
            questions = self.service.field_questions(quarter, industry)
            if questions:
                lines = "\n".join(f"{i}. {q['question']}" for i, q in enumerate(questions[:6], 1))
                more = f"\n(외 {len(questions) - 6}건은 진단카드 체크리스트에 있습니다.)" if len(questions) > 6 else ""
                text = f"{text}\n\n현장 확인 질문(등록 진단·채용공고 기반):\n{lines}{more}"
        source_type = INTERNAL_RAG if intent == R.SUPPORT_FUNCTIONS else INTERNAL_DIAGNOSTIC
        citations = [Citation(title=c.get("title") or c.get("requirement_id") or "요건 카드",
                              url=c["source_url"], source_type=INTERNAL_RAG, official=True,
                              institution=c.get("institution"), checked_at=c.get("verified_at"))
                     for c in result.get("policy_sources") or [] if c.get("source_url")]
        return CopilotAnswer(answer=text, source_type=source_type, route=decision.route, intent=intent,
                             answer_type=result["answer_type"], caveats=list(result.get("caveats") or []),
                             citations=citations, target=target,
                             official_evidence_sufficient=bool(citations) if source_type == INTERNAL_RAG else None)

    # ------------------------------------------------------------ E/R/A/P · Q1~Q3 (등록값)
    def _numeric(self, intent: str, rec: dict, decision: R.RouteDecision) -> str:
        head = f"{rec['industry']} · {rec['quarter']}"
        if intent == R.SIGNAL:
            rows = rule_evidence_rows(rec, self._rules())
            letters = decision.signals
            chosen = [rows[SIGNAL_ROW[x]] for x in letters if x in SIGNAL_ROW] or rows
            rules = self._rules()
            lines = []
            for row in chosen:
                bounds = " / ".join(f"{name} {value}" for name, value in
                                    (("진입", row["entry_threshold"]), ("상위", row["upper_threshold"])) if value)
                lines.append(f"- {row['signal']}: {row['current']}"
                             + (f" (등록 경계 {bounds})" if bounds else "") + f" → 판정 표시 '{row['verdict']}'"
                             + (f"\n  정의: {row['definition']}" if row.get("definition") else ""))
            ladder = rules.get("ladder", {}).get("definition")
            return (f"{head} 등록 신호값\n" + "\n".join(lines)
                    + (f"\n판정 규칙: {ladder} (운영 경계값이며 법정 기준·최적값이 아닙니다.)" if ladder else ""))
        if intent == R.Q1:
            q1 = rec["q1"]
            return (f"{head} Q1 상태는 {q1['state'] or '판정 불가'} ({q1['state_label'] or '자료 없음'})입니다. "
                    f"생산 YoY {_f(q1.get('production_yoy'), 1, '%', True)}, "
                    f"고용 YoY {_f(q1.get('employment_yoy'), 2, '%', True)}."
                    + (f"\n확인 방향: {q1['question_route']}" if q1.get("question_route") else ""))
        if intent == R.Q2:
            q2 = rec["q2"]
            return (f"{head} Q2 고용 규모: 고용 {_f(q2.get('employment'), suffix='명')} "
                    f"(전년동기 {_f(q2.get('employment_lag4'), suffix='명')}, "
                    f"증감 {_f(q2.get('emp_delta'), suffix='명', signed=True)}, "
                    f"YoY {_f(q2.get('employment_yoy'), 2, '%', True)}). "
                    f"산단 제조업 고용 비중 {_f(q2.get('employment_share_pct'), 2, '%')}, "
                    f"산단 순감소 기여율 {_f(q2.get('contribution_pct'), 2, '%')}.")
        q3 = rec["q3"]
        repeated = {True: "있음", False: "없음"}.get(q3.get("repeated_signal"), "미확인")
        return (f"{head} Q3 시간: 현재 상태 {_f(q3.get('state_run_length'))}분기 지속 · "
                f"전이 {q3.get('transition') or '없음'} · 반복 진입신호(연속 2분기) {repeated}.")
