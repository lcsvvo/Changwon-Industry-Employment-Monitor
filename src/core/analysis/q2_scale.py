# -*- coding: utf-8 -*-
"""Section 3 — Q2 규모(최신분기 고용 증감 인원·비중, 분기별 변화 구성, 상세표시 업종 선정).

notebooks/02_eda.ipynb 셀 41·42·43의 계산을 그대로 옮겼다.
상세표시 대상 선정 기준(SHARE_CUT, ABS_CUT)은 기존 표시 기준을 유지한 것이며
정책 우선순위 또는 통계적으로 검증된 경계가 아니다.
"""
import pandas as pd

from . import config


# ---------------------------------------------------------------- Q2-A. 최신분기 규모
def latest_scale(state, mfg, ctx):
    """최신분기 업종별 고용·증감인원·증감률·비중·국면(증감인원 오름차순).

    Returns
    -------
    q2 : DataFrame
    net : float      제조업 전체 순증감
    ratio : float    순변화/총변화 비율
    usable : bool    기여율 표시 가능 여부
    """
    d = state[state.quarter == ctx.latest].set_index('industry')
    q2 = pd.DataFrame({
        '고용': d.employment,
        '고용_전년': d.employment_lag4_lvl,
        '증감인원': d.emp_delta,
        '증감률%': d.employment_yoy,
        '고용비중%': d.employment / d.employment.sum() * 100,
        '국면': d.state,
    }).sort_values('증감인원')
    net = q2.증감인원.sum()
    ratio = mfg.loc[ctx.latest, 'net_gross_ratio']
    usable = bool(mfg.loc[ctx.latest, 'contrib_usable'])
    if usable:
        q2['기여율%'] = q2.증감인원 / net * 100
    return q2, net, ratio, usable


# ---------------------------------------------------------------- Q2-B. 분기별 구성
def quarterly_composition(state, ctx, main_cand_n=config.MAIN_CAND_N):
    """분기별 제조업 전체 고용 변화의 업종 구성(상위 업종 + 나머지 합).

    Returns
    -------
    plot_df : DataFrame   index=분기, columns=상위 업종 + '나머지 n개 업종 합'
    qs : list             emp_delta가 있는 분기
    main_cand, rest : list
    """
    main_cand = ctx.ind_order_emp[:main_cand_n]
    rest = [i for i in ctx.ind_order_emp if i not in main_cand]

    dd = state.dropna(subset=['emp_delta'])
    qs = [q for q in ctx.quarters if q in set(dd.quarter)]
    piv = dd.pivot_table(index='quarter', columns='industry', values='emp_delta').reindex(qs)
    plot_df = piv[main_cand].copy()
    plot_df[f'나머지 {len(rest)}개 업종 합'] = piv[rest].sum(axis=1)
    return plot_df, qs, main_cand, rest


# ---------------------------------------------------------------- 상세표시 업종 선정
def scale_summary(state, q2, ctx, share_cut=config.SHARE_CUT, abs_cut=config.ABS_CUT,
                  recent_n=config.RECENT_N):
    """최근 4분기 집계를 붙인 규모 요약표와 상세표시 대상 업종.

    Returns
    -------
    summary : DataFrame
    main_ind : list   상세 경로를 표시할 업종
    recent4 : list    최근 4분기
    """
    recent4 = ctx.quarters[-recent_n:]
    rec_state = state[state.quarter.isin(recent4)]
    rec = rec_state.groupby('industry').emp_delta.agg(
        최근4분기_평균고용_전년대비증감=lambda s: s.sum(min_count=len(recent4)) / len(recent4),
        최근4분기_YoY증감절대합=lambda s: s.abs().sum())
    # 네 분기 YoY 증감의 합을 분기 수로 나누면 '최근 4분기 평균 고용 - 그 이전 4분기 평균 고용'과 같다.
    # 기간 순증감(최신분기 - 4분기 전)과는 다른 값이다. 절대합은 상세표시 대상을 고르는 변화 크기 지표일 뿐이다.
    rec['최근4분기_기간순증감'] = q2.증감인원
    summary = pd.DataFrame({'고용비중%': q2['고용비중%'], f'{ctx.latest}_증감인원': q2.증감인원,
                            f'{ctx.latest}_증감률%': q2['증감률%'],
                            f'{ctx.latest}_국면': q2.국면}).join(rec).reindex(ctx.ind_order_emp)
    c1 = summary['고용비중%'] >= share_cut
    c2 = summary['최근4분기_YoY증감절대합'] >= abs_cut
    main_ind = [i for i in ctx.ind_order_emp if c1[i] and c2[i]]
    summary['상세표시대상'] = c1 & c2
    if '초과증감' in q2:
        summary = summary.join(q2[['비례기대증감', '초과증감']])
    return summary, main_ind, recent4


# ---------------------------------------------------------------- Q2-C. 비례배분 기준선
def baseline_comparison(q2):
    """규모를 통제한 비교 — 비례배분 기준선 대비 초과 증감 컬럼을 붙인 q2를 돌려준다.

    기준선(비례기대증감) = 기준분기(전년동기) 고용비중 x 제조업 전체 순증감.
    당분기 비중을 쓰면 결과가 분모에 다시 들어가므로 기준분기 비중을 쓴다.
    기준선은 '모든 업종이 같은 비율로 변했다면'이라는 가정의 비교값이며 원인을 뜻하지 않는다.
    scale_summary()보다 먼저 호출해야 요약표에 두 컬럼이 들어간다.
    """
    out = q2.copy()
    out['비례기대증감'] = out.고용_전년 / out.고용_전년.sum() * out.증감인원.sum()
    out['초과증감'] = out.증감인원 - out.비례기대증감
    return out


def q2_results(q2, summary, main_ind, net, ratio, usable, ctx,
               share_cut=config.SHARE_CUT, abs_cut=config.ABS_CUT):
    """results_summary['q2']에 들어가는 값."""
    out = {
        'quarter': ctx.latest, 'employment': float(q2.고용.sum()), 'net_delta': float(net),
        'net_yoy_pct': float(net / q2.고용_전년.sum() * 100), 'ratio': float(ratio),
        'contrib_usable': usable,
        'largest_decrease_industries': q2.index[q2.증감인원.eq(q2.증감인원.min())
                                                & q2.증감인원.lt(0)].tolist(),
        'min_delta': float(q2.증감인원.min()), 'main_industries': main_ind,
        'main_share_pct': float(summary.loc[main_ind, '고용비중%'].sum()),
        'selection_share_cut': share_cut, 'selection_abs_cut': abs_cut}
    if '초과증감' in q2:
        out.update({
            'baseline_max_excess_decrease_industry': q2.초과증감.idxmin(),
            'baseline_max_excess_decrease': float(q2.초과증감.min()),
            'baseline_excess': {i: float(q2.loc[i, '초과증감']) for i in ctx.ind_order_emp}})
    return out
