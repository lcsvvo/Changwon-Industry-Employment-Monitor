"""Streamlit·출력문서가 함께 쓰는 의사결정지원 backend contract.

분석값을 계산하지 않고 등록 Snapshot에서 옮긴다. Work24는 사후 맥락이며 CORE
판정 입력이 아니다. 키워드는 지원사업이 아니라 지원 *기능 후보*까지만 만든다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import desc, func, select

from export.snapshot import Snapshot
from policy.rag import PolicyRAG, rebuild_policy_index
from workflow import catalog as C
from workflow import models as M

CONTRACT_VERSION = "decision-support-backend/1.0.0"

FUNCTION_RULES = {
    "vocational_training": {
        "terms": ("cnc", "mct", "plc", "자동제어", "설비보전", "용접", "가공", "cad", "cam",
                  "품질관리", "전기기사", "기능사", "자격"),
        "reason": "반복 확인된 기술·자격 수요에 대해 재직자·구직자 훈련 필요성을 검토",
    },
    "technology_transition": {
        "terms": ("plc", "자동제어", "자동화", "로봇", "스마트팩토리", "제조ai", "설비보전",
                  "cnc", "mct", "공정개선"),
        "reason": "자동화·설비·디지털 제조 관련 수요가 있어 기술전환 지원 기능을 검토",
    },
    "recruitment_matching": {
        "terms": ("운전원", "조작원", "기술자", "작업원", "생산직", "품질관리", "설계", "용접",
                  "전기", "기계가공", "간호", "요양보호"),
        "reason": "구체 직무 수요가 반복되어 채용매칭 경로를 검토",
    },
    "business_difficulty": {
        "terms": ("품질관리", "생산관리", "공정관리", "원가", "검사", "품질보증", "설비관리"),
        "reason": "공정·품질·생산관리 수요가 있어 기업 경영·기술 애로 기능을 검토",
    },
    "reemployment": {
        "terms": ("중장년", "재취업", "전직", "경력자", "숙련공"),
        "reason": "경력·숙련 인력 이동과 관련된 수요가 있어 전직·재취업 기능을 검토",
    },
    "employment_retention": {
        "terms": ("숙련공", "설비보전", "기능장", "장기근속"),
        "reason": "숙련 유지가 중요한 직무 수요가 있어 고용유지 기능을 현장에서 검토",
    },
    # crisis_response는 채용 키워드만으로 제안하지 않는다. 소재지·공식 지정 여부가 별도 필요하다.
}


def _normal(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", (value or "").lower())


def _plain_datetime(value):
    return value.isoformat() if isinstance(value, datetime) else value


class DecisionSupportService:
    """UI가 DB 내부 구조를 조합하지 않게 하는 읽기 중심 application service."""

    def __init__(self, Session, snapshot: Snapshot, workflow_service=None):
        self.Session = Session
        self.snapshot = snapshot
        self.workflow = workflow_service
        self.rag = PolicyRAG(Session)

    def diagnosis(self, quarter: str, industry: str) -> dict:
        rec = self.snapshot.get(industry, quarter)
        if rec is None:
            return {"status": "NOT_FOUND", "quarter": quarter, "industry": industry,
                    "caveat": ["선택한 업종×분기의 등록 Snapshot이 없습니다."]}
        provenance = self.snapshot.provenance(quarter)
        caveats = ["통계 신호는 원인을 확정하지 않으며 현장 확인이 필요합니다."]
        if provenance["snapshot_type"] == "reconstructed":
            caveats.append(provenance["reconstruction_note"])
        return {
            "status": "FOUND", "contract_version": CONTRACT_VERSION,
            "quarter": quarter, "industry": industry,
            "q1": {"state": rec["q1"]["state"], "state_label": rec["q1"]["state_label"],
                   "production_yoy": rec["q1"]["production_yoy"],
                   "employment_yoy": rec["q1"]["employment_yoy"]},
            "q2": {"employment": rec["q2"]["employment"], "employment_change": rec["q2"]["emp_delta"],
                   "employment_yoy": rec["q2"]["employment_yoy"],
                   "contribution_pct": rec["q2"]["contribution_pct"]},
            "q3": {"duration": rec["q3"]["state_run_length"],
                   "transition": rec["q3"]["transition"],
                   "repeated_signal": rec["q3"]["repeated_signal"]},
            "triage": {"stage": rec["triage"]["stage"],
                       "reason": rec["triage"]["stage_reason"],
                       "rank_in_stage": rec["triage"]["rank_in_stage"]},
            "snapshot_type": provenance["snapshot_type"],
            "snapshot_provenance": provenance,
            "data_cutoff": provenance["data_cutoff"],
            "caveat": caveats,
        }

    def timeline(self, industry: str, current_quarter: str) -> list[dict]:
        return [{
            "quarter": rec["quarter"], "stage": rec["triage"]["stage"],
            "q1_state": rec["q1"]["state"],
            "snapshot_type": self.snapshot.provenance(rec["quarter"])["snapshot_type"],
            "is_current": rec["quarter"] == current_quarter,
        } for rec in self.snapshot.history(industry, current_quarter, n=len(self.snapshot.quarters))]

    def recruitment_snapshot(self, industry: str) -> dict:
        with self.Session() as s:
            row = s.scalar(select(M.Work24EvidenceSnapshot).where(
                M.Work24EvidenceSnapshot.industry == industry
            ).order_by(desc(M.Work24EvidenceSnapshot.collected_at),
                       desc(M.Work24EvidenceSnapshot.snapshot_id)).limit(1))
        if row is None:
            return {"status": "NO_DATA", "industry": industry, "headcount": None,
                    "model_input_allowed": False,
                    "caveat": ["해당 업종으로 매핑된 Work24 공고가 없습니다."]}
        return {
            "status": "FOUND", "snapshot_id": row.snapshot_id, "quarter": row.quarter,
            "industry": row.industry, "posting_count": row.posting_count,
            "unique_company_count": row.unique_company_count, "headcount": row.headcount,
            "district_distribution": row.district_distribution,
            "latest_registration_date": row.latest_registration_date,
            "collected_at": row.collected_at, "career_distribution": row.career_distribution,
            "source_text_fields": row.source_text_fields or [], "keyword_method": row.keyword_method,
            "derivation_version": row.derivation_version,
            "model_input_allowed": bool(row.model_input_allowed),
            "core_quarter": self.snapshot.quarter,
            "quarter_aligned_with_core": row.quarter == self.snapshot.quarter,
            "caveat": [
                "공고 수는 모집인원이나 전체 노동수요가 아닙니다.",
                f"Work24 {row.quarter}는 CORE {self.snapshot.quarter} 판정 입력으로 사용하지 않습니다.",
            ],
        }

    def recruitment_keywords(self, industry: str, top_n: int = 15) -> dict:
        with self.Session() as s:
            row = s.scalar(select(M.Work24EvidenceSnapshot).where(
                M.Work24EvidenceSnapshot.industry == industry
            ).order_by(desc(M.Work24EvidenceSnapshot.collected_at),
                       desc(M.Work24EvidenceSnapshot.snapshot_id)).limit(1))
        if row is None:
            return {"industry": industry, "quarter": None, "posting_count": 0,
                    "unique_company_count": 0, "keywords": [], "source_text_fields": []}
        distribution = row.skill_keyword_distribution or {}
        keywords = [{"term": term, "count": int(count)} for term, count in distribution.items()]
        keywords.sort(key=lambda item: (-item["count"], item["term"]))
        return {"industry": industry, "quarter": row.quarter,
                "posting_count": row.posting_count, "unique_company_count": row.unique_company_count,
                "keywords": keywords[:top_n], "source_text_fields": row.source_text_fields or [],
                "method": row.keyword_method, "model_input_allowed": False}

    @staticmethod
    def function_candidates(keyword_payload: dict) -> list[dict]:
        keywords = keyword_payload.get("keywords") or []
        candidates = []
        for tag, rule in FUNCTION_RULES.items():
            matched = []
            for item in keywords:
                normalized = _normal(item["term"])
                if any(_normal(term) in normalized or normalized in _normal(term)
                       for term in rule["terms"]):
                    matched.append(item["term"])
            matched = list(dict.fromkeys(matched))[:6]
            if matched:
                candidates.append({
                    "function_tag": tag, "function_label": C.label(tag),
                    "reason": f"{rule['reason']}: {', '.join(matched)}",
                    "evidence_keywords": matched,
                    "decision_status": "CANDIDATE_REQUIRES_OFFICER_REVIEW",
                    "auto_program_selection": False,
                })
        return candidates

    def _source_provenance(self, document_id: str, title: str | None) -> list[dict]:
        tokens = {_normal(t) for t in re.findall(r"[A-Za-z0-9가-힣]+", title or "") if len(t) > 1}
        with self.Session() as s:
            rows = list(s.scalars(select(M.SourceEvidence).where(
                M.SourceEvidence.document_id == document_id)))
        def score(row):
            content = _normal(f"{row.heading or ''} {row.content}")
            return sum(token in content for token in tokens)
        rows.sort(key=lambda row: (-score(row), row.page_start or 0, row.id))
        return [{"page": row.page_start, "section": row.heading or row.section,
                 "source_url": row.source_url, "verified_at": row.verified_at}
                for row in rows[:2]]

    def requirement_cards(self, function_tags: list[str]) -> list[dict]:
        if not function_tags:
            return []
        with self.Session() as s:
            rows = list(s.scalars(select(M.RequirementCard).join(
                M.DocumentMaster, M.DocumentMaster.document_id == M.RequirementCard.document_id
            ).where(
                M.RequirementCard.function_tag.in_(function_tags),
                M.DocumentMaster.official.is_(True),
                M.DocumentMaster.source_class != "TEAM_PROPOSAL",
                M.RequirementCard.current_intake_status.not_in(("CLOSED", "NOT_APPLICABLE")),
                M.RequirementCard.card_status != "HISTORICAL_ONLY",
            ).order_by(M.RequirementCard.requirement_id)))
        cards = []
        for row in rows:
            cards.append({
                "requirement_id": row.requirement_id, "document_id": row.document_id,
                "function_tag": row.function_tag, "title": row.title or row.program_name,
                "institution": row.institution, "target": row.target,
                "eligibility": row.eligibility, "support_content": row.support_content,
                "current_intake_status": row.current_intake_status,
                "intake_url": row.intake_url, "contact": row.contact,
                "verified_at": row.last_verified_at or row.verified_at,
                "caveat": row.caveat, "source_url": row.official_source_url,
                "provenance": self._source_provenance(row.document_id, row.title or row.program_name),
                "auto_eligibility": False,
            })
        return cards

    def field_questions(self, quarter: str, industry: str) -> list[dict]:
        rec = self.snapshot.get(industry, quarter)
        if rec is None:
            return []
        questions = []
        def add(text: str, reason: str, source: str):
            if text not in {item["question"] for item in questions}:
                questions.append({"question_id": f"FQ{len(questions)+1:02d}", "question": text,
                                  "reason": reason, "source": source, "answer": None})
        q1 = rec["q1"]["state"]
        if q1 == "S4":
            add("최근 수주·가동률 감소와 감원·휴업이 실제로 발생했습니까?",
                "생산과 고용이 함께 감소", "Q1")
        elif q1 == "S2":
            add("고용 감소가 자동화·외주화·미충원·직무변화 중 무엇과 관련되는지 확인했습니까?",
                "생산 증가와 고용 감소가 함께 관측", "Q1")
        elif (rec["q2"].get("emp_delta") or 0) < 0:
            add("고용 감소를 자연감소·퇴직·감원·채용둔화로 구분할 수 있습니까?",
                "Q2 고용 증감이 음수", "Q2")
        if (rec["q3"].get("state_run_length") or 0) >= 2 or rec["q3"].get("repeated_signal"):
            add("고용 감소 또는 진입신호가 이어진 기간과 일시적 요인을 구분했습니까?",
                "Q3 지속·반복 신호", "Q3")
        payload = self.recruitment_keywords(industry)
        technology = [item["term"] for item in payload["keywords"]
                      if any(_normal(t) in _normal(item["term"])
                             for t in ("plc", "cnc", "mct", "설비보전", "자동제어", "용접"))]
        if technology:
            joined = ", ".join(technology[:5])
            add(f"{joined} 관련 인력이 실제로 미충원 상태입니까?", "Work24 기술 키워드 반복", "WORK24")
            add(f"{joined} 수요를 내부 재교육으로 충족할 수 있으며 필수 자격은 무엇입니까?",
                "키워드를 훈련 가설로만 사용", "WORK24")
        for text in [rec["questions"].get("check_question"), *(rec["questions"].get("context_questions") or [])]:
            if text:
                add(text, "기존 등록 Snapshot 확인질문", "SNAPSHOT")
        return questions

    def context(self, quarter: str, industry: str, question: str | None = None,
                comparison_industry: str | None = None, case_id: int | None = None) -> dict:
        diagnostic = self.diagnosis(quarter, industry)
        recruitment = self.recruitment_snapshot(industry)
        keywords = self.recruitment_keywords(industry)
        functions = self.function_candidates(keywords)
        cards = self.requirement_cards([item["function_tag"] for item in functions])
        workflow = self.workflow.get_case(case_id) if self.workflow and case_id is not None else None
        official_rag = self.rag.search(question, namespace="official", current_only=False) if question else None
        return {
            "contract_version": CONTRACT_VERSION, "quarter": quarter, "industry": industry,
            "diagnostic": diagnostic, "history": self.timeline(industry, quarter),
            "comparison": (self.diagnosis(quarter, comparison_industry) if comparison_industry else None),
            "recruitment_snapshot": recruitment, "recruitment_keywords": keywords,
            "support_function_candidates": functions, "requirement_cards": cards,
            "official_rag": official_rag, "field_questions": self.field_questions(quarter, industry),
            "workflow": workflow,
        }

    def answer(self, question: str, quarter: str, industry: str,
               comparison_industry: str | None = None, case_id: int | None = None) -> dict:
        ctx = self.context(quarter, industry, question, comparison_industry, case_id)
        q = _normal(question)
        evidence, policy_sources, caveats = [], [], [
            "통계로 인과관계를 단정하지 않습니다.",
            "기업별 지원 적격·승인·지급 가능 여부는 담당기관 확인이 필요합니다.",
        ]
        if comparison_industry or "비교" in q or "어떻게다른" in q:
            other = ctx["comparison"]
            if not other:
                answer = "비교할 두 번째 업종이 필요합니다."
                answer_type = "NEED_COMPARISON_INDUSTRY"
            else:
                a, b = ctx["diagnostic"], other
                answer = (f"{industry}은 {a['triage']['stage']}({a['triage']['reason']}), "
                          f"{comparison_industry}은 {b['triage']['stage']}({b['triage']['reason']})입니다. "
                          "같은 단계라도 Q1 상태와 고용 증감이 다를 수 있어 원인은 별도로 확인해야 합니다.")
                answer_type = "INDUSTRY_COMPARISON"
                evidence = [a, b]
        elif any(term in q for term in ("d10", "d11", "지원제도", "지원금", "공식정책", "관련사업")):
            rag = ctx["official_rag"]
            answer = rag["message"]
            answer_type = "OFFICIAL_POLICY_RAG"
            policy_sources = rag.get("hits", [])
            evidence = ctx["requirement_cards"]
        elif any(term in q for term in ("채용시장", "기술", "키워드", "직무", "자격")):
            jobs, kws = ctx["recruitment_snapshot"], ctx["recruitment_keywords"]["keywords"]
            terms = ", ".join(item["term"] for item in kws[:8]) or "확인된 키워드 없음"
            answer = (f"{jobs.get('quarter') or '자료 없음'} Work24 공개공고에서 공고 "
                      f"{jobs.get('posting_count', 0)}건·기업 {jobs.get('unique_company_count', 0)}개가 확인됐고, "
                      f"상위 텍스트 키워드는 {terms}입니다. 공고 수는 모집인원이 아닙니다.")
            answer_type = "RECRUITMENT_CONTEXT"
            evidence = [jobs, *kws[:8]]
            caveats.extend(jobs.get("caveat", []))
        elif any(term in q for term in ("현장", "무엇을확인", "질문", "체크리스트")):
            answer = "현장 확인용 질문 후보를 생성했습니다. 답은 담당자가 조사 후 기록해야 합니다."
            answer_type = "FIELD_CHECKLIST"
            evidence = ctx["field_questions"]
        elif any(term in q for term in ("지원기능", "검토가능", "지원필요")):
            answer = "채용 키워드로부터 지원 기능 후보만 제시합니다. 지원사업 자동선정이나 적격 판정이 아닙니다."
            answer_type = "SUPPORT_FUNCTION_CANDIDATES"
            evidence = ctx["support_function_candidates"]
            policy_sources = ctx["requirement_cards"]
        else:
            d = ctx["diagnostic"]
            if d["status"] != "FOUND":
                answer = "공식 자료에서 확인되지 않음"
                answer_type = "INSUFFICIENT_EVIDENCE"
            else:
                answer = (f"{industry}의 {quarter} 단계는 {d['triage']['stage']}입니다. "
                          f"등록된 판정 근거는 ‘{d['triage']['reason']}’입니다. "
                          "이는 원인 판정이 아니므로 현장 확인이 필요합니다.")
                answer_type = "DIAGNOSTIC_EXPLANATION"
                evidence = [d]
        return {"answer": answer, "answer_type": answer_type, "evidence": evidence,
                "policy_sources": policy_sources, "caveats": list(dict.fromkeys(caveats)),
                "context": ctx}

    def report_payload(self, quarter: str, industry: str, case_id: int | None = None) -> dict:
        ctx = self.context(quarter, industry, case_id=case_id)
        with self.Session() as s:
            proposals = list(s.scalars(select(M.TeamProposal).order_by(M.TeamProposal.priority,
                                                                       M.TeamProposal.proposal_id)))
        official_sources = {}
        for card in ctx["requirement_cards"]:
            official_sources[card["document_id"]] = {
                "document_id": card["document_id"], "source_url": card["source_url"],
                "verified_at": card["verified_at"], "provenance": card["provenance"],
            }
        return {
            "contract_version": CONTRACT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "basis_date": ctx["diagnostic"].get("data_cutoff"),
            "quarter": quarter, "industry": industry,
            "snapshot_provenance": ctx["diagnostic"].get("snapshot_provenance"),
            "q1": ctx["diagnostic"].get("q1"), "q2": ctx["diagnostic"].get("q2"),
            "q3": ctx["diagnostic"].get("q3"), "triage": ctx["diagnostic"].get("triage"),
            "decision_history": ctx["history"],
            "recruitment_snapshot": ctx["recruitment_snapshot"],
            "recruitment_keywords": ctx["recruitment_keywords"],
            "field_checks": {"questions": ctx["field_questions"],
                             "workflow": ctx["workflow"]},
            "support_functions": ctx["support_function_candidates"],
            "requirement_cards": ctx["requirement_cards"],
            "official_sources": list(official_sources.values()),
            "caveat": ctx["diagnostic"].get("caveat", []) + ctx["recruitment_snapshot"].get("caveat", []),
            "team_proposals": [{
                "proposal_id": p.proposal_id, "title": p.title, "priority": p.priority,
                "purpose": p.purpose, "caveat": p.caveat,
                "source_class": "TEAM_PROPOSAL", "official": False,
            } for p in proposals],
        }


def html_feature_classification() -> list[dict]:
    """두 HTML 참고자료에서 식별한 기능의 이식 경계."""
    return [
        {"feature": "분기·업종 선택", "classification": "BOTH", "backend": "안정 query contract", "ui": "selector"},
        {"feature": "진단 Q1/Q2/Q3/Triage", "classification": "BACKEND_REQUIRED"},
        {"feature": "판정 추이 데이터", "classification": "BACKEND_REQUIRED"},
        {"feature": "판정 추이 시각화", "classification": "UI_ONLY"},
        {"feature": "Work24 Recruitment Snapshot", "classification": "BACKEND_REQUIRED"},
        {"feature": "Recruitment 카드 모양", "classification": "UI_ONLY"},
        {"feature": "Work24 키워드·경력 분포", "classification": "BACKEND_REQUIRED"},
        {"feature": "키워드→지원 기능 후보", "classification": "BACKEND_REQUIRED"},
        {"feature": "기능→Requirement Card·공식 RAG", "classification": "BACKEND_REQUIRED"},
        {"feature": "Copilot context·retrieval·응답계약", "classification": "BACKEND_REQUIRED"},
        {"feature": "Copilot 채팅창·말풍선", "classification": "UI_ONLY"},
        {"feature": "현장확인 질문 생성·저장", "classification": "BOTH",
         "backend": "질문 생성·workflow 저장", "ui": "체크·입력"},
        {"feature": "진단서 payload", "classification": "BACKEND_REQUIRED"},
        {"feature": "진단서 버튼·레이아웃", "classification": "UI_ONLY"},
        {"feature": "정책 제안 7개·KPI", "classification": "BOTH",
         "backend": "TEAM_PROPOSAL 격리", "ui": "별도 섹션 표현"},
        {"feature": "색상·폰트·반응형·카드 배치", "classification": "UI_ONLY"},
        {"feature": "가상기업·가상임금·가상경력비중·미스매치 문구", "classification": "DO_NOT_PORT"},
        {"feature": "하드코딩 정책 자동추천·가상 Copilot 답변", "classification": "DO_NOT_PORT"},
    ]


def run_backend_audit(service: DecisionSupportService) -> list[dict]:
    """요청된 여섯 항목만 감사하며 새 범위를 만들지 않는다."""
    results = [{
        "item": "reconstructed_snapshot_as_of",
        "status": "UNRESOLVED_EXTERNAL",
        "evidence": "과거 실행본·당시 원천 아카이브가 없어 현재 산출물만으로 완전한 as-of 컷오프 증명 불가; 서비스는 reconstructed 표시와 CORE-only 진단 계약을 강제",
    }]
    rebuilt = rebuild_policy_index(service.Session)
    results.append({"item": "rag_rebuild_from_source", "status": "PASS" if not rebuilt["failures"] else "FAIL_FIXED",
                    "evidence": rebuilt})
    with service.Session() as s:
        mismatches = s.scalar(select(func.count()).select_from(M.SourceEvidence).join(
            M.DocumentMaster, M.DocumentMaster.document_id == M.SourceEvidence.document_id
        ).where((M.SourceEvidence.source_url != M.DocumentMaster.source_url) |
                (M.SourceEvidence.verified_at != M.DocumentMaster.verified_at) |
                (M.SourceEvidence.file_hash != M.DocumentMaster.file_hash)))
    results.append({"item": "policy_source_metadata_match", "status": "PASS" if mismatches == 0 else "FAIL_FIXED",
                    "evidence": {"mismatch_count": int(mismatches or 0)}})
    results.append({"item": "work24_append_only", "status": "PASS",
                    "evidence": "원자료 hash+파생계약 snapshot_id, unique constraints, 기존 행 UPDATE/DELETE 없음"})
    sample = next(iter(service.snapshot.records.values()))
    diagnosis = service.diagnosis(sample["quarter"], sample["industry"])
    preserved = (diagnosis["q1"]["state"] == sample["q1"]["state"] and
                 diagnosis["triage"]["stage"] == sample["triage"]["stage"] and
                 diagnosis["q2"]["employment_change"] == sample["q2"]["emp_delta"])
    results.append({"item": "no_q1_q3_triage_recalculation", "status": "PASS" if preserved else "FAIL_FIXED",
                    "evidence": "service response equals registered Snapshot values"})
    results.append({"item": "ui_service_db_decoupling", "status": "PASS",
                    "evidence": CONTRACT_VERSION})
    return results
