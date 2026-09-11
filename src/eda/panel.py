# -*- coding: utf-8 -*-
"""Section 0 — 공통 분석 기준·데이터 적재·검산.

notebooks/02_eda.ipynb Section 0(셀 2·4·6·7·8·10)의 계산을 그대로 옮겼다.
국면 분류, YoY 검산, 가산성 검증, 제조업 전체 집계 기준은 노트북과 동일하다.
"""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------- 데이터 적재
def load_panels(dir_proc):
    """본분석 패널(state)과 산단 전체 총계(total)를 읽는다."""
    dir_proc = Path(dir_proc)
    state = pd.read_csv(dir_proc / 'kicox' / 'changwon_state_panel.csv')
    total = pd.read_csv(dir_proc / 'kicox' / 'changwon_total_master.csv')
    state.columns = [c.lstrip('﻿') for c in state.columns]
    total.columns = [c.lstrip('﻿') for c in total.columns]
    state = state.sort_values(['industry', 'quarter_index']).reset_index(drop=True)
    return state, total


# ---------------------------------------------------------------- 공통 기준(고정)
@dataclass
class PanelContext:
    """노트북 Section 0이 만드는 공통 기준값 묶음.

    노트북에서는 QUARTERS·LATEST·PREV·BASE_Q·INDUSTRIES·INVALID_QUARTERS·
    THRESHOLD·IND_ORDER_EMP 라는 전역 이름으로 쓰인다.
    """
    quarters: list
    latest: str
    prev: str
    base_q: str
    industries: list
    invalid_quarters: list
    threshold: float
    ind_order_emp: list = field(default_factory=list)


def build_context(state):
    """분석기간·최신분기·업종 정렬 등 노트북의 공통 기준을 계산한다."""
    quarters = sorted(state.quarter.unique())          # 분석기간: 본분석 패널 그대로
    latest = quarters[-1]                              # 최신분기(현재 국면 판정 기준)
    prev = quarters[-2]                                # 직전분기
    base_q = str(pd.Period(latest, freq='Q') - 4)      # 최신분기의 전년동기(YoY 비교 기준분기)
    industries = sorted(state.industry.unique())       # 업종 정의: 전처리 산출물 그대로
    invalid_quarters = sorted(state.loc[state.state == 'INVALID', 'quarter'].unique())
    threshold = state.threshold.iloc[0]                # 중립구간 기준(본분석 = 0)
    # 최신분기 고용비중 내림차순 — 모든 그림·표의 기본 업종 정렬 기준
    ind_order_emp = (state[state.quarter == latest]
                     .sort_values('employment', ascending=False).industry.tolist())
    return PanelContext(quarters=quarters, latest=latest, prev=prev, base_q=base_q,
                        industries=industries, invalid_quarters=invalid_quarters,
                        threshold=threshold, ind_order_emp=ind_order_emp)


# ---------------------------------------------------------------- 표현용 집계
def add_display_columns(state):
    """고용 증감 '인원' 등 표현용 파생변수를 붙인다(입력 프레임을 제자리에서 수정).

    고용 증감 인원은 01 산출물에 없어 여기서 파생한다. employment_yoy(01 산출물)와
    동일한 lag4 정의를 쓰며, 기간 절단 전 확보된 전년동기 값을 사용한다.
    """
    state['employment_lag4_lvl'] = state.employment_lag4
    state['emp_delta'] = state.employment - state.employment_lag4_lvl
    state['production_lag4_lvl'] = state.production_lag4
    return state


def manufacturing_totals(state, ctx, share_min_ratio=config.SHARE_MIN_RATIO):
    """제조업 전체(= 패널의 업종 합계) 고용 순변화·총변화 집계를 만든다."""
    mfg = (state.groupby('quarter')
           .agg(mfg_employment=('employment', 'sum'),
                mfg_emp_delta=('emp_delta', 'sum'),
                mfg_emp_gross=('emp_delta', lambda s: s.abs().sum()),
                n_delta=('emp_delta', 'count'))
           .reindex(ctx.quarters))
    mfg.loc[mfg.n_delta < len(ctx.industries), ['mfg_emp_delta', 'mfg_emp_gross']] = np.nan
    # 순변화/총변화 비율 = |순증감| / |업종별 증감|합. 1에 가까우면 같은 방향, 0에 가까우면 상쇄가 크다.
    mfg['net_gross_ratio'] = mfg.mfg_emp_delta.abs() / mfg.mfg_emp_gross
    # 기여율(%)은 분모(순증감)가 작으면 값이 과도해지므로 아래 기준을 넘는 분기에만 사용한다.
    mfg['contrib_usable'] = mfg.net_gross_ratio >= share_min_ratio
    return mfg


# ---------------------------------------------------------------- 국면 분류
def classify(p, e, threshold=0):
    """생산·고용 YoY 한 쌍을 국면으로 분류한다(본분석 정의)."""
    if pd.isna(p) or pd.isna(e):
        return 'INVALID'
    if abs(p) <= threshold or abs(e) <= threshold:
        return 'N'
    return {(True, True): 'S1', (True, False): 'S2',
            (False, True): 'S3', (False, False): 'S4'}[(p > 0, e > 0)]


