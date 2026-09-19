# -*- coding: utf-8 -*-
"""확인신호 프로필 (multi-label) 과 경계 민감도.

이 층이 만드는 것은 '원인 유형' 이 아니다
    가동업체수가 줄고 고용도 줄었다는 동시관측은, 업체 이탈이 고용감소를
    일으켰다는 근거가 되지 않는다. 따라서 이름을 '업체수 감소 신호' 처럼
    관측 자체로 쓰고, 하나의 유형으로 강제 배정하지 않는다.

multi-label
    A 업체수 감소 신호
    B 가동률 위축 신호
    C PPI 조정 생산 위축 신호
    D 생산유지·고용감소 패턴
    각각 독립 True/False 다. 카드 요약용으로 '대표 확인신호' 를 하나 뽑되,
    대표 ≠ 유일한 원인임을 문구로 함께 전달한다.

경계
    전부 OWN(프로젝트 운영규칙). 좋은 값을 고르기 위한 것이 아니라 흔들림을
    재기 위한 기준선이며, 민감도 결과를 보고 재설정하지 않는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (EMP_DECLINE_FOR_PATTERN, FIRMS_OP_DECLINE, OP_RATE_DECLINE,
                     PROD_MAINTAINED, REAL_PROD_DECLINE, SENSITIVITY_GRID)

SIGNAL_LABELS = {
    "firms_op_decline_signal": "업체수 감소 신호",
    "operating_rate_decline_signal": "가동 위축 신호",
    "ppi_adjusted_production_decline_signal": "실질생산 위축 신호(PPI 조정)",
    "production_maintained_employment_decline": "생산유지·고용감소 신호",
}
# 대표 확인신호 표시 순서. 우열이나 인과 순서가 아니라 결정적 표시순서일 뿐이다.
REPRESENTATIVE_ORDER = list(SIGNAL_LABELS)
NO_SIGNAL = "해석 보류"
PROFILE_NAME = "확인신호 프로필"


def compute_signals(d: pd.DataFrame, *,
                    firms_thr: float = FIRMS_OP_DECLINE,
                    op_rate_thr: float = OP_RATE_DECLINE,
                    real_prod_thr: float = REAL_PROD_DECLINE) -> pd.DataFrame:
    """multi-label 확인신호. 입력 결측은 0/정상으로 바꾸지 않고 <NA> 로 남긴다."""
    out = pd.DataFrame(index=d.index)

    out["firms_op_decline_signal"] = (d["firms_op_yoy"] <= firms_thr) \
        .astype("boolean").where(d["firms_op_yoy"].notna())

    op = (d["op_rate_yoy"] <= op_rate_thr).astype("boolean").where(d["op_rate_yoy"].notna())
    out["operating_rate_decline_signal"] = op

    # PPI 조정 생산: 단일값이 있는 A/B 등급에서만 단정한다. C 는 밴드, D 는 산출 없음.
    adj = d["ppi_adjusted_production_yoy"]
    usable = adj.notna() & d["ppi_mapping_grade"].isin(["A", "B"])
    out["ppi_adjusted_production_decline_signal"] = (
        (adj <= real_prod_thr).astype("boolean").where(usable))
    band = d["ppi_mapping_grade"].eq("C") & d["ppi_adjusted_low"].notna()
    out["ppi_adjusted_production_decline_band"] = np.where(
        band,
        np.where(d["ppi_adjusted_high"] <= real_prod_thr, "후보 모두 위축",
                 np.where(d["ppi_adjusted_low"] <= real_prod_thr,
                          "후보에 따라 갈림 — 단정 보류", "후보 모두 위축 아님")),
        "")

    # 생산유지·고용감소: 생산은 명목·조정 중 확인 가능한 값으로 판단하되,
    # 조정값이 없으면 명목만으로 판단했다는 사실을 함께 남긴다.
    prod_basis = adj.where(usable, d["nominal_production_yoy"])
    out["production_maintained_employment_decline"] = (
        (prod_basis >= PROD_MAINTAINED) & (d["e_yoy"] <= EMP_DECLINE_FOR_PATTERN)
    ).astype("boolean").where(prod_basis.notna() & d["e_yoy"].notna())
    out["production_maintained_basis"] = np.where(
        usable, "PPI 조정 생산",
        np.where(d["nominal_production_yoy"].notna(), "명목 생산만(가격효과 미조정)", "판단 불가"))

    labels = [c for c in SIGNAL_LABELS if c in out.columns]
    out["signal_count"] = out[labels].sum(axis=1, skipna=True).astype("Int64")
    # 결측(<NA>)은 '신호 없음' 이 아니라 '판단 불가' 다. 프로필 문자열에서는
    # True 만 나열하고, 판단 불가 여부는 signal_input_incomplete 로 따로 전달한다.
    on = out[labels].fillna(False).astype(bool)
    out["signal_profile"] = on.apply(
        lambda r: " · ".join(SIGNAL_LABELS[c] for c in labels if r[c]) or NO_SIGNAL, axis=1)
    out["representative_signal"] = on.apply(
        lambda r: next((SIGNAL_LABELS[c] for c in REPRESENTATIVE_ORDER
                        if c in labels and r[c]), NO_SIGNAL), axis=1)
    out["representative_signal_note"] = np.where(
        out["signal_count"].fillna(0) > 1,
        "대표 확인신호는 표시순서에 따른 요약이며, 유일한 원인이 아니다. "
        "확인신호 프로필 전체를 함께 읽어야 한다.", "")
    out["signal_input_incomplete"] = out[labels].isna().any(axis=1)
    return out


def sensitivity(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """경계를 흔들었을 때 신호 flag 가 몇 행에서 달라지는지.

    반환: (행 단위 상세, 요약). 좋은 경계를 고르기 위한 표가 아니다.
    """
    base_kwargs = dict(firms_thr=FIRMS_OP_DECLINE, op_rate_thr=OP_RATE_DECLINE,
                       real_prod_thr=REAL_PROD_DECLINE)
    base = compute_signals(d, **base_kwargs)
    arg_of = {"firms_op_decline_signal": "firms_thr",
              "operating_rate_decline_signal": "op_rate_thr",
              "ppi_adjusted_production_decline_signal": "real_prod_thr"}
    rows, detail = [], []
    for signal, grid in SENSITIVITY_GRID.items():
        for thr in grid:
            kw = dict(base_kwargs)
            kw[arg_of[signal]] = thr
            alt = compute_signals(d, **kw)
            changed = alt[signal].ne(base[signal]) & (alt[signal].notna() | base[signal].notna())
            n_true_base = int(base[signal].fillna(False).sum())
            n_true_alt = int(alt[signal].fillna(False).sum())
            sub = d.loc[changed, ["industry", "quarter", "employment", "firms_op"]].copy()
            sub["signal"] = signal
            sub["baseline_threshold"] = base_kwargs[arg_of[signal]]
            sub["alternative_threshold"] = thr
            sub["baseline_value"] = base.loc[changed, signal].astype("object").values
            sub["alternative_value"] = alt.loc[changed, signal].astype("object").values
            detail.append(sub)
            by_ind = d.loc[changed, "industry"].value_counts()
            small = d.loc[changed, "employment"].lt(300).sum()
            rows.append(dict(
                signal=signal, signal_label=SIGNAL_LABELS[signal],
                baseline_threshold=base_kwargs[arg_of[signal]], alternative_threshold=thr,
                n_true_baseline=n_true_base, n_true_alternative=n_true_alt,
                n_rows_changed=int(changed.sum()),
                pct_rows_changed=round(float(changed.mean()) * 100, 2),
                n_industries_changed=int(by_ind.size),
                top_industry=by_ind.index[0] if by_ind.size else "",
                top_industry_rows=int(by_ind.iloc[0]) if by_ind.size else 0,
                changed_rows_in_small_industries=int(small),
                small_industry_share_pct=(round(float(small) / int(changed.sum()) * 100, 1)
                                          if changed.sum() else np.nan)))
    detail_df = (pd.concat(detail, ignore_index=True) if detail
                 else pd.DataFrame(columns=["industry", "quarter", "signal"]))
    return detail_df, pd.DataFrame(rows)
