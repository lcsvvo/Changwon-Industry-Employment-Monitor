from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection.work24_api import Work24ApiAccessError, parse_detail_xml  # noqa: E402
from export.snapshot import load_snapshot  # noqa: E402
from policy.decision_support import (  # noqa: E402
    DecisionSupportService, html_feature_classification, run_backend_audit,
)
from policy.rag import rebuild_policy_index  # noqa: E402
from policy.work24_evidence import register_work24_snapshot  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow.service import WorkflowService  # noqa: E402


@pytest.fixture(scope="module")
def backend(tmp_path_factory):
    path = tmp_path_factory.mktemp("decision_backend") / "workflow.db"
    Session = M.make_session_factory(f"sqlite:///{path.as_posix()}")
    report = rebuild_policy_index(Session)
    assert report["failures"] == []
    registered = register_work24_snapshot(Session)
    assert registered["status"] == "CREATED"
    snapshot = load_snapshot("2026Q2", "v3")
    workflow = WorkflowService(Session)
    return Session, snapshot, workflow, DecisionSupportService(Session, snapshot, workflow)


def test_diagnosis_view_model_preserves_registered_core(backend):
    _, snapshot, _, service = backend
    source = snapshot.get("기계", "2026Q2")
    result = service.diagnosis("2026Q2", "기계")
    assert result["q1"]["state"] == source["q1"]["state"]
    assert result["q2"]["employment_change"] == source["q2"]["emp_delta"]
    assert result["q3"]["duration"] == source["q3"]["state_run_length"]
    assert result["triage"]["stage"] == source["triage"]["stage"]
    assert result["snapshot_type"] == "contemporaneous"


def test_timeline_distinguishes_reconstructed_from_current(backend):
    _, _, _, service = backend
    rows = service.timeline("기계", "2026Q2")
    assert len(rows) == 18 and sum(row["is_current"] for row in rows) == 1
    assert rows[-1]["snapshot_type"] == "contemporaneous"
    assert all(row["snapshot_type"] == "reconstructed" for row in rows[:-1])


def test_recruitment_snapshot_is_actual_and_never_headcount(backend):
    _, _, _, service = backend
    result = service.recruitment_snapshot("기계")
    assert result["snapshot_id"].endswith("-rc1")
    assert (result["posting_count"], result["unique_company_count"]) == (380, 228)
    assert result["latest_registration_date"] == "2026-09-18"
    assert result["headcount"] is None and result["model_input_allowed"] is False
    assert result["quarter"] == "2026Q3" and result["quarter_aligned_with_core"] is False
    assert [level["count"] for level in result["evidence_levels"]] == [380, 161, 137, 3]
    assert result["detail_needed_count"] == 136
    assert result["job_relevance_distribution"] == {"CORE_INDUSTRIAL": 3}


def test_keyword_ranking_is_deterministic_and_real(backend):
    _, _, _, service = backend
    first = service.recruitment_keywords("기계", 20)
    second = service.recruitment_keywords("기계", 20)
    assert first == second
    assert first["posting_count"] == 380
    terms = {item["term"] for item in first["keywords"]}
    assert {"CNC", "MCT"} <= terms
    assert first["source_text_fields"] == ["title_raw"]


def test_keyword_to_function_is_candidate_not_program(backend):
    _, _, _, service = backend
    payload = {"keywords": [{"term": "PLC", "count": 5}, {"term": "설비보전", "count": 4},
                            {"term": "CNC", "count": 3}]}
    candidates = service.function_candidates(payload)
    tags = {row["function_tag"] for row in candidates}
    assert {"vocational_training", "technology_transition"} <= tags
    assert all(row["auto_program_selection"] is False and row["evidence_keywords"] for row in candidates)


