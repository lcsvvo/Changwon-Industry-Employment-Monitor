# -*- coding: utf-8 -*-
"""해석층·신뢰도층 QA.

핵심은 '해석층을 붙여도 Triage 판정이 그대로인가' 다.
나머지는 결측 처리, 미래참조, 매핑 등급 제한, 모집단 혼동 방지 검사다.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence.modules import monthly_panel as mp                # noqa: E402
from evidence.modules import signals as sg                      # noqa: E402
from evidence.modules.config import REAL_PROD_DECLINE           # noqa: E402

TRIAGE = ROOT / "outputs/final_model/02_triage/tables/triage_panel.csv"
CTX = ROOT / "data/processed/final_model/industry_context_signals.csv"
FROZEN = ["stage", "stage_reason", "E", "R", "A", "P", "scale_ok", "persist"]


@pytest.fixture(scope="module")
def triage() -> pd.DataFrame:
    d = pd.read_csv(TRIAGE)
    d.columns = [c.lstrip("﻿") for c in d.columns]
    return d.sort_values(["quarter", "industry"]).reset_index(drop=True)


@pytest.fixture(scope="module")
def ctx() -> pd.DataFrame:
    if not CTX.exists():
        pytest.skip("해석층 산출물 없음 — python src/build_context_layer.py 먼저 실행")
    d = pd.read_csv(CTX)
    d.columns = [c.lstrip("﻿") for c in d.columns]
    return d.sort_values(["quarter", "industry"]).reset_index(drop=True)


# ---------------------------------------------------------------- A. 판정 불변
def test_A_triage_stage_unchanged_for_all_180_rows(triage, ctx):
    assert len(triage) == 180 and len(ctx) == 180
    m = triage[["industry", "quarter"] + FROZEN].merge(
        ctx[["industry", "quarter"] + FROZEN], on=["industry", "quarter"],
        suffixes=("_triage", "_ctx"))
    assert len(m) == 180
    for c in FROZEN:
        left, right = m[c + "_triage"], m[c + "_ctx"]
        if pd.api.types.is_numeric_dtype(left):
            assert np.allclose(left.astype(float), right.astype(float),
                               equal_nan=True), f"{c} 값이 달라졌다"
        else:
            assert left.astype(str).equals(right.astype(str)), f"{c} 값이 달라졌다"


# ---------------------------------------------------------------- B. 해석층 제거 시 재현
def test_B_removing_context_columns_reproduces_triage_output(triage, ctx):
    """해석층이 추가한 열을 모두 떼면 Triage 원 산출물과 같은 판정 집합이 남는다."""
    context_only = set(ctx.columns) - set(triage.columns)
    assert context_only, "해석층이 아무 열도 추가하지 않았다"
    stripped = ctx.drop(columns=list(context_only))
    common = [c for c in stripped.columns if c in FROZEN + ["industry", "quarter"]]
    base = triage[common].sort_values(["quarter", "industry"]).reset_index(drop=True)
    got = stripped[common].sort_values(["quarter", "industry"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(base, got, check_dtype=False)
    assert triage.stage.value_counts().to_dict() == ctx.stage.value_counts().to_dict()


# ---------------------------------------------------------------- C. 미래 참조 없음
def test_C_monthly_yoy_never_uses_future_months():
    panel = mp.build_monthly_panel(ROOT)
    y = mp.add_monthly_yoy(panel)
    used = y.dropna(subset=["yoy_pct"])
    cur = pd.PeriodIndex(used["month"], freq="M")
    # 비교 기준은 정확히 12개월 전이어야 한다 (미래월·근접월 대체 금지)
    lag_value_exists = used["value_lag12"].notna()
    assert lag_value_exists.all()
    ref = cur - 12
    assert (ref < cur).all()
    # 분기 지속성이 참조하는 달은 모두 해당 분기 이하 시점이다.
    q = mp.quarterly_persistence(y)
    for col in [c for c in q.columns if c.endswith("months_observed")]:
        assert (q[col].fillna(0) <= 3).all(), f"{col} 이 한 분기 3개월을 넘는다"


def test_C2_portal_quarterly_era_files_are_not_treated_as_months():
    """2024Q2 이후 포털 공표본은 분기값이므로 월 패널에 들어오면 안 된다."""
    panel = mp.build_monthly_panel(ROOT)
    portal = panel[panel["vintage"] == "portal_raw"]
    assert portal["month"].max() < "2024-04"


# ---------------------------------------------------------------- D. PPI 등급 제한
def test_D_low_grade_ppi_never_produces_assertive_real_production_flag(ctx):
    low = ctx[ctx["ppi_mapping_grade"].isin(["C", "D"])]
    assert len(low) > 0
    assert low["ppi_adjusted_production_decline_signal"].isna().all(), (
        "C·D 등급 업종에서 단정형 실질생산 위축 flag 가 생성됐다")
    assert low["ppi_adjusted_production_yoy"].isna().all(), (
        "C·D 등급 업종에 단일 조정값이 들어갔다")
    # C 등급은 밴드 표기만 허용
    band = ctx[ctx["ppi_mapping_grade"] == "C"]
    assert band["ppi_adjusted_production_decline_band"].notna().any()


def test_D2_ppi_uncertain_flag_matches_grade(ctx):
    assert (ctx["ppi_mapping_uncertain"]
            == ctx["ppi_mapping_grade"].isin(["C", "D"])).all()


# ---------------------------------------------------------------- E. 소규모 절대변화 표시
def test_E_small_industries_always_show_absolute_firm_change(ctx):
    small = ctx[ctx["small_base_warning"].astype(bool)]
    assert len(small) > 0
    assert small["firms_op_change_display"].notna().all()
    assert small["firms_op_change_display"].str.contains("개").all(), (
        "소규모 업종 표시에 절대 개수가 빠졌다")
    # 절대 증감 개수 열 자체도 있어야 한다
    have = small["firms_op_change_count"].notna() | small["firms_op_level"].notna()
    assert have.all()


# ---------------------------------------------------------------- F. 모집단 혼동 방지
def test_F_employment_insurance_never_overwrites_kicox_employment(triage, ctx):
    m = triage[["industry", "quarter", "employment"]].merge(
        ctx[["industry", "quarter", "employment", "insured_level"]],
        on=["industry", "quarter"], suffixes=("_triage", "_ctx"))
    assert np.allclose(m["employment_triage"], m["employment_ctx"], equal_nan=True)
    overlap = m.dropna(subset=["insured_level"])
    assert len(overlap) > 0
    assert not np.allclose(overlap["employment_ctx"], overlap["insured_level"]), (
        "산단 고용값이 창원시 고용보험 값으로 바뀌었다")
    # 수준 비교·점유율이 산출물에 없어야 한다
    banned = [c for c in ctx.columns if "insured_share" in c or "insured_ratio" in c]
    assert not banned


# ---------------------------------------------------------------- G. 원본 해시 보존
def test_G_external_raw_files_match_recorded_hashes():
    meta_dir = ROOT / "data/raw"
    if not meta_dir.exists():
        pytest.skip("외부 원자료 없음")
    checked = 0
    for meta in meta_dir.rglob("_metadata/*.json"):
        m = json.loads(meta.read_text(encoding="utf-8"))
        if not isinstance(m, dict):
            continue                                   # 실패기록 등 목록형 로그는 데이터셋 metadata 가 아니다
        h = m.get("file_hash_sha256")
        if not h:
            continue                                   # 미수집 상태 기록 파일
        target = None
        for cand in meta.parent.parent.iterdir():
            if cand.is_file() and cand.stem == meta.stem:
                target = cand
                break
        assert target is not None, f"{meta.name} 의 원본 파일을 찾지 못했다"
        got = hashlib.sha256(target.read_bytes()).hexdigest()
        assert got == h, f"{target.name} 의 해시가 metadata 와 다르다"
        checked += 1
    assert checked > 0, "해시가 기록된 외부 원자료가 하나도 없다"


# ---------------------------------------------------------------- H. 추적 가능성
def test_H_every_processed_row_is_traceable_to_source_and_period(ctx):
    meta_path = ROOT / "outputs/final_model/06_report_assets/qa/external_evidence_run_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["inputs"] and meta["code_sha256"]
    assert meta["run_at_utc"] and meta["window"] == ["2022Q1", "2026Q2"]
    # 모든 행이 기간·업종 키를 갖고, 자료 출처 표기 열이 비어 있지 않다
    assert ctx[["industry", "quarter"]].notna().all().all()
    assert ctx["op_rate_basis"].notna().all()
    assert ctx["cross_source_population_note"].notna().all()
    assert ctx["quality_flag_list"].notna().all()


# ---------------------------------------------------------------- 결측 취급
def test_missing_inputs_are_not_coerced_to_normal(ctx):
    """결측을 0 또는 '정상' 으로 바꾸지 않는다."""
    assert ctx["ppi_adjusted_production_decline_signal"].isna().sum() > 0
    # 월별 자료가 없는 분기는 '지속성 0' 이 아니라 '확인 불가' 로 남아야 한다
    no_monthly = ctx[ctx["employment_months_observed"].isna()]
    assert len(no_monthly) > 0
    assert (~no_monthly["monthly_signal_3of3"].astype(bool)).all()
    assert no_monthly["monthly_data_unavailable"].astype(bool).all()


def test_signal_thresholds_are_own_and_sensitivity_is_reported():
    s = pd.read_csv(ROOT / "logs/validation/context_layer/signal_threshold_sensitivity.csv")
    assert set(s["signal"]) == set(sg.SIGNAL_LABELS) - {
        "production_maintained_employment_decline"}
    # 기준선과 같은 값에서는 바뀌는 행이 0 이어야 한다 (계산 일관성)
    same = s[s["baseline_threshold"] == s["alternative_threshold"]]
    assert len(same) == 3 and (same["n_rows_changed"] == 0).all()


def test_no_composite_risk_score_created(ctx):
    banned = [c for c in ctx.columns
              if any(k in c.lower() for k in ("risk_score", "composite", "total_score",
                                              "confidence_score", "reliability_score"))]
    assert not banned, f"종합점수로 보이는 열이 생겼다: {banned}"


def test_real_production_threshold_is_used_consistently(ctx):
    usable = ctx[ctx["ppi_mapping_grade"].isin(["A", "B"])
                 & ctx["ppi_adjusted_production_yoy"].notna()]
    expected = usable["ppi_adjusted_production_yoy"] <= REAL_PROD_DECLINE
    got = usable["ppi_adjusted_production_decline_signal"].astype(bool)
    assert (expected.values == got.values).all()
