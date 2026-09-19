# -*- coding: utf-8 -*-
"""신뢰도층 — 개별 플래그를 그대로 전달한다.

점수로 합산하지 않는 이유
    여러 플래그를 하나의 '신뢰도 점수' 로 묶으면 가중치를 정해야 하고,
    그 가중치의 근거가 다시 없다. 이 프로젝트가 ELECTRE 가중치에서 겪은
    문제와 같은 문제가 반복된다. 그래서 합산하지 않고 나열한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FLAG_COLUMNS = [
    "employment_cross_source_agreement",
    "employment_cross_source_disagreement",
    "monthly_signal_3of3",
    "monthly_signal_2of3",
    "nominal_real_sign_disagreement",
    "ppi_mapping_uncertain",
    "small_base_warning",
    "source_missing",
    "source_revision_warning",
    "industry_mapping_uncertain",
    "op_rate_definition_break",
    "monthly_data_unavailable",
]

FLAG_LABELS = {
    "employment_cross_source_agreement": "고용보험 지표와 방향 일치",
    "employment_cross_source_disagreement": "고용보험 지표와 방향 불일치",
    "monthly_signal_3of3": "분기 내 3개월 모두 같은 방향",
    "monthly_signal_2of3": "분기 내 2개월에서 같은 방향",
    "nominal_real_sign_disagreement": "명목·PPI 조정 생산 방향 불일치",
    "ppi_mapping_uncertain": "PPI 매핑 불확실(C·D 등급)",
    "small_base_warning": "소규모 분모 — 비율 변동 과대 가능",
    "source_missing": "입력 자료 일부 미확인",
    "source_revision_warning": "연간보정 개정본 사용 구간",
    "industry_mapping_uncertain": "외부자료 업종 대응 불확실",
    "op_rate_definition_break": "가동률 공표 정의 단절 구간",
    "monthly_data_unavailable": "월별 원자료 미제공 구간",
}


def build_quality_flags(d: pd.DataFrame) -> pd.DataFrame:
    """업종×분기 자료품질·신뢰도 플래그. 결측은 정상으로 바꾸지 않는다."""
    q = pd.DataFrame(index=d.index)
    q["industry"] = d["industry"]
    q["quarter"] = d["quarter"]

    q["employment_cross_source_agreement"] = d["employment_cross_source_agreement"].fillna(False)
    q["employment_cross_source_disagreement"] = d["employment_cross_source_disagreement"].fillna(False)

    obs = d.get("employment_months_observed")
    neg = d.get("employment_negative_months")
    if obs is None:
        obs = pd.Series(np.nan, index=d.index)
        neg = pd.Series(np.nan, index=d.index)
    q["monthly_signal_3of3"] = (obs.eq(3) & neg.eq(3)).fillna(False)
    q["monthly_signal_2of3"] = (obs.eq(3) & neg.eq(2)).fillna(False)
    q["monthly_data_unavailable"] = obs.isna() | obs.lt(3)

    q["nominal_real_sign_disagreement"] = d["sign_agreement"].eq(False).fillna(False)
    q["ppi_mapping_uncertain"] = d["ppi_mapping_grade"].isin(["C", "D"])
    q["small_base_warning"] = d["small_base_warning"].fillna(False)

    core = ["employment", "production", "firms_op", "op_rate"]
    q["source_missing"] = d[core].isna().any(axis=1)
    q["source_missing_fields"] = d[core].isna().apply(
        lambda r: "|".join(c for c in core if r[c]), axis=1)

    rev_cols = [c for c in d.columns if c.endswith("_is_revised")]
    q["source_revision_warning"] = (d[rev_cols].fillna(0).astype(float).sum(axis=1) > 0
                                    if rev_cols else False)
    q["industry_mapping_uncertain"] = d["industry_mapping_uncertain"].fillna(False)
    q["op_rate_definition_break"] = d["op_rate_definition_break"].fillna(False)

    q["quality_flags_raised"] = q[[c for c in FLAG_COLUMNS if c in q.columns]].sum(axis=1)
    q["quality_flag_list"] = q[[c for c in FLAG_COLUMNS if c in q.columns]].apply(
        lambda r: " · ".join(FLAG_LABELS[c] for c in FLAG_COLUMNS
                             if c in r.index and bool(r[c])) or "표시할 플래그 없음", axis=1)
    q["quality_score_intentionally_absent"] = (
        "가중치 근거가 없어 신뢰도 점수를 만들지 않는다. 플래그를 그대로 읽는다.")
    return q
