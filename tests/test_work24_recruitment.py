from __future__ import annotations

import sys
import csv
import json
from collections import Counter
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


def test_canonical_layer_validation_and_m140_detail_contract():
    quality_path = (ROOT / "data/processed/work24/"
                    "work24_recruitment_layer_quality_20260923.json")
    layer_path = (ROOT / "data/processed/work24/"
                  "work24_recruitment_layer_20260923.csv")
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    with layer_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    target_rows = [row for row in rows
                   if row["detailed_validation_target"].strip().lower() == "true"]
    target_status_counts = Counter(row["detail_access_status"] for row in target_rows)

    assert len(rows) == 2045
    assert quality["validation"]["list_total"] == 2045
    assert quality["validation"]["mapped_total"] == 663
    assert quality["validation"]["industry_count_sum"] == 663
    assert quality["validation"]["wanted_auth_no_duplicates"] == 0
    assert quality["validation"]["detail_verified_total"] == 141
    assert quality["validation"]["privacy_phone_hits"] == 0
    assert quality["validation"]["privacy_email_hits"] == 0
    assert quality["industrial_complex_gate"]["status_counts_mapped_only"] == {
        "CONFIRMED": 257, "POSSIBLE": 79, "UNKNOWN": 327, "NOT_MATCHED": 0}
    assert quality["job_relevance_gate"]["status_counts_mapped_only"] == {
        "UNKNOWN": 530, "CORE_INDUSTRIAL": 113,
        "INDUSTRIAL_SUPPORT": 9, "GENERAL_NONCORE": 11}
    assert quality["priority_industries"] == ["기계", "목재종이"]
    funnel = quality["detail_target_funnel"]
    assert [funnel[key] for key in (
        "A_kicox_mapped", "B_official_complex_confirmed",
        "C_latest_priority_industries", "D_currently_active",
        "M_final_validation_targets",
    )] == [663, 257, 166, 141, 140]
    assert funnel["E_remaining_detail_needed"] == 5
    assert funnel["existing_detail_success_removed"] == 1
    assert funnel["exact_natural_key_duplicate_groups"] == 0
    assert funnel["exact_natural_key_rows_removed"] == 0
    assert funnel["repost_candidate_not_auto_collapsed"] == 0
    assert len(target_rows) == 140
    assert target_status_counts == {"success": 135, "parse_failed": 5}
    assert quality["detail_collection_M"]["access_status_counts"] == {
        "success": 135, "partial": 0, "list_only": 0, "expired": 0,
        "removed": 0, "blocked": 0, "parse_failed": 5, "unknown": 0,
    }
    assert quality["detail_collection_M"]["access_status_counts_sum_to_target"] is True
    assert quality["queue"]["detail_needed"] == 5
    assert quality["queue"]["request_scope_status"] == "UNCLEAR_PENDING_KEIS_CONFIRMATION"
    assert quality["validation"]["work24_detail_http_requests_this_run"] == 0
    assert quality["validation"]["official_factory_exact_complex_rows"] == 3553
    assert quality["industry_counts"]["기계"]["mapped_postings"] == 380
    assert quality["industry_counts"]["기계"]["official_confirmed_postings"] == 161
    assert quality["raw_detail_provenance"]["unique_M_postings_with_attempts"] == 140
    assert quality["raw_detail_provenance"]["latest_status_counts"]["success"] == 135
    assert quality["raw_detail_provenance"]["latest_status_counts"]["parse_failed"] == 5
    assert quality["raw_detail_provenance"]["source_filename"] == (
        "work24_priority_industry_detail_20260923.csv")
    assert quality["raw_detail_provenance"]["initial_requests_for_M"] == 140
    assert quality["raw_detail_provenance"]["retry_requests_for_M"] == 10
    assert quality["raw_detail_provenance"]["max_attempts_per_M_posting"] == 3
    assert len(quality["raw_detail_provenance"]["sha256"]) == 64
    assert quality["raw_detail_provenance"]["failed_posting_ids"] == [
        "K131112609090004", "K131132609080016", "K131132609090043",
        "K131132609100036", "K131132609140059",
    ]
    assert quality["raw_detail_provenance"]["collection_started_at_utc"]
    assert quality["raw_detail_provenance"]["collection_last_attempt_at_utc"]
    assert quality["canonical_generation_basis"]["saved_target_count"] == 140
    assert quality["canonical_generation_basis"]["target_selection"] == (
        "reuse saved M=140 IDs; no reselection")
