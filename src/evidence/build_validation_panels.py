# -*- coding: utf-8 -*-
"""
build_validation_panels.py
PPI(생산자물가지수)·EIS(고용행정통계) 검증·보조 패널 생성 (오프라인, 읽기 전용)

KICOX core state panel에 병합하지 않는다. 검증용 별도 패널만 생성한다.

PPI
    - data/raw/ppi/ppi_raw.csv 는 KOSIS 생산자물가지수(기본분류) 전국 월별 데이터다(지역 구분 없음).
    - KICOX 10개 업종과 PPI 세부품목의 공식 대응표가 아직 확정되지 않았으므로(사용자 승인 보류),
      업종별 실질생산 변환은 이 파이프라인에서 수행하지 않는다.
    - 총지수(C1_NM == '총지수')만 월->분기 평균해 제한적 검증 패널로 저장한다.
    - 후보 매핑표는 별도 파일로만 저장하고 "confirmed=False"로 명시한다.

EIS
    - data/raw/eis/*.csv 는 이미 분기 단위(분기말 월, stock)로 정리되어 있다.
    - 가용기간은 2022Q1~2026Q2이며, 결측 분기는 보간하지 않는다.
    - KICOX 고용과 모집단이 다르므로 비율/점유율은 계산하지 않는다.

산출물
    data/processed/ppi/ppi_validation_panel.csv
    data/processed/ppi/ppi_industry_mapping_candidates.csv   (후보만, 전부 confirmed=False)
    data/processed/eis/eis_validation_panel.csv
"""
from __future__ import annotations

import os
import sys

import pandas as pd

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
P_PPI_RAW = os.path.join(BASE, "data", "raw", "ppi", "ppi_raw.csv")
P_EIS_RAW = os.path.join(BASE, "data", "raw", "eis", "eis_changwon_insured_2022M03_2026M06.csv")
P_TOTAL_MASTER = os.path.join(BASE, "data", "processed", "kicox", "changwon_total_master.csv")

DIR_PPI_OUT = os.path.join(BASE, "data", "processed", "ppi")
DIR_EIS_OUT = os.path.join(BASE, "data", "processed", "eis")

# KICOX 10개 업종 <-> PPI 대분류 후보 매핑. 사용자 승인 전까지 전부 보류(confirmed=False)이며
# 이 파이프라인은 이 표를 실제 계산에 사용하지 않는다 — 검토용 참고자료로만 저장한다.
PPI_MAPPING_CANDIDATES = [
    dict(kicox_industry="음식료", ppi_candidate_code="대분류", ppi_candidate_item="음식료품(식료품/음료품/담배)",
         basis="명칭 직접 대응", confirmed=False),
    dict(kicox_industry="섬유의복", ppi_candidate_code="대분류", ppi_candidate_item="섬유및의복",
         basis="가죽·가방 등 범위 상이 가능", confirmed=False),
    dict(kicox_industry="목재종이", ppi_candidate_code="대분류 2개 합산",
         ppi_candidate_item="목재및목제품 + 펄프및종이제품", basis="두 대분류 합산 필요", confirmed=False),
    dict(kicox_industry="석유화학", ppi_candidate_code="대분류 2개 합산",
         ppi_candidate_item="화학제품 + 석탄및석유제품",
         basis="KICOX는 단일업종, PPI는 정유/화학 분리 — 1:1 아님", confirmed=False),
    dict(kicox_industry="비금속", ppi_candidate_code="대분류", ppi_candidate_item="비금속광물제품",
         basis="시멘트·유리·요업 등 매칭 양호", confirmed=False),
    dict(kicox_industry="철강", ppi_candidate_code="대분류(과대매칭 위험)", ppi_candidate_item="1차금속제품(철강+비철금속)",
         basis="비철금속(동·알루미늄) 포함되어 범위 과대", confirmed=False),
    dict(kicox_industry="기계", ppi_candidate_code="대분류", ppi_candidate_item="기계및장비",
         basis="매칭 양호", confirmed=False),
    dict(kicox_industry="전기전자", ppi_candidate_code="대분류 2개 합산",
         ppi_candidate_item="전기장비 + 컴퓨터전자및광학기기",
         basis="KICOX는 단일업종, PPI는 전기/전자 분리", confirmed=False),
    dict(kicox_industry="운송장비", ppi_candidate_code="대분류", ppi_candidate_item="운송장비(자동차+기타운송장비)",
         basis="매칭 양호", confirmed=False),
    dict(kicox_industry="기타", ppi_candidate_code="매칭 불가 수준", ppi_candidate_item="공산품 잔여(기타제조업제품 등)",
         basis="정의 이질적", confirmed=False),
]