def test_function_to_cards_excludes_closed_and_forbids_auto_eligibility(backend):
    _, _, _, service = backend
    cards = service.requirement_cards(["vocational_training", "recruitment_matching", "crisis_response"])
    ids = {row["requirement_id"] for row in cards}
    assert {"R02", "R10", "R11-A", "R11-B"} <= ids
    assert "R03" not in ids  # 현재 신청대상이 아닌 공급기관 안내
    assert "R09" not in ids
    assert all(row["current_intake_status"] != "CLOSED" and row["auto_eligibility"] is False for row in cards)
    assert next(row for row in cards if row["requirement_id"] == "R10")["provenance"]


def test_copilot_context_and_official_policy_rag_are_separated(backend):
    _, _, _, service = backend
    result = service.answer("D10 참여와 D11 지원금의 관계는 무엇인가?", "2026Q2", "기계")
    assert result["answer_type"] == "OFFICIAL_POLICY_RAG"
    assert "자동" in result["answer"] and "아닙니다" in result["answer"]
    assert result["policy_sources"]
    assert all(item["source_class"] != "TEAM_PROPOSAL" for item in result["policy_sources"])
    assert result["context"]["recruitment_snapshot"]["model_input_allowed"] is False


def test_field_question_engine_and_report_payload(backend):
    _, _, _, service = backend
    questions = service.field_questions("2026Q2", "기계")
    assert questions and all(item["answer"] is None for item in questions)
    report = service.report_payload("2026Q2", "기계")
    assert report["q1"] and report["q2"] and report["q3"] and report["triage"]
    assert report["decision_history"] and report["recruitment_snapshot"]["quarter"] == "2026Q3"
    assert report["official_sources"]
    assert report["team_proposals"] and all(not row["official"] for row in report["team_proposals"])


def test_generated_questions_can_be_saved_in_existing_workflow(backend):
    _, snapshot, workflow, service = backend
    workflow.start_candidate_review("테스터", snapshot, "기계", "2026Q2", "질문 저장 테스트")
    cid = workflow.open_case("테스터", snapshot, "기계", "2026Q2", "현장 확인", "테스터")
    questions = [item["question"] for item in service.field_questions("2026Q2", "기계")[:2]]
    added = workflow.append_context_questions("테스터", cid, questions)
    assert len(added) == len(questions)
    assert workflow.append_context_questions("테스터", cid, questions) == []
    case = workflow.get_case(cid)
    texts = [item["question_text"] for item in case["current_scope"]["checks"]]
    assert set(questions) <= set(texts)


def test_requested_six_item_backend_audit(backend):
    _, _, _, service = backend
    audit = run_backend_audit(service)
    assert len(audit) == 6
    assert {row["status"] for row in audit} <= {"PASS", "FAIL_FIXED", "UNRESOLVED_EXTERNAL"}
    assert next(row for row in audit if row["item"] == "reconstructed_snapshot_as_of")["status"] == "UNRESOLVED_EXTERNAL"


def test_html_feature_boundary_has_all_classes():
    classes = {row["classification"] for row in html_feature_classification()}
    assert classes == {"BACKEND_REQUIRED", "UI_ONLY", "BOTH", "DO_NOT_PORT"}


def test_work24_official_detail_xml_contract():
    xml = """<wantedDtl><wantedAuthNo>K1</wantedAuthNo><wantedInfo>
    <jobsNm>CNC 선반 조작원</jobsNm><jobsCd>8132</jobsCd><jobCont>CNC 가공</jobCont>
    <collectPsncnt>3</collectPsncnt><certificate>컴퓨터응용선반기능사</certificate>
    <keywordList><srchKeywordNm>CNC</srchKeywordNm></keywordList></wantedInfo></wantedDtl>"""
    result = parse_detail_xml(xml)
    assert result["recruitment_count"] == "3" and result["occupation_code"] == "8132"
    assert result["api_keywords"] == ["CNC"]
    with pytest.raises(Work24ApiAccessError, match="PERSONAL_ACCOUNT_NOT_ALLOWED"):
        parse_detail_xml("<GO24><error>개인회원은 사용할 수 없는 OPEN-API입니다.</error></GO24>")
