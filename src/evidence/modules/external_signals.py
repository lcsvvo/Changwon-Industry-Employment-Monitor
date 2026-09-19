# -*- coding: utf-8 -*-
"""외부 수집자료 → 업종×분기 확인신호·맥락 플래그.

역할별로 열 이름을 분리한다. 섞어 읽지 않도록 접두사를 둔다.

    trade_*          CONTEXT / EXTERNAL_DEMAND   업종 단위(확인된 품목 일부)
    mfg_flow_*       FLOW_INTERPRETATION         창원시 제조업 총계(반기) — 업종 공통
    bsi_region_*     CONTEXT / BUSINESS_SENTIMENT 경남 제조업 총계 — 업종 공통
    bsi_industry_*   CONTEXT / BUSINESS_SENTIMENT 전국 업종별 — 업종 대응은 참고용

무엇을 하지 않는가
    - Triage stage 를 바꾸지 않는다.
    - 제조업 총계 값을 업종별 값으로 복제하지 않는다. 공통 맥락임을 이름과
      플래그(`*_scope`)로 계속 표시한다.
    - 원인을 확정하지 않는다. '함께 관측되는가' 만 본다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# OWN 경계. 성능에 맞춰 고른 값이 아니라 표시 기준선이다.
EXPORT_DECLINE = -5.0          # 확인된 품목 합계 수출 YoY (%)
FLOW_DECLINE = -5.0            # 입직자/피보험 종사자 YoY (%)
LOSS_INCREASE = 5.0            # 이직자 YoY (%)
BSI_NEUTRAL = 100.0            # BSI 기준선
POWER_DECLINE = -3.0           # 창원시 제조업 전력사용량 YoY (%)


def _half_of(quarter: str) -> str:
    y, q = quarter[:4], int(quarter[-1])
    return f"{y}0{1 if q <= 2 else 2}"


def add_trade_signals(d: pd.DataFrame, trade: pd.DataFrame,
                      coverage: pd.DataFrame | None = None) -> pd.DataFrame:
    """업종별 수출 맥락.

    coverage 는 업종별 수집 커버리지표. 값이 없는 업종에 대해
    '대응 품목 없음' 과 '수집 미완' 을 구분해 표시하는 데 쓴다.
    """
    out = d.copy()
    if trade.empty:
        for c in ["trade_export_usd", "trade_export_yoy", "trade_import_yoy",
                  "trade_n_items", "trade_mapping_grade"]:
            out[c] = np.nan
        out["trade_data_available"] = False
        out["n_hs6_excluded_incomplete"] = 0
        out["trade_unavailable_reason"] = "수출입 패널 없음"
        out["trade_export_decline_signal"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
        out["trade_coverage_flag"] = "no_data"
        return out
    t = trade.rename(columns={
        "export_usd": "trade_export_usd", "export_yoy": "trade_export_yoy",
        "import_yoy": "trade_import_yoy", "n_hs6_items": "trade_n_items",
        "mapping_grade": "trade_mapping_grade", "coverage_flag": "trade_coverage_flag"})
    cols = ["industry", "quarter", "trade_export_usd", "trade_export_yoy",
            "trade_import_yoy", "trade_n_items", "trade_mapping_grade",
            "trade_coverage_flag", "n_hs6_excluded_incomplete"]
    cols = [c for c in cols if c in t.columns or c in ("industry", "quarter")]
    out = out.merge(t[cols], on=["industry", "quarter"], how="left", validate="one_to_one")
    out["trade_data_available"] = out["trade_export_yoy"].notna()
    out["trade_export_decline_signal"] = (
        (out["trade_export_yoy"] <= EXPORT_DECLINE).astype("boolean")
        .where(out["trade_export_yoy"].notna()))
    out["trade_coverage_flag"] = out["trade_coverage_flag"].fillna("no_data")
    out["n_hs6_excluded_incomplete"] = out.get(
        "n_hs6_excluded_incomplete", pd.Series(0, index=out.index)).fillna(0).astype(int)
    # 자료가 없는 이유를 구분한다. '대응 품목 없음'·'수집 미완'·'창원 거래 없음'은
    # 서로 다른 사실이다. 커버리지표를 근거로 각각 다르게 적는다.
    if coverage is not None and not coverage.empty:
        out = out.merge(coverage[["industry", "trade_coverage_status",
                                  "trade_unavailable_reason", "n_hs6_mapped",
                                  "n_hs6_complete", "n_hs6_incomplete"]],
                        on="industry", how="left")
        out["trade_coverage_status"] = out["trade_coverage_status"].fillna(
            "no_mapped_chapter")
        out["trade_unavailable_reason"] = out["trade_unavailable_reason"].fillna(
            "해당 업종에 귀속 근거가 있는 HS 류가 없다")
        out.loc[out["trade_data_available"], "trade_unavailable_reason"] = ""
    else:
        out["trade_coverage_status"] = np.where(
            out["trade_data_available"], "usable", "unknown")
        out["trade_unavailable_reason"] = np.where(
            out["trade_data_available"], "", "커버리지표 없음")
    out["trade_scope"] = ("창원시 전역 통관 · 연도창을 모두 확보한 HS6 합계"
                          "(업종 수출 총액 아님)")
    return out


def add_flow_signals(d: pd.DataFrame, flow: pd.DataFrame) -> pd.DataFrame:
    """창원시 제조업 총계 고용 flow. 업종별 값이 아니라 모든 업종에 공통으로 붙는다."""
    out = d.copy()
    cols = ["mfg_flow_workers", "mfg_flow_workers_yoy", "mfg_flow_acquisitions",
            "mfg_flow_acquisition_yoy", "mfg_flow_losses", "mfg_flow_loss_yoy",
            "mfg_flow_net", "mfg_flow_job_openings"]
    if flow.empty:
        for c in cols:
            out[c] = np.nan
        out["mfg_flow_data_available"] = False
        out["mfg_flow_period"] = ""
        for c in ["mfg_flow_employment_decrease", "mfg_flow_acquisition_decrease",
                  "mfg_flow_loss_increase"]:
            out[c] = pd.Series(pd.NA, index=out.index, dtype="boolean")
        out["mfg_flow_scope"] = "자료 없음"
        return out
    f = flow[flow["industry_code"] == "IND201701"].copy()      # 광업.제조업(BC)
    f = f.rename(columns={
        "workers": "mfg_flow_workers", "workers_yoy": "mfg_flow_workers_yoy",
        "acquisitions": "mfg_flow_acquisitions", "acquisition_yoy": "mfg_flow_acquisition_yoy",
        "losses": "mfg_flow_losses", "loss_yoy": "mfg_flow_loss_yoy",
        "net_flow": "mfg_flow_net", "job_openings": "mfg_flow_job_openings",
        "period": "mfg_flow_period"})
    out["_half"] = out["quarter"].map(_half_of)
    out = out.merge(f[["mfg_flow_period"] + cols], left_on="_half",
                    right_on="mfg_flow_period", how="left").drop(columns="_half")
    out["mfg_flow_data_available"] = out["mfg_flow_workers"].notna()
    out["mfg_flow_period"] = out["mfg_flow_period"].fillna("")
    out["mfg_flow_employment_decrease"] = (
        (out["mfg_flow_workers_yoy"] < 0).astype("boolean")
        .where(out["mfg_flow_workers_yoy"].notna()))
    out["mfg_flow_acquisition_decrease"] = (
        (out["mfg_flow_acquisition_yoy"] <= FLOW_DECLINE).astype("boolean")
        .where(out["mfg_flow_acquisition_yoy"].notna()))
    out["mfg_flow_loss_increase"] = (
        (out["mfg_flow_loss_yoy"] >= LOSS_INCREASE).astype("boolean")
        .where(out["mfg_flow_loss_yoy"].notna()))
    out["mfg_flow_scope"] = (
        "창원시 전역 제조업 총계 · 반기 · 표본조사. 업종별 값이 아니며 "
        "입직-이직을 KICOX 고용 증감과 같다고 보지 않는다.")
    return out


def add_power_signals(d: pd.DataFrame, power: pd.DataFrame) -> pd.DataFrame:
    """창원시 제조업 전력사용량. 업종별 값이 아니라 모든 업종에 공통으로 붙는다."""
    out = d.copy()
    cols = ["power_usage_kwh", "power_usage_yoy", "power_customers",
            "power_customers_yoy"]
    if power.empty:
        for c in cols:
            out[c] = np.nan
        out["power_data_available"] = False
        out["power_usage_decline"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
        out["power_scope"] = "자료 없음"
        return out
    pw = power.rename(columns={"customers": "power_customers",
                               "customers_yoy": "power_customers_yoy"})
    out = out.merge(pw[["quarter"] + cols], on="quarter", how="left",
                    validate="many_to_one")
    out["power_data_available"] = out["power_usage_yoy"].notna()
    out["power_usage_decline"] = (
        (out["power_usage_yoy"] <= POWER_DECLINE).astype("boolean")
        .where(out["power_usage_yoy"].notna()))
    # 가동률과 전력의 방향이 같은지 / 갈리는지 (원인 판정이 아니라 대조)
    op = out.get("op_rate_yoy")
    if op is not None:
        both = op.notna() & out["power_usage_yoy"].notna()
        out["oprate_power_both_decline"] = (
            (op < 0) & (out["power_usage_yoy"] < 0)).astype("boolean").where(both)
        out["oprate_power_direction_split"] = (
            (np.sign(op) != np.sign(out["power_usage_yoy"]))
        ).astype("boolean").where(both)
    out["power_scope"] = ("창원시 전역 제조업 총계 전력사용량 · 월→분기 합계. "
                          "업종별 값이 아니며 가동률과 개념·모집단이 다르다.")
    return out


def add_bsi_signals(d: pd.DataFrame, bsi: pd.DataFrame) -> pd.DataFrame:
    """경남 제조업 BSI(업종 공통)와 전국 업종별 BSI(참고)."""
    out = d.copy()
    if bsi.empty:
        for c in ["bsi_region_business", "bsi_region_production", "bsi_industry_business"]:
            out[c] = np.nan
        out["bsi_region_below_100"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
        out["bsi_industry_below_100"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
        out["bsi_data_available"] = False
        return out
    reg = bsi[bsi["scope"].str.startswith("경남")]
    piv = reg.pivot_table(index="period", columns="indicator", values="value",
                          aggfunc="first")
    ren = {"업황BSI": "bsi_region_business", "생산BSI": "bsi_region_production",
           "신규수주BSI": "bsi_region_new_orders", "가동률BSI": "bsi_region_operation",
           "인력사정BSI": "bsi_region_labor"}
    piv = piv.rename(columns=ren).reset_index().rename(columns={"period": "quarter"})
    keep = ["quarter"] + [c for c in ren.values() if c in piv.columns]
    out = out.merge(piv[keep], on="quarter", how="left", validate="many_to_one")

    ind = bsi[(bsi["scope"].str.startswith("전국"))
              & (bsi["indicator"] == "업황BSI")
              & bsi["mapped_kicox_industry"].notna()
              & (bsi["mapped_kicox_industry"] != "해당없음(제조업 총계)")]
    ind = (ind.groupby(["mapped_kicox_industry", "period"])
              .agg(bsi_industry_business=("value", "mean"),
                   bsi_industry_mapping_grade=("mapping_grade", lambda s: sorted(set(s))[-1]),
                   bsi_industry_n_codes=("region_or_industry_code", "nunique"))
              .reset_index()
              .rename(columns={"mapped_kicox_industry": "industry", "period": "quarter"}))
    ind["bsi_industry_business"] = ind["bsi_industry_business"].round(2)
    out = out.merge(ind, on=["industry", "quarter"], how="left", validate="one_to_one")

    out["bsi_region_below_100"] = (
        (out["bsi_region_business"] < BSI_NEUTRAL).astype("boolean")
        .where(out["bsi_region_business"].notna()))
    out["bsi_industry_below_100"] = (
        (out["bsi_industry_business"] < BSI_NEUTRAL).astype("boolean")
        .where(out["bsi_industry_business"].notna()))
    out["bsi_data_available"] = out["bsi_region_business"].notna()
    out["bsi_region_scope"] = "경상남도 제조업 총계(업종 공통 배경)"
    out["bsi_industry_scope"] = ("전국 업종별 심리지수. 창원국가산단 개별 업종의 "
                                 "신호가 아니라 같은 업종의 전국 분위기다.")
    return out