def _month_to_quarter(yyyymm: int) -> str:
    y, m = divmod(int(yyyymm), 100)
    return f"{y}Q{(m - 1) // 3 + 1}"


def build_ppi_validation_panel() -> pd.DataFrame:
    df = pd.read_csv(P_PPI_RAW, encoding="utf-8-sig")
    total = df[df.C1_NM == "총지수"].copy()
    if total.empty:
        raise ValueError("PPI 원자료에서 '총지수' 계열을 찾지 못했습니다")
    total["quarter"] = total.PRD_DE.astype(int).map(_month_to_quarter)
    g = total.groupby("quarter").DT
    panel = g.agg(ppi_total_index="mean", ppi_total_index_n_months="count").reset_index()
    panel = panel.sort_values("quarter").reset_index(drop=True)
    panel["ppi_total_index_complete_quarter"] = panel.ppi_total_index_n_months == 3
    panel["ppi_total_index_yoy_pct"] = (
        panel.ppi_total_index / panel.ppi_total_index.shift(4) - 1) * 100
    panel.loc[~panel.ppi_total_index_complete_quarter, "ppi_total_index_yoy_pct"] = pd.NA
    panel["note"] = ("전국 단위 KOSIS 생산자물가지수(기본분류) 총지수, 월평균을 분기 평균한 값. "
                      "업종별 매핑 미확정으로 총지수 기준 제한적 민감도에만 사용한다.")
    return panel


def build_ppi_mapping_candidates() -> pd.DataFrame:
    return pd.DataFrame(PPI_MAPPING_CANDIDATES)


EIS_GU_MFG_COLS = [
    "uichang_mfg", "seongsan_mfg", "masanhappo_mfg", "masanhoewon_mfg", "jinhae_mfg",
]
EIS_CORE_NUMERIC_COLS = [
    "changwon_total_all_industry", "changwon_manufacturing", *EIS_GU_MFG_COLS,
]
EIS_EXPECTED_QUARTER_START = "2022Q1"
EIS_EXPECTED_QUARTER_END = "2026Q2"
EIS_EXPECTED_N_QUARTERS = 18


def _quarter_end_month(quarter: str) -> str:
    y, q = quarter.split("Q")
    return f"{int(q) * 3:02d}"


def _validate_eis_raw(df: pd.DataFrame) -> None:
    expected_quarters = [
        f"{y}Q{q}"
        for y in range(2022, 2027)
        for q in range(1, 5)
        if f"{y}Q{q}" <= EIS_EXPECTED_QUARTER_END
    ]

    actual_quarters = df["quarter"].tolist()
    assert len(actual_quarters) == EIS_EXPECTED_N_QUARTERS, (
        f"EIS 분기 수가 {EIS_EXPECTED_N_QUARTERS}개가 아님: {len(actual_quarters)}개")
    assert sorted(set(actual_quarters)) == sorted(expected_quarters), (
        f"EIS 기간이 {EIS_EXPECTED_QUARTER_START}~{EIS_EXPECTED_QUARTER_END}(18개 분기)와 불일치: "
        f"{sorted(set(actual_quarters))}")

    assert df["quarter"].is_unique, (
        f"EIS quarter 중복 존재: {df.loc[df['quarter'].duplicated(), 'quarter'].tolist()}")

    key_cols = ["quarter", "month", *EIS_CORE_NUMERIC_COLS]
    na_counts = df[key_cols].isna().sum()
    assert na_counts.sum() == 0, f"EIS 주요 변수 결측 존재:\n{na_counts[na_counts > 0]}"

    for _, row in df.iterrows():
        year_str, month_str = row["month"].split("-")
        expected_year = row["quarter"][:4]
        expected_month = _quarter_end_month(row["quarter"])
        assert year_str == expected_year and month_str == expected_month, (
            f"quarter-month 분기말월 불일치: quarter={row['quarter']}, month={row['month']}")

    gu_sum = df[EIS_GU_MFG_COLS].sum(axis=1)
    mismatch = df.loc[gu_sum != df["changwon_manufacturing"], "quarter"]
    assert mismatch.empty, f"5개 구 제조업 합 != changwon_manufacturing 인 분기: {mismatch.tolist()}"

    for col in EIS_CORE_NUMERIC_COLS:
        assert pd.api.types.is_numeric_dtype(df[col]), f"EIS 컬럼이 숫자형이 아님: {col}"
        assert (df[col] >= 0).all(), f"EIS 컬럼에 음수 존재: {col}"


