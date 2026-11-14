# -*- coding: utf-8 -*-
"""Section 4 — Q3 시간(현재 국면 지속기간, 최장 관측 지속기간, 인접 국면 전환).

notebooks/02_eda.ipynb 셀 47·48·49의 계산을 그대로 옮겼다.
지속기간은 전처리 정의대로 S1~S4만 집계하고, 인접 전환표에는 N도 포함한다.
결측 구간을 연결하지 않으며 censoring(좌·우 절단) 표시를 유지한다.
"""
import pandas as pd

from . import config


# ---------------------------------------------------------------- Q3-B. 현재 국면 지속기간
def current_runs(state, ctx):
    """최신분기 기준 업종별 현재 국면·연속분기 수(지속 길이 → 고용비중 내림차순)."""
    cur = state[state.quarter == ctx.latest].set_index('industry').reindex(ctx.ind_order_emp)
    sort_key = pd.DataFrame({'_sort': cur.run_length.fillna(-1),
                             '_share': cur.employment / cur.employment.sum()})
    return cur.loc[sort_key.sort_values(['_sort', '_share'], ascending=[False, False]).index]


# ---------------------------------------------------------------- Q3-C. 최장 관측 지속기간
def longest_runs(state, ctx):
    """S1~S4 연속구간(run) 목록과 업종별 최장 관측 지속기간.

    Returns
    -------
    runs : DataFrame      업종×run 단위 (중복 제거)
    longest : DataFrame   업종별 최장 run
    share2plus : float    2분기 이상 run의 비율(%)
    """
    runs = state.dropna(subset=['run_id']).drop_duplicates(['industry', 'run_id'])
    share2plus = (runs.run_total_length >= 2).mean() * 100
    longest = (runs.sort_values('run_total_length', ascending=False)
               .drop_duplicates('industry').set_index('industry')
               [['state', 'state_start_quarter', 'run_total_length',
                 'run_left_censored', 'run_right_censored']]
               .reindex(ctx.ind_order_emp)
               .rename(columns={'state': '국면', 'state_start_quarter': '시작분기',
                                'run_total_length': '지속분기',
                                'run_left_censored': '좌절단', 'run_right_censored': '우절단'}))
    longest['경계절단'] = longest.좌절단.eq(True) | longest.우절단.eq(True)
    return runs, longest, share2plus


def valid_blocks(state):
    """연속 판정이 가능한 구간(INVALID로 끊기지 않는 분기 블록)의 길이.

    최장 관측값이 블록 길이와 같으면 관측 구간 경계에 막힌 것이므로 실제 길이는 확정할 수 없다.

    Returns
    -------
    blocks : list | dict   전 업종 공통이면 블록 길이 목록, 다르면 업종별 dict
    max_observable : int   관측할 수 있는 최장 지속(분기)
    """
    per_industry = {}
    for ind, g in state.groupby('industry'):
        lengths, run = [], 0
        for s in g.sort_values('quarter_index').state:
            if s == 'INVALID':
                if run:
                    lengths.append(run)
                run = 0
            else:
                run += 1
        if run:
            lengths.append(run)
        per_industry[ind] = lengths
    unique = {tuple(v) for v in per_industry.values()}
    blocks = list(next(iter(unique))) if len(unique) == 1 else per_industry
    return blocks, int(max(max(v) for v in per_industry.values()))


def low_n_rows(row_n, min_row_n=config.TRANSITION_MIN_ROW_N, states5=config.STATES5):
    """행 관측이 min_row_n보다 적어 비율을 표시하지 않는 전환행렬 행."""
    return [s for s in states5 if row_n[s] < min_row_n]


# ---------------------------------------------------------------- Q3-C. 전환행렬
def transition_matrix(state, states5=config.STATES5):
    """인접 분기 국면 전환 건수와 행 기준 비율.

    Returns
    -------
    trans : DataFrame   valid_transition5 관측
    mat : DataFrame     전환 건수
    mat_pct : DataFrame 행 기준 비율(%)
    row_n : Series      행별 관측 수
    diag : int          같은 국면 유지 건수
    """
    trans = state[state.valid_transition5 == True]   # noqa: E712
    mat = pd.crosstab(trans.state, trans.next_state).reindex(index=states5, columns=states5,
                                                             fill_value=0)
    row_n = mat.sum(axis=1)
    mat_pct = mat.div(row_n, axis=0).fillna(0) * 100
    diag = sum(mat.loc[s, s] for s in states5)
    return trans, mat, mat_pct, row_n, diag


def q3_results(runs, share2plus, trans, diag, cur, longest=None, blocks=None,
               max_observable=None, low_rows=None, min_row_n=config.TRANSITION_MIN_ROW_N):
    """results_summary['q3']에 들어가는 값."""
    extra = {}
    if max_observable is not None:
        extra = {'transition_min_row_n': min_row_n, 'transition_low_n_rows': low_rows or [],
                 'valid_block_lengths': blocks, 'max_observable_run': max_observable,
                 'max_run_at_ceiling': bool(runs.run_total_length.max() == max_observable),
                 'n_longest_censored': int(longest.경계절단.sum()) if longest is not None else None}
    return {
        'n_runs': len(runs), 'n_runs_2plus': int((runs.run_total_length >= 2).sum()),
        'share_2plus_pct': float(share2plus), 'mean_run': float(runs.run_total_length.mean()),
        'max_run': int(runs.run_total_length.max()), 'n_adjacent': len(trans), 'n_same': int(diag),
        'same_pct': float(diag / len(trans) * 100),
        **extra,
        'current': [
            {'industry': i, 'state': r.state,
             'length': None if pd.isna(r.run_length) else int(r.run_length)}
            for i, r in cur.iterrows()]}
