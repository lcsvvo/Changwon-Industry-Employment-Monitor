# -*- coding: utf-8 -*-
"""가동업체수·가동률 확인신호와 소규모 집계 트랙.

원칙
    - 가동업체수 감소와 고용 감소가 같은 분기에 관측되어도, 업체 이탈이 고용
      감소를 '일으켰다' 고 볼 수 없다. 여기서 만드는 것은 원인 판정이 아니라
      함께 확인해야 할 '확인신호' 다.
    - 300인 게이트는 Triage 에서 그대로 유지된다. 이 모듈은 게이트를 없애거나
      완화하지 않고, 게이트 아래 업종을 별도 트랙으로 '표시' 만 한다.
    - 소규모 업종은 비율(%)만 보면 과대해석된다. 절대 개수를 항상 함께 낸다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (OP_RATE_DEFINITION_BREAK_QUARTER, SMALL_FIRMS_OP_BASE,
                     SMALL_INDUSTRY_NOTE)


def _yoy(d: pd.DataFrame, col: str, out: str) -> pd.DataFrame:
    """달력분기 기준 전년동기 대비. 결측 분기를 건너뛰어 붙이지 않는다."""
    lag = d[["industry", "quarter", col]].copy()
    lag["quarter"] = (pd.PeriodIndex(lag["quarter"], freq="Q") + 4).astype(str)
    lag = lag.rename(columns={col: col + "_lag4"})
    d = d.merge(lag, on=["industry", "quarter"], how="left", validate="one_to_one")
    base = d[col + "_lag4"]
    d[out] = (d[col] / base - 1) * 100
    d.loc[base.isna() | (base == 0), out] = np.nan
    d[out] = d[out].replace([np.inf, -np.inf], np.nan)
    d[col + "_change_count"] = d[col] - base
    return d


def build_firm_activity_panel(master: pd.DataFrame) -> pd.DataFrame:
    """가동업체수·입주업체수·가동률의 YoY 와 절대 증감.

    master 는 창원 업종 마스터 전체(2018Q1~)를 받아야 lag4 가 끊기지 않는다.
    """
    d = master.copy()
    d.columns = [c.lstrip("﻿") for c in d.columns]
    d = d.sort_values(["industry", "quarter"]).reset_index(drop=True)
    # 가동률은 2024Q2 를 기점으로 공표 정의가 바뀐다. 두 계열을 합치되 출처를 남긴다.
    d["op_rate"] = d["op_rate_official"].where(d["op_rate_official"].notna(),
                                               d["op_rate_approx"])
    d["op_rate_basis"] = np.where(d["op_rate_official"].notna(), "official_quarterly",
                                  np.where(d["op_rate_approx"].notna(),
                                           "monthly_simple_mean_approx", "missing"))
    for col, out in [("firms_op", "firms_op_yoy"), ("firms_in", "firms_in_yoy"),
                     ("op_rate", "op_rate_yoy")]:
        d = _yoy(d, col, out)
    # 가동률 YoY 가 정의 단절을 가로지르는지 (현재/전년 basis 가 다른 경우)
    basis_lag = d[["industry", "quarter", "op_rate_basis"]].copy()
    basis_lag["quarter"] = (pd.PeriodIndex(basis_lag["quarter"], freq="Q") + 4).astype(str)
    basis_lag = basis_lag.rename(columns={"op_rate_basis": "op_rate_basis_lag4"})
    d = d.merge(basis_lag, on=["industry", "quarter"], how="left", validate="one_to_one")
    d["op_rate_definition_break"] = (
        d["op_rate_basis"].ne(d["op_rate_basis_lag4"])
        & d["op_rate_basis"].ne("missing")
        & d["op_rate_basis_lag4"].notna()
        & d["op_rate_basis_lag4"].ne("missing"))
    d["op_rate_definition_break_note"] = np.where(
        d["op_rate_definition_break"],
        f"가동률 공표 정의가 {OP_RATE_DEFINITION_BREAK_QUARTER} 를 기점으로 바뀌어 "
        "당기와 전년동기의 산출방식이 다르다", "")
    # 가동률 YoY 는 %p 차이도 함께 둔다 (비율의 비율은 오독되기 쉽다)
    d["op_rate_yoy_pp"] = d["op_rate"] - d["op_rate_lag4"]
    return d


def add_small_industry_track(d: pd.DataFrame, scale_min: int) -> pd.DataFrame:
    """메인 트랙 / 소규모 집계 트랙 구분. Triage 판정은 건드리지 않는다."""
    d = d.copy()
    d["employment_level"] = d["employment"]
    d["firms_op_level"] = d["firms_op"]
    d["scale_gate_threshold"] = scale_min
    d["small_industry_flag"] = d["employment"] < scale_min
    d["track"] = np.where(d["small_industry_flag"], "소규모 집계 트랙", "메인 트랙")
    d["small_base_warning"] = (d["small_industry_flag"]
                               | (d["firms_op"] <= SMALL_FIRMS_OP_BASE))
    d["small_track_note"] = np.where(d["small_industry_flag"], SMALL_INDUSTRY_NOTE, "")
    # 소규모 업종에서는 비율 대신 절대 개수를 먼저 읽게 한다.
    def _fmt(r):
        if pd.isna(r.firms_op) or pd.isna(r.firms_op_lag4):
            return "가동업체수 비교기간 미확인"
        pct = "" if pd.isna(r.firms_op_yoy) else f", {r.firms_op_yoy:+.1f}%"
        return (f"{r.firms_op_lag4:,.0f}개 → {r.firms_op:,.0f}개 "
                f"({r.firms_op_change_count:+,.0f}개{pct})")
    d["firms_op_change_display"] = d.apply(_fmt, axis=1)
    return d
