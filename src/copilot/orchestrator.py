"""Copilot 오케스트레이터 — 기존 backend를 감싸는 계층.

User Query → Router → ① INTERNAL_DIAGNOSTIC ② INTERNAL_RAG → (부족 시) ③ EXTERNAL_WEB → ④ GENERAL_LLM

- 등록 진단(Snapshot)·판정·RAG 로직은 바꾸지 않고 읽기만 한다.
- 세션 입력(체크리스트 답변·메모)은 기존 backend(answer())에만 전달하고 외부 provider로 보내지 않는다.
- 어느 경로에도 해당하지 않으면 현재 업종 진단으로 대신 답하지 않는다.
- Gemini 작성 모드(compose_with_llm, 앱 기본 켜짐): 정책 RAG·기업마당을 뺀 답변을 LLM이 쓴다. 등록 진단 답변은
  원문을 근거로 다시 쓰고, 범위 밖·짧은 질문은 등록 진단 요약만 근거로 답한다. 둘 다 수치·판정 보존 검증을 통과해야
  쓰며, 실패하면 원래 답변을 그대로 돌려준다. LLM 입력에 세션 입력·담당자 정보는 넣지 않는다.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

from sqlalchemy import select

from workflow import catalog as C
from workflow import models as M

from . import guardrails, router as R, sufficiency
from .audit import AuditRecord, AuditSink, NullAuditSink, question_digest
from .contracts import (
    CAPABILITY, EXTERNAL_WEB, GENERAL_LLM, GREETING, INTERNAL_DIAGNOSTIC, INTERNAL_RAG, SYSTEM, UNSUPPORTED,
    Citation, CopilotAnswer,
)
from .internal import InternalDiagnostics
from .domains import TIER1_DOMAINS
from .providers.base import (
    LLMProvider, NullLLMProvider, NullWebSearchProvider, SourceDoc, WebSearchProvider, official_apis_from_env,
    providers_from_env,
)

# 질문의 지원 기능어 → 기존 지원기능 태그(workflow.catalog 라벨 기준 + 소수 별칭). 정책 RAG 무결과 시에만 사용.
FUNCTION_ALIASES = {"훈련": "vocational_training", "내일배움": "vocational_training",
                    "스마트공장": "technology_transition"}


def function_tags(question: str) -> list[str]:
    import re
    compact = re.sub(r"\s+", "", question or "")
    tags = [f["tag"] for f in C.functions()
            if any(len(w) >= 2 and w in compact for w in (x.replace(" ", "") for x in f["label"].split("·")))]
    tags += [tag for word, tag in FUNCTION_ALIASES.items() if word in compact]
    return list(dict.fromkeys(tags))


WEB_DOMAINS = (*TIER1_DOMAINS, "go.kr")  # 검색 힌트 + 사후 필터 기준(Tier 1 지정 기관, Tier 2 *.go.kr)

# LLM에 주는 지시 — 판정·수치·대상 확정 금지. 입력은 호출부가 고른 문자열뿐(세션 입력·담당자 정보 없음).
GENERAL_SYSTEM = (
    "당신은 제조업·고용 행정 용어를 설명하는 도우미입니다. 일반적인 개념만 한국어로 3~6문장으로 설명하세요. "
    "창원국가산단의 특정 업종 판정, 조치등급, E/R/A/P·Q1~Q3 값, 특정 기업의 지원 대상 여부나 원인은 말하지 마세요. "
    "모르는 내용은 추측하지 말고 모른다고 하세요.")
REPHRASE_SYSTEM = (
    "다음은 행정 시스템의 등록된 진단 문장입니다. 제공된 답변의 의미를 쉽게 다시 표현하세요.\n"
    "절대 추가하지 말 것: 새로운 사실, 새로운 숫자, 새로운 비율, 새로운 순위, 새로운 단계, 새로운 기간"
    "(예: '1년 전', '3개월'), 새로운 예시, 새로운 정책 자격, 새로운 신청 가능 여부, 새로운 인과관계.\n"
    "원문에 없는 숫자를 만들지 마세요. 숫자를 반올림·환산·풀어쓰기(예: 3.47% → 약 3%, 100명 중 3명)하지 마세요.\n"
    "원문에 있는 숫자는 값·단위·부호·소수점을 그대로 쓰세요. '2026Q2' 같은 분기 표기도 그대로 쓰세요.\n"
    "단계명(우선점검/추가확인/관찰)·업종명은 원문 그대로 쓰고, 원문의 한계 문구(원인 판정이 아님 등)는 유지하세요.\n"
    "원인을 단정하는 표현('~때문입니다', '원인은 ~입니다')과 지원 대상·선정·확정·추천·'받을 수 있습니다' 같은 "
    "표현을 쓰지 마세요. 판정 이유는 원문처럼 '판정 근거는 ~입니다'로 쓰세요.\n"
    "원문의 의미를 바꾸지 말고, 문장을 짧게 하며 어려운 표현만 쉬운 표현으로 바꾸세요. 5문장 이내.")
GROUNDED_SYSTEM = (
    "당신은 창원국가산단 산업·고용 전환진단 시스템의 행정 AI 비서입니다. 아래 '등록 진단 요약'만을 이 업종·분기에 관한 "
    "사실 근거로 쓰세요.\n"
    "- 질문이 이 업종·분기와 관련되면 요약에 있는 사실만으로 2~4문장으로 답하세요. 요약에 없는 숫자·비율·순위·판정·원인은 "
    "만들지 마세요.\n"
    "- 숫자와 분기 표기는 요약에 있는 그대로 쓰고 반올림하거나 풀어쓰지 마세요. 단계명(우선점검/추가확인/관찰)은 요약 그대로 쓰세요.\n"
    "- 지원사업·지원금·신청 가능 여부를 물으면 구체적인 사업명·금액은 말하지 말고, 완전한 문장으로 이렇게 안내하세요: "
    "'기존 공식 지원체계는 \"연결 가능한 공식 지원은?\"으로, 지금 모집 중인 공고는 \"현재 신청 가능한 지원사업은?\"으로 "
    "물어보시면 공식 근거로 확인해 드립니다.'\n"
    "- 질문이 모호하면 진단 결과·최근 채용 신호·현장 확인사항·연결 가능한 공식 지원 중 무엇을 확인할지 한 문장으로 되물으세요.\n"
    "- 질문이 산업·고용 진단과 무관하면(예: 날씨) 이 비서가 창원국가산단의 산업·고용 진단과 정책 연계를 지원한다고 "
    "한 문장으로 알려 주세요.\n"
    "- 원인을 단정하거나('~때문입니다') 지원 대상·선정·적격·추천을 확정하는 표현을 쓰지 마세요.")
RAG_SYSTEM = (
    "공식 문서 발췌만 근거로 질문에 답하세요. 발췌에 없는 금액·기간·대상은 쓰지 마세요. "
    "개별 기업의 적격·승인·지급을 확정하지 말고, 담당기관 확인이 필요하다고 덧붙이세요.")

EXAMPLES = ("이 업종이 왜 우선점검인가?", "E값은?", "Q1 상태 알려줘", "현장에서 뭘 확인해야 해?",
            "직전 분기 대비 판정 변화는?", "현재 신청 가능한 고용유지 사업 있어?")
CAPABILITY_TEXT = (
    "이 Copilot은 선택한 업종·분기에 대해 다음을 답합니다.\n"
    "- 등록된 진단결과: 조치등급과 판정 근거, E/R/A/P 신호값, Q1~Q3, 이전 분기 대비 변화, 업종 비교, "
    "Work24 채용 스냅샷, 현장 확인 질문, 자료의 한계\n"
    "- 공식문서 기반: 지원사업·지원금·훈련·담당기관 등 색인된 공식 원문 근거\n"
    "- 외부 최신정보·일반 AI 설명: provider가 설정된 경우에만(현재 설정 여부는 답변 배지로 표시)\n"
    "원인을 확정하거나 지원 대상·사업을 자동 선정하지 않습니다.")


class Copilot:
    def __init__(self, service, llm: LLMProvider | None = None, web: WebSearchProvider | None = None,
                 audit: AuditSink | None = None, today=None, *, summarize_rag: bool = False,
                 official_apis: list | None = None, compose_with_llm: bool = False):
        self.service = service
        # 정책 RAG·기업마당을 뺀 나머지 답변을 LLM(Gemini)이 등록 진단 근거로 작성한다(수치·판정 보존 검증, 실패 시 원문).
        # 생성자 기본은 꺼짐 — 앱은 from_env(COPILOT_LLM_COMPOSE, 기본 all)로 켠다.
        self.compose_with_llm = compose_with_llm
        self.official_apis = list(official_apis or [])  # 공식 구조화 API(예: 기업마당) — 최신 공고 1순위
        self.internal = InternalDiagnostics(service)
        self.llm = llm or NullLLMProvider()
        self.web = web or NullWebSearchProvider()
        self.audit = audit or NullAuditSink()
        self._today = today or date.today
        self.summarize_rag = summarize_rag  # 정책 RAG 결과 LLM 요약(기본 꺼짐 — 명시적으로 켤 때만)

    @classmethod
    def from_env(cls, service, audit: AuditSink | None = None, env: dict | None = None) -> "Copilot":
        import os
        llm, web = providers_from_env(env)
        env = os.environ if env is None else env
        return cls(service, llm, web, audit, summarize_rag=env.get("COPILOT_LLM_RAG_SUMMARY") == "1",
                   official_apis=official_apis_from_env(None if env is os.environ else env),
                   compose_with_llm=env.get("COPILOT_LLM_COMPOSE", "all").strip().lower() != "off")

    # ------------------------------------------------------------ 진입점
    def ask(self, question: str, quarter: str, industry: str, *, comparison_industry: str | None = None,
            field_context: dict | None = None) -> dict:
        started = time.perf_counter()
        snap = self.service.snapshot
        decision = R.route(question, list(snap.industries), list(snap.quarters))
        trace = [{"stage": "ROUTER", "route": decision.route, "intent": decision.intent,
                  "needs_recency": decision.needs_recency, "reason": decision.reason}]
        target_industry, target_quarter, comparison = self._target(decision, quarter, industry, comparison_industry)
        usage = {"llm": False, "web": False, "domains": (), "error": None, "provider": None, "model": None}
        if decision.route == INTERNAL_DIAGNOSTIC:
            ans = self._diagnostic(decision, target_quarter, target_industry, comparison, field_context, trace, usage)
        elif decision.route == INTERNAL_RAG:
            ans = self._policy(decision, question, target_quarter, target_industry, trace, usage)
        elif decision.route == EXTERNAL_WEB:
            ans = self._web_only(decision, question, target_quarter, target_industry, trace, usage)
            if ans.source_type == SYSTEM and self._composing():  # 외부 검색 결과가 없으면 등록 진단 근거로 Gemini가 답한다
                ans = self._grounded(decision, question, target_quarter, target_industry, ans, trace, usage)
        elif decision.route == GENERAL_LLM:
            ans = self._general(decision, question, trace, usage)
        else:
            ans = self._system(decision)
            if self._composing():  # 인사·범위 밖·짧은 질문 → 등록 진단 요약 근거의 Gemini 답변
                ans = self._grounded(decision, question, target_quarter, target_industry, ans, trace, usage)
        ans.route_trace = trace + ans.route_trace
        ans = guardrails.finalize(ans)
        self._record(question, decision, ans, usage, started)
        return ans.to_dict()

    def _target(self, decision: R.RouteDecision, quarter: str, industry: str, comparison: str | None):
        inds = decision.industries
        if decision.intent == R.COMPARE and len(inds) >= 2:
            return inds[0], decision.quarter or quarter, inds[1]
        target = inds[0] if len(inds) == 1 else industry
        if decision.intent == R.COMPARE and comparison is None and len(inds) == 1 and inds[0] != industry:
            return industry, decision.quarter or quarter, inds[0]
        return target, decision.quarter or quarter, comparison

    # ------------------------------------------------------------ ① 등록 진단
    def _diagnostic(self, decision, quarter, industry, comparison, field_context, trace, usage) -> CopilotAnswer:
        ans = self.internal.answer(decision, quarter, industry, comparison_industry=comparison,
                                   field_context=field_context)
        trace.append({"stage": INTERNAL_DIAGNOSTIC, "status": ans.answer_type})
        if decision.intent == R.REPHRASE:
            ans = self._rephrase(ans, quarter, industry, trace, usage)
        elif self._composing() and decision.intent != R.COMPARE:
            # 비교는 화면이 등록 수치로 구조화해 보여주므로 제외. 나머지 등록 진단 답변은 Gemini가 같은 근거로 다시 쓴다.
            ans = self._rephrase(ans, quarter, industry, trace, usage, compose=True)
        return ans

    def _composing(self) -> bool:
        return self.compose_with_llm and self.llm.available

    def _rephrase(self, base: CopilotAnswer, quarter, industry, trace, usage, compose: bool = False) -> CopilotAnswer:
        """등록 답변(read-only)을 LLM이 바꿔 쓰고, 수치·단계 보존 검증 통과분만 쓴다.

        compose=False: 사용자가 쉬운 설명을 명시적으로 요청한 경우. compose=True: Gemini 작성 모드(COPILOT_LLM_COMPOSE)에서
        모든 등록 진단 답변에 적용. 검증 실패·호출 실패 시 두 경우 모두 등록 원문을 그대로 쓴다.
        """
        if base.source_type != INTERNAL_DIAGNOSTIC:
            return base
        stage_name = "COMPOSE_LLM" if compose else "REPHRASE_LLM"
        if not self.llm.available:
            trace.append({"stage": stage_name, "status": "NOT_CONFIGURED"})
            base.caveats = [*base.caveats, "쉬운 설명(LLM) 기능이 설정되지 않아 등록 답변을 그대로 표시합니다."]
            return base
        rec = self.service.snapshot.get(industry, quarter)
        stage = rec["triage"]["stage"] if rec else None
        usage["llm"] = True
        result = self.llm.generate(base.answer, system=REPHRASE_SYSTEM)  # 입력 = 등록 답변 문장뿐
        if not result.ok:
            usage["error"] = result.error
            trace.append({"stage": stage_name, "status": "FAILED", "error": result.error})
            base.caveats = [*base.caveats, ("Gemini 답변 작성에 실패해 등록 답변을 그대로 표시합니다." if compose
                                            else "쉬운 설명을 만들지 못해 등록 답변을 그대로 표시합니다.")]
            return base
        ok, why = guardrails.check_rewrite(base.answer, result.text, stage)
        trace.append({"stage": stage_name, "status": "ACCEPTED" if ok else "REJECTED", "check": why,
                      **({"matched": guardrails.assertive(result.text)[:3]} if why == "ASSERTIVE" else {})})
        if not ok:
            base.caveats = [*base.caveats, "AI 문장이 수치·판정 보존 검증을 통과하지 못해 등록 답변을 그대로 표시합니다."
                            if compose else "AI 쉬운 설명이 수치·판정 보존 검증을 통과하지 못해 등록 답변을 그대로 표시합니다."]
            base.guardrail = f"{'COMPOSE' if compose else 'REPHRASE'}_REJECTED:{why}"
            return base
        base.evidence = [*base.evidence, {"registered_answer": base.answer}]
        base.caveats = [*base.caveats, ("Gemini가 등록 진단 답변을 근거로 작성했습니다. 수치·판정이 원문과 같은지 자동 검증했으며, "
                                        "원문은 근거(evidence)에 남아 있습니다." if compose else
                                        "AI가 등록 답변을 쉬운 말로 바꾼 것입니다. 수치·판정이 원문과 같은지 자동 검증했으며, "
                                        "원문은 근거(evidence)에 남아 있습니다.")]
        base.answer, base.composer = result.text, "LLM"
        base.official_evidence_sufficient = True  # 등록 진단 원문이 근거
        return base

    # ------------------------------------------------------------ ② 정책 RAG
    def _policy(self, decision, question, quarter, industry, trace, usage) -> CopilotAnswer:
        if decision.intent == R.SUPPORT_FUNCTIONS:
            ans = self.internal.answer(decision, quarter, industry)
            trace.append({"stage": INTERNAL_RAG, "status": "SUPPORT_FUNCTION_CARDS", "cards": len(ans.citations)})
            return ans
        terms = sufficiency.topic_terms(question)
        if not terms and not decision.needs_recency:
            cards = self.service.context(quarter, industry)["requirement_cards"]
            trace.append({"stage": INTERNAL_RAG, "status": "INDUSTRY_REQUIREMENT_CARDS", "cards": len(cards)})
            if cards:
                return self._cards_answer(decision, cards, industry, quarter)
        rag = self.service.rag.search(question, namespace="official", current_only=False)
        meta = self._doc_meta([h["document_id"] for h in rag.get("hits", [])])
        suff = sufficiency.evaluate(rag, question, needs_recency=decision.needs_recency, doc_meta=meta,
                                    today=self._today())
        trace.append({"stage": INTERNAL_RAG, "status": rag["status"], "sufficient": suff.sufficient,
                      "topic_terms": suff.topic_terms, "reasons": suff.reasons[:5]})
        # 최신 공고 보완(BIZINFO): '현재·지금·모집 중·신청 가능' 질문에서만 호출. 정책 RAG를 대체하지 않는다.
        biz = self._official(decision, question, quarter, industry, trace, usage) if decision.needs_recency else None
        if suff.sufficient:
            ans = self._rag_answer(decision, rag, suff.usable_hits, meta, sufficient=True)
            ans = self._summarize(ans, question, suff.usable_hits, trace, usage) if self.summarize_rag else ans
            return self._attach_bizinfo(ans, biz, decision, quarter, industry)
        insufficient = "색인된 공식 원문만으로는 충분하지 않습니다: " + "; ".join(suff.reasons[:3])
        if biz and biz["items"]:  # 공식 API가 접수 중 공고를 직접 뒷받침 → Grounding 불필요
            if rag.get("hits"):
                ans = self._rag_answer(decision, rag, rag["hits"], meta, sufficient=False)
                ans.caveats = [*ans.caveats, insufficient]
            else:
                ans = CopilotAnswer(
                    answer="색인된 공식 원문에서는 이 질문의 제도 근거를 찾지 못했습니다.", source_type=EXTERNAL_WEB,
                    route=decision.route, intent=decision.intent, answer_type="OFFICIAL_API",
                    official_evidence_sufficient=False, target={"industry": industry, "quarter": quarter})
            return self._attach_bizinfo(ans, biz, decision, quarter, industry)
        web = self._web(decision, question, quarter, industry, trace, usage)  # Grounding: 기능 플래그가 켜진 경우만
        if web is not None:
            return web
        if rag.get("hits"):
            ans = self._rag_answer(decision, rag, rag["hits"], meta, sufficient=False)
            ans.caveats = [*ans.caveats, insufficient]
            if decision.needs_recency and biz is None:
                ans.caveats.append("최신 공고 조회(기업마당·외부 검색)가 설정되지 않아 현재 모집 여부는 실시간 확인하지 못했습니다."
                                   if not self.web.available else
                                   "외부 공식 도메인에서 인용 가능한 최신 정보를 찾지 못해 현재 모집 여부를 확인하지 못했습니다.")
            return self._attach_bizinfo(ans, biz, decision, quarter, industry)
        tags = function_tags(question)
        cards = self.service.requirement_cards(tags) if tags else []
        trace.append({"stage": INTERNAL_RAG, "status": "FUNCTION_REQUIREMENT_CARDS", "tags": tags, "cards": len(cards)})
        if cards:
            labels = ", ".join(C.label(tag) for tag in tags)
            ans = self._cards_answer(decision, cards, industry, quarter,
                                     heading=f"질문과 관련된 지원 기능({labels})에 연결된 공식 요건 카드입니다.")
            return self._attach_bizinfo(ans, biz, decision, quarter, industry)
        ans = CopilotAnswer(
            answer="색인된 공식 원문에서 이 질문의 근거를 찾지 못했습니다. "
                   "지원 대상이나 사업을 추정해 답하지 않습니다 — 담당기관 공식 안내를 확인하세요.",
            source_type=SYSTEM, route=decision.route, intent=decision.intent, answer_type="NO_OFFICIAL_EVIDENCE",
            official_evidence_sufficient=False, target={"industry": industry, "quarter": quarter})
        return self._attach_bizinfo(ans, biz, decision, quarter, industry)

    def _summarize(self, ans: CopilotAnswer, question: str, hits: list[dict], trace, usage) -> CopilotAnswer:
        """충분한 공식 hit만 근거로 LLM 요약. 인용·숫자 검증 실패 시 결정론 목록 그대로."""
        if not self.llm.available:
            return ans
        sources = [SourceDoc(id=f"{h['document_id']}:{h.get('page') or h.get('section')}", title=h["title"],
                             text=h.get("excerpt") or "", url=h.get("source_url"), checked_at=h.get("verified_at"))
                   for h in hits[:5]]
        usage["llm"] = True
        result = self.llm.generate_with_sources(question, sources, system=RAG_SYSTEM)
        extra = (guardrails.numbers_supported(result.text, [f"{s.title} {s.text}" for s in sources])
                 if result.ok else set())
        ok = result.ok and not extra and not guardrails.assertive(result.text)
        trace.append({"stage": "RAG_SUMMARY_LLM", "status": "ACCEPTED" if ok else "REJECTED",
                      "error": result.error, "unsupported_numbers": sorted(extra)})
        if not ok:
            usage["error"] = usage["error"] or result.error
            return ans
        listing = ans.answer.split("\n", 1)[-1]
        ans.answer = f"{result.text}\n\n근거 원문:\n{listing}"
        ans.composer = "LLM"
        return ans

    def _doc_meta(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        with self.service.Session() as s:
            rows = s.execute(select(M.DocumentMaster.document_id, M.DocumentMaster.official,
                                    M.DocumentMaster.institution).where(M.DocumentMaster.document_id.in_(set(ids))))
            return {r.document_id: {"official": bool(r.official), "institution": r.institution} for r in rows}

    def _rag_answer(self, decision, rag, hits, meta, *, sufficient: bool) -> CopilotAnswer:
        lines, citations, seen = [], [], set()
        for hit in hits:
            locator = f"{hit['page']}쪽" if hit.get("page") else (hit.get("section") or "본문")
            lines.append(f"- {hit['document_id']} {hit['title']} · {locator} · 접수 {hit.get('current_intake_status')}"
                         f" · 확인 {hit.get('verified_at')}")
            key = (hit["document_id"], locator)
            if hit.get("source_url") and key not in seen:
                seen.add(key)
                citations.append(Citation(title=f"{hit['document_id']} {hit['title']}", url=hit["source_url"],
                                          source_type=INTERNAL_RAG, official=bool(meta.get(hit["document_id"], {}).get("official")),
                                          institution=meta.get(hit["document_id"], {}).get("institution"),
                                          checked_at=hit.get("verified_at"), locator=locator))
        return CopilotAnswer(answer=f"{rag['message']}\n" + "\n".join(lines[:5]), source_type=INTERNAL_RAG,
                             route=decision.route, intent=decision.intent, answer_type="OFFICIAL_POLICY_RAG",
                             citations=citations[:5], official_evidence_sufficient=sufficient,
                             evidence=[{k: h.get(k) for k in ("document_id", "page", "section", "score")} for h in hits[:5]])

    def _cards_answer(self, decision, cards, industry, quarter, heading: str | None = None) -> CopilotAnswer:
        lines = [f"- {c.get('title')} · {c.get('institution') or '기관 확인 필요'} · 접수 {c.get('current_intake_status')}"
                 f" · 확인 {c.get('verified_at')}" for c in cards]
        return CopilotAnswer(
            answer=(heading or f"{industry}의 지원 기능 후보와 연결되는 공식 요건 카드입니다.")
                   + " 연계 검토 후보이며 개별 적격·신청·승인·"
                   "지급을 자동 판정하지 않습니다.\n" + "\n".join(lines),
            source_type=INTERNAL_RAG, route=decision.route, intent=decision.intent, answer_type="REQUIREMENT_CARDS",
            citations=[Citation(title=c.get("title") or "요건 카드", url=c["source_url"], source_type=INTERNAL_RAG,
                                official=True, institution=c.get("institution"), checked_at=c.get("verified_at"))
                       for c in cards if c.get("source_url")],
            official_evidence_sufficient=True, target={"industry": industry, "quarter": quarter})

    # ------------------------------------------------------------ ③ 외부: 공식 API → 공식 도메인 grounding
    def _authority_note(self, decision, quarter, industry) -> str:
        """외부 자료가 등록 진단을 대체하지 않음을 밝힌다(업종·동향 문맥일 때)."""
        if not (decision.industries or decision.intent == R.TREND):
            return ""
        rec = self.service.snapshot.get(industry, quarter)
        if not rec:
            return ""
        return (f"\n\n※ 외부 자료는 대상·시점이 달라 본 시스템의 등록 진단({quarter} 창원국가산단 {industry}: "
                f"{rec['triage']['stage']})을 대체하지 않습니다. 등록 진단이 기준입니다.")

    def _official(self, decision, question, quarter, industry, trace, usage) -> dict | None:
        """최신 공식 공고(BIZINFO) 조회 → 결정론 view model. API 미설정이면 None, 장애면 status=UNAVAILABLE.

        접수상태·지역·업종 판정은 provider의 결정론 파서가 하고, LLM에는 넘기지 않는다.
        """
        if not self.official_apis:
            return None
        api = self.official_apis[0]
        if not api.available:
            trace.append({"stage": "OFFICIAL_API", "provider": api.name, "status": "NOT_CONFIGURED"})
            return None
        industries = set(self.service.snapshot.industries)
        # 업종어('제조업'·'기계업종' 등)는 거르는 조건이 아니라 업종 근거 표시에 쓴다 — 그 밖의 주제어만 필터
        topic = [t for t in sufficiency.topic_terms(question)
                 if not any(name in t for name in industries) and t not in ("제조업", "제조", "업종", "중소기업")]
        usage.update(web=True, provider=api.name, model=None, domains=("bizinfo.go.kr",))
        result = api.search(question, terms=topic, today=self._today(), industry_terms=tuple(decision.industries))
        status = "OK" if result.ok else ("NO_MATCH" if result.error in ("NO_MATCHING_OPEN_ITEMS", "EMPTY")
                                         else "UNAVAILABLE")
        if status == "UNAVAILABLE":
            usage["error"] = result.error
        meta = result.meta or {}
        trace.append({"stage": "OFFICIAL_API", "provider": api.name, "status": status, "error": result.error,
                      "raw": result.raw_result_count, "kept": len(result.results), "topic_terms": topic})
        return {"provider": api.name, "status": status, "error": result.error, "items": meta.get("items") or [],
                "status_counts": meta.get("status_counts") or {}, "fetched": meta.get("fetched"),
                "total_count": meta.get("total_count"), "region_filter": meta.get("region_filter"),
                "checked_at": meta.get("checked_at") or self._today().isoformat(), "topic_terms": topic,
                "eligibility_verified": False,
                "citations": [Citation(title=r.title, url=r.url, source_type=EXTERNAL_WEB, official=True,
                                       institution=r.institution, checked_at=r.retrieved_at, tier=r.tier)
                              for r in result.results]}

    def _attach_bizinfo(self, ans: CopilotAnswer, biz: dict | None, decision, quarter, industry) -> CopilotAnswer:
        """정책 RAG 답변 뒤에 '현재 모집 공고' 구역을 따로 붙인다(RAG 문장과 섞지 않음)."""
        if biz is None:
            return ans
        ans.meta = {**ans.meta, "bizinfo": {k: v for k, v in biz.items() if k != "citations"}}
        scope = (f"조회 범위: 기업마당 {biz.get('region_filter') or ''} 태그 공고 중 최근 등록 {biz.get('fetched') or 0}건"
                 + (f"(전체 {biz['total_count']:,}건)" if biz.get("total_count") else "")
                 + ". 신청기간 날짜로 접수 중이 확인된 공고만 표시합니다.")
        head = f"[현재 모집 공고 · 기업마당 공식 API · {biz['checked_at']} 조회]"
        if biz["status"] == "UNAVAILABLE":
            ans.caveats = [*ans.caveats, "기업마당 조회가 되지 않아 현재 모집 여부는 실시간 확인하지 못했습니다."]
            return ans
        if not biz["items"]:
            ans.answer += f"\n\n{head}\n{scope}\n관련된 접수 중 공고를 찾지 못했습니다."
            return ans
        lines = []
        for item in biz["items"]:
            agency = " / ".join(x for x in (item.get("agency"), item.get("executor")) if x) or "기관 확인 필요"
            lines.append(f"- {item['title']} · 소관·수행 {agency} · 접수 {item['start']}~{item['end']}(접수 중)"
                         f" · 대상 {item.get('target') or '공고 확인'} · 지역: {item['region_match']['evidence']}"
                         f" · 업종: {item['industry_match']['evidence']}")
        ans.answer += (f"\n\n{head}\n{scope}\n" + "\n".join(lines)
                       + "\n실제 신청 가능 여부는 공고의 세부 자격 확인이 필요합니다."
                       + self._authority_note(decision, quarter, industry))
        ans.citations = [*ans.citations, *biz["citations"]]
        return ans

    def _web(self, decision, question, quarter, industry, trace, usage) -> CopilotAnswer | None:
        """Gemini Google Search grounding → 공식 도메인 인용 문장만. 미설정·실패·인용 없음이면 None."""
        if not self.web.available:
            trace.append({"stage": EXTERNAL_WEB, "status": "NOT_CONFIGURED"})
            return None
        usage.update(web=True, provider=self.web.name, model=self.web.model)
        result = self.web.search(question, domains=WEB_DOMAINS)  # 질문 문장만(세션 입력·진단값 없음)
        step = {"stage": EXTERNAL_WEB, "status": "OK" if result.ok else "NO_OFFICIAL_RESULT", "error": result.error,
                "raw": result.raw_result_count, "kept": len(result.results)}
        trace.append(step)
        if not result.ok:
            usage["error"] = result.error if result.error not in ("NO_OFFICIAL_SUPPORT",) else None
            return None
        # 단정 표현(대상·선정·원인 확정) 문장은 뺀다 — 남는 문장이 없으면 외부 답변을 쓰지 않는다
        segments = result.meta.get("segments") or [{"text": result.answer, "marks": ""}]
        sentences = [f"{s['text']} {s['marks']}".strip() for s in segments]
        kept = [s for seg, s in zip(segments, sentences) if not guardrails.assertive(seg["text"])]
        step["assertive_removed"] = len(sentences) - len(kept)
        if not kept:
            step["status"] = "ALL_SENTENCES_REMOVED"
            return None
        usage["domains"] = tuple(dict.fromkeys(r.domain for r in result.results if r.domain))
        return CopilotAnswer(
            answer=" ".join(kept) + self._authority_note(decision, quarter, industry),
            source_type=EXTERNAL_WEB, route=decision.route, intent=decision.intent, answer_type="WEB_GROUNDED",
            composer="LLM",
            citations=[Citation(title=r.title, url=r.url, source_type=EXTERNAL_WEB, official=True,
                                institution=r.institution, checked_at=r.retrieved_at, tier=r.tier)
                       for r in result.results],
            official_evidence_sufficient=False, target={"industry": industry, "quarter": quarter},
            meta={"search_entry_point": result.meta.get("search_entry_point")})

    def _web_only(self, decision, question, quarter, industry, trace, usage) -> CopilotAnswer:
        web = self._web(decision, question, quarter, industry, trace, usage)
        if web is not None:
            return web
        note = ""
        if decision.industries:
            rec = self.service.snapshot.get(industry, quarter)
            if rec:
                note = (f"\n참고로 본 시스템의 등록 진단({quarter} {industry})은 {rec['triage']['stage']}이며, "
                        "외부 동향 자료로 이 판정을 바꾸지 않습니다.")
        configured = self.web.available
        return CopilotAnswer(
            answer="최신 동향은 등록 진단·공식 원문 색인 범위 밖이며, "
                   + ("외부 공식 도메인에서 인용 가능한 최신 정보를 찾지 못했습니다." if configured
                      else "외부 최신정보 검색이 아직 설정되지 않았습니다.") + note,
            source_type=SYSTEM, route=decision.route, intent=decision.intent,
            answer_type="WEB_NO_OFFICIAL_RESULT" if configured else "WEB_NOT_CONFIGURED",
            target={"industry": industry, "quarter": quarter})

    # ------------------------------------------------------------ ④ 일반 LLM(P1)
    def _general(self, decision, question, trace, usage) -> CopilotAnswer:
        if not self.llm.available:
            trace.append({"stage": GENERAL_LLM, "status": "NOT_CONFIGURED"})
            return CopilotAnswer(
                answer="일반 개념 설명(AI) 기능이 아직 설정되지 않았습니다. 등록된 진단 내용으로 대신 답하지 않습니다.",
                source_type=SYSTEM, route=decision.route, intent=decision.intent, answer_type="LLM_NOT_CONFIGURED")
        usage["llm"] = True
        result = self.llm.generate(question, system=GENERAL_SYSTEM)  # 질문 문장만(진단값·세션 입력 없음)
        if not result.ok:
            usage["error"] = result.error
            trace.append({"stage": GENERAL_LLM, "status": "FAILED", "error": result.error})
            return CopilotAnswer(answer="일반 개념 설명을 지금 만들지 못했습니다. 잠시 후 다시 시도하세요.",
                                 source_type=SYSTEM, route=decision.route, intent=decision.intent,
                                 answer_type="LLM_FAILED")
        if guardrails.mentions_internal_judgment(result.text):
            trace.append({"stage": GENERAL_LLM, "status": "REJECTED", "check": "INTERNAL_JUDGMENT"})
            return CopilotAnswer(answer="일반 설명에 본 시스템의 판정·신호에 대한 서술이 섞여 표시하지 않습니다. "
                                        "판정·신호는 등록 진단 질문(예: 'E값은?', '왜 우선점검인가?')으로 확인하세요.",
                                 source_type=SYSTEM, route=decision.route, intent=decision.intent,
                                 answer_type="LLM_REJECTED", guardrail="BLOCKED_INTERNAL_JUDGMENT")
        trace.append({"stage": GENERAL_LLM, "status": "ACCEPTED"})
        return CopilotAnswer(answer=result.text, source_type=GENERAL_LLM, route=decision.route,
                             intent=decision.intent, answer_type="GENERAL_CONCEPT", composer="LLM")

    # ------------------------------------------------------------ ④-2 등록 진단 요약 근거의 LLM 답변(Gemini 작성 모드)
    def _diagnosis_summary(self, quarter: str, industry: str) -> tuple[str, str | None]:
        """LLM에 줄 근거 = 등록 진단 값만(세션 입력·담당자 정보 없음). (요약문, 등록 단계)"""
        d = self.service.diagnosis(quarter, industry)
        if d.get("status") != "FOUND":
            return f"업종 {industry} · 분기 {quarter} · 등록 진단 없음", None
        num = lambda v, digits=2: "자료 없음" if v is None else (f"{v:,}" if isinstance(v, int) else f"{v:.{digits}f}")
        q1, q2, q3, t = d["q1"], d["q2"], d["q3"], d["triage"]
        summary = (f"업종 {industry} · 분기 {quarter} · 등록 판정 {t['stage']} · 판정 근거: {t['reason']} · "
                   f"Q1 상태 {q1['state']}({q1['state_label']}) · 생산 YoY {num(q1['production_yoy'], 1)}% · "
                   f"고용 증감 {num(q2['employment_change'])}명 · 고용 YoY {num(q2['employment_yoy'])}% · "
                   f"동일 상태 지속 {num(q3['duration'])}분기 · 자료 기준 {d['data_cutoff']} · "
                   "통계 신호는 원인을 확정하지 않으며 현장 확인이 필요함")
        return summary, t["stage"]

    def _grounded(self, decision, question, quarter, industry, fallback: CopilotAnswer, trace, usage) -> CopilotAnswer:
        """범위 밖·짧은 질문(과 외부검색 미설정)도 Gemini가 답하되, 등록 진단 요약만 근거로 쓰고 수치 보존을 검증한다.

        호출·검증 실패 시 원래 답변(fallback)을 그대로 돌려준다 — 화면은 그때 되묻기/범위 안내를 보여준다.
        """
        summary, stage = self._diagnosis_summary(quarter, industry)
        usage["llm"] = True
        result = self.llm.generate(f"[등록 진단 요약]\n{summary}\n\n[질문]\n{question}", system=GROUNDED_SYSTEM)
        if not result.ok:
            usage["error"] = result.error
            trace.append({"stage": "GROUNDED_LLM", "status": "FAILED", "error": result.error})
            return fallback
        ok, why = guardrails.check_rewrite(f"{summary} {question}", result.text, stage)
        trace.append({"stage": "GROUNDED_LLM", "status": "ACCEPTED" if ok else "REJECTED", "check": why})
        if not ok:
            fallback.guardrail = f"GROUNDED_REJECTED:{why}"
            return fallback
        return CopilotAnswer(
            answer=result.text, source_type=INTERNAL_DIAGNOSTIC, route=decision.route, intent=decision.intent,
            answer_type="LLM_GROUNDED", composer="LLM", evidence=[{"registered_summary": summary}],
            caveats=["Gemini가 등록 진단 요약만 근거로 작성했습니다. 수치·판정이 등록값과 같은지 자동 검증했습니다."],
            official_evidence_sufficient=False, target={"industry": industry, "quarter": quarter})

    # ------------------------------------------------------------ 인사·안내·미지원
    def _system(self, decision) -> CopilotAnswer:
        if decision.route == GREETING:
            text = "안녕하세요. 선택한 업종·분기의 등록 진단과 공식 근거를 바탕으로 답합니다.\n" + CAPABILITY_TEXT
            answer_type = "GREETING"
        elif decision.route == CAPABILITY:
            text, answer_type = CAPABILITY_TEXT, "CAPABILITY"
        else:
            text = ("이 질문은 Copilot 지원 범위 밖이라 답하지 않습니다. 현재 업종 진단으로 대신 답하지 않습니다.\n"
                    "질문 예: " + " · ".join(EXAMPLES))
            answer_type = "UNSUPPORTED"
        return CopilotAnswer(answer=text, source_type=SYSTEM, route=decision.route, intent=decision.intent,
                             answer_type=answer_type)

    # ------------------------------------------------------------ 감사 기록
    def _record(self, question: str, decision, ans: CopilotAnswer, usage: dict, started: float) -> None:
        provider, model = usage.get("provider"), usage.get("model")
        if provider is None and usage["llm"]:
            provider, model = self.llm.name, self.llm.model
        self.audit.record(AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            question_digest=question_digest(question), route=decision.route, intent=decision.intent,
            source_type=ans.source_type, provider=provider or "none", model=model,
            llm_used=usage["llm"], web_search_used=usage["web"], searched_domains=tuple(usage["domains"]),
            citation_count=len(ans.citations), latency_ms=int((time.perf_counter() - started) * 1000),
            success=usage["error"] is None, guardrail=ans.guardrail, error=usage["error"],
            stages=tuple(step.get("stage", "") for step in ans.route_trace)))
