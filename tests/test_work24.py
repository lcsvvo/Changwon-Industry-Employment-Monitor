# -*- coding: utf-8 -*-
"""work24 파이프라인 규칙 테스트.

순수함수 테스트는 항상 돈다. 원자료(data/raw/**)는 저장소에 커밋되지 않으므로
(프로젝트 정책: 원자료 로컬 보관) 자료가 있어야 하는 테스트만 skip 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/evidence/collection"))

import work24 as w  # noqa: E402

RAW_5GU = sorted(w.RAW_DIR.glob("work24_5gu_*.csv"))
HAS_SNAPSHOT = bool(RAW_5GU)
HAS_HISTORICAL = w.HISTORICAL.exists()
HAS_OUTPUTS = (w.OUT_DIR / "work24_analysis_ready.csv").exists()

needs_snapshot = pytest.mark.skipif(not HAS_SNAPSHOT, reason="5개 구 RAW 없음(로컬 자료)")
needs_outputs = pytest.mark.skipif(not HAS_OUTPUTS, reason="processed 산출물 없음")


# ── 목록 파서 ────────────────────────────────────────────────────────────
LIST_HTML = """
<table class="tbl_list"><tbody>
<tr>
  <td><a href="http://www.work.go.kr/empInfo/empInfoSrch/detail/empDetailAuthView.do?callPage=detail&amp;wantedAuthNo=K13113260918005">(주)테스트기계</a></td>
  <td class="pl20 al">
    <a href="...wantedAuthNo=K13113260918005">머시닝센터 가공사원 모집</a><br/>
    <span><em class="ico_pay month">월급</em> 300 만원 이상</span><br/>
    <span class="fs_13">경남 창원시 성산구</span>
  </td>
  <td>[인증]</td>
  <td><p id="hak0"><script>var hak = '고졸이상';</script></p>경력 3년 </td>
  <td>26-09-18</td>
  <td><strong>26-11-17</strong></td>
