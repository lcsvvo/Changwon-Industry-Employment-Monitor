"""Copilot P0 — 라우터·등록 진단 답변·RAG 충분성·guardrail·감사 기록 (외부 provider 없이)."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.view_models import rule_evidence_rows  # noqa: E402
from copilot import Copilot, guardrails, router as R, sufficiency  # noqa: E402
from copilot.audit import JsonlAuditSink, MemoryAuditSink, audit_path_for, question_digest  # noqa: E402
from copilot.contracts import (  # noqa: E402
    EXTERNAL_WEB, GENERAL_LLM, INTERNAL_DIAGNOSTIC, INTERNAL_RAG, LLM, SYSTEM, Citation, CopilotAnswer,
)
from copilot.domains import classify  # noqa: E402
from copilot.internal import CANONICAL  # noqa: E402
from export.snapshot import SNAPSHOT_ROOT, load_snapshot  # noqa: E402
from policy.decision_support import DecisionSupportService  # noqa: E402
from policy.rag import rebuild_policy_index  # noqa: E402
from policy.work24_evidence import register_work24_snapshot  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow.service import WorkflowService  # noqa: E402

TODAY = date(2026, 9, 23)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    path = tmp_path_factory.mktemp("copilot") / "workflow.db"
    Session = M.make_session_factory(f"sqlite:///{path.as_posix()}")
    assert rebuild_policy_index(Session)["failures"] == []
    register_work24_snapshot(Session)
    snap = load_snapshot("2026Q2", "v3")
    service = DecisionSupportService(Session, snap, WorkflowService(Session))
    audit = MemoryAuditSink()
    return snap, service, Copilot(service, audit=audit, today=lambda: TODAY), audit


def ask(copilot, question, industry="기계", quarter="2026Q2", **kw):
    return copilot.ask(question, quarter, industry, **kw)


# ------------------------------------------------------------------ 라우터
IND = ["기계", "기타", "목재종이", "비금속", "석유화학", "섬유의복", "운송장비", "음식료", "전기전자", "철강"]
QS = [f"{y}Q{q}" for y in range(2022, 2027) for q in range(1, 5)][:18]
ROUTES = [
    ("기계가 왜 우선점검이야?", INTERNAL_DIAGNOSTIC, R.STAGE),
    ("이 업종이 왜 관찰인가?", INTERNAL_DIAGNOSTIC, R.STAGE),      # 빠른 질문 칩(단계별 문구)
    ("이 업종이 왜 추가확인인가?", INTERNAL_DIAGNOSTIC, R.STAGE),
    ("이 업종의 판정 근거는?", INTERNAL_DIAGNOSTIC, R.STAGE),
    ("E값은?", INTERNAL_DIAGNOSTIC, R.SIGNAL),
    ("R은 뭐야?", INTERNAL_DIAGNOSTIC, R.SIGNAL),               # 시스템 고유 개념은 등록 정의로
    ("E R A P 값 알려줘", INTERNAL_DIAGNOSTIC, R.SIGNAL),
    ("Q1 상태 알려줘", INTERNAL_DIAGNOSTIC, R.Q1),
    ("고용 증감은 몇 명이야?", INTERNAL_DIAGNOSTIC, R.Q2),
    ("몇 분기째 지속되고 있어?", INTERNAL_DIAGNOSTIC, R.Q3),
    ("현장에서는 뭘 확인해야 해?", INTERNAL_DIAGNOSTIC, R.FIELD),
    ("현재 조치등급은?", INTERNAL_DIAGNOSTIC, R.STAGE),         # '현재'가 있어도 진단 우선
    ("2025Q4 철강 판정은?", INTERNAL_DIAGNOSTIC, R.STAGE),
    ("기계와 목재종이 비교", INTERNAL_DIAGNOSTIC, R.COMPARE),
    ("이 판정의 한계는?", INTERNAL_DIAGNOSTIC, R.GAPS),
    ("이 결과를 쉽게 설명해줘", INTERNAL_DIAGNOSTIC, R.REPHRASE),
    ("한 문장으로 설명해줘", INTERNAL_DIAGNOSTIC, R.REPHRASE),
    ("공작기계 조작원 채용 많아?", INTERNAL_DIAGNOSTIC, R.RECRUITMENT),
    ("현재 신청 가능한 고용유지 사업 있어?", INTERNAL_RAG, R.POLICY),
    ("기술전환 지원사업은?", INTERNAL_RAG, R.POLICY),            # 충돌: '기술'≠채용
    ("직업훈련 공고 있어?", INTERNAL_RAG, R.POLICY),              # 충돌: '공고'≠채용
    ("최근 정책 변경 있어?", INTERNAL_RAG, R.POLICY),             # 충돌: '변경'≠판정 변화
    ("기계가 우선점검인데 받을 수 있는 지원사업은?", INTERNAL_RAG, R.POLICY),
    ("관할 고용센터 어디야?", INTERNAL_RAG, R.POLICY),
    ("검토 가능한 지원 기능 후보는?", INTERNAL_RAG, R.SUPPORT_FUNCTIONS),
    ("창원 기계산업 최근 동향은?", EXTERNAL_WEB, R.TREND),
    ("CNC가 뭐야?", GENERAL_LLM, R.CONCEPT),
    ("MCT와 CNC 차이가 뭐야?", GENERAL_LLM, R.CONCEPT),
    ("CNC를 쉽게 설명해줘", GENERAL_LLM, R.CONCEPT),
    ("안녕하세요", "GREETING", "GREETING"),
    ("뭘 할 수 있어?", "CAPABILITY", "CAPABILITY"),
    ("오늘 점심 뭐 먹지", "UNSUPPORTED", "UNSUPPORTED"),
    ("", "UNSUPPORTED", "EMPTY"),
]


@pytest.mark.parametrize("question,route,intent", ROUTES)
def test_router_golden_set(question, route, intent):
    decision = R.route(question, IND, QS)
    assert (decision.route, decision.intent) == (route, intent), decision.scores


def test_router_extracts_target_without_compound_false_positive():
    assert R.route("2025Q4 철강 판정은?", IND, QS).industries == ("철강",)
    assert R.route("2025Q4 철강 판정은?", IND, QS).quarter == "2025Q4"
    assert R.route("공작기계 조작원 채용 많아?", IND, QS).industries == ()  # '공작기계'≠기계
    assert R.route("Q1~Q3 알려줘", IND, QS).subintents[:3] and {
        R.Q1, R.Q2, R.Q3} <= set(R.route("Q1~Q3 알려줘", IND, QS).subintents)


def test_quick_prompt_chips_route_as_designed():
    from app.view_models import quick_prompts
    expected = [(INTERNAL_DIAGNOSTIC, R.STAGE), (INTERNAL_DIAGNOSTIC, R.FIELD), (INTERNAL_DIAGNOSTIC, R.CHANGE),
                (INTERNAL_DIAGNOSTIC, R.RECRUITMENT), (INTERNAL_RAG, R.SUPPORT_FUNCTIONS), (INTERNAL_RAG, R.POLICY),
                (INTERNAL_DIAGNOSTIC, R.GAPS)]
    for prompt, want in zip(quick_prompts("우선점검"), expected):
        decision = R.route(prompt, IND, QS)
        assert (decision.route, decision.intent) == want, prompt


# ------------------------------------------------------------------ 등록 진단(기존 backend 위임·등록값)
def test_canonical_prompts_hit_intended_backend_branch(env):
    _, service, _, _ = env
    for intent, (prompt, answer_type) in CANONICAL.items():
        other = "목재종이" if intent == R.COMPARE else None
        assert service.answer(prompt, "2026Q2", "기계", comparison_industry=other)["answer_type"] == answer_type


def test_signal_answer_uses_registered_values_and_thresholds(env):
    snap, _, copilot, _ = env
    rec = snap.get("기계", "2026Q2")
    rows = rule_evidence_rows(rec, {r["rule_name"]: r for r in snap.reference["triage_rules"]})
    result = ask(copilot, "E값은?")
    assert result["source_type"] == INTERNAL_DIAGNOSTIC and result["composer"] == "TEMPLATE"
    assert rows[0]["current"] in result["answer"]                         # 6.34% — 등록값 그대로
    assert "진입 5%" in result["answer"] and "상위 10%" in result["answer"]  # 등록 규칙 문자열
    assert f"'{rows[0]['verdict']}'" in result["answer"]
    assert "R 산단평균" not in result["answer"]                           # 물어본 신호만
    assert "다시 계산하지 않았습니다" in result["answer"]
    everything = ask(copilot, "E R A P 값 알려줘")["answer"]
    assert all(row["current"] in everything for row in rows[:4])


def test_q1_q3_answers_come_from_snapshot(env):
    snap, _, copilot, _ = env
    rec = snap.get("기계", "2026Q2")
    text = ask(copilot, "Q1~Q3 알려줘")["answer"]
    assert rec["q1"]["state"] in text and f"{rec['q2']['emp_delta']:+,}명" in text
    assert f"{rec['q3']['state_run_length']}분기 지속" in text
    assert text.index("Q1 상태") < text.index("Q2 고용") < text.index("Q3 시간")


def test_named_industry_and_quarter_override_selection(env):
    snap, _, copilot, _ = env
    result = ask(copilot, "2025Q4 철강 판정은?")
    assert result["target"]["industry"] == "철강" and result["target"]["quarter"] == "2025Q4"
    assert snap.get("철강", "2025Q4")["triage"]["stage"] in result["answer"]


def test_field_intent_lists_backend_questions_and_uses_session_count(env):
    _, service, copilot, _ = env
    questions = service.field_questions("2026Q2", "기계")
    ctx = {"responses": [{"question_id": questions[0]["question_id"], "question": questions[0]["question"],
                          "checked": True, "answer": None, "source": "Q1"}], "note": None}
    result = ask(copilot, "현장에서는 뭘 확인해야 해?", field_context=ctx)
    assert "응답된 항목은 1건" in result["answer"] and questions[0]["question"] in result["answer"]


# ------------------------------------------------------------------ 미지원·일반 질문은 진단으로 fallback하지 않음
@pytest.mark.parametrize("question", ["오늘 점심 뭐 먹지", "CNC가 뭐야?", "창원 기계산업 최근 동향은?", "안녕하세요"])
def test_non_diagnostic_questions_never_fall_back_to_diagnosis(env, question):
    snap, _, copilot, _ = env
    result = ask(copilot, question)
    assert result["source_type"] == SYSTEM
    assert snap.get("기계", "2026Q2")["triage"]["stage_reason"] not in result["answer"]
    assert result["answer_type"] not in ("DIAGNOSTIC_EXPLANATION",)


def test_trend_question_states_internal_authority_without_external_content(env):
    _, _, copilot, _ = env
    result = ask(copilot, "창원 기계산업 최근 동향은?")
    assert "외부 동향 자료로 이 판정을 바꾸지 않습니다" in result["answer"] and not result["citations"]


# ------------------------------------------------------------------ 정책 RAG · 충분성
def test_policy_question_uses_official_rag_with_citations(env):
    _, _, copilot, _ = env
    result = ask(copilot, "산업·일자리전환 채용장려금 지원금액은?")
    assert result["source_type"] == INTERNAL_RAG and result["official_evidence_sufficient"] is True
    assert result["citations"] and all(c["url"].startswith("http") and c["checked_at"] for c in result["citations"])
    assert all(c["official"] for c in result["citations"])


def test_recency_question_with_unknown_intake_is_insufficient_and_tries_web(env):
    _, _, copilot, _ = env
    result = ask(copilot, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert result["official_evidence_sufficient"] is False
    stages = [(step.get("stage"), step.get("status")) for step in result["route_trace"]]
    assert ("EXTERNAL_WEB", "NOT_CONFIGURED") in stages
    rag_step = next(step for step in result["route_trace"] if step.get("stage") == INTERNAL_RAG)
    assert any("UNKNOWN" in reason for reason in rag_step["reasons"])
    # 최신 공고 조회(BIZINFO·외부 검색)가 없으면 '현재 모집 여부는 실시간 확인 못함'을 밝힌다
    assert any("설정되지 않아" in c and "실시간 확인하지 못했습니다" in c for c in result["caveats"])


def test_generic_support_question_uses_industry_requirement_cards(env):
    _, _, copilot, _ = env
    result = ask(copilot, "연결 가능한 공식 지원은?")
    assert result["answer_type"] == "REQUIREMENT_CARDS" and result["citations"]
    assert "자동 판정하지 않습니다" in result["answer"]


def test_sufficiency_rules():
    base = {"document_id": "D11", "title": "지원금 시행지침", "section": None, "excerpt": "채용장려금 지급",
            "score": 12, "source_class": "OFFICIAL_POLICY", "current_intake_status": "OPEN",
            "verified_at": "2026-09-20"}
    meta = {"D11": {"official": True}, "T1": {"official": False}}
    ok = sufficiency.evaluate({"status": "FOUND", "hits": [base]}, "채용장려금 신청 가능해?",
                              needs_recency=True, doc_meta=meta, today=TODAY)
    assert ok.sufficient
    for change, why in (({"current_intake_status": "UNKNOWN"}, "접수 여부"), ({"verified_at": "2026-07-01"}, "확인일"),
                        ({"score": 3}, "관련도"), ({"excerpt": "훈련비 지원"}, "주제어"),
                        ({"document_id": "T1", "source_class": "TEAM_PROPOSAL"}, "공식 문서 아님")):
        result = sufficiency.evaluate({"status": "FOUND", "hits": [{**base, **change}]}, "채용장려금 신청 가능해?",
                                      needs_recency=True, doc_meta=meta, today=TODAY)
        assert not result.sufficient and any(why in r for r in result.reasons), change
    # 최신성 질문이 아니면 접수 상태·확인일은 요구하지 않는다
    assert sufficiency.evaluate({"status": "FOUND", "hits": [{**base, "current_intake_status": "UNKNOWN"}]},
                                "채용장려금 금액", needs_recency=False, doc_meta=meta, today=TODAY).sufficient
    assert sufficiency.topic_terms("현재 신청 가능한 고용유지 사업 있어?") == ["고용유지"]


# ------------------------------------------------------------------ guardrail · 도메인
def test_external_web_without_official_citation_is_blocked():
    web = CopilotAnswer(answer="모집 중입니다.", source_type=EXTERNAL_WEB, route=EXTERNAL_WEB, intent="POLICY",
                        answer_type="WEB", citations=[Citation("블로그", "https://blog.example.com/x", EXTERNAL_WEB,
                                                               False, checked_at="2026-09-23")])
    out = guardrails.finalize(web)
    assert out.source_type == SYSTEM and out.guardrail == "BLOCKED_NO_OFFICIAL_CITATION"
    kept = guardrails.finalize(CopilotAnswer(
        answer="고용노동부 공고 기준", source_type=EXTERNAL_WEB, route=EXTERNAL_WEB, intent="POLICY",
        answer_type="WEB", citations=[Citation("공고", "https://www.moel.go.kr/news/1", EXTERNAL_WEB, False,
                                               checked_at="2026-09-23")]))
    assert kept.source_type == EXTERNAL_WEB and kept.citations[0].institution == "고용노동부"
    assert kept.citations[0].tier == 1 and kept.citations[0].official


def test_domain_tiers():
    assert classify("https://www.changwon.go.kr/a") == (1, "창원특례시")
    assert classify("https://sub.kicox.or.kr/b")[0] == 1
    assert classify("https://www.mss.go.kr")[0] == 2
    assert classify("https://news.example.com") == (None, None)
    assert classify("https://fake-moel.go.kr.evil.com") == (None, None)


def test_rewrite_checks_numbers_stage_and_assertions():
    original = "기계의 2026Q2 단계는 우선점검입니다. 고용감소 6.3%, 감소 -3,979명."
    assert guardrails.check_rewrite(original, "기계는 우선점검 단계예요. 고용이 6.3% 줄었어요.", "우선점검")[0]
    assert guardrails.check_rewrite(original, "고용이 7% 줄었어요.", "우선점검")[1].startswith("NEW_NUMBERS")
    assert guardrails.check_rewrite(original, "기계는 관찰 단계예요.", "우선점검")[1] == "STAGE_CHANGED"
    assert guardrails.check_rewrite(original, "지원 대상입니다.", "우선점검")[1] == "ASSERTIVE"
    llm = CopilotAnswer(answer="이 기업은 지원 대상입니다.", source_type=GENERAL_LLM, route=GENERAL_LLM,
                        intent="CONCEPT", answer_type="LLM", composer=LLM)
    assert guardrails.finalize(llm).guardrail == "BLOCKED_ASSERTIVE"


# ------------------------------------------------------------------ 감사 기록 · 보호
def test_audit_records_minimal_metadata_only(env, tmp_path):
    _, _, copilot, audit = env
    ask(copilot, "E값은?", field_context={"responses": [], "note": "비밀메모-담당자홍길동"})
    record = audit.records[-1]
    blob = json.dumps(record.__dict__, ensure_ascii=False)
    assert "E값" not in blob and "비밀메모" not in blob and "홍길동" not in blob
    assert record.question_digest == question_digest("E값은?") and len(record.question_digest) == 16
    assert record.route == INTERNAL_DIAGNOSTIC and record.llm_used is False and record.web_search_used is False
    sink = JsonlAuditSink(tmp_path / "audit.jsonl")
    sink.record(record)
    assert json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8"))["source_type"] == INTERNAL_DIAGNOSTIC
    assert audit_path_for("sqlite:///C:/tmp/x/workflow.db", env={}) == Path("C:/tmp/x/copilot_audit.jsonl")
    assert audit_path_for(None, env={"COPILOT_AUDIT_LOG": "a.jsonl"}) == Path("a.jsonl")


def test_copilot_package_has_no_write_path_to_snapshot_or_workflow():
    import re
    forbidden = ("export.snapshot import", "from export import", "workflow.service", "rebuild_policy_index",
                 "to_csv", "write_text(", "data/processed", "data/raw", "snapshots/")
    db_write = re.compile(r"\b(s|session|db|conn)\.(add|add_all|delete|commit|merge|flush|execute\(\s*(insert|update|delete))")
    for path in (ROOT / "src" / "copilot").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name}: {token}"
        assert not db_write.search(text), f"{path.name}: DB write"


def test_asking_never_changes_registered_snapshot_files(env):
    _, _, copilot, _ = env
    files = sorted((SNAPSHOT_ROOT / "2026Q2" / "v3").glob("*.json"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    for question, *_ in ROUTES:
        ask(copilot, question)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    assert before == after
