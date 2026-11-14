# -*- coding: utf-8 -*-
"""KEPCO 전력사용량 → 업종×분기 보조패널 + 강건성 비교.

역할: **CONTEXT / ACTIVITY (보조·강건성).** Triage 판정변수가 아니다.
이 모듈이 만드는 어떤 값도 stage / E / R / A / P 를 바꾸지 않는다.

왜 보조인가
    전력사용량은 생산량이 아니다. 같은 생산량이라도 전력집약도·설비교체·
    에너지효율·자가발전·계절기온에 따라 크게 움직인다. 그래서 '조업강도의
    보조 proxy' 로만 읽고, 방향(증가/감소) 일치 여부까지만 본다.

공간 단위 경고
    KEPCO 는 **창원시 5개 행정구**를 준다. 창원국가산단 경계가 아니다.
    산단 밖 공장·상업·가정 수요가 모두 섞여 있다. 업종별로 잘라도 마찬가지다.
    그래서 KICOX 업종 생산·고용을 대체하지 않는다.

월 → 분기 변환 규칙 (변수 성격별로 다르다)
    powerUsage  flow      분기 내 3개월 **합계**. 3개월이 모두 COMPLETE 일 때만 만든다.
    custCnt     stock     **분기말 월** 값. 분기평균은 `*_mean` 으로 따로 둔다.
    cntrPwr     stock     **분기말 월** 값. 계약전력은 시점 등록용량이라 custCnt 와
                          성격이 같다. 평균은 `*_mean` 으로 따로 둔다.

월별 지속성 (분기 판정을 바꾸지 않는 보조지표)
    monthly_negative_months    해당 분기의 유효 월 중 power_usage_yoy < 0 인 월 수 (0~3)
    monthly_signal_consistency PERSISTENT 3/3 · MAJORITY 2/3 · WEAK 1/3 · NONE 0/3
                               INCOMPLETE 세 달의 월별 YoY 가 다 갖춰지지 않음
    불완전 분기를 완전 분기와 같게 취급하지 않는다. 월자료는 '표본이 3배 늘어난 것'이
    아니라 같은 분기 안에서 신호가 반복되는지를 보는 보조지표다.

분기 완전성 상태 — '자료 없음'과 '수집 실패'를 섞지 않는다
    COMPLETE        3개월 모두 정상
    PARTIAL         1~2개월만 정상 (powerUsage 합계를 만들지 않는다)
    NO_DATA         3개월 모두 원자료가 비어 있음 (공급측)
    REQUEST_FAILED  수집 실패가 섞여 있음
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW = "data/raw/kepco/api"
BIZ_CSV = f"{RAW}/changwon_business_type_power_monthly.csv"
IND_CSV = f"{RAW}/changwon_industry_type_power_monthly.csv"
CUST_CSV = f"{RAW}/changwon_custnum_change_monthly.csv"
STATUS_JSON = f"{RAW}/_metadata/collection_status.json"
XWALK = "data/processed/final_model/reference/industry_crosswalk/kepco_biztype_to_kicox.csv"

FLOW_COLS = ["power_usage_kwh"]
STOCK_COLS = ["cust_cnt", "cntr_pwr_kw"]

# 분기 내 월별 지속성 라벨. 정의를 코드 한 곳에만 둔다.
#   PERSISTENT 3/3  MAJORITY 2/3  WEAK 1/3  NONE 0/3  INCOMPLETE 월 YoY 3개 미확보
PERSISTENCE_LABEL = {3: "PERSISTENT", 2: "MAJORITY", 1: "WEAK", 0: "NONE"}
PERSISTENCE_LEVELS = ("PERSISTENT", "MAJORITY", "WEAK", "NONE", "INCOMPLETE")


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """0·음수·결측 분모를 비율로 가장하지 않는다."""
    denominator = pd.to_numeric(denominator, errors="coerce")
    numerator = pd.to_numeric(numerator, errors="coerce")
    valid = numerator.notna() & denominator.notna() & (denominator > 0)
    return (numerator / denominator).where(valid)


def _add_monthly_metrics(monthly: pd.DataFrame) -> pd.DataFrame:
    """월별 정규화 지표와 정확한 전년동월비를 붙인다.

    행 수를 세어 12행을 밀지 않고 달력 월 인덱스로 조인한다. 원자료가 비거나
    SOURCE_DEGENERATE 인 달이 끼어도 다른 달을 잘못 전년동월로 쓰지 않기 위해서다.
    """
    d = monthly.copy()
    # 같은 (업종, 월) 이 두 번 들어오면 분기 flow 합계가 조용히 부풀려진다.
    # 결합 전에 잡는다.
    dup = d.duplicated(["kicox_industry", "ym"])
    if dup.any():
        bad = d.loc[dup, ["kicox_industry", "ym"]].drop_duplicates()
        raise ValueError(f"월 패널에 (업종, 월) 중복: {bad.to_dict('records')}")
    d["power_usage_per_customer"] = _safe_ratio(d["power_usage_kwh"], d["cust_cnt"])
    d["power_usage_per_contract_power"] = _safe_ratio(
        d["power_usage_kwh"], d["cntr_pwr_kw"])
    d["mi"] = (d["ym"].str[:4].astype(int) * 12
               + d["ym"].str[5:7].astype(int) - 1)
    metrics = ["power_usage_kwh", "cust_cnt", "cntr_pwr_kw"]
    lag = d[["kicox_industry", "mi", "month_completeness"] + metrics].copy()
    lag["mi"] += 12
    lag = lag.rename(columns={
        "month_completeness": "month_completeness_lag12",
        **{c: f"{c}_lag12" for c in metrics},
    })
    n_before = len(d)
    d = d.merge(lag, on=["kicox_industry", "mi"], how="left")
    if len(d) != n_before:
        raise ValueError("전년동월 결합에서 행이 늘었다 — (업종, 월) 키 중복")
    aliases = {
        "power_usage_kwh": "total_power_usage_yoy",
        "cust_cnt": "customer_count_yoy",
        "cntr_pwr_kw": "contract_power_yoy",
    }
    complete = ((d["month_completeness"] == "COMPLETE")
                & (d["month_completeness_lag12"] == "COMPLETE"))
    for c, alias in aliases.items():
        base = d[f"{c}_lag12"]
        valid = complete & d[c].notna() & base.notna() & (base > 0)
        d[alias] = ((d[c] / base - 1) * 100).where(valid)
    return d.drop(columns=["mi"])


# ---------------------------------------------------------------- 공통
def quarter_of(ym: str) -> str:
    y, m = ym.split("-")
    return f"{y}Q{(int(m) - 1) // 3 + 1}"


def _month_status(root: Path, dataset: str) -> dict[str, str]:
    p = root / STATUS_JSON
    if not p.exists():
        return {}
    meta = root / RAW / "_metadata" / {
        "business_type": "changwon_business_type_power_monthly",
        "industry_type": "changwon_industry_type_power_monthly",
        "custnum_change": "changwon_custnum_change_monthly",
    }[dataset]
    f = meta.with_suffix(".json")
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8")).get("completeness_by_month") or {}


def load_crosswalk(root: Path) -> pd.DataFrame:
    x = pd.read_csv(root / XWALK, encoding="utf-8-sig")
    x = x.rename(columns={"source_category": "kepco_biz_type",
                          "target_kicox_industry": "kicox_industry",
                          "rationale": "mapping_basis",
                          "mapping_confidence": "evidence_level"})
    x["kepco_biz_type"] = x["kepco_biz_type"].astype(str).str.split().str.join(" ")
    return x


# ---------------------------------------------------------------- 월별 패널
def build_monthly_panel(root: Path) -> pd.DataFrame:
    """업종별 원자료 → KICOX 업종 × 월 패널. 대응 없는 업종(D)은 버리지 않고 표시만 한다."""
    p = root / BIZ_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig", dtype={"ym": str, "year": str, "month": str})
    d = d.rename(columns={"industry": "kepco_biz_type", "custCnt": "cust_cnt",
                          "powerUsage": "power_usage_kwh", "cntrPwr": "cntr_pwr_kw"})
    for c in ["cust_cnt", "power_usage_kwh", "cntr_pwr_kw"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    x = load_crosswalk(root)
    d = d.merge(x[["kepco_biz_type", "kicox_industry", "mapping_type",
                   "evidence_level", "official_crosswalk"]],
                on="kepco_biz_type", how="left")
    unmapped = sorted(d.loc[d["kicox_industry"].isna(), "kepco_biz_type"].unique())
    if unmapped:
        raise ValueError(f"crosswalk 에 없는 업종: {unmapped}")

    st = _month_status(root, "business_type")
    d["month_completeness"] = d["ym"].map(st).fillna("UNKNOWN")
    d["quarter"] = d["ym"].map(quarter_of)
    d["kicox_mapped"] = d["kicox_industry"] != "해당없음"

    # KICOX 업종 × 월 집계. D 등급(해당없음)은 별도 행으로 남긴다.
    g = (d.groupby(["quarter", "ym", "kicox_industry", "month_completeness"],
                   as_index=False)
           .agg(power_usage_kwh=("power_usage_kwh", "sum"),
                cust_cnt=("cust_cnt", "sum"),
                cntr_pwr_kw=("cntr_pwr_kw", "sum"),
                n_biz_types=("kepco_biz_type", "nunique"),
                evidence_level=("evidence_level", lambda s: max(s)),
                biz_types=("kepco_biz_type", lambda s: "|".join(sorted(set(s))))))
    g["kicox_mapped"] = g["kicox_industry"] != "해당없음"
    # 등급 B 만 쓴 민감도용 계열
    b = (d[d["evidence_level"] == "B"]
         .groupby(["quarter", "ym", "kicox_industry"], as_index=False)
         .agg(power_usage_kwh_B=("power_usage_kwh", "sum")))
    g = g.merge(b, on=["quarter", "ym", "kicox_industry"], how="left")
    g = g.sort_values(["kicox_industry", "ym"]).reset_index(drop=True)
    return _add_monthly_metrics(g)


# ---------------------------------------------------------------- 분기 패널
def _quarter_state(statuses: list[str]) -> tuple[str, int]:
    ok = sum(s == "COMPLETE" for s in statuses)
    if "REQUEST_FAILED" in statuses:
        return "REQUEST_FAILED", ok
    if ok == 3:
        return "COMPLETE", ok
    if ok == 0:
        return "NO_DATA", 0
    return "PARTIAL", ok


def build_quarterly_panel(monthly: pd.DataFrame) -> pd.DataFrame:
    """월 → 분기. flow 는 합계, stock 은 분기말. 불완전 분기의 flow 는 만들지 않는다."""
    if monthly.empty:
        return pd.DataFrame()
    rows = []
    for (q, ind), g in monthly.groupby(["quarter", "kicox_industry"], sort=True):
        g = g.sort_values("ym")
        state, n_ok = _quarter_state(list(g["month_completeness"]))
        ok = g[g["month_completeness"] == "COMPLETE"]
        last = ok.iloc[-1] if len(ok) else None
        monthly_yoy = (ok["total_power_usage_yoy"]
                       if "total_power_usage_yoy" in ok.columns
                       else pd.Series(dtype=float))
        persistence_available = state == "COMPLETE" and len(monthly_yoy) == 3 \
            and monthly_yoy.notna().all()
        negative_months = int((monthly_yoy < 0).sum()) if persistence_available else np.nan
        # 분기 내 신호가 몇 달에 걸쳐 반복되는지만 본다. 표본이 3배 늘어난 것이 아니다.
        persistence = (PERSISTENCE_LABEL[int(negative_months)]
                       if persistence_available else "INCOMPLETE")
        rows.append(dict(
            quarter=q, kicox_industry=ind,
            completeness=state, n_months_complete=n_ok, n_months=len(g),
            months="|".join(g["ym"]),
            # flow: 3개월이 다 있을 때만.
            power_usage_kwh=float(ok["power_usage_kwh"].sum()) if state == "COMPLETE" else np.nan,
            power_usage_kwh_B=(float(ok["power_usage_kwh_B"].sum())
                               if state == "COMPLETE" else np.nan),
            # stock: 분기말 월 값(기본) / 분기평균(민감도)
            cust_cnt=float(last["cust_cnt"]) if last is not None else np.nan,
            cust_cnt_mean=float(ok["cust_cnt"].mean()) if len(ok) else np.nan,
            cntr_pwr_kw=float(last["cntr_pwr_kw"]) if last is not None else np.nan,
            cntr_pwr_kw_mean=float(ok["cntr_pwr_kw"].mean()) if len(ok) else np.nan,
            monthly_negative_months=negative_months,
            monthly_signal_consistency=persistence,
            evidence_level=g["evidence_level"].max(),
            biz_types=g["biz_types"].iloc[0],
            kicox_mapped=bool(g["kicox_mapped"].iloc[0]),
        ))
    d = pd.DataFrame(rows)

    d["power_usage_per_customer"] = _safe_ratio(d["power_usage_kwh"], d["cust_cnt"])
    d["power_usage_per_contract_power"] = _safe_ratio(
        d["power_usage_kwh"], d["cntr_pwr_kw"])

    # YoY: 현재와 4분기 전이 **둘 다** COMPLETE 일 때만 계산한다.
    d["qi"] = d["quarter"].str[:4].astype(int) * 4 + d["quarter"].str[5].astype(int) - 1
    ratio_cols = ["power_usage_per_customer", "power_usage_per_contract_power"]
    metric_cols = FLOW_COLS + STOCK_COLS + ["power_usage_kwh_B"] + ratio_cols
    lag = d[["kicox_industry", "qi", "completeness"] + metric_cols].copy()
    lag["qi"] += 4
    lag = lag.rename(columns={c: c + "_lag4" for c in
                              metric_cols + ["completeness"]})
    n_before = len(d)
    d = d.merge(lag, on=["kicox_industry", "qi"], how="left")
    if len(d) != n_before:
        raise ValueError("전년동기 결합에서 행이 늘었다 — (업종, 분기) 키 중복")
    for c in metric_cols:
        base = d[c + "_lag4"]
        val = (d[c] / base - 1) * 100
        bad = base.isna() | (base == 0) | d[c].isna()
        # flow뿐 아니라 stock도 불완전 분기의 임의 '마지막 관측월'로 YoY를 만들지 않는다.
        bad |= ((d["completeness"] != "COMPLETE")
                | (d["completeness_lag4"] != "COMPLETE"))
        d[c + "_yoy"] = val.where(~bad)
    d["total_power_usage_yoy"] = d["power_usage_kwh_yoy"]
    d["customer_count_yoy"] = d["cust_cnt_yoy"]
    d["contract_power_yoy"] = d["cntr_pwr_kw_yoy"]
    d["power_yoy_computable"] = d["power_usage_kwh_yoy"].notna()
    d["power_yoy_reason"] = np.where(
        d["power_yoy_computable"], "valid",
        np.where(d["completeness"] != "COMPLETE", "current_" + d["completeness"].str.lower(),
                 np.where(d["completeness_lag4"].isna(), "lag4_absent",
                          "lag4_" + d["completeness_lag4"].fillna("").str.lower())))
    return d.drop(columns=["qi"]).sort_values(
        ["kicox_industry", "quarter"]).reset_index(drop=True)


# ---------------------------------------------------------------- 제조업 총량
def build_manufacturing_total(root: Path) -> pd.DataFrame:
    """산업분류별 API 의 KSIC C 제조업 — 창원시 전체. 업종별 결과의 macro check."""
    p = root / IND_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig", dtype={"ym": str})
    d["industry"] = d["industry"].astype(str).str.strip()
    d = d[d["industry"] == "제조업"].copy()
    d = d.rename(columns={"custCnt": "cust_cnt", "powerUsage": "power_usage_kwh",
                          "bill": "bill_won", "unitCost": "unit_cost_won_per_kwh"})
    for c in ["cust_cnt", "power_usage_kwh", "bill_won", "unit_cost_won_per_kwh"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    st = _month_status(root, "industry_type")
    d["month_completeness"] = d["ym"].map(st).fillna("UNKNOWN")
    d["quarter"] = d["ym"].map(quarter_of)

    rows = []
    for q, g in d.groupby("quarter", sort=True):
        g = g.sort_values("ym")
        state, n_ok = _quarter_state(list(g["month_completeness"]))
        ok = g[g["month_completeness"] == "COMPLETE"]
        last = ok.iloc[-1] if len(ok) else None
        rows.append(dict(
            quarter=q, completeness=state, n_months_complete=n_ok,
            power_usage_kwh=float(ok["power_usage_kwh"].sum()) if state == "COMPLETE" else np.nan,
            bill_won=float(ok["bill_won"].sum()) if state == "COMPLETE" else np.nan,
            cust_cnt=float(last["cust_cnt"]) if last is not None else np.nan,
            unit_cost_won_per_kwh=(float(ok["unit_cost_won_per_kwh"].mean())
                                   if len(ok) else np.nan),
        ))
    t = pd.DataFrame(rows)
    t["qi"] = t["quarter"].str[:4].astype(int) * 4 + t["quarter"].str[5].astype(int) - 1
    lag = t[["qi", "power_usage_kwh", "cust_cnt", "completeness"]].copy()
    lag["qi"] += 4
    lag.columns = ["qi", "power_usage_kwh_lag4", "cust_cnt_lag4", "completeness_lag4"]
    t = t.merge(lag, on="qi", how="left")
    ok = (t["completeness"] == "COMPLETE") & (t["completeness_lag4"] == "COMPLETE")
    t["power_usage_kwh_yoy"] = ((t["power_usage_kwh"] / t["power_usage_kwh_lag4"] - 1)
                                * 100).where(ok)
    # stock 도 flow 와 같은 게이트를 건다. 불완전 분기의 '마지막 관측월' 값으로
    # 전년동기비를 만들면 실제로는 다른 달끼리 비교하게 된다.
    t["cust_cnt_yoy"] = ((t["cust_cnt"] / t["cust_cnt_lag4"] - 1) * 100).where(
        ok & t["cust_cnt_lag4"].notna() & (t["cust_cnt_lag4"] > 0))
    return t.drop(columns=["qi"])


# ---------------------------------------------------------------- 고객 증감
def build_custnum_panel(root: Path) -> pd.DataFrame:
    """신설·증설·해지 KWH(KSIC 제조업, 창원 합) × 분기.

    공식 화면의 단위 표기는 각 항목 모두 KWH다. 따라서 고객·계약의 '건수'나
    KICOX 입주업체수 증감으로 해석하지 않는다. 상세 산식이 공표되지 않아
    분석 투입 상태는 NOT_SUITABLE이며, 원값 보존과 진단만 수행한다.
    """
    p = root / CUST_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig", dtype={"ym": str})
    d["industry"] = d["industry"].astype(str).str.strip()
    d = d[d["industry"] == "제조업"].copy()
    for c in ["new", "expansion", "cancel"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    st = _month_status(root, "custnum_change")
    d["month_completeness"] = d["ym"].map(st).fillna("UNKNOWN")
    d["quarter"] = d["ym"].map(quarter_of)
    g = d.groupby(["quarter", "ym", "month_completeness"], as_index=False)[
        ["new", "expansion", "cancel"]].sum()
    rows = []
    for q, gg in g.groupby("quarter", sort=True):
        state, n_ok = _quarter_state(list(gg["month_completeness"]))
        ok = gg[gg["month_completeness"] == "COMPLETE"]
        rows.append(dict(quarter=q, completeness=state, n_months_complete=n_ok,
                         new_kwh=float(ok["new"].sum()) if state == "COMPLETE" else np.nan,
                         expansion_kwh=float(ok["expansion"].sum()) if state == "COMPLETE" else np.nan,
                         cancel_kwh=float(ok["cancel"].sum()) if state == "COMPLETE" else np.nan,
                         interpretation_status="NOT_SUITABLE"))
    t = pd.DataFrame(rows)
    t["net_new_cancel_kwh"] = t["new_kwh"] - t["cancel_kwh"]
    return t