def build_eis_validation_panel() -> pd.DataFrame:
    df = pd.read_csv(P_EIS_RAW, comment="#", encoding="utf-8-sig")
    df = df.sort_values("quarter").reset_index(drop=True)
    _validate_eis_raw(df)

    df["eis_manufacturing_yoy_pct"] = (
        df["changwon_manufacturing"] / df["changwon_manufacturing"].shift(4) - 1) * 100

    if os.path.exists(P_TOTAL_MASTER):
        tot = pd.read_csv(P_TOTAL_MASTER)[["quarter", "employment_total"]].rename(
            columns={"employment_total": "kicox_employment_total"})
        df = df.merge(tot, on="quarter", how="left")
    df["note"] = ("고용노동부 EIS 창원시 고용보험 피보험자수(stock, 분기말월). "
                   "KICOX 산단 고용과 모집단이 달라 비율/점유율은 계산하지 않는다. "
                   "eis_manufacturing_yoy_pct는 EIS 제조업 피보험자수(5개구 합)만의 검증용 "
                   "전년동분기대비 증감률이며 KICOX 지표와 무관하다. "
                   "가용기간은 2022Q1~2026Q2이며, 결측 분기는 보간하지 않는다.")
    return df


def main() -> None:
    os.makedirs(DIR_PPI_OUT, exist_ok=True)
    os.makedirs(DIR_EIS_OUT, exist_ok=True)

    ppi_panel = build_ppi_validation_panel()
    ppi_panel.to_csv(os.path.join(DIR_PPI_OUT, "ppi_validation_panel.csv"),
                     index=False, encoding="utf-8-sig")
    print(f"[PPI] ppi_validation_panel.csv 저장 ({len(ppi_panel)}행, "
          f"{ppi_panel.quarter.min()}~{ppi_panel.quarter.max()})")

    mapping = build_ppi_mapping_candidates()
    mapping.to_csv(os.path.join(DIR_PPI_OUT, "ppi_industry_mapping_candidates.csv"),
                   index=False, encoding="utf-8-sig")
    print(f"[PPI] ppi_industry_mapping_candidates.csv 저장 "
          f"({len(mapping)}건, 전부 confirmed=False — 보류)")

    eis_panel = build_eis_validation_panel()
    eis_panel.to_csv(os.path.join(DIR_EIS_OUT, "eis_validation_panel.csv"),
                     index=False, encoding="utf-8-sig")
    print(f"[EIS] eis_validation_panel.csv 저장 ({len(eis_panel)}행, "
          f"{eis_panel.quarter.min()}~{eis_panel.quarter.max()})")
    print("[EIS] 검증 통과: 기간 18개 분기, quarter 중복 없음, 주요 변수 결측 없음, "
          "quarter-month 분기말월 대응 일치, 5개 구 제조업 합계 == changwon_manufacturing, "
          "전 컬럼 숫자형·음수 없음")


if __name__ == "__main__":
    main()