# ---------------------------------------------------------------- 검산
def verify_panel(state, ctx, states4=config.STATES4, states5=config.STATES5):
    """달력 분기·YoY·국면·연속기간·인접 전환의 계산 일관성을 확인한다."""
    assert not state.duplicated(['industry', 'quarter']).any(), '업종×분기 중복'
    assert len(ctx.quarters) == len(pd.period_range(ctx.quarters[0], ctx.latest, freq='Q')), '분기 누락'
    assert state.groupby('industry').size().eq(len(ctx.quarters)).all(), '불균형 패널'
    assert state.threshold.nunique() == 1 and ctx.threshold == 0, '본분석 중립기준 확인 필요'

    for variable in ['production', 'employment']:
        calc = (state[variable] / state[f'{variable}_lag4'] - 1) * 100
        calc = calc.where(state[f'{variable}_lag4'].ne(0))
        assert np.allclose(calc, state[f'{variable}_yoy'], equal_nan=True), f'{variable} YoY 불일치'
    assert all(classify(r.production_yoy, r.employment_yoy) == r.state
               for r in state.itertuples()), '국면 불일치'
    for ind, g in state.groupby('industry'):
        g = g.sort_values('quarter_index').reset_index(drop=True)
        expected_next = g.state.shift(-1)
        valid_next = g.state.isin(states5) & expected_next.isin(states5)
        assert np.array_equal(valid_next, g.valid_transition5), f'{ind}: 인접 전환 불일치'
        assert g.loc[valid_next, 'next_state'].eq(expected_next[valid_next]).all()
        start = 0
        for j in range(len(g)):
            if j == 0 or g.state[j] != g.state[j - 1]:
                start = j
            if g.state[j] in states4:
                assert g.run_length[j] == j - start + 1, f'{ind}: 연속분기 불일치'
        for _, block in g[g.state.isin(states4)].groupby('run_id'):
            assert block.run_total_length.eq(len(block)).all(), f'{ind}: 총 지속길이 불일치'
    return '검산: 달력 분기, YoY, 국면, 연속기간, 인접 전환 일치'


def state_counts(state, states6=config.STATES6):
    """국면별 관측 수."""
    return state.state.value_counts().reindex(states6, fill_value=0).rename('관측 수').to_frame()


def missing_summary(state):
    """계산 불가(INVALID) 사유를 당분기 / 전년동기로 구분한다."""
    return state.loc[state.state.eq('INVALID')].groupby('quarter').agg(
        관측수=('industry', 'size'), 당분기생산결측=('production_current_missing', 'sum'),
        전년동기생산결측=('production_lag4_missing', 'sum'))


# ---------------------------------------------------------------- 가산성 검증
def additivity_check(state, total, mfg, ctx):
    """10개 업종 합계와 산단 전체 총계의 차이, 고용 증감 항등식을 확인한다.

    Returns
    -------
    chk : DataFrame          분기별 생산·고용 잔차
    lag_mfg : Series         업종별 전년동기 고용의 분기 합계
    summary : dict           results_summary['additivity']에 들어가는 값
    """
    agg = state.groupby('quarter')[['production', 'employment']].sum(min_count=1).reindex(ctx.quarters)
    chk = agg.join(total.set_index('quarter')[['production_total', 'employment_total']])
    chk['생산_잔차'] = chk.production - chk.production_total
    chk['고용_잔차'] = chk.employment - chk.employment_total
    chk['고용_잔차_비율%'] = chk.고용_잔차 / chk.employment_total * 100
    lag_mfg = (state.groupby('quarter').employment_lag4
               .sum(min_count=len(ctx.industries)).reindex(ctx.quarters))
    gap = (mfg.mfg_emp_delta - (agg.employment - lag_mfg)).abs().max()
    assert gap < 1e-6, '제조업 전체와 업종별 고용 증감 합 불일치'
    summary = {'production_max_abs_gap': float(chk.생산_잔차.abs().max()),
               'employment_gap_latest': float(chk.loc[ctx.latest, '고용_잔차']),
               'delta_identity_gap': float(gap)}
    return chk, lag_mfg, summary


# ---------------------------------------------------------------- 자료 개정 점검
def verification_scope(root, dir_proc):
    """보조 산출물의 존재 여부만 확인한다(원자료 재현 검증과 구분)."""
    root = Path(root)
    optional_files = [
        root / 'outputs/tables/vintage_수정폭_실측.csv',
        root / 'outputs/tables/창원상의_교차검증.csv',
        root / 'outputs/tables/결측보완_2023Q4_2024Q4_국면.csv',
        Path(dir_proc) / 'kicox/changwon_state_gapfill_panel.csv',
    ]
    return pd.DataFrame([
        {
            '파일': str(p.relative_to(root)),
            '존재': p.is_file(),
            '이번 노트북의 처리': ('참고자료 존재 — 원자료 재현 검증과 구분'
                             if p.is_file() else '파일 없음 — 검증 범위에서 제외'),
        }
        for p in optional_files
    ])


def source_versions(state):
    """사용한 생산·고용 출처의 분기별 조합."""
    return state.groupby('quarter')[['production_source', 'employment_source']].first()


# ---------------------------------------------------------------- 경로 문자열·출처 기록
def state_path(state, ind, n=6, sep=' → '):
    """업종별 최근 n분기 국면 경로 문자열(INVALID 포함, 관측 순서 그대로)."""
    g = state[state.industry == ind].sort_values('quarter_index').tail(n)
    return sep.join(g.state.tolist())


def make_input_recorder(root):
    """입력 파일의 경로·역할·해시를 모으는 기록기(input_audit, record_input)를 만든다."""
    root = Path(root)
    input_audit = []

    def record_input(path, role):
        path = Path(path)
        input_audit.append({'path': str(path.relative_to(root)), 'role': role,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    return input_audit, record_input
