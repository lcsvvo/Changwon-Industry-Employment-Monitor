from __future__ import annotations

import sys
from pathlib import Path
import datetime as dt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import work24_current as current  # noqa: E402
from evidence.collection import work24_recruitment as recruitment  # noqa: E402
from evidence.collection import kicox_factory as factory  # noqa: E402


def detail(**values):
    return {"request_status": "SUCCESS", **values}


def test_job_gate_uses_multiple_verified_detail_fields():
    core = recruitment.classify_job_relevance(detail(
        title="H-MCT 가공 경력자 모집",
        occupation_raw="금속 공작기계 조작원",
        occupation_keywords="밸브가공원",
        job_description_clean="MCT CNC 선반가공 경력자",
    ))
    support = recruitment.classify_job_relevance(detail(
        title="납품사원 모집",
        occupation_raw="배송·납품 운전원",
        occupation_keywords="납품운전원",
        job_description_clean="제조업체 포장물 납품",
    ))
    general = recruitment.classify_job_relevance(detail(
        title="홍보팀 추가 채용",
        occupation_raw="광고·홍보 전문가",
        job_description_clean="온라인 홍보 전략과 마케팅 업무",
    ))
    assert core["job_relevance_class"] == "CORE_INDUSTRIAL"
    assert support["job_relevance_class"] == "INDUSTRIAL_SUPPORT"
    assert general["job_relevance_class"] == "GENERAL_NONCORE"
    assert all(not row["job_relevance_manual_review"] for row in (core, support, general))


def test_unverified_detail_is_not_classified_from_title_alone():
    result = recruitment.classify_job_relevance({
        "request_status": "NOT_REQUESTED", "title": "CNC 기계 가공원"})
    assert result["job_relevance_class"] == "UNKNOWN"
    assert result["job_relevance_manual_review"] is True


def test_complex_proxy_never_becomes_confirmed():
    possible = recruitment.normalized_complex_gate({
        "industrial_complex_match_status": "POSSIBLE",
        "industrial_complex_match_method": "LEGAL_DONG_PROXY",
    })
    nonmatch = recruitment.normalized_complex_gate({
        "industrial_complex_match_status": "NOT_MATCH",
        "industrial_complex_match_method": "LEGAL_DONG_PROXY",
    })
    assert possible[0] == "POSSIBLE" and possible[2] is False
    assert nonmatch[0] == "NOT_MATCHED" and nonmatch[2] is False


def test_official_evidence_can_override_old_not_matched():
    result = recruitment.normalized_complex_gate(
        {"industrial_complex_match_status": "NOT_MATCH"},
        {"status": "CONFIRMED", "basis": "OFFICIAL_EXACT_COMPANY_NAME_AND_ADDRESS",
         "official_evidence": True},
    )
    assert result == ("CONFIRMED", "OFFICIAL_EXACT_COMPANY_NAME_AND_ADDRESS", True)


def test_posting_activity_uses_stored_due_date_only():
    as_of = dt.date(2026, 9, 23)
    assert recruitment.posting_activity({"due_date": "2026-09-23"}, as_of)[0] == "ACTIVE"
    assert recruitment.posting_activity({"due_date": "2026-09-22"}, as_of)[0] == "EXPIRED"
    assert recruitment.posting_activity({"due_date": ""}, as_of)[0] == "ACTIVE_UNKNOWN"


def test_all_industry_targets_are_existing_mappings_only():
    targets, stats = current.industry_targets("all")
    assert stats["target_count"] == 663
    assert stats["industry_counts"] == {
        "음식료": 17, "섬유의복": 0, "목재종이": 15, "석유화학": 13,
        "비금속": 7, "철강": 22, "기계": 380, "전기전자": 101,
        "운송장비": 101, "기타": 7,
    }
    assert all(row["kicox_mapping_status"] == "MAPPED" for row in targets)


def test_canonical_layer_validation_and_six_detail_reclassifications():
    quality = recruitment.build_recruitment_layer("20260923")
    assert quality["validation"]["list_total"] == 2045
    assert quality["validation"]["mapped_total"] == 663
    assert quality["validation"]["industry_count_sum"] == 663
    assert quality["validation"]["wanted_auth_no_duplicates"] == 0
    assert quality["validation"]["detail_verified_total"] == 6
    assert quality["validation"]["privacy_phone_hits"] == 0
    assert quality["validation"]["privacy_email_hits"] == 0
    assert quality["industrial_complex_gate"]["status_counts_mapped_only"] == {
        "CONFIRMED": 257, "POSSIBLE": 79, "UNKNOWN": 327, "NOT_MATCHED": 0}
    assert quality["job_relevance_gate"]["status_counts_mapped_only"] == {
        "CORE_INDUSTRIAL": 4, "INDUSTRIAL_SUPPORT": 1,
        "GENERAL_NONCORE": 1, "UNKNOWN": 657}
    assert quality["priority_industries"] == ["기계", "목재종이"]
    assert quality["detail_target_funnel"] == {
        "A_kicox_mapped": 663,
        "B_official_complex_confirmed": 257,
        "C_latest_priority_industries": 166,
        "D_currently_active": 141,
        "E_final_detail_needed": 140,
        "exact_natural_key_duplicate_groups": 0,
        "exact_natural_key_rows_removed": 0,
        "existing_detail_success_removed": 1,
        "repost_candidate_not_auto_collapsed": 0,
    }
    assert quality["queue"]["detail_needed"] == 140
    assert quality["queue"]["http_collection_authorized"] is False
    assert quality["validation"]["work24_detail_http_requests_this_run"] == 0
    assert quality["validation"]["official_factory_exact_complex_rows"] == 3553
    assert quality["industry_counts"]["기계"]["mapped_postings"] == 380
    assert quality["industry_counts"]["기계"]["official_confirmed_postings"] == 161
