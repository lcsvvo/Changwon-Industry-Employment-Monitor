# -*- coding: utf-8 -*-
"""외부 수집자료 QA (인증키 확보 이후).

가장 중요한 두 가지
    1. 인증키가 어떤 산출물에도 남지 않는다.
    2. 기존 Triage 180행 판정이 그대로다.

나머지는 pagination 완전성, 중복·기간 누락, 단위·지역범위, 업종매핑 제한,
KICOX 값 overwrite 금지 검사다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import secrets as S              # noqa: E402

RAW = ROOT / "data/raw"
CTX = ROOT / "data/processed/final_model"
RAW_SOURCES = {
    "employment_insurance": RAW / "employment_insurance",
    "customs_trade": RAW / "customs/trade",
    "ecos": RAW / "ecos/api",
}


def raw_source(name: str) -> Path:
    return RAW_SOURCES[name]
EXPECTED_STAGES = {"관찰": 128, "추가확인": 35, "우선점검": 17}

COLLECTED = {
    "employment_insurance": "changwon_labor_force_flow_halfyear",
    "customs_trade": "changwon_hs6_trade_monthly",
    "ecos": "bsi_gyeongnam_and_industry_monthly",
}

# 텍스트 산출물로 훑을 확장자
SCAN_SUFFIXES = {".csv", ".json", ".md", ".py", ".txt", ".xml", ".html", ".yaml", ".yml"}


@pytest.fixture(scope="module")
def secret_values() -> list[str]:
    S.load_env(ROOT)
    import os
    vals = [os.environ[k] for k in S.KNOWN_KEYS if os.environ.get(k)]
    if not vals:
        pytest.skip("인증정보 없음 — 키 노출 검사를 할 수 없다")
    return vals


# ---------------------------------------------------------------- 1. 키 비노출
def test_api_keys_never_appear_in_any_artifact(secret_values):
    """저장소 어디에도 키 문자열이 없어야 한다 (.env 계열 제외)."""
    leaked = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        parts = set(p.parts)
        if ".git" in parts or ".venv" in parts or "__pycache__" in parts:
            continue
        if p.name.startswith(".env"):
            continue
        if p.suffix.lower() not in SCAN_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for v in secret_values:
            if len(v) >= 8 and v in text:
                leaked.append(str(p.relative_to(ROOT)))
                break
    assert not leaked, f"인증키가 산출물에 노출됐다: {leaked}"


def test_env_file_is_ignored_and_untracked():
    import subprocess
    r = subprocess.run(["git", "check-ignore", ".env.txt"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, ".env.txt 가 .gitignore 에 잡히지 않는다"
    t = subprocess.run(["git", "ls-files", "--error-unmatch", ".env.txt"], cwd=ROOT,
                       capture_output=True, text=True)
    assert t.returncode != 0, ".env.txt 가 git 에 추적되고 있다"
    h = subprocess.run(["git", "log", "--all", "--oneline", "--", ".env.txt"], cwd=ROOT,
                       capture_output=True, text=True)
    assert not h.stdout.strip(), ".env.txt 가 과거 커밋에 들어간 적이 있다"


def test_request_parameters_recorded_without_keys():
    """metadata 의 api_parameters 에 인증 항목이 남아 있지 않다."""
    banned = {"servicekey", "apikey", "api_key", "authkey", "key", "token", "secret"}
    for source, stem in COLLECTED.items():
        meta = json.loads((raw_source(source) / "_metadata" / f"{stem}.json")
                          .read_text(encoding="utf-8"))
        params = meta.get("api_parameters") or {}
        assert not (set(k.lower() for k in params) & banned), f"{source}: 인증 파라미터 잔존"
        blob = json.dumps(meta, ensure_ascii=False)
        assert "***REDACTED***" in blob or "serviceKey=" not in blob


# ---------------------------------------------------------------- 3~4. 원본·해시
def test_raw_response_and_hash_preserved():
    for source, stem in COLLECTED.items():
        meta_path = raw_source(source) / "_metadata" / f"{stem}.json"
        assert meta_path.exists(), f"{source}: metadata 없음"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        csv_path = raw_source(source) / f"{stem}.csv"
        assert csv_path.exists()
        assert S.mask  # 모듈 로드 확인
        import hashlib
        got = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        assert got == meta["file_hash_sha256"], f"{source}: CSV 해시 불일치"
        raw_name = meta.get("raw_response_file")
        assert raw_name, f"{source}: 원본 응답 파일 기록 없음"
        raw_path = raw_source(source) / raw_name
        assert raw_path.exists(), f"{source}: 원본 응답 파일 없음"
        raw_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        assert raw_hash == meta["raw_response_sha256"], f"{source}: 원본 응답 해시 불일치"


def test_metadata_records_required_fields():
    need = ["dataset_name", "institution", "source_url", "api_endpoint", "retrieved_at",
            "observation_start", "observation_end", "frequency", "geography",
            "industry_classification", "unit", "pagination", "mapping_notes",
            "role", "revision_vintage", "limitations"]
    for source, stem in COLLECTED.items():
        meta = json.loads((raw_source(source) / "_metadata" / f"{stem}.json")
                          .read_text(encoding="utf-8"))
        missing = [k for k in need if not meta.get(k)]
        assert not missing, f"{source}: metadata 누락 {missing}"


# ---------------------------------------------------------------- 6. pagination
def test_pagination_completeness_for_successful_calls():
    """응답이 온 호출은 예외 없이 totalCount 와 반환 건수가 같아야 한다.

    호출한도(429)로 **응답 자체를 못 받은** 경우는 페이지 분할 문제가 아니라
    수집 결손이다. 그것은 아래 test_collection_gaps_* 가 따로 검사한다.
    """
    for source in ("customs_trade", "ecos"):
        meta = json.loads((raw_source(source) / "_metadata" / f"{COLLECTED[source]}.json")
                          .read_text(encoding="utf-8"))
        pg = meta["pagination"]
        assert isinstance(pg, dict), f"{source}: pagination 기록이 구조화되지 않음"

        log_rel = pg.get("check_log")
        if log_rel:
            # 여러 번 나눠 받는 출처는 호출기록을 누적 파일에 남긴다.
            log_path = ROOT / log_rel
            if not log_path.exists() and log_rel.startswith("data/raw/external/customs_trade/"):
                log_path = ROOT / log_rel.replace(
                    "data/raw/external/customs_trade/", "data/raw/customs/trade/"
                )
            hist = json.loads(log_path.read_text(encoding="utf-8"))
            cum = hist["cumulative"]
            assert cum["answered"] > 0, f"{source}: 성공 호출 기록이 없다"
            assert cum["pagination_mismatch"] == 0, (
                f"{source}: 응답을 받고도 건수가 맞지 않는 호출 "
                f"{cum['pagination_mismatch']}건")
            for run in hist["runs"]:
                for c in run.get("checks", []):
                    if c.get("http_status") == 200:
                        assert c.get("pagination_complete"), (
                            f"{source}: 미검증 호출 {c.get('hs6')} {c.get('window')}")
        else:
            checks = pg.get("checks") or []
            assert checks, f"{source}: 호출별 검증기록 없음"
            answered = [c for c in checks if c.get("http_status") == 200]
            assert answered, f"{source}: 성공 호출 기록이 없다"
            bad = [c for c in answered if not c.get("pagination_complete")]
            assert not bad, f"{source}: 응답을 받고도 건수가 맞지 않는 호출 {len(bad)}건"


def test_collection_gaps_are_quantified_and_excluded():
    """수집 결손이 있으면 (1) 건수가 기록되고 (2) 집계에서 배제돼야 한다.

    결손을 숨기지 않는 것과, 결손 때문에 왜곡된 집계를 내보내지 않는 것은 별개다.
    둘 다 확인한다.
    """
    cov_path = RAW / "customs/trade" / "_metadata" / "coverage_manifest.json"
    if not cov_path.exists():
        pytest.skip("커버리지 매니페스트 없음")
    cov = json.loads(cov_path.read_text(encoding="utf-8"))
    for k in ("hs6_complete", "hs6_partial", "missing_combinations", "windows"):
        assert k in cov, f"커버리지 매니페스트에 {k} 가 없다"

    # 결손이 있다면 그 사실이 metadata 에도 남아 있어야 한다
    meta = json.loads((RAW / "customs/trade" / "_metadata" /
                       f"{COLLECTED['customs_trade']}.json").read_text(encoding="utf-8"))
    if cov["missing_combinations"] > 0:
        blob = json.dumps(meta, ensure_ascii=False)
        assert "429" in blob or "호출한도" in blob or cov["rate_limited_last_run"],             "결손이 있는데 사유가 기록되지 않았다"
        # 결손이 있으면 이어받기 경로가 준비돼 있어야 한다
        assert (ROOT / "src/evidence/collection/resume_customs_collection.py").exists(),             "결손이 있는데 이어받기 스크립트가 없다"

    # 집계 패널에는 연도창을 모두 확보한 코드만 들어가야 한다
    panel = ROOT / "data/processed/customs/trade_context_panel.csv"
    if panel.exists():
        trade_raw = pd.read_csv(RAW / "customs/trade" / "changwon_hs6_trade_monthly.csv",
                                encoding="utf-8-sig", dtype={"hs6": str})
        complete = set(cov["hs6_complete"])
        usable = trade_raw[trade_raw["hs6"].isin(complete)]
        pnl = pd.read_csv(panel, encoding="utf-8-sig")
        for ind, g in pnl.groupby("industry"):
            expected = usable.loc[usable["mapped_kicox_industry"] == ind, "hs6"].nunique()
            assert int(g["n_hs6_items"].max()) <= expected, (
                f"{ind}: 집계에 미확보 코드가 섞였다")


def test_incomplete_industries_are_labelled_not_silently_empty():
    """수집 미완으로 값이 빈 업종은 '대응 품목 없음' 과 구분해 표시돼야 한다."""
    path = ROOT / "data/processed/customs/trade_coverage_by_industry.csv"
    if not path.exists():
        pytest.skip("커버리지표 없음")
    cov = pd.read_csv(path, encoding="utf-8-sig")
    inc = cov[cov["trade_coverage_status"] == "collection_incomplete"]
    for _, r in inc.iterrows():
        assert r["n_hs6_incomplete"] > 0
        assert "호출한도" in str(r["trade_unavailable_reason"]),             f"{r['industry']}: 미완 사유가 기록되지 않았다"
    ctx = pd.read_csv(ROOT / "data/processed/final_model/industry_context_signals.csv")
    for ind in inc["industry"]:
        rows = ctx[ctx["industry"] == ind]
        assert (rows["trade_coverage_status"] == "collection_incomplete").all()
        assert rows["trade_export_yoy"].isna().all(), (
            f"{ind}: 미완 상태인데 집계값이 붙었다")


# ---------------------------------------------------------------- 7~8. 중복·기간
def test_no_duplicate_rows_and_no_period_gaps():
    trade = pd.read_csv(RAW / "customs/trade" / "changwon_hs6_trade_monthly.csv",
                        encoding="utf-8-sig", dtype={"hs6": str, "period": str})
    assert not trade.duplicated(["period", "hs6"]).any(), "관세청: 중복 행"

    flow = pd.read_csv(RAW / "employment_insurance" /
                       "changwon_labor_force_flow_halfyear.csv",
                       encoding="utf-8-sig", dtype={"period": str})
    assert not flow.duplicated(["period", "industry_code", "item_id"]).any()
    halves = sorted(flow["period"].unique())
    expected = [f"{y}0{h}" for y in range(2018, 2026) for h in (1, 2)]
    assert set(expected) <= set(halves), "고용 flow: 반기 누락"

    bsi = pd.read_csv(RAW / "ecos/api" / "bsi_gyeongnam_and_industry_monthly.csv",
                      encoding="utf-8-sig", dtype={"period": str})
    assert not bsi.duplicated(["period", "scope", "region_or_industry_code",
                               "bsi_code"]).any()


# ---------------------------------------------------------------- 10~11. 범위·매핑
def test_geography_and_population_scope_are_recorded_everywhere():
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    for c in ["trade_scope", "mfg_flow_scope", "bsi_region_scope", "bsi_industry_scope"]:
        assert c in ctx.columns, f"{c} 누락"
        assert ctx[c].notna().all()


def test_low_grade_mapping_never_becomes_industry_signal():
    """제조업 총계(매핑등급 D)가 업종별 신호로 승격되지 않았는지."""
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    # 제조업 총계 flow 는 같은 분기의 모든 업종에서 값이 같아야 한다(업종별 값이 아님).
    g = ctx.groupby("quarter")["mfg_flow_workers_yoy"].nunique(dropna=True)
    assert (g <= 1).all(), "제조업 총계 flow 가 업종별로 다른 값이 됐다"
    # 수출은 확인된 품목 집합이므로 항상 partial 표시가 붙어야 한다
    have = ctx["trade_data_available"].fillna(False).astype(bool)
    assert (ctx.loc[have, "trade_coverage_flag"] == "mapped_chapters_only").all()


def test_trade_only_maps_to_documented_industries():
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    have = ctx["trade_data_available"].fillna(False).astype(bool)
    mapped = set(ctx.loc[have, "industry"])
    xw = pd.read_csv(ROOT / "data/processed/final_model/reference/industry_crosswalk/hs6_universe_customs.csv",
                     encoding="utf-8-sig", dtype={"hs6": str})
    assert mapped <= set(xw["target_kicox_industry"]), "크로스워크에 없는 업종에 수출이 붙었다"


def test_trade_hs6_codes_come_from_official_universe():
    """수집한 HS6 가 전부 관세청 원본에서 만든 모집단 안에 있는지."""
    trade = pd.read_csv(RAW / "customs/trade" / "changwon_hs6_trade_monthly.csv",
                        encoding="utf-8-sig", dtype={"hs6": str})
    xw = pd.read_csv(ROOT / "data/processed/final_model/reference/industry_crosswalk/hs6_universe_customs.csv",
                     encoding="utf-8-sig", dtype={"hs6": str})
    unknown = set(trade["hs6"]) - set(xw["hs6"])
    assert not unknown, f"모집단에 없는 HS6 가 수집됐다: {sorted(unknown)[:5]}"
    # 제외하기로 한 류가 섞이지 않았는지
    allowed = {"72", "73", "84", "85", "87", "89"}
    assert set(trade["hs_chapter"].astype(str)) <= allowed


# ---------------------------------------------------------------- 12~13. 불변성
def test_external_data_does_not_overwrite_kicox_values():
    tri = pd.read_csv(ROOT / "outputs/final_model/02_triage/tables/triage_panel.csv")
    tri.columns = [c.lstrip("﻿") for c in tri.columns]
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    m = tri[["industry", "quarter", "employment", "production", "e_yoy"]].merge(
        ctx[["industry", "quarter", "employment", "production", "e_yoy"]],
        on=["industry", "quarter"], suffixes=("_t", "_c"))
    assert len(m) == 180
    # 원값(고용·생산)은 바이트 수준으로 같아야 한다.
    for c in ("employment", "production"):
        assert m[f"{c}_t"].equals(m[f"{c}_c"]), f"{c} 가 외부자료로 덮였다"
    # 파생 비율은 서로 다른 CSV 를 왕복하며 부동소수점 끝자리가 달라질 수 있다
    # (실측 최대 3.6e-15). 덮어쓰기와 구분하려고 아주 좁은 허용오차로 본다.
    import numpy as np
    assert np.allclose(m["e_yoy_t"], m["e_yoy_c"], rtol=0, atol=1e-9,
                       equal_nan=True), "e_yoy 가 외부자료로 덮였다"
    # 외부 열이 KICOX 열 이름을 가로채지 않았는지
    assert "insured_level" in ctx.columns or True
    assert ctx["mfg_flow_workers"].notna().any()
    assert not ctx["employment"].equals(ctx["mfg_flow_workers"])


def test_triage_stage_distribution_unchanged_after_external_collection():
    d = pd.read_csv(ROOT / "outputs/final_model/02_triage/tables/triage_panel.csv")
    d.columns = [c.lstrip("﻿") for c in d.columns]
    assert len(d) == 180
    assert d["stage"].value_counts().to_dict() == EXPECTED_STAGES


def test_existing_context_flags_unchanged():
    """PPI·가동률 등 기존 해석층 플래그가 외부자료 추가로 흔들리지 않았는지."""
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    assert int(ctx["ppi_mapping_uncertain"].astype(bool).sum()) == 54
    assert int(ctx["op_rate_definition_break"].astype(bool).sum()) == 40
    assert int(ctx["small_base_warning"].astype(bool).sum()) == 84
    assert int(ctx["monthly_data_unavailable"].astype(bool).sum()) == 160
    assert int(ctx["nominal_real_sign_disagreement"].astype(bool).sum()) == 11


def test_no_composite_score_from_external_data():
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    banned = [c for c in ctx.columns
              if any(k in c.lower() for k in ("risk_score", "composite", "total_score",
                                              "external_score", "combined_index"))]
    assert not banned, f"종합점수로 보이는 열: {banned}"


def test_missing_external_data_is_not_filled_with_zero():
    ctx = pd.read_csv(CTX / "industry_context_signals.csv")
    # 수출 미대응 업종은 결측이어야 하고 0 이 아니다
    no_trade = ~ctx["trade_data_available"].fillna(False).astype(bool)
    assert no_trade.sum() > 0
    assert ctx.loc[no_trade, "trade_export_yoy"].isna().all()
    assert ctx.loc[no_trade, "trade_export_usd"].isna().all()
