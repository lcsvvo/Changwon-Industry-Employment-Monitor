from __future__ import annotations

import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from policy.rag import PolicyRAG, rebuild_policy_index  # noqa: E402
from policy.work24_evidence import register_work24_snapshot  # noqa: E402
from workflow import models as M  # noqa: E402


@pytest.fixture(scope="module")
def policy_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("policy") / "policy.db"
    Session = M.make_session_factory(f"sqlite:///{path.as_posix()}")
    report = rebuild_policy_index(Session)
    assert report["failures"] == []
    assert report["indexed_documents"] == 14
    return Session, PolicyRAG(Session), report


def test_policy_master_and_requirement_card_contract(policy_db):
    Session, _, report = policy_db
    assert report["chunks"] > 100
    with Session() as s:
        assert s.query(M.DocumentMaster).count() == 14
        assert s.query(M.TeamProposal).count() == 8
        cards = s.query(M.RequirementCard).all()
        assert {c.requirement_id for c in cards} == {
            "R01", "R02", "R03", "R04", "R06", "R07", "R08", "R09", "R10", "R11-A", "R11-B"
        }
        assert all(c.auto_eligibility is False for c in cards)
        assert s.query(M.RequirementCard).filter(M.RequirementCard.requirement_id == "R05").count() == 0


def test_policy_schema_compiles_for_postgresql():
    dialect = postgresql.dialect()
    ddl = [str(CreateTable(table).compile(dialect=dialect)) for table in M.Base.metadata.sorted_tables]
    indexes = [str(CreateIndex(index).compile(dialect=dialect))
               for table in M.Base.metadata.sorted_tables for index in table.indexes]
    assert any("document_master" in statement for statement in ddl)
    assert any("source_evidence" in statement for statement in ddl)
    assert all(statement.strip() for statement in ddl + indexes)


