# -*- coding: utf-8 -*-
"""Section 5 — 보조분석(가동률·업체수·업체당 고용·고용증감 산술분해).

notebooks/02_eda.ipynb 셀 52·53의 계산을 그대로 옮겼다.
분해는 E = F x (E/F)의 산술 분해이며 기업동학(진입·퇴출·채용·감원) 분석이 아니다.
"""
import numpy as np
import pandas as pd


# ---------------------------------------------------------------- 가동률
def op_rate_frame(state):
    """가동률(공표값)이 있는 관측만 남긴 프레임과 그 분기 목록."""
    op = state[state.op_rate_official.notna()]
    return op, sorted(op.quarter.unique())


def op_rate_yoy_scope(state):
    """가동률 전년동기 차이를 계산할 수 있는 관측 범위."""
    return state[state.op_rate_official_yoy_pp.notna()]


# ---------------------------------------------------------------- 고용 증감 산술분해
def firm_decomposition(state, ctx, main_ind):
    """E = F x (E/F)의 산술 분해. 실제 기업별 고용 흐름 분해가 아니다.

    Returns
    -------
    margin : DataFrame   고용증감·업체수·업체당 인원과 세 분해항
    parts : DataFrame    업체수변화항 / 평균인원변화항 / 교차항
    """
    m = state[state.quarter == ctx.latest].set_index('industry').reindex(main_ind)
    b = pd.DataFrame({'employment': m.employment_lag4, 'firms_op': m.firms_op_lag4})
    epf_b = b.employment / b.firms_op.replace(0, np.nan)
    epf_m = m.employment / m.firms_op.replace(0, np.nan)
    margin = pd.DataFrame({'고용증감': m.emp_delta, '가동업체_전년': b.firms_op,
                           '가동업체_당분기': m.firms_op, '업체당_전년': epf_b,
                           '업체당_당분기': epf_m})
    margin['업체수증감'] = m.firms_op - b.firms_op
    margin['업체수변화항'] = margin.업체수증감 * epf_b
    margin['평균인원변화항'] = b.firms_op * (epf_m - epf_b)
    margin['교차항'] = margin.업체수증감 * (epf_m - epf_b)
    assert np.allclose(margin[['업체수변화항', '평균인원변화항', '교차항']].sum(axis=1), margin.고용증감)
    parts = margin[['업체수변화항', '평균인원변화항', '교차항']]
    return margin, parts


# ---------------------------------------------------------------- 보조지표 표
def aux_table(state, ctx):
    """최신분기 업종별 가동률·업체수 보조지표 표.

    가동률과 가동업체/입주업체 비율은 서로 다른 지표다.
    """
    aux = state[state.quarter == ctx.latest].set_index('industry').reindex(ctx.ind_order_emp)
    return pd.DataFrame({'국면': aux.state, '가동률%': aux.op_rate_official,
                         '가동률YoY(%p)': aux.op_rate_official_yoy_pp, '입주업체': aux.firms_in,
                         '입주YoY%': aux.firms_in_yoy, '가동업체': aux.firms_op,
                         '가동YoY%': aux.firms_op_yoy, '가동업체비율': aux.active_firm_ratio})
