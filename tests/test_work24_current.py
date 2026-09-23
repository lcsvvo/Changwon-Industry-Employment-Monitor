from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import work24_current as current  # noqa: E402


CURRENT_ROBOTS = """
Allow: /
Sitemap: https://www.work24.go.kr/cm/static/sitemap.xml

User-Agent: *
disallow: /cm/common/
disallow: /sa/
disallow: /ei/
disallow: /cm/f/c/0100/selectUnifySearchPost.do
"""

LEGACY_ROBOTS = """
User-Agent: *
Disallow: /empInfo/
Allow: /
"""


def test_domain_specific_robots_are_not_confused():
    for path in current.CURRENT_PATHS.values():
        assert current.robots_allows(
            CURRENT_ROBOTS, current.CURRENT_ROBOTS_URL, current.CURRENT_ORIGIN + path)
    assert not current.robots_allows(
        LEGACY_ROBOTS,
        current.LEGACY_ROBOTS_URL,
        "https://www.work.go.kr/empInfo/empInfoSrch/detail/empDetailAuthView.do",
    )


def test_current_search_contract_has_verified_parameters():
    params = current.list_params(
        page_index=2, region_codes=("48121", "48123"),
        registered_from="20260901", registered_to="20260930",
    )
    assert params["pageIndex"] == "2"
    assert params["region"] == "48121|48123"
    assert params["regDateStdtParam"] == "20260901"
    assert params["regDateEndtParam"] == "20260930"
    with pytest.raises(ValueError):
        current.list_params(registered_from="2026-09-01")


LIST_HTML = """
<table id="contentArea"><tbody><tr id="list1">
 <td><p class="cp_name">테스트기업</p>
 <a href="/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo=K123&amp;infoTypeCd=VALIDATION&amp;infoTypeGroup=tb_workinfoworknet">CNC 가공원</a></td>
 <td>월급 300만원 경력무관 학력무관 경남 창원시 성산구</td>
 <td>마감일 : 2026-10-31 등록일 : 2026-09-23</td>
</tr></tbody></table>
"""


def test_current_list_parser_gets_id_from_public_detail_link():
    row = current.parse_current_list(LIST_HTML)[0]
    assert row["wanted_auth_no"] == "K123"
    assert row["company"] == "테스트기업"
    assert row["title"] == "CNC 가공원"
    assert row["info_type_cd"] == "VALIDATION"
    assert row["info_type_group"] == "tb_workinfoworknet"
    assert row["due_date_raw"] == "2026-10-31"
    assert row["registration_date_raw"] == "2026-09-23"


DETAIL_HTML = """
<div class="tit_area"><p class="corp_info"><strong>테스트기업</strong></p>
 <strong class="title">CNC 조작원 모집</strong></div>
<div class="fold"><strong>직무내용</strong>CNC 가공. 담당자 test@example.com 010-1234-5678</div>
<table><tbody>
 <tr><th>모집 인원</th><td>3명</td><th>모집 직종</th><td>CNC 선반 조작원</td></tr>
 <tr><th>직종 키워드</th><td>CNC</td><th>경력</th><td>경력무관</td></tr>
 <tr><th>학력</th><td>학력무관</td><th>자격 면허</th><td>관계없음</td></tr>
 <tr><th>고용 형태</th><td>기간의 정함이 없는 근로계약</td><th>임금 조건</th><td>월급 300만원</td></tr>
 <tr><th>근무 예정지</th><td>경남 창원시 성산구</td></tr>
 <tr><th>채용공고 등록일시</th><td>2026.09.23 09:00:00</td>
     <th>구인인증번호</th><td>K123</td></tr>
</tbody></table>
<div><strong>접수 마감일</strong><p>2026.10.31 24:00</p></div>
<section><h3>채용 담당자</h3><p>홍길동 055-123-4567 private@example.com</p></section>
"""


def test_current_detail_parser_is_field_complete_and_privacy_minimised():
    url = current.current_detail_url("K123")
    row = current.parse_current_detail(DETAIL_HTML, url, "2026-09-23T00:00:00+00:00")
    assert row["wanted_auth_no"] == "K123"
    assert row["company"] == "테스트기업"
    assert row["recruitment_count_raw"] == "3명"
    assert row["recruitment_count"] == 3
    assert row["occupation"] == "CNC 선반 조작원"
    assert row["occupation_keywords"] == "CNC"
    assert "test@example.com" not in row["job_description"]
    assert "010-1234-5678" not in row["job_description"]
    assert "홍길동" not in str(row.values())
    assert row["personal_contact_fields_collected"] is False


def test_recruitment_count_only_parses_unambiguous_value():
    assert current.parse_recruitment_count("5명") == 5
    assert current.parse_recruitment_count("2 명") == 2
    assert current.parse_recruitment_count("5명 이상") is None
    assert current.parse_recruitment_count(None) is None


def test_changwon_address_derivation_is_conservative():
    parsed = current.parse_changwon_address("경상남도 창원시 성산구 성산동 12")
    assert parsed == {
        "city": "창원시", "district": "성산구", "dong_eup_myeon": "성산동"}
    assert current.parse_changwon_address("부산광역시 강서구") == {
        "city": None, "district": None, "dong_eup_myeon": None}


def test_sample_is_capped_and_full_collection_is_not_a_cli_mode():
    with pytest.raises(ValueError):
        current.existing_ids(current.SAMPLE_MAX + 1)
    parser_modes = ("audit", "enrich-priority")
    assert "collect-all" not in parser_modes


def test_priority_targets_come_only_from_latest_model_and_existing_mapping():
    targets, stats = current.priority_targets()
    assert set(stats["priority_industries"]) == {"기계", "목재종이"}
    assert stats["existing_total"] == 2045
    assert stats["industry_counts"] == {"기계": 380, "목재종이": 15}
    assert stats["unique_wanted_auth_no"] == 395
    assert len({row["wanted_auth_no"] for row in targets}) == len(targets)
    assert all(row["kicox_industry"] in {"기계", "목재종이"} for row in targets)


def test_priority_validation_queue_is_recent_and_industry_interleaved():
    rows = [
        {"kicox_industry": "기계", "wanted_auth_no": "M1", "reg_date": "2026-01-01"},
        {"kicox_industry": "기계", "wanted_auth_no": "M2", "reg_date": "2026-02-01"},
        {"kicox_industry": "목재종이", "wanted_auth_no": "W1", "reg_date": "2026-01-15"},
        {"kicox_industry": "목재종이", "wanted_auth_no": "W2", "reg_date": "2026-02-15"},
    ]
    queued = current.interleaved_targets(rows)
    assert [row["wanted_auth_no"] for row in queued] == ["M2", "W2", "M1", "W1"]


def test_small_validation_cap_is_shared_across_industry_runs(tmp_path, monkeypatch):
    snapshot = tmp_path / "detail.csv"
    for index in range(current.SAMPLE_MAX):
        current.append_detail_row(snapshot, {
            "wanted_auth_no": f"K{index}",
            "request_status": "FAILED",
            "http_status": 200,
            "error": "expired",
        })
    monkeypatch.setattr(current, "current_access_gate", lambda client: {"checked": True})
    with pytest.raises(current.Work24AccessStop, match="lifetime cap"):
        current.collect_priority_details(
            [{"wanted_auth_no": "NEW", "kicox_industry": "전기전자"}],
            snapshot,
            max_requests=1,
        )
