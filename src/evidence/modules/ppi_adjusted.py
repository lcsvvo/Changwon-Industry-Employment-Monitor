# -*- coding: utf-8 -*-
"""명목 생산과 PPI 조정 생산의 이중표기.

용어
    'PPI 조정 생산' 은 물리적 생산량이 아니다. 전국 단위 생산자물가지수로
    명목 생산액에서 가격효과를 일부 제거한 잠정 지표다. 산단·업종 고유의
    가격변동과 제품구성 변화는 제거되지 않는다.

Triage 와의 관계
    Triage 의 P 축은 명목 생산 YoY 를 그대로 쓴다. 이 모듈은 그 값을
    바꾸지 않으며, 카드·해석층에 병기할 보조 열만 만든다.

매핑 등급
    A/B  단일값 제시 가능
    C    복수 후보만 존재 → low/high 밴드로만 제시하고 단정형 위축 판정 금지
    D    사용 불가 → 조정값을 만들지 않는다
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import PPI_GRADE_BAND_ONLY, PPI_GRADE_SINGLE_VALUE_OK, REAL_PROD_DECLINE

PPI_PANEL = "data/processed/ppi/ppi_industry_panel.csv"


def load_ppi(root: Path) -> pd.DataFrame:
    p = pd.read_csv(root / PPI_PANEL)
    p.columns = [c.lstrip("﻿") for c in p.columns]
    return p.rename(columns={"kicox_industry": "industry"})


def build_ppi_adjusted_panel(root: Path, triage_panel: pd.DataFrame) -> pd.DataFrame:
    """업종 × 분기 × (PPI 후보) 조정 생산 YoY 패널.

    조정 YoY 는 (1+명목YoY)/(1+PPI YoY)-1 로 계산한다. 생산액과 물가지수의
    분기 정의가 다르므로 근사이며, 그 사실을 note 로 남긴다.
    """
    ppi = load_ppi(root)
    base = triage_panel[["industry", "quarter", "p_yoy", "production",
                         "production_masked"]].copy()
    base = base.rename(columns={"p_yoy": "nominal_production_yoy"})
    d = base.merge(ppi[["industry", "quarter", "grade", "ppi_level", "component_id",
                        "ppi_item", "ppi_index", "ppi_index_yoy_pct",
                        "ppi_index_complete_quarter"]],
                   on=["industry", "quarter"], how="left")
    nom = d["nominal_production_yoy"] / 100.0
    dfl = d["ppi_index_yoy_pct"] / 100.0
    d["ppi_adjusted_production_yoy"] = ((1 + nom) / (1 + dfl) - 1) * 100
    d.loc[dfl.isna() | nom.isna() | (dfl <= -1), "ppi_adjusted_production_yoy"] = np.nan
    d["ppi_mapping_grade"] = d["grade"].fillna("D")
    d["ppi_mapping_uncertainty"] = d["ppi_mapping_grade"].map({
        "A": "대분류 직접 대응",
        "B": "상위 범주가 넓어 범위 과대·과소 가능",
        "C": "복수 후보만 존재 — 가중치 근거 없음. 밴드로만 해석",
        "D": "대응 항목 없음 — 조정 생산 산출 불가",
    }).fillna("D 등급(대응 항목 없음)")
    d["ppi_index_incomplete_quarter"] = ~d["ppi_index_complete_quarter"].fillna(False)
    return d


def collapse_to_industry_quarter(cand: pd.DataFrame) -> pd.DataFrame:
    """후보가 여러 개인 C 등급은 밴드(low/high)로, A/B 는 단일값으로 요약한다."""
    g = cand.groupby(["industry", "quarter"], dropna=False)
    out = g.agg(
        nominal_production_yoy=("nominal_production_yoy", "first"),
        ppi_mapping_grade=("ppi_mapping_grade", "first"),
        ppi_mapping_uncertainty=("ppi_mapping_uncertainty", "first"),
        n_ppi_candidates=("ppi_item", lambda s: int(s.notna().sum())),
        ppi_candidate_items=("ppi_item", lambda s: "|".join(sorted(x for x in s.dropna()))),
        ppi_adjusted_low=("ppi_adjusted_production_yoy", "min"),
        ppi_adjusted_high=("ppi_adjusted_production_yoy", "max"),
        ppi_index_incomplete_quarter=("ppi_index_incomplete_quarter", "any"),
    ).reset_index()

    single = out["ppi_mapping_grade"].isin(PPI_GRADE_SINGLE_VALUE_OK)
    out["ppi_adjusted_production_yoy"] = np.where(
        single, out["ppi_adjusted_low"], np.nan)
    out["ppi_adjusted_band_only"] = out["ppi_mapping_grade"].isin(PPI_GRADE_BAND_ONLY)

    # 부호·경계 일치 (단일값이 있는 A/B 에 대해서만 단정한다)
    nom, adj = out["nominal_production_yoy"], out["ppi_adjusted_production_yoy"]
    both = nom.notna() & adj.notna()
    out["sign_agreement"] = (np.sign(nom) == np.sign(adj)).astype("boolean").where(both)
    thr = REAL_PROD_DECLINE
    out["pct5_threshold_agreement"] = ((nom <= thr) == (adj <= thr)).astype("boolean").where(both)

    # C 등급 밴드에서는 후보 간 방향이 갈리는지만 표시한다.
    band = out["ppi_adjusted_band_only"] & out["ppi_adjusted_low"].notna()
    out["band_sign_split"] = (
        np.sign(out["ppi_adjusted_low"]) != np.sign(out["ppi_adjusted_high"])
    ).astype("boolean").where(band)
    out["band_threshold_split"] = (
        (out["ppi_adjusted_low"] <= thr) != (out["ppi_adjusted_high"] <= thr)
    ).astype("boolean").where(band)
    return out


def disagreement_rows(summary: pd.DataFrame) -> pd.DataFrame:
    """명목과 PPI 조정 생산의 부호 또는 5% 경계가 갈리는 행 전부."""
    m = (summary["sign_agreement"].eq(False).fillna(False)
         | summary["pct5_threshold_agreement"].eq(False).fillna(False))
    cols = ["industry", "quarter", "nominal_production_yoy", "ppi_adjusted_production_yoy",
            "ppi_mapping_grade", "sign_agreement", "pct5_threshold_agreement"]
    return summary.loc[m, cols].sort_values(["quarter", "industry"]).reset_index(drop=True)
