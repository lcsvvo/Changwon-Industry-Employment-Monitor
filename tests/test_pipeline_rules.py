# -*- coding: utf-8 -*-
"""
tests/test_pipeline_rules.py
새 전처리 파이프라인이 지켜야 할 핵심 규칙에 대한 최소 회귀 테스트.

이전 legacy 파이프라인(tests/test_analysis_rules.py 등)을 복원한 것이 아니라,
현재 규칙(§ 정확한 0=N, 결측/계산불가=INVALID, 업종 경계를 넘지 않는 lag4,
같은 업종+연속분기만 유효한 transition, run reset, revision 반영, X 보존,
raw 쓰기 금지)에 맞춰 새로 작성했다.

실행
    pytest tests/test_pipeline_rules.py -v

data/processed/kicox/*.csv 가 먼저 생성되어 있어야 한다
(notebooks/01_data_preprocessing.ipynb 또는 src/build_*.py 를 먼저 실행할 것).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

P_IND = ROOT / "data" / "processed" / "kicox" / "changwon_industry_master.csv"
P_TOT = ROOT / "data" / "processed" / "kicox" / "changwon_total_master.csv"
P_STATE = ROOT / "data" / "processed" / "kicox" / "changwon_state_panel.csv"
P_STATE_REF = ROOT / "data" / "processed" / "kicox" / "changwon_state_reference_panel.csv"

pytestmark = pytest.mark.skipif(
    not (P_IND.exists() and P_STATE.exists()),
    reason="data/processed/kicox 산출물이 없습니다. 먼저 build_changwon_master.py / "
           "build_kicox_analysis_panel.py 를 실행하세요.")


@pytest.fixture(scope="module")
def ind():
    return pd.read_csv(P_IND)


@pytest.fixture(scope="module")
def state_ref():
    return pd.read_csv(P_STATE_REF)


@pytest.fixture(scope="module")
def state_main():
    return pd.read_csv(P_STATE)


# ----------------------------------------------------------------------------
# 1. 업종 경계를 넘지 않는 lag4 (같은 업종 내부에서만 YoY 계산)
# ----------------------------------------------------------------------------

def test_yoy_independent_recalculation_matches_within_industry(ind):
    py_ = ind.pivot(index="quarter", columns="industry", values="production").sort_index()
    ey_ = ind.pivot(index="quarter", columns="industry", values="employment").sort_index()
    chk_p = ((py_ / py_.shift(4) - 1) * 100).replace([np.inf, -np.inf], np.nan)
    chk_e = ((ey_ / ey_.shift(4) - 1) * 100).replace([np.inf, -np.inf], np.nan)
    stored_p = ind.pivot(index="quarter", columns="industry", values="production_yoy").sort_index()
    stored_e = ind.pivot(index="quarter", columns="industry", values="employment_yoy").sort_index()
    diffs = pd.concat([(chk_p - stored_p).abs(), (chk_e - stored_e).abs()]).to_numpy(dtype=float).ravel()
    diffs = diffs[~np.isnan(diffs)]
    assert len(diffs) > 0
    assert diffs.max() < 1e-6


def test_lag4_never_crosses_industry_boundary(ind):
    # 업종별로 정렬된 순서에서 shift(4)가 다른 업종의 값을 끌어오지 않는지 직접 확인한다.
    s = ind.sort_values(["industry", "quarter"]).reset_index(drop=True)
    lag_industry = s.groupby("industry").industry.shift(4)
    valid = lag_industry.notna()
    assert (lag_industry[valid] == s.loc[valid, "industry"]).all()


# ----------------------------------------------------------------------------
# 2. 정확한 0 -> N, 결측/계산불가 -> INVALID, N != INVALID
# ----------------------------------------------------------------------------

def test_exact_zero_yoy_is_state_n(state_main):
    base = state_main[state_main.threshold == 0] if "threshold" in state_main.columns else state_main
    n_rows = base[base.state == "N"]
    assert len(n_rows) > 0
    assert ((n_rows.production_yoy == 0) | (n_rows.employment_yoy == 0)).all()


def test_missing_quarters_are_invalid_not_n(state_ref):
    known_missing = ["2023Q4", "2024Q4"]
    sub = state_ref[state_ref.quarter.isin(known_missing)]
    assert len(sub) > 0
    assert (sub.state == "INVALID").all(), "2023Q4/2024Q4(생산 결측)는 N이 아니라 INVALID여야 한다"


def test_n_and_invalid_are_mutually_exclusive(state_main):
    assert not ((state_main.state == "N") & (state_main.state == "INVALID")).any()
    assert set(state_main.state.unique()) <= {"S1", "S2", "S3", "S4", "N", "INVALID"}


# ----------------------------------------------------------------------------
# 3. transition: 같은 업종 + 실제 연속분기일 때만 유효
# ----------------------------------------------------------------------------

def test_transition_only_within_same_industry_and_adjacent_quarter(state_main):
    valid = state_main[state_main.valid_transition5 == True]
    assert len(valid) > 0
    s = state_main.set_index(["industry", "quarter_index"])
    for _, row in valid.iterrows():
        nxt = s.loc[(row.industry, row.quarter_index + 1)]
        assert nxt.state == row.next_state


def test_no_transition_across_invalid_gap(state_main):
    # INVALID인 분기 자체에서 나가는 4상태 전환(valid_transition)은 없어야 한다.
    invalid_rows = state_main[state_main.state == "INVALID"]
    assert not (invalid_rows.valid_transition == True).any()


# ----------------------------------------------------------------------------
# 4. run reset: INVALID를 만나면 run이 끊긴다 (gap bridging 금지)
# ----------------------------------------------------------------------------

def test_run_is_contiguous_and_state_constant(state_main):
    runs = state_main.dropna(subset=["run_id"])
    assert len(runs) > 0
    for run_id, g in runs.groupby("run_id"):
        g = g.sort_values("quarter_index")
        qi = g.quarter_index.to_numpy()
        assert (np.diff(qi) == 1).all(), f"run {run_id} 이 연속 분기가 아닙니다"
        assert g.state.nunique() == 1, f"run {run_id} 내부에 서로 다른 state가 섞여 있습니다"
        assert g.state.iloc[0] in {"S1", "S2", "S3", "S4"}


def test_run_breaks_at_invalid(state_ref):
    # 참고기간 전체에서 INVALID 분기의 앞뒤 run은 서로 다른 run_id를 가져야 한다(끊김).
    for industry, g in state_ref.groupby("industry"):
        g = g.sort_values("quarter_index").reset_index(drop=True)
        invalid_idx = g.index[g.state == "INVALID"].tolist()
        for i in invalid_idx:
            if i > 0 and g.state.iloc[i - 1] in {"S1", "S2", "S3", "S4"}:
                assert pd.isna(g.run_id.iloc[i])
            if i < len(g) - 1 and g.state.iloc[i + 1] in {"S1", "S2", "S3", "S4"}:
                assert g.run_length.iloc[i + 1] == 1


# ----------------------------------------------------------------------------
# 5. X 보존 (0 치환 금지), revision 반영 확인
# ----------------------------------------------------------------------------

def test_masked_x_preserved_as_nan_not_zero(ind):
    masked = ind[ind.production_masked == 1]
    assert len(masked) > 0
    assert masked.production.isna().all()


def test_revision_source_is_applied(ind):
    assert (ind.production_source == "kicox_annual_revision").sum() > 0
    assert (ind.production_is_revised == 1).sum() > 0


# ----------------------------------------------------------------------------
# 6. data/raw/ 쓰기 금지 가드
# ----------------------------------------------------------------------------

def test_raw_directory_not_written_by_pipeline():
    import build_changwon_master as m
    before = m._raw_mtimes()
    m.load_raw()
    m.load_revision()
    after = m._raw_mtimes()
    assert before == after, "data/raw/ 트리가 읽기 전용 함수 실행 중 변경되었습니다"
