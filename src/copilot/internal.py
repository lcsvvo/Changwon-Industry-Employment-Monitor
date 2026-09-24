"""INTERNAL_DIAGNOSTIC 답변 — 기존 backend 결과만 쓰는 결정론적 문구.

- 기존 의도(판정 근거·판정 변화·채용·현장·한계·업종 비교·지원 기능)는 DecisionSupportService.answer()에
  고정 질의문(CANONICAL)으로 위임한다. 사용자 문장을 그대로 넘기면 answer() 내부 키워드 분기가 엇갈릴 수 있어서다.
- E/R/A/P·Q1~Q3는 등록 Snapshot 값과 등록 규칙 경계 문자열을 그대로 옮긴다(재계산 없음).
"""
from __future__ import annotations

from dataclasses import replace

from app.view_models import (
    evidence_level, function_name, institution_status_text, q1_plain, rank_text, reason_sentence, rule_evidence_rows,
    run_text, stage_display,
)
from workflow import catalog as C

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
# LIMIT 주제별 (결론, 설명) — 점검 신호로 원인·구조조정·위기·채용난을 단정하지 않는다
LIMIT_TEXT = {
    "RESTRUCTURING": ("아니요. 현재 진단만으로 구조조정이 발생했다고 판단할 수 없습니다.",
                      "생산·고용 변화는 점검 신호이며, 실제 감원·휴업·이직 증가 여부와 기업별 고용조정 계획은 현장에서 추가로 "
                      "확인해야 합니다."),
    "CRISIS": ("아니요. 현재 진단만으로 이 업종을 산업위기라고 판단할 수 없습니다.",
               "점검단계(우선점검 후보·추가확인·관찰)는 프로젝트 운영규칙에 따른 업종 단위 점검 순서이며 법정 위기 지정 기준이 "
               "아닙니다. 수주·가동·고용조정 등 실제 상황은 현장 확인과 관계기관 판단이 필요합니다."),
    "HIRING": ("아니요. 현재 채용공고만으로 채용난이나 기술 미스매치가 발생했다고 판단할 수 없습니다.",
               "채용공고는 판정 입력이 아닌 보조근거이며, 공고 수는 모집인원이나 전체 노동수요가 아닙니다. 실제 미충원 여부는 "
               "기업 확인이 필요합니다."),
    "CAUSE": ("아니요. 현재 자료만으로 고용 변화의 원인(수주·자동화·폐업·외주화 등)을 판단할 수 없습니다.",
              "생산·고용의 동반변화는 인과관계의 증거가 아니며, 원인 후보는 현장에서 확인해야 합니다."),
}
NO_ELIGIBILITY = "아니요. 이 도우미는 개별 기업의 지원사업 대상·적격 여부를 판단하지 않습니다."


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
        if intent in (R.LIMIT, R.SUMMARY, R.INSTITUTION, R.ELIGIBILITY):
            return self._guided(decision, rec, quarter, industry, target)
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

    # ------------------------------------------------------------ 단정 여부 · 진단카드 요약 · 담당기관 · 적격 요청
    def _facts(self, rec: dict) -> str:
        """등록 진단 사실 한 줄(재계산 없음)."""
        q1, q2 = rec["q1"], rec["q2"]
        return (f"등록 진단({rec['industry']} · {rec['quarter']}): {stage_display(rec['triage']['stage'])} · "
                f"{q1_plain(q1.get('state'))}({q1.get('state') or '—'}) · 고용 증감 "
                f"{_f(q2.get('emp_delta'), suffix='명', signed=True)}(YoY {_f(q2.get('employment_yoy'), 2, '%', True)}) · "
                f"명목 생산액 YoY {_f(q1.get('production_yoy'), 1, '%', True)}.")

    def _functions(self, quarter: str, industry: str) -> list[dict]:
        return self.service.context(quarter, industry)["support_function_candidates"]

    def _institutions(self, tag: str) -> list[dict]:
        """기능 1개의 인계 가능(verified) 기관 — 업무 DB 등록부까지 보는 기존 조회를 우선 쓴다(읽기 전용)."""
        workflow = getattr(self.service, "workflow", None)
        if workflow is not None:
            return workflow.institution_candidates(self.snapshot, tag)
        return C.institution_candidates(tag, self.snapshot.reference.get("institution_routing_map") or [])

    def _guided(self, decision: R.RouteDecision, rec: dict, quarter: str, industry: str,
                target: dict) -> CopilotAnswer:
        intent, citations = decision.intent, []
        questions = self.service.field_questions(quarter, industry)
        first_check = questions[0]["question"] if questions else None
        if intent == R.LIMIT:
            topics = [t for t in decision.subintents if t in LIMIT_TEXT] or ["CAUSE"]
            lines = [LIMIT_TEXT[t][0] for t in topics] + [LIMIT_TEXT[t][1] for t in topics]
            if "HIRING" in topics:
                jobs = self.service.recruitment_snapshot(industry)
                active = (evidence_level(jobs, "ACTIVE_CONFIRMED") or {}).get("count")
                detail = (evidence_level(jobs, "DETAIL_VERIFIED") or {}).get("count")
                if jobs.get("status") != "FOUND" or (not active and not detail):
                    lines.append("현재 검증된 채용공고가 없어 채용수요를 판단할 수 없습니다.")
                else:
                    lines.append(f"확보된 Work24 공고(수집 단면): 목록 {_f(jobs.get('posting_count'))}건 · 현재 유효 "
                                 f"{_f(active)}건 · 상세 검증 {_f(detail)}건.")
            if "CAUSE" in topics and rec["q1"].get("question_route"):
                lines.append(f"확인 방향(등록): {rec['q1']['question_route']}")
            lines.append(self._facts(rec))
            if first_check:
                lines.append(f"현장에서 우선 확인: {first_check}")
            source_type, answer_type = INTERNAL_DIAGNOSTIC, "LIMIT_NOT_DETERMINABLE"
        elif intent == R.SUMMARY:
            q1, q2, q3, t = rec["q1"], rec["q2"], rec["q3"], rec["triage"]
            rows = rule_evidence_rows(rec, self._rules())
            lines = [f"{industry} · {quarter} 진단카드 요약: {stage_display(t['stage'])} "
                     f"({rank_text(t['stage'], t.get('rank_in_stage'))}).",
                     f"Q1 산업·고용 상태: {q1_plain(q1.get('state'))}({q1.get('state') or '—'}) · "
                     f"명목 생산액 YoY {_f(q1.get('production_yoy'), 1, '%', True)}",
                     f"Q2 고용 영향 규모: 고용 증감 {_f(q2.get('emp_delta'), suffix='명', signed=True)}"
                     f"(YoY {_f(q2.get('employment_yoy'), 2, '%', True)}) · 산단 고용 비중 "
                     f"{_f(q2.get('employment_share_pct'), 2, '%')}",
                     f"Q3 지속·전환: {run_text(q3)} · 전환 {q3.get('transition') or '자료 없음'}",
                     f"판정 이유: {reason_sentence(rec, rows)}"]
            if first_check:
                lines.append(f"현장에서 우선 확인: {first_check}")
            lines.append("통계 신호는 원인을 확정하지 않으며 현장 확인이 필요합니다.")
            source_type, answer_type = INTERNAL_DIAGNOSTIC, "DIAGNOSTIC_SUMMARY"
        elif intent == R.INSTITUTION:
            functions = self._functions(quarter, industry)
            if functions:
                lines = [f"{industry} · {quarter}의 검토 지원 기능별 담당기관 검증상태입니다(등록된 기관 매핑만 사용)."]
                for f in functions:
                    cands = self._institutions(f["function_tag"])
                    lines.append(f"{function_name(f['function_tag'], C.label(f['function_tag']))}: "
                                 f"{institution_status_text(cands)}")
                    citations += [Citation(title=c["institution"], url=c["source_url"], source_type=INTERNAL_RAG,
                                           official=True, institution=c["institution"], checked_at=c.get("verified_at"))
                                  for c in cands if c.get("source_url")]
            else:
                lines = [f"{industry} · {quarter}에는 채용 키워드로 연결된 검토 지원 기능 후보가 없어 담당기관을 특정하지 않습니다."]
            lines.append("등록되지 않은 기관·연락처는 제시하지 않습니다. 실제 인계 전 담당기관 확인이 필요하며, 참고 기관 목록과 "
                         "검증상태는 정책·지원 연계의 '참고 기관 · 검토 경로'에서 볼 수 있습니다.")
            source_type, answer_type = INTERNAL_RAG, "INSTITUTION_STATUS"
        else:  # ELIGIBILITY
            functions = self._functions(quarter, industry)
            cards = self.service.requirement_cards([f["function_tag"] for f in functions])
            labels = ", ".join(function_name(f["function_tag"], C.label(f["function_tag"])) for f in functions)
            lines = [NO_ELIGIBILITY, "적격·선정 여부는 공고문 요건과 담당기관 확인으로 정해집니다."]
            lines.append(f"참고로 {industry} · {quarter} 등록 진단에서 검토할 수 있는 지원 기능 후보는 {labels}이며, 연결된 공식 "
                         f"요건 카드는 {len(cards)}건입니다(연계 검토 후보)." if functions else
                         f"참고로 {industry} · {quarter} 등록 진단에는 연결된 지원 기능 후보가 없습니다.")
            lines.append("요건 카드와 공식 근거는 정책·지원 연계의 '공식 지원 연계'에서 확인하세요.")
            citations = [Citation(title=c.get("title") or "요건 카드", url=c["source_url"], source_type=INTERNAL_RAG,
                                  official=True, institution=c.get("institution"), checked_at=c.get("verified_at"))
                         for c in cards if c.get("source_url")]
            source_type, answer_type = INTERNAL_RAG, "ELIGIBILITY_NOT_DETERMINED"
        return CopilotAnswer(answer="\n".join(lines), source_type=source_type, route=decision.route, intent=intent,
                             answer_type=answer_type, citations=citations[:5], target=target,
                             evidence=[{"industry": industry, "quarter": quarter}],
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
