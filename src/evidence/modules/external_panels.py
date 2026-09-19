# -*- coding: utf-8 -*-
"""외부 수집자료 → 업종/기간 보조패널.

세 자료는 역할이 다르다. 섞지 않는다.

    고용 flow (KOSIS 사업체노동력조사)  FLOW_INTERPRETATION
    수출입    (관세청 시군구별 품목별)   CONTEXT / EXTERNAL_DEMAND
    BSI       (한국은행 ECOS)            CONTEXT / BUSINESS_SENTIMENT

공통 원칙
    - 빈도·공간·업종 단위가 KICOX 업종×분기와 다르면 억지로 맞추지 않는다.
      맞출 수 없는 축은 그대로 두고 coverage_flag 로 표시한다.
    - 결측을 0 으로 채우지 않는다.
    - 어떤 값도 KICOX 고용·생산을 대체하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

FLOW_CSV = "data/raw/employment_insurance/changwon_labor_force_flow_halfyear.csv"
TRADE_CSV = "data/raw/customs/trade/changwon_hs6_trade_monthly.csv"
TRADE_COVERAGE = "data/raw/customs/trade/_metadata/coverage_manifest.json"
BSI_CSV = "data/raw/ecos/api/bsi_gyeongnam_and_industry_monthly.csv"
POWER_CSV = "data/raw/kepco/api/changwon_industry_type_power_monthly.csv"
CUSTNUM_CSV = "data/raw/kepco/api/changwon_custnum_change_monthly.csv"
XWALK = "data/processed/final_model/reference/industry_crosswalk"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


# ---------------------------------------------------------------- 고용 flow
def build_employment_flow_panel(root: Path) -> pd.DataFrame:
    """창원시 × 제조업 × 반기 고용 flow.

    반기 자료다. 분기로 쪼개지 않는다 — 한 반기 값을 두 분기에 복제하면
    없는 분기 변동을 만들어내기 때문이다. 대신 `quarters_covered` 로
    어느 분기들이 이 반기에 속하는지만 표시한다.
    """
    p = root / FLOW_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig", dtype={"period": str})
    wide = d.pivot_table(index=["period", "region_name", "industry_code", "industry_name"],
                         columns="item_name", values="value", aggfunc="first").reset_index()
    wide.columns.name = None
    ren = {"전체종사자": "workers", "입직자": "acquisitions", "이직자": "losses",
           "빈일자리": "job_openings", "입직률": "acquisition_rate",
           "이직률": "loss_rate", "빈일자리율": "job_opening_rate"}
    wide = wide.rename(columns=ren)
    for c in ren.values():
        if c in wide:
            wide[c] = _num(wide[c])
    wide["net_flow"] = wide["acquisitions"] - wide["losses"]
    # 전년 동반기 대비
    wide = wide.sort_values(["industry_code", "period"]).reset_index(drop=True)
    lag = wide[["industry_code", "period", "workers", "acquisitions", "losses"]].copy()
    lag["period"] = (lag["period"].astype(int) + 100).astype(str)
    lag = lag.rename(columns={"workers": "workers_lag", "acquisitions": "acq_lag",
                              "losses": "loss_lag"})
    wide = wide.merge(lag, on=["industry_code", "period"], how="left", validate="one_to_one")
    for src, base, out in [("workers", "workers_lag", "workers_yoy"),
                           ("acquisitions", "acq_lag", "acquisition_yoy"),
                           ("losses", "loss_lag", "loss_yoy")]:
        wide[out] = (wide[src] / wide[base] - 1) * 100
        wide.loc[wide[base].isna() | (wide[base] == 0), out] = np.nan
    year = wide["period"].str[:4].astype(int)
    half = wide["period"].str[4:].astype(int)
    wide["quarters_covered"] = np.where(
        half == 1, year.astype(str) + "Q1|" + year.astype(str) + "Q2",
        year.astype(str) + "Q3|" + year.astype(str) + "Q4")
    wide["industry"] = "해당없음(제조업 총계)"
    wide["mapping_grade"] = "D"
    wide["geography"] = "경상남도 창원시"
    wide["population_scope"] = "창원시 전역 사업체 표본조사 — 창원국가산단 아님"
    wide["source"] = "고용노동부 사업체노동력조사(지역편), KOSIS"
    wide["source_table_id"] = "DT_118N_MONA49 / DT_118N_MONA59"
    wide["frequency"] = "반기"
    wide["coverage_flag"] = "manufacturing_aggregate_halfyear"
    wide["role"] = "FLOW_INTERPRETATION"
    wide["net_flow_note"] = ("입직-이직이며 KICOX 고용 증감과 같은 개념이 아니다. "
                             "모집단·정의·빈도가 모두 다르다.")
    return wide


# ---------------------------------------------------------------- 수출입
def build_trade_context_panel(root: Path) -> pd.DataFrame:
    """HS6 품목을 KICOX 업종 × 분기로 합산한 수출입.

    두 겹의 제한이 있다. 둘 다 coverage 열로 계속 표시한다.

    1. **류 제한** — 관세청 HS부호 원본에서 만든 유효 HS6 모집단 중 류 단위로
       KICOX 업종 귀속 근거가 있는 것만 담았다(72·73·84·85·87·89류).
       비철(74~81)·광학의료(90) 등은 의도적으로 제외했다.
    2. **수집 완전성 제한** — OpenAPI 일일 호출한도(HTTP 429)로 생긴 결손은
       관세청 무역통계 포털의 지역별 실적 CSV 일괄조회로 보완했다. 그래도
       방어적으로 **6개 연도창을 모두 확보한 코드만 집계에 쓴다.**

    그래서 이 값은 **업종 수출 총액이 아니다.** 시점 간 비교가 성립하는
    일관된 부분집합의 합계다.
    """
    p = root / TRADE_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig",
                    dtype={"period": str, "hs6": str, "hs_chapter": str})

    # 연도창을 모두 확보한 코드만 남긴다 (시점 간 비교 가능성 확보).
    cov_path = root / TRADE_COVERAGE
    excluded_by_industry: dict[str, int] = {}
    if cov_path.exists():
        cov = json.loads(cov_path.read_text(encoding="utf-8"))
        complete = set(cov.get("hs6_complete") or [])
        if complete:
            dropped = d[~d["hs6"].isin(complete)]
            excluded_by_industry = (dropped.groupby("mapped_kicox_industry")["hs6"]
                                    .nunique().to_dict())
            d = d[d["hs6"].isin(complete)]
    d["export_usd"] = _num(d["export_usd"])
    d["import_usd"] = _num(d["import_usd"])
    year = d["period"].str[:4].astype(int)
    month = d["period"].str[5:7].astype(int)
    d["quarter"] = year.astype(str) + "Q" + ((month - 1) // 3 + 1).astype(str)
    g = (d.groupby(["mapped_kicox_industry", "quarter"])
           .agg(export_usd=("export_usd", "sum"), import_usd=("import_usd", "sum"),
                n_hs6_items=("hs6", "nunique"), months=("period", "nunique"),
                mapping_grade=("mapping_grade", lambda s: sorted(set(s))[-1]),
                coverage_flag=("coverage_flag", "first"),
                hs_chapters=("hs_chapter", lambda s: "|".join(sorted(set(s)))))
           .reset_index().rename(columns={"mapped_kicox_industry": "industry"}))
    g = g.sort_values(["industry", "quarter"]).reset_index(drop=True)
    lag = g[["industry", "quarter", "export_usd", "import_usd"]].copy()
    lag["quarter"] = (pd.PeriodIndex(lag["quarter"], freq="Q") + 4).astype(str)
    lag = lag.rename(columns={"export_usd": "export_lag4", "import_usd": "import_lag4"})
    g = g.merge(lag, on=["industry", "quarter"], how="left", validate="one_to_one")
    for src, base, out in [("export_usd", "export_lag4", "export_yoy"),
                           ("import_usd", "import_lag4", "import_yoy")]:
        g[out] = (g[src] / g[base] - 1) * 100
        g.loc[g[base].isna() | (g[base] == 0), out] = np.nan
    g["n_hs6_excluded_incomplete"] = g["industry"].map(excluded_by_industry).fillna(0).astype(int)
    g["geography"] = "경상남도 창원시"
    g["population_scope"] = "창원시 전역 통관실적 — 창원국가산단 아님"
    g["source"] = "관세청 시군구별 품목별 수출입실적 + 무역통계 지역별 실적"
    g["source_table_id"] = "data.go.kr 15134343 + tradedata.go.kr"
    g["frequency"] = "월→분기 합산"
    g["role"] = "CONTEXT / EXTERNAL_DEMAND"
    g["coverage_note"] = ("관세청 HS부호 원본의 유효 HS6 중 (1)KICOX 업종 귀속 근거가 있는 "
                          "류이고 (2)6개 연도창을 모두 확보한 코드만 합산했다. "
                          "업종 수출 총액이 아니라 시점 간 비교가 성립하는 부분집합이다.")
    return g


def trade_industry_coverage(root: Path) -> pd.DataFrame:
    """업종별 수출입 수집 커버리지. 패널에 행이 없는 업종도 반드시 한 줄 남긴다.

    '대응 품목 없음' 과 '수집 미완' 은 전혀 다른 사실이다. 패널이 비어 있다는
    이유만으로 둘을 뭉뚱그리면 카드가 사실과 다른 말을 하게 된다.
    """
    uni_path = root / XWALK / "hs6_universe_customs.csv"
    if not uni_path.exists():
        return pd.DataFrame()
    uni = pd.read_csv(uni_path, encoding="utf-8-sig", dtype={"hs6": str})
    cov_path = root / TRADE_COVERAGE
    complete: set = set()
    if cov_path.exists():
        complete = set(json.loads(cov_path.read_text(encoding="utf-8"))
                       .get("hs6_complete") or [])
    trade_path = root / TRADE_CSV
    with_trade: set = set()
    if trade_path.exists():
        with_trade = set(pd.read_csv(trade_path, encoding="utf-8-sig",
                                     dtype={"hs6": str})["hs6"].unique())
    rows = []
    for industry, g in uni.groupby("target_kicox_industry"):
        codes = set(g["hs6"])
        n_complete = len(codes & complete)
        n_incomplete = len(codes & with_trade - complete)
        if n_complete > 0:
            status, reason = "usable", ""
        elif n_incomplete > 0:
            status = "collection_incomplete"
            reason = ("수집 미완(포털 일일 호출한도 초과) — 연도창 일부만 확보해 "
                      "시점 비교가 불가능하므로 집계에서 제외했다. 한도 초기화 후 "
                      "이어받기로 채울 수 있다.")
        else:
            status = "no_changwon_trade"
            reason = "귀속 근거가 있는 HS6 중 창원시 거래가 확인된 코드가 없다"
        rows.append(dict(industry=industry, n_hs6_mapped=len(codes),
                         n_hs6_complete=n_complete,
                         n_hs6_incomplete=n_incomplete,
                         trade_coverage_status=status,
                         trade_unavailable_reason=reason))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 전력
def build_electricity_activity_panel(root: Path) -> pd.DataFrame:
    """창원시 제조업 전력사용량·고객 증감 → 분기 패널.

    granularity 판정 (6-1 기준)
        제공 단위는 **창원시 × KSIC 대분류 × 월** 이다. 제조업이 'C' 한 칸이라
        KICOX 10업종으로 나눌 수 없다 → 우선순위 B(창원시 × 산업용 총계 × 월).
        따라서 **지역 산업활동 맥락**으로만 쓰고 업종별로 복제하지 않는다.

    전력사용량은 기간 합계(flow), 고객호수는 시점값(stock)이므로 분기 집계가 다르다.
    전력 감소를 생산 감소라고 단정하지 않는다 — 가동률과 개념이 다르다.
    """
    p = root / POWER_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig", dtype={"ym": str})
    d = d[d["industry"].astype(str).str.strip() == "제조업"].copy()
    if d.empty:
        return pd.DataFrame()
    for c in ("custCnt", "powerUsage", "bill", "unitCost"):
        d[c] = _num(d[c])
    d["quarter"] = d["ym"].str[:4] + "Q" + (
        ((d["ym"].str[5:7].astype(int) - 1) // 3 + 1).astype(str))
    g = (d.sort_values("ym").groupby("quarter")
           .agg(power_usage_kwh=("powerUsage", "sum"),          # flow
                customers=("custCnt", "last"),                  # stock(분기말)
                bill_krw=("bill", "sum"),
                unit_cost_avg=("unitCost", "mean"),
                months=("ym", "nunique"))
           .reset_index())
    g = g[g["months"] == 3]            # 분기가 3개월 다 차야 합계를 쓴다
    lag = g[["quarter", "power_usage_kwh", "customers"]].copy()
    lag["quarter"] = (pd.PeriodIndex(lag["quarter"], freq="Q") + 4).astype(str)
    lag = lag.rename(columns={"power_usage_kwh": "power_lag4",
                              "customers": "customers_lag4"})
    g = g.merge(lag, on="quarter", how="left", validate="one_to_one")
    for src, base, out in [("power_usage_kwh", "power_lag4", "power_usage_yoy"),
                           ("customers", "customers_lag4", "customers_yoy")]:
        g[out] = (g[src] / g[base] - 1) * 100
        g.loc[g[base].isna() | (g[base] == 0), out] = np.nan

    # 고객 증감(신규/증설/해지)은 **쓰지 않는다.**
    #
    # 이유: 값이 고객 '건수'로 성립하지 않는다. 창원시 제조업 전기사용 고객은
    # 약 6,000호인데, 2025-01 성산구 제조업 한 달 cancel 이 271,258, 2025-02
    # 전체 new 가 236,809 로 나온다(중앙값은 40). 한전 고객증감 API 의 해당 항목은
    # 계약전력(kW)일 가능성이 높고, 수집 metadata 의 `unit: 건` 은 확인되지 않은
    # 표기다. 단위가 확정되기 전에는 '업체 신규·해지'로 읽으면 안 된다.
    #
    # 고객 '수' 는 powerUsage/industryType 의 custCnt 를 쓴다. 이쪽은 5,785→6,026 으로
    # 범위·추세가 모두 성립한다.
    _CUSTNUM_EXCLUDED = (
        "change/custNum/industryType.do 의 new/expansion/cancel 은 단위 미확정"
        "(건수로 보기에는 값이 고객 수를 크게 넘는다)이라 패널에서 제외했다. "
        "고객 수는 powerUsage 의 custCnt 를 사용한다.")

    g["industry"] = "해당없음(제조업 총계)"
    g["mapping_grade"] = "D"
    g["geography"] = "경상남도 창원시"
    g["geography_grade"] = "B"
    g["population_scope"] = "창원시 전역 전기사용 고객 — 창원국가산단 아님"
    g["source"] = "한국전력 전력데이터개방포털"
    g["source_table_id"] = ("powerUsage/industryType.do + "
                            "change/custNum/industryType.do")
    g["frequency"] = "월→분기 (사용량 합계 / 고객호수 분기말)"
    g["coverage_flag"] = "manufacturing_aggregate_city"
    g["role"] = "CONTEXT / ACTIVITY"
    g["usage_note"] = ("업종별로 복제하지 않는다. 전력 감소를 생산 감소로 단정하지 않는다 — "
                       "가동률과 개념·모집단이 다르다.")
    g["excluded_series_note"] = _CUSTNUM_EXCLUDED
    return g.reset_index(drop=True)


# ---------------------------------------------------------------- BSI
def build_business_sentiment_panel(root: Path) -> pd.DataFrame:
    """경남(제조업 총계)과 전국(업종별) BSI 를 분기 평균으로."""
    p = root / BSI_CSV
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, encoding="utf-8-sig", dtype={"period": str})
    d["value"] = _num(d["value"])
    d["period"] = d["period"].astype(str)
    year = d["period"].str[:4].astype(int)
    month = d["period"].str[4:6].astype(int)
    d["quarter"] = year.astype(str) + "Q" + ((month - 1) // 3 + 1).astype(str)
    xw = pd.read_csv(root / XWALK / "ecos_bsi_to_kicox.csv", encoding="utf-8-sig")
    xw = xw[["source_code", "target_kicox_industry", "mapping_confidence"]].rename(
        columns={"source_code": "region_or_industry_code",
                 "target_kicox_industry": "mapped_kicox_industry",
                 "mapping_confidence": "mapping_grade"})
    d = d.merge(xw, on="region_or_industry_code", how="left")
    g = (d.groupby(["quarter", "scope", "region_or_industry_code",
                    "region_or_industry_name", "bsi_code", "bsi_name",
                    "mapped_kicox_industry", "mapping_grade"], dropna=False)
           .agg(value=("value", "mean"), months=("period", "nunique"))
           .reset_index())
    g = g.rename(columns={"quarter": "period", "region_or_industry_name": "region_or_industry",
                          "bsi_name": "indicator"})
    g["value"] = g["value"].round(2)
    g = g.sort_values(["scope", "region_or_industry_code", "bsi_code", "period"])
    prev = g[["scope", "region_or_industry_code", "bsi_code", "period", "value"]].copy()
    prev["period"] = (pd.PeriodIndex(prev["period"], freq="Q") + 4).astype(str)
    prev = prev.rename(columns={"value": "value_lag4"})
    g = g.merge(prev, on=["scope", "region_or_industry_code", "bsi_code", "period"],
                how="left", validate="one_to_one")
    # BSI 는 지수라 증감률보다 포인트 차이가 자연스럽다.
    g["change_vs_year_ago_pt"] = (g["value"] - g["value_lag4"]).round(2)
    g["below_100"] = g["value"] < 100
    g["source_table_code"] = np.where(g["scope"].str.startswith("경남"), "512Y019", "512Y007")
    g["geography"] = np.where(g["scope"].str.startswith("경남"), "경상남도", "전국")
    g["coverage_flag"] = np.where(g["scope"].str.startswith("경남"),
                                  "region_manufacturing_aggregate", "national_by_industry")
    g["role"] = "CONTEXT / BUSINESS_SENTIMENT"
    g["usage_note"] = ("업종별 자동판정에 쓰지 않는다. 전국 업종 BSI 를 창원국가산단 "
                       "개별 업종의 신호라고 부르지 않는다.")
    return g.reset_index(drop=True)
