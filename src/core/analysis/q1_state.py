# -*- coding: utf-8 -*-
"""Section 2 — Q1 상태(최신분기 국면, 업종×분기 국면 분포, 방향 비교, threshold 민감도).

notebooks/02_eda.ipynb 셀 34·36·37·39의 계산을 그대로 옮겼다.
국면 정의와 중립구간(threshold=0)은 본분석 패널을 따르며 여기서 다시 만들지 않는다.
"""
import pandas as pd

from . import config
from .panel import classify


# ---------------------------------------------------------------- Q1-A. 최신분기 국면
def latest_quadrant(state, ctx):
    """최신분기의 유효 관측만 남긴 업종별 프레임(고용비중 내림차순)."""
    q = state[(state.quarter == ctx.latest) & state.valid_state].set_index('industry')
    return q.reindex([i for i in ctx.ind_order_emp if i in q.index])


def latest_state_summary(state, ctx):
    """최신분기 고용 감소 업종 중 명목 생산액이 증가한 업종과 그 고용비중.

    Returns
    -------
    d : DataFrame    최신분기 전체 업종(INVALID 포함)
    dn : DataFrame   고용 감소 & 유효 관측
    up : DataFrame   그중 생산 증가
    summary : dict   results_summary['q1_latest']
    """
    d = state[state.quarter == ctx.latest].set_index('industry').reindex(ctx.ind_order_emp)
    dn = d[(d.employment_yoy < 0) & d.valid_state]
    up = dn[dn.production_yoy > 0]
    summary = {'quarter': ctx.latest, 'n_down': len(dn), 'n_nominal_up': len(up),
               'nominal_up_industries': list(up.index),
               'employment_denominator': float(d.employment.sum()),
               'nominal_employment_numerator': float(up.employment.sum()),
               'nominal_employment_share_pct': float(up.employment.sum() / d.employment.sum() * 100)}
    return d, dn, up, summary


# ---------------------------------------------------------------- Q1-B. 업종×분기 국면 분포
def state_grid(state, ctx, states5=config.STATES5):
    """국면 격자(pivot)와 업종별 국면 구성비.

    INVALID는 전 업종 공통이라 정보가 없어 구성비에서 제외하고 유효 분기 기준으로 정규화한다.
    """
    pivot = state.pivot(index='industry', columns='quarter', values='state').reindex(
        index=ctx.ind_order_emp, columns=ctx.quarters)
    valid = state[state.state != 'INVALID']
    comp = (pd.crosstab(valid.industry, valid.state, normalize='index')
            .reindex(index=ctx.ind_order_emp).reindex(columns=states5, fill_value=0))
    return pivot, comp


# ---------------------------------------------------------------- 전체기간 방향 비교
def history_stats(state, ctx, top_n=config.EDA_TOP_SHARE_N):
    """전체 관측기간 고용 감소 관측 중 명목 생산액이 증가한 비율.

    Returns
    -------
    emp_down : DataFrame   고용 감소 & 유효 관측
    t4 : DataFrame         그중 고용 상위 업종 관측
    summary : dict         results_summary['q1_history']
    """
    emp_down = state[(state.employment_yoy < 0) & state.valid_state]
    simple_pct = (emp_down.production_yoy > 0).mean()
    weighted_pct = ((emp_down.production_yoy > 0) * emp_down.employment).sum() / emp_down.employment.sum()
    t4 = emp_down[emp_down.industry.isin(ctx.ind_order_emp[:top_n])]
    summary = {
        'n_down': len(emp_down),
        'n_up_down': int((emp_down.production_yoy > 0).sum()),
        'simple_pct': float(simple_pct * 100),
        'weighted_pct': float(weighted_pct * 100),
    }
    return emp_down, t4, summary


# ---------------------------------------------------------------- threshold 민감도
def threshold_sensitivity(state, thresholds=None, states6=config.STATES6):
    """중립구간만 변경한 보조집계. 본분석 국면은 유지한다."""
    thresholds = config.SENSITIVITY_THRESHOLDS if thresholds is None else thresholds
    rows = []
    for threshold in thresholds:
        values = [classify(r.production_yoy, r.employment_yoy, threshold) for r in state.itertuples()]
        counts = pd.Series(values).value_counts().reindex(states6, fill_value=0)
        rows.append({'threshold': threshold, **counts.to_dict()})
    return pd.DataFrame(rows).set_index('threshold')
