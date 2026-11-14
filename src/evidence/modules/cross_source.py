# -*- coding: utf-8 -*-
"""KICOX 산단 고용과 고용보험 피보험자 지표의 방향 교차확인.

이것은 검증(validation)이 아니다
    두 자료의 모집단이 다르다. KICOX 는 창원국가산단 입주 사업체,
    고용보험은 창원시 전역 사업장이다. 따라서 "고용보험으로 KICOX 를 검증했다"
    고 말할 수 없고, "방향을 교차확인했다" 가 정확한 표현이다.

무엇을 계산하는가
    방향 일치 / 방향 불일치 / 비교 불가  세 가지뿐이다.
    변화율 차이(%p)는 보조표시이며 수준·점유율은 계산하지 않는다.

자료
    창원시 제조업 총계  : data/raw/eis/… (고용노동부 고용행정통계, 분기말월 stock)
    창원시 업종별       : data/raw/changwon_chamber/… (창원상의 보고서 수록 고용보험DB)
                          업종 표기가 KICOX 10업종과 1:1 이 아니므로 크로스워크
                          등급(B/C)을 함께 전달하고, C 등급은 단정하지 않는다.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

EIS_RAW = "data/raw/eis/eis_changwon_insured_2022M03_2026M06.csv"
CCI_RAW = "data/raw/changwon_chamber/창원시_업종별_고용보험피보험자_동향.csv"
CROSSWALK = "data/processed/final_model/reference/industry_crosswalk/employment_insurance_to_kicox.csv"

DIRECTION_AGREE = "방향 일치"
DIRECTION_DISAGREE = "방향 불일치"
DIRECTION_NA = "비교자료 없음"
POPULATION_NOTE = ("KICOX 산단 고용과 고용보험 피보험자는 모집단이 다르다"
                   "(산단 입주 사업체 vs 창원시 전역 사업장). 수준·점유율 비교 금지.")


def _read_commented_csv(path: Path) -> pd.DataFrame:
    """앞부분 주석(#) 줄을 건너뛰고 읽는다. 주석 내용은 metadata 로 남긴다."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.strip() and not ln.lstrip('"').startswith("#"))
    return pd.read_csv(path, skiprows=start)


def load_eis_manufacturing(root: Path) -> pd.DataFrame:
    d = _read_commented_csv(root / EIS_RAW)
    d = d[["quarter", "month", "changwon_manufacturing"]].copy()
    lag = d[["quarter", "changwon_manufacturing"]].copy()
    lag["quarter"] = (pd.PeriodIndex(lag["quarter"], freq="Q") + 4).astype(str)
    lag = lag.rename(columns={"changwon_manufacturing": "eis_mfg_lag4"})
    d = d.merge(lag, on="quarter", how="left", validate="one_to_one")
    d["eis_manufacturing_yoy"] = (d["changwon_manufacturing"] / d["eis_mfg_lag4"] - 1) * 100
    d.loc[d["eis_mfg_lag4"].isna(), "eis_manufacturing_yoy"] = np.nan
    return d.rename(columns={"changwon_manufacturing": "eis_manufacturing_level"})


def load_cci_industry(root: Path) -> pd.DataFrame:
    """창원상의 보고서 수록 업종별 고용보험 피보험자 → KICOX 업종 후보."""
    d = _read_commented_csv(root / CCI_RAW)
    d = d.rename(columns={"분기": "quarter_raw"})
    d["quarter"] = (d["quarter_raw"].str.extract(r"(\d{4})")[0] + "Q"
                    + d["quarter_raw"].str.extract(r"(\d)Q")[0])
    with (root / CROSSWALK).open(encoding="utf-8-sig") as f:
        xw = {r["source_category"]: r for r in csv.DictReader(f)}
    recs = []
    for label, row in xw.items():
        if label not in d.columns or row["target_kicox_industry"].startswith("해당없음"):
            continue
        for x in d[["quarter", label]].dropna().itertuples(index=False):
            recs.append(dict(quarter=x[0], source_category=label,
                             industry=row["target_kicox_industry"],
                             insured_level=float(x[1]),
                             mapping_type=row["mapping_type"],
                             mapping_confidence=row["mapping_confidence"],
                             mapping_rationale=row["rationale"]))
    out = pd.DataFrame(recs)
    if out.empty:
        return out
    lag = out[["industry", "quarter", "insured_level"]].copy()
    lag["quarter"] = (pd.PeriodIndex(lag["quarter"], freq="Q") + 4).astype(str)
    lag = lag.rename(columns={"insured_level": "insured_lag4"})
    out = out.merge(lag, on=["industry", "quarter"], how="left", validate="one_to_one")
    out["insured_yoy"] = (out["insured_level"] / out["insured_lag4"] - 1) * 100
    out.loc[out["insured_lag4"].isna(), "insured_yoy"] = np.nan
    return out


def _direction(a: pd.Series, b: pd.Series) -> pd.Series:
    """부호 비교. 어느 한쪽이 없으면 비교불가. 정확히 0 은 어느 쪽과도 '일치'로
    보지 않고 별도 표기한다."""
    out = pd.Series(DIRECTION_NA, index=a.index, dtype="object")
    both = a.notna() & b.notna()
    zero = both & ((a == 0) | (b == 0))
    agree = both & ~zero & (np.sign(a) == np.sign(b))
    dis = both & ~zero & (np.sign(a) != np.sign(b))
    out[agree] = DIRECTION_AGREE
    out[dis] = DIRECTION_DISAGREE
    out[zero] = "한쪽이 정확한 0 — 방향 판정 보류"
    return out


def build_crosscheck_panel(root: Path, triage_panel: pd.DataFrame) -> pd.DataFrame:
    """업종×분기 교차확인 패널.

    업종 단위 비교는 창원상의 업종별 고용보험 수치로만 가능하고, 그 대응은
    B/C 등급이다. 나머지 업종은 산단 제조업 총계 대 창원시 제조업 총계의
    거시 방향만 참고로 붙인다(업종 신호로 쓰지 않는다).
    """
    base = triage_panel[["industry", "quarter", "e_yoy", "mfg_emp_yoy",
                         "employment"]].copy()
    base = base.rename(columns={"e_yoy": "kicox_employment_yoy"})

    eis = load_eis_manufacturing(root)[["quarter", "eis_manufacturing_level",
                                        "eis_manufacturing_yoy"]]
    d = base.merge(eis, on="quarter", how="left")
    d["aggregate_direction"] = _direction(d["mfg_emp_yoy"], d["eis_manufacturing_yoy"])
    d["aggregate_yoy_gap_pp"] = d["mfg_emp_yoy"] - d["eis_manufacturing_yoy"]

    cci = load_cci_industry(root)
    if not cci.empty:
        d = d.merge(cci[["industry", "quarter", "source_category", "insured_level",
                         "insured_yoy", "mapping_type", "mapping_confidence",
                         "mapping_rationale"]],
                    on=["industry", "quarter"], how="left", validate="one_to_one")
    else:                                              # pragma: no cover
        for c in ["source_category", "insured_level", "insured_yoy",
                  "mapping_type", "mapping_confidence", "mapping_rationale"]:
            d[c] = np.nan

    d["industry_direction"] = _direction(d["kicox_employment_yoy"], d["insured_yoy"])
    d["industry_yoy_gap_pp"] = d["kicox_employment_yoy"] - d["insured_yoy"]
    d["industry_mapping_uncertain"] = d["mapping_confidence"].isin(["C", "D"])
    # C 등급 대응은 방향 판정을 단정하지 않는다.
    d.loc[d["industry_mapping_uncertain"] & d["industry_direction"].isin(
        [DIRECTION_AGREE, DIRECTION_DISAGREE]), "industry_direction"] += " (매핑 C등급 — 참고)"
    d["employment_cross_source_agreement"] = d["industry_direction"].str.startswith(
        DIRECTION_AGREE)
    d["employment_cross_source_disagreement"] = d["industry_direction"].str.startswith(
        DIRECTION_DISAGREE)
    d["cross_source_population_note"] = POPULATION_NOTE
    d["cross_source_available"] = d["insured_yoy"].notna()
    return d


def crosscheck_summary(panel: pd.DataFrame) -> pd.DataFrame:
    g = (panel.groupby("industry")
         .agg(quarters=("quarter", "size"),
              industry_comparable=("cross_source_available", "sum"),
              direction_agree=("employment_cross_source_agreement", "sum"),
              direction_disagree=("employment_cross_source_disagreement", "sum"),
              mapping_confidence=("mapping_confidence", lambda s: s.dropna().iloc[0]
                                  if s.notna().any() else "매핑 없음"))
         .reset_index())
    g["agreement_rate"] = (g["direction_agree"] /
                           g["industry_comparable"].replace(0, np.nan))
    return g