def test_sqlite_datetime_uses_explicit_adapter_without_deprecation_warning(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        Session = M.make_session_factory(f"sqlite:///{(tmp_path / 'datetime.db').as_posix()}")
        with Session.begin() as s:
            s.add(M.AuditLog(actor="tester", actor_id="local:tester", action="datetime.test",
                             target_type="test", target_id="1", before=None, after=None,
                             snapshot_quarter=None, snapshot_version=None,
                             created_at=datetime.now(timezone.utc), is_example=False))
        with Session() as s:
            stored = s.query(M.AuditLog).one().created_at
        assert isinstance(stored, datetime)


def test_document_states_and_d10_d11_relation(policy_db):
    Session, _, _ = policy_db
    with Session() as s:
        d09, d10, d11, d13 = [s.get(M.DocumentMaster, key) for key in ("D09", "D10", "D11", "D13")]
        assert (d09.current_intake_status, d09.requirement_card_status, d09.content_extraction_scope) == (
            "CLOSED", "HISTORICAL_ONLY", "ATTACHMENT_VERIFIED")
        assert d10.current_intake_status == "OPEN" and d10.intake_url.startswith("https://docs.google.com/forms/")
        assert (d11.current_intake_status, d11.rag_status) == ("UNKNOWN", "RAG_READY_WITH_CAVEAT")
        assert d13.current_intake_status == "CLOSED" and "별첨" in d13.caveat
        rel = s.query(M.RelatedDocument).one()
        assert (rel.from_document_id, rel.to_document_id) == ("D10", "D11")
        assert rel.equivalent_program is False and rel.auto_eligibility is False


@pytest.mark.parametrize("address,district,institution", [
    ("창원시 의창구 북면", "의창구", "창원고용센터"),
    ("경남 창원시 성산구 중앙대로", "성산구", "창원고용센터"),
    ("창원시 진해구", "진해구", "창원고용센터"),
    ("창원시 마산회원구", "마산회원구", "마산고용센터"),
    ("창원시 마산합포구", "마산합포구", "마산고용센터"),
])
def test_address_only_jurisdiction_routing(policy_db, address, district, institution):
    _, rag, _ = policy_db
    result = rag.route_jurisdiction(address)
    assert result["jurisdiction_status"] == "MATCHED"
    assert (result["district"], result["institution"]) == (district, institution)


@pytest.mark.parametrize("address", [None, "", "창원국가산업단지", "창원시", "의창구 또는 성산구"])
def test_missing_or_ambiguous_location_is_not_guessed(policy_db, address):
    _, rag, _ = policy_db
    result = rag.route_jurisdiction(address)
    assert result["institution"] is None and result["jurisdiction_status"] == "NEED_LOCATION"


def test_rag_smoke_d11_recruitment_amount(policy_db):
    _, rag, _ = policy_db
    result = rag.search("산업·일자리전환 채용장려금 지원금액은?")
    assert result["matched_requirement_ids"] == ["R11-A"]
    assert result["hits"][0]["document_id"] == "D11"
    assert any(h["page"] == 28 and "720만원" in h["excerpt"] for h in result["hits"])


def test_rag_smoke_d11_training_limit(policy_db):
    _, rag, _ = policy_db
    result = rag.search("산업·일자리전환 훈련지원금의 훈련비 한도는?")
    assert result["matched_requirement_ids"] == ["R11-B"]
    assert result["hits"][0]["document_id"] == "D11"
    assert any("300만원" in h["excerpt"] for h in result["hits"])


def test_rag_smoke_d09_excludes_changwon_national_complex(policy_db):
    _, rag, _ = policy_db
    result = rag.search("2026 상반기 Stand-up 대상지역에 창원국가산단이 포함되는가?")
    assert result["hits"][0]["document_id"] == "D09" and result["hits"][0]["page"] == 7
    assert "포함되지 않습니다" in result["message"] and "D13" in result["message"]


def test_rag_smoke_d10_is_not_d11_auto_approval(policy_db):
    _, rag, _ = policy_db
    result = rag.search("D10 컨설팅에 참여하면 D11 지원금이 자동 승인되는가?")
    assert result["hits"] and result["hits"][0]["document_id"] == "D11"
    assert "자동 적격·신청·승인·지급이 아닙니다" in result["message"]


def test_team_namespace_is_excluded_from_official_search(policy_db):
    _, rag, _ = policy_db
    official = rag.search("산업·고용 조기경보 정례협의체", namespace="official")
    team = rag.search("산업·고용 조기경보 정례협의체", namespace="team")
    assert all(h["source_class"] != "TEAM_PROPOSAL" for h in official["hits"])
    assert team["hits"] and all(h["source_class"] == "TEAM_PROPOSAL" for h in team["hits"])


def test_current_only_excludes_historical_documents(policy_db):
    _, rag, _ = policy_db
    result = rag.search("Stand-up 맞춤지원", current_only=True)
    assert all(h["current_intake_status"] != "CLOSED" for h in result["hits"])


def test_no_evidence_returns_safe_failure(policy_db):
    _, rag, _ = policy_db
    result = rag.search("공식문서에 존재하지 않는 가상 양자보조금")
    assert result == {"status": "NO_OFFICIAL_EVIDENCE", "message": "공식 자료에서 확인되지 않음", "hits": []}


def test_work24_external_evidence_is_append_only_and_not_model_input(policy_db):
    Session, _, _ = policy_db
    first = register_work24_snapshot(Session)
    second = register_work24_snapshot(Session)
    assert (first["status"], second["status"]) == ("CREATED", "EXISTS")
    assert first["rows"] == 2045 and first["company_matches"] == 683 and first["kicox_mapped"] == 663
    assert first["quarter"] == "2026Q3" and first["headcount"] is None
    assert first["headcount_coverage_pct"] == 0.0 and first["model_input_allowed"] is False
    with Session() as s:
        assert s.query(M.Work24EvidenceItem).count() == 2045
        summaries = s.query(M.Work24EvidenceSnapshot).all()
        assert sum(row.posting_count for row in summaries) == 2045
        assert all(row.model_input_allowed is False and row.headcount is None for row in summaries)
