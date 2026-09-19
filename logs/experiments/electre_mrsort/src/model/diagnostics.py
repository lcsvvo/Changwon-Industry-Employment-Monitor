# -*- coding: utf-8 -*-
"""파라미터 없이 산출하는 기준 중복성 진단.

상관계수는 기술통계이며 원인이나 기준 중복을 확정하지 않는다.
g4는 본분석 delta_emp가 등록되지 않았으므로 δ=0.0 민감도 컬럼(g4_delta00)을 사용하고 그 사실을 기록한다.
"""
import itertools

import pandas as pd

from . import config

G = config.CRITERION_COLUMNS
REDUNDANCY_COLUMNS = {'g1': G['g1'], 'g2': G['g2'], 'g3': G['g3'], 'g4': 'g4_delta00'}
DEFINITIONS = {
    'g1': f"{config.CRITERION_LABELS['g1']} = max(0, employment_lag4 - employment)",
    'g2': f"{config.CRITERION_LABELS['g2']} = max(0, -employment_yoy)",
    'g3': f"{config.CRITERION_LABELS['g3']} = max(0, -production_yoy)",
    'g4': (f"{config.CRITERION_LABELS['g4']}(δ=0.0 민감도 컬럼 g4_delta00): employment_yoy < 0이면 직전 값+1, "
           '아니면 0; 결측이면 NA'),
}
METHODS = ('pearson', 'spearman')


def _pair_rows(frame, pairs, scope, scope_description, n_pool, n_excluded_missing, n_excluded_scope):
    rows = []
    for x, y in pairs:
        for method in METHODS:
            sub = frame[[REDUNDANCY_COLUMNS[x], REDUNDANCY_COLUMNS[y]]]
            a, b = sub.iloc[:, 0], sub.iloc[:, 1]
            if method == 'spearman':
                # Spearman = 평균 순위(동점 평균)의 Pearson 상관. scipy에 의존하지 않는다.
                a, b = a.rank(method='average'), b.rank(method='average')
            value = a.corr(b, method='pearson') if len(sub) >= 2 else float('nan')
            rows.append({
                'scope': scope, 'scope_description': scope_description,
                'criterion_x': x, 'criterion_x_column': REDUNDANCY_COLUMNS[x], 'criterion_x_definition': DEFINITIONS[x],
                'criterion_y': y, 'criterion_y_column': REDUNDANCY_COLUMNS[y], 'criterion_y_definition': DEFINITIONS[y],
                'method': method, 'correlation': value,
                'n_rows_pool': n_pool, 'n_rows_used': int(len(sub)),
                'n_rows_excluded_missing': n_excluded_missing, 'n_rows_excluded_by_scope': n_excluded_scope,
                'n_rows_x_zero': int((sub.iloc[:, 0] == 0).sum()), 'n_rows_y_zero': int((sub.iloc[:, 1] == 0).sum()),
                'interpretation_note': config.REDUNDANCY_NOTE,
            })
    return rows


def criteria_redundancy(panel):
    """완전관측 행의 g1~g4 상관과 고용감소 행(g1>0)의 g1·g2 상관."""
    cols = list(REDUNDANCY_COLUMNS.values())
    values = panel[cols].astype(float)
    complete = values.notna().all(axis=1)
    n_all = int(len(panel))
    rows = _pair_rows(values[complete], list(itertools.combinations(config.CRITERIA, 2)),
                      'complete_cases', 'g1~g4가 모두 계산되는 완전관측 행',
                      n_all, int((~complete).sum()), 0)

    decline_complete = complete & (values[G['g1']] > 0)
    rows += _pair_rows(values[decline_complete], [('g1', 'g2')], 'employment_decline_complete_cases',
                       '완전관측 행 중 고용감소 행(g1>0)', int(complete.sum()), 0,
                       int((complete & ~(values[G['g1']] > 0)).sum()))

    g12 = values[[G['g1'], G['g2']]].notna().all(axis=1)
    decline_all = g12 & (values[G['g1']] > 0)
    rows += _pair_rows(values[decline_all], [('g1', 'g2')], 'employment_decline_all_rows',
                       'g1·g2가 계산되는 전체 행 중 고용감소 행(g1>0), 생산 YoY 결측 행 포함',
                       n_all, int((~g12).sum()), int((g12 & ~(values[G['g1']] > 0)).sum()))
    return pd.DataFrame(rows)