</tr>
</tbody></table>
"""


def test_list_parser_extracts_core_fields():
    rows = w.parse_list_page(LIST_HTML)
    assert len(rows) == 1
    r = rows[0]
    assert r["wanted_auth_no"] == "K13113260918005"
    assert r["company_raw"] == "(주)테스트기계"
    assert r["title_raw"] == "머시닝센터 가공사원 모집"
    assert r["region_raw"] == "경남 창원시 성산구"
    assert r["reg_date_raw"] == "26-09-18"
    assert r["due_date_raw"] == "26-11-17"


def test_list_parser_recovers_wage_type_and_education():
    """기존 크롤러가 놓친 두 값 — 임금유형(em 클래스)과 학력(script var hak)."""
    r = w.parse_list_page(LIST_HTML)[0]
    assert r["wage_type_raw"] == "월급"
    assert r["education_raw"] == "고졸이상"
    assert "경력 3년" in r["career_raw"]
    assert "고졸이상" not in r["career_raw"]      # 학력이 경력칸에 새지 않는다


def test_list_parser_skips_row_without_posting_id():
    """공고 ID 가 없으면 행을 만들지 않는다 — ID 를 임의 생성하지 않는다."""
    assert w.parse_list_page(LIST_HTML.replace("wantedAuthNo=", "x=")) == []


def test_parse_total_reads_expected_count():
    assert w.parse_total("총게시물 : <span>1,454</span>건") == 1454
    assert w.parse_total("<span>없음</span>") is None


# ── 지역 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("region,expected", [
    ("경남 창원시 의창구", "의창구"),
    ("경남 창원시 마산합포구", "마산합포구"),
    ("경남 의령군", "의령군"),
    ("서울 강남구", None),
])
def test_region_parsing(region, expected):
    assert w.parse_gu(region) == expected


def test_uiryeong_is_out_of_scope():
    assert "의령군" in w.OUT_OF_SCOPE_GU
    assert "의령군" not in w.IN_SCOPE_GU
    assert len(w.IN_SCOPE_GU) == 5


# ── 회사명 정규화 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("주식회사 한국기계", "(주)한국기계"),
    ("㈜한국기계", "한국기계"),
    ("（주）한국기계", "한국기계"),          # 전각 괄호
    ("유한회사 한국기계", "한국기계"),
])
def test_company_normalization_equates_legal_forms(a, b):
    assert w.normalize_company(a) == w.normalize_company(b)


def test_company_normalization_keeps_distinct_firms_apart():
    """문자열 정규화로 서로 다른 기업을 합치지 않는다."""
    assert w.normalize_company("(주)대성기계") != w.normalize_company("(주)대신기계")


def test_company_match_keys_handles_english_alias():
    keys = w.company_match_keys("주식회사 인시스(INSYS)")
    assert "인시스" in keys                     # 영문병기를 뗀 형태도 후보
    assert "인시스INSYS" in keys                # 원형도 유지
    # 한글 괄호주석은 영문병기가 아니므로 떼지 않는다
    assert w.company_match_keys("한국기계(창원공장)") == ["한국기계창원공장"]


# ── 임금 ────────────────────────────────────────────────────────────────
def test_wage_parsing_distinguishes_units():
    assert w.parse_wage("시급 10,320 원 이상", "시급")["wage_type"] == "시급"
    assert w.parse_wage("월급 300 만원 이상", "월급")["wage_type"] == "월급"
    assert w.parse_wage("연봉 3,600 만원", "연봉")["wage_type"] == "연봉"


def test_wage_parsing_converts_manwon_but_not_across_units():
    m = w.parse_wage("월급 300 만원 이상", "월급")
    assert m["wage_min"] == 3_000_000 and m["wage_unit"] == "원"
    h = w.parse_wage("시급 10,320 원 이상", "시급")
    # 근무시간이 없으므로 시급을 월급으로 환산하지 않는다
    assert h["wage_min"] == 10_320 and h["wage_type"] == "시급"


def test_wage_parsing_marks_unparsed_instead_of_guessing():
    assert w.parse_wage("회사内규정에 따름", "")["wage_parse_status"] == "UNPARSED"
    assert w.parse_wage("", "")["wage_min"] is None


# ── 경력 ────────────────────────────────────────────────────────────────
def test_career_parsing_separates_irrelevant_from_entry_level():
    """'관계없음' 과 '신입' 을 같은 0개월로 뭉개지 않는다."""
    irrelevant = w.parse_career("관계없음")
    entry = w.parse_career("신입")
    assert irrelevant["career_type"] == "관계없음"
    assert irrelevant["career_min_months"] is None      # 0 이 아니다
    assert entry["career_type"] == "신입"
    assert entry["career_min_months"] == 0
    assert irrelevant["career_min_months"] != entry["career_min_months"]


def test_career_parsing_reads_duration():
    assert w.parse_career("경력 3년")["career_min_months"] == 36
    assert w.parse_career("경력 6개월")["career_min_months"] == 6
    assert w.parse_career("경력")["career_parse_status"] == "PARSED_NO_DURATION"


# ── 날짜 ────────────────────────────────────────────────────────────────
def test_date_parsing_to_iso():
    assert w.parse_date("26-09-18") == ("2026-09-18", "PARSED")
    assert w.parse_date("26-11-17")[0] == "2026-11-17"


def test_invalid_date_is_flagged_not_dropped():
    assert w.parse_date("26-13-45") == (None, "INVALID_DATE")
    assert w.parse_date("상시채용") == (None, "UNPARSED")
    assert w.parse_date("") == (None, "EMPTY")


# ── 제조업 / KICOX ───────────────────────────────────────────────────────
@pytest.mark.parametrize("mid,expected", [
    ("29", True), ("10", True), ("34", True),
    ("68", False), ("86", False),
    (None, None), ("", None),
])
def test_manufacturing_classification(mid, expected):
    assert w.is_manufacturing_mid(mid) is expected


def test_unresolved_company_stays_unknown_not_non_manufacturing():
    """기업을 식별하지 못했다고 비제조업으로 단정하지 않는다."""
    assert w.is_manufacturing_mid(None) is None


def test_kicox_map_covers_manufacturing_mids():
    m = w.load_kicox_map()
    assert m["29"]["kicox_industry"] == "기계"
    assert m["30"]["kicox_industry"] == "운송장비"
    assert m["24"]["kicox_industry"] == "철강"


def test_kicox_etc_is_a_real_industry_not_a_fallback():
    """KICOX 실제 업종 '기타' 와 매핑 실패 UNMAPPED 는 다른 값이다."""
    m = w.load_kicox_map()
    assert m["32"]["kicox_industry"] == "기타"      # 가구 제조업 → 실제 '기타'
    assert "99" not in m                            # 미분류를 '기타'로 채우지 않는다


# ── 공식 KSIC 대조표 ─────────────────────────────────────────────────────
@pytest.mark.skipif(not w.KSIC_XLSX.exists(), reason="KSIC 연계표 없음(로컬 자료)")
def test_ksic_lookup_is_unambiguous():
    lut = w.load_ksic_lookup()
    assert lut["key"].is_unique                     # 한 이름이 두 중분류에 걸리지 않는다
    assert lut["ksic_mid"].str.fullmatch(r"\d{2}").all()


@pytest.mark.skipif(not w.KSIC_XLSX.exists(), reason="KSIC 연계표 없음(로컬 자료)")
def test_ksic_key_normalizes_punctuation_only():
    """공백·구두점만 지운다. 의미가 다른 이름을 같게 만들지 않는다."""
    assert w.ksic_key("절삭가공 및 유사 처리업") == w.ksic_key("절삭가공 및 유사처리업")
    assert w.ksic_key("기타 기계.장비") == w.ksic_key("기타 기계·장비")
    assert w.ksic_key("금속 가공업") != w.ksic_key("금속 주조업")


# ── 재공고 ───────────────────────────────────────────────────────────────
def test_repost_candidates_are_flagged_not_deleted():
    import pandas as pd
    df = pd.DataFrame({
        "company_raw": ["(주)가나", "주식회사 가나", "(주)다라"],
        "title_raw": ["용접원 모집", "용접원 모집", "경리 모집"],
    })
    df["normalized_company"] = df["company_raw"].map(w.normalize_company)
    out = w.flag_reposts(df)
    assert len(out) == len(df)                      # 행이 삭제되지 않는다
    assert out["repost_candidate"].tolist() == [True, True, False]
    assert out.loc[0, "duplicate_group_id"] == out.loc[1, "duplicate_group_id"]


# ── 원자료 보존 / 동결 snapshot ──────────────────────────────────────────
@pytest.mark.skipif(not HAS_HISTORICAL, reason="historical snapshot 없음(로컬 자료)")
def test_historical_snapshot_hash_is_unchanged():
    """2026-09-18 1,504건은 원본 바이트 그대로여야 한다."""
    assert w.sha256_file(w.HISTORICAL) == (
        "f33f36a335dfaf335095ad31ab7778b09eeb63ed0770731d41be2ee8ce8c5028")


@pytest.mark.skipif(not HAS_HISTORICAL, reason="historical snapshot 없음(로컬 자료)")
def test_historical_snapshot_is_1504_rows_and_three_gu():
    import pandas as pd
    df = pd.read_csv(w.HISTORICAL, encoding="utf-8-sig", dtype=str)
    assert len(df) == 1504
    gu = set(df["region"].map(w.parse_gu).dropna())
    assert gu == {"의창구", "성산구", "진해구"}      # 5개 구 자료가 아니다


@needs_snapshot
def test_snapshot_metadata_is_complete():
    meta = json.loads(RAW_5GU[-1].with_suffix(".metadata.json")
                      .read_text(encoding="utf-8"))
    for key in ("snapshot_id", "crawl_timestamp", "source", "source_url", "center",
                "region_scope", "query_filters", "expected_total", "collected_total",
                "pages_requested", "pages_failed", "parse_failures",
                "region_filter_mismatch", "robots_checked_at", "file_sha256"):
        assert key in meta, key
    assert meta["source"] == "work24"
    assert meta["file_sha256"] == w.sha256_file(RAW_5GU[-1])


@needs_snapshot
def test_snapshot_matches_site_expected_total():
    """조용한 누락(silent truncation)이 없었는지 총게시물과 대조한다."""
    meta = json.loads(RAW_5GU[-1].with_suffix(".metadata.json")
                      .read_text(encoding="utf-8"))
    assert meta["collected_total"] == meta["expected_total"]
    assert meta["pages_failed"] == 0 and meta["parse_failures"] == 0


@needs_snapshot
def test_snapshot_covers_five_gu_in_one_run():
    import pandas as pd
    df = pd.read_csv(RAW_5GU[-1], encoding="utf-8-sig", dtype=str)
    gu = df["region_raw"].map(w.parse_gu)
    assert set(gu.dropna()) >= set(w.IN_SCOPE_GU)
    assert df["crawl_timestamp"].nunique() == 1      # 동일 실행시점
    assert df["wanted_auth_no"].is_unique            # 공고 ID 보존·유일


# ── 산출물 규칙 ──────────────────────────────────────────────────────────
def _analysis():
    import pandas as pd
    return pd.read_csv(w.OUT_DIR / "work24_analysis_ready.csv", encoding="utf-8-sig")


@needs_outputs
def test_out_of_scope_rows_excluded_from_analysis_but_kept_in_raw():
    import pandas as pd
    a = pd.read_csv(w.OUT_DIR / "work24_analysis_ready.csv", encoding="utf-8-sig")
    assert (a["gu"] == "의령군").sum() == 0
    raw = pd.read_csv(RAW_5GU[-1], encoding="utf-8-sig", dtype=str)
    assert (raw["region_raw"].map(w.parse_gu) == "의령군").sum() > 0


@needs_outputs
def test_posting_id_preserved_and_unique():
    a = _analysis()
    assert a["wanted_auth_no"].is_unique
    assert a["wanted_auth_no"].notna().all()


@needs_outputs
def test_recruitment_count_missing_is_null_not_zero():
    """미확보 모집인원을 0명으로 처리하지 않는다."""
    a = _analysis()
    assert a["recruitment_count"].isna().all()
    assert (a["recruitment_count"] == 0).sum() == 0
    assert set(a["recruitment_count_source"]) == {"NOT_COLLECTED_ACCESS_POLICY"}


@needs_outputs
def test_posting_count_is_not_recruitment_count():
    """공고 수와 모집인원은 다른 값이다. 모집인원 미확보 시 합계를 만들지 않는다."""
    a = _analysis()
    summary = json.loads((w.OUT_DIR / "work24_quality_summary.json")
                         .read_text(encoding="utf-8"))
    assert len(a) > 0
    assert summary["decision_gate_evidence"]["level_b_available"] is False
    assert summary["decision_gate_evidence"]["recruitment_count_coverage_pct"] == 0.0


@needs_outputs
def test_ksic_direct_and_enriched_are_separated():
    a = _analysis()
    assert set(a["ksic_source"].dropna()) <= {
        "ENRICHED_FROM_FACTORY_REGISTER", "NOT_COLLECTED_ACCESS_POLICY"}
    # 공고 source 에서 직접 얻은 KSIC 는 없다 — 있다고 표시하지 않는다
    assert "SOURCE_DIRECT" not in set(a["ksic_resolution_method"])
    resolved = a[a["ksic_resolution_method"] == "COMPANY_MASTER_EXACT"]
    assert (resolved["company_match_status"] == "MATCH").all()


@needs_outputs
def test_raw_and_enriched_address_are_separate_columns():
    a = _analysis()
    assert "workplace_address_raw" in a.columns
    assert "workplace_address_enriched" in a.columns
    assert a["workplace_address_raw"].isna().all()     # 목록·상세에서 미확보
    enriched = a[a["workplace_address_enriched"].notna()]
    assert (enriched["address_source"] == "ENRICHED_FROM_FACTORY_REGISTER").all()
    assert (enriched["address_reference_date"] == "2024-12-31").all()


@needs_outputs
def test_unidentified_company_is_unknown_not_non_manufacturing():
    a = _analysis()
    unresolved = a[a["ksic_resolution_method"] == "UNRESOLVED"]
    assert unresolved["is_manufacturing"].isna().all()


@needs_outputs
def test_unmapped_kicox_is_null_not_etc():
    """매핑 실패를 KICOX 실제 업종 '기타' 로 채우지 않는다."""
    a = _analysis()
    unmapped = a[a["kicox_mapping_status"] == "UNMAPPED"]
    assert unmapped["kicox_industry"].isna().all()
    mapped = a[a["kicox_mapping_status"] == "MAPPED"]
    assert mapped["kicox_industry"].notna().all()
    assert set(mapped["kicox_industry"]) <= set(w.KICOX_INDUSTRIES)


@needs_outputs
def test_industrial_complex_never_claims_match_without_official_boundary():
    """공식 산단 경계가 없으므로 MATCH 를 부여하지 않는다."""
    a = _analysis()
    statuses = set(a["industrial_complex_match_status"])
    assert "MATCH" not in statuses
    assert statuses <= {"POSSIBLE", "NOT_MATCH", "UNKNOWN"}


@needs_outputs
def test_industrial_complex_not_inferred_from_gu_alone():
    """「성산구니까 산단」이 아니다 — 같은 구 안에서도 판정이 갈려야 한다."""
    a = _analysis()
    seongsan = a[a["gu"] == "성산구"]["industrial_complex_match_status"]
    assert seongsan.nunique() > 1


@needs_outputs
def test_industry_is_not_inferred_from_job_title():
    """직무 키워드로 산업을 정하지 않는다 — 기업 미식별이면 업종도 비어 있다."""
    a = _analysis()
    welding = a[a["title_raw"].str.contains("용접|조립|생산|품질", na=False)]
    unresolved = welding[welding["company_match_status"] != "MATCH"]
    assert unresolved["kicox_industry"].isna().all()


@needs_outputs
def test_evidence_rows_carry_their_matching_basis():
    import pandas as pd
    ev = pd.read_csv(w.OUT_DIR / "work24_decision_gate_evidence.csv",
                     encoding="utf-8-sig")
    for col in ("q1_q3_industry", "kicox_industry", "wanted_auth_no", "company_raw",
                "ksic_resolution_method", "company_match_status",
                "industrial_complex_match_status", "evidence_status"):
        assert col in ev.columns, col
    assert ev["kicox_industry"].notna().all()
    assert ev["recruitment_count"].isna().all()


@needs_outputs
def test_quality_summary_reports_failures_and_limits():
    s = json.loads((w.OUT_DIR / "work24_quality_summary.json")
                   .read_text(encoding="utf-8"))
    assert s["snapshot"]["collected_vs_expected_diff"] == 0
    assert s["snapshot"]["pages_failed"] == 0
    assert s["industrial_complex"]["match_status_blocked"] is True
    assert any("모집인원" in t for t in s["interpretation_limits"])
    assert any("노동수요" in t for t in s["interpretation_limits"])
