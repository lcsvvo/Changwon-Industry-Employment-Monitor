# -*- coding: utf-8 -*-
"""파생지표·품질 플래그 단위 테스트(합성자료).

실행
    pytest tests/test_model_derive.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import config, derive, ppi_aux  # noqa: E402


def make_panel(yoy, industry='A', start='2022Q1', quarters=None, **extra):
    quarters = quarters or [str(pd.Period(start, freq='Q') + i) for i in range(len(yoy))]
    frame = pd.DataFrame({'industry': industry, 'quarter': quarters,
                          'quarter_index': derive.calendar_ordinal(quarters),
                          'employment_yoy': np.asarray(yoy, dtype=float)})
    for key, value in extra.items():
        frame[key] = value
    return frame


def g4(panel, delta=0.0, window_n=None):
    window_n = window_n or panel['quarter'].nunique()
    latest = max(panel['quarter'], key=lambda q: pd.Period(q, freq='Q'))
    return derive.emp_yoy_below_run(panel, delta, window_n, latest)


def as_list(series):
    return [None if pd.isna(v) else v for v in series]


# ---------------------------------------------------------------- g4
def test_g4_counts_consecutive_below_and_resets_to_zero():
    out = g4(make_panel([-1, -2, 0, -3, -1]))
    assert as_list(out['run']) == [1, 2, 0, 1, 2]
    assert as_list(out['left_censored']) == [True, True, False, False, False]
    assert as_list(out['open_run']) == [False, False, False, True, True]
    assert not out['window_saturated'].any()


def test_g4_exact_zero_is_not_below_at_delta_zero():
    out = g4(make_panel([0.0, -0.1, -0.0]))
    assert as_list(out['run']) == [0, 1, 0]


def test_g4_uses_strict_threshold_minus_delta():
    panel = make_panel([-0.4, -0.6, -1.0, -1.2])
    assert as_list(g4(panel, 0.5)['run']) == [0, 1, 2, 3]
    assert as_list(g4(panel, 1.0)['run']) == [0, 0, 0, 1]


def test_g4_missing_yoy_is_na_and_resets_run():
    out = g4(make_panel([-1, np.nan, -1, -1]))
    assert as_list(out['run']) == [1, None, 1, 2]
    assert as_list(out['start_after_break']) == [False, None, True, True]
    assert as_list(out['left_censored']) == [True, None, False, False]


def test_g4_does_not_link_non_adjacent_calendar_quarters():
    panel = make_panel([-1, -1, -1, -1], quarters=['2022Q1', '2022Q2', '2022Q4', '2023Q1'])
    out = g4(panel, window_n=4)
    assert as_list(out['run']) == [1, 2, 1, 2]
    assert as_list(out['start_after_break']) == [False, False, True, True]


def test_g4_crosses_production_missing_quarters():
    base = make_panel([-1, -1, -1, -1, -1])
    with_missing = base.assign(production_yoy=[1.0, np.nan, np.nan, -2.0, 3.0],
                               state=['S2', 'INVALID', 'INVALID', 'S4', 'S2'])
    assert as_list(g4(with_missing)['run']) == as_list(g4(base)['run']) == [1, 2, 3, 4, 5]


def test_g4_window_saturation_open_and_left_censored():
    out = g4(make_panel([-1] * 6), window_n=6)
    assert int(out['run'].iloc[-1]) == 6
    assert bool(out['window_saturated'].iloc[-1]) and bool(out['left_censored'].iloc[-1])
    assert bool(out['open_run'].iloc[-1])


def test_g4_industries_are_independent():
    panel = pd.concat([make_panel([-1, -1, -1], industry='A'), make_panel([1, -1, -1], industry='B')],
                      ignore_index=True)
    out = g4(panel)
    assert as_list(out['run']) == [1, 2, 3, 0, 1, 2]
    assert as_list(out['left_censored']) == [True, True, True, False, False, False]


def test_g4_rejects_invalid_delta():
    with pytest.raises(ValueError):
        g4(make_panel([-1]), delta=-0.5)
    with pytest.raises(ValueError):
        g4(make_panel([-1]), delta=None)


# ---------------------------------------------------------------- g1~g3
def criteria_panel(**overrides):
    base = dict(employment=[100.0, 90.0, 110.0], employment_lag4=[100.0, 100.0, 100.0],
                employment_yoy=[-0.0, -10.0, 10.0], production_yoy=[-0.0, np.nan, -5.0])
    base.update(overrides)
    return pd.DataFrame(base)


def test_core_criteria_normalizes_negative_zero_and_keeps_missing():
    out = derive.core_criteria(criteria_panel())
    g1, g2, g3 = (out[config.CRITERION_COLUMNS[k]] for k in ('g1', 'g2', 'g3'))
    assert g1.tolist() == [0.0, 10.0, 0.0] and not np.signbit(g1).any()
    assert g2.tolist() == [0.0, 10.0, 0.0] and not np.signbit(g2).any()
    assert g3.iloc[0] == 0.0 and not np.signbit(g3.iloc[0])
    assert np.isnan(g3.iloc[1]), '생산 YoY 결측은 0이 아니라 NA여야 한다'
    assert g3.iloc[2] == 5.0


def test_core_criteria_stops_on_data_errors():
    with pytest.raises(ValueError):
        derive.core_criteria(criteria_panel(employment=[-1.0, 90.0, 110.0]))
    with pytest.raises(ValueError):
        derive.core_criteria(criteria_panel(employment_lag4=[0.0, 100.0, 100.0]))


def test_clean_negative_zero():
    out = derive.clean_negative_zero([-0.0, 0.0, np.nan, -1.5])
    assert not np.signbit(out[:2]).any() and np.isnan(out[2]) and out[3] == -1.5


# ---------------------------------------------------------------- threshold 플래그
def test_threshold_flags_follow_first_neutral_threshold():
    panel = pd.DataFrame({'production_yoy': [5, 0.3, 0.8, 1.5, 0, np.nan],
                          'employment_yoy': [5, 5, 5, -5, 5, 5]})
    flags = derive.threshold_quality_flags(panel)
    assert flags['threshold_flag'].tolist() == ['STABLE_2_0', 'SENSITIVE_0_5', 'SENSITIVE_1_0',
                                                'SENSITIVE_2_0', 'EXACT_ZERO', 'INVALID']
    assert flags['state_t0'].tolist() == ['S1', 'S1', 'S1', 'S2', 'N', 'INVALID']
    moves = derive.threshold_state_moves(flags)
    assert not moves['s_to_other_s'].any()


def test_threshold_flag_labels_match_spec():
    assert derive.threshold_flag_labels() == ['STABLE_2_0', 'SENSITIVE_0_5', 'SENSITIVE_1_0',
                                              'SENSITIVE_2_0', 'EXACT_ZERO', 'INVALID']


# ---------------------------------------------------------------- QoQ·업체 수
def test_qoq_and_firm_context_rules():
    panel = make_panel([-2, -1, -1, 3], quarters=['2022Q1', '2022Q2', '2022Q4', '2023Q1'],
                       employment=[100.0, 105.0, 104.0, 104.0], firms_op=[12.0, 10.0, 0.0, 9.0],
                       firms_op_lag4=[12.0, 11.0, 5.0, 9.0])
    out = derive.qoq_and_firm_context(panel)
    assert as_list(out['emp_qoq_delta']) == [None, 5.0, None, 0.0]
    assert not np.signbit(out['emp_qoq_delta'].iloc[3])
    assert as_list(out['qoq_recovery_while_yoy_below']) == [None, True, None, False]
    assert as_list(out['firm_count_delta_qoq']) == [None, -2.0, None, 9.0]
    assert as_list(out['firm_count_delta_yoy']) == [0.0, -1.0, -5.0, 0.0]
    assert as_list(out['firm_count_changed_yoy']) == [False, True, True, False]
    assert np.isnan(out['emp_per_firm'].iloc[2]), 'firms_op=0이면 업체당 고용은 NA'
    assert as_list(out['small_firm_count_flag']) == [False, True, True, True]
    assert out['small_firm_caution'].iloc[1] == config.SMALL_FIRM_CAUTION
    assert out['small_firm_caution'].iloc[0] == ''


# ---------------------------------------------------------------- 판정가능·결측 원인·잔여 범주
def test_status_fields_root_cause_propagation_and_residual():
    panel = pd.DataFrame({
        'industry': ['A', 'A', config.RESIDUAL_CATEGORIES[0]],
        'quarter': ['2023Q4', '2024Q4', '2025Q1'],
        'employment_yoy': [-1.0, -2.0, 3.0], 'production_yoy': [np.nan, np.nan, 2.0],
        'state': ['INVALID', 'INVALID', 'S1'],
        'production_current_missing': [True, False, False], 'production_lag4_missing': [False, True, False],
    })
    criteria = pd.DataFrame({config.CRITERION_COLUMNS['g1']: [1.0, 2.0, 0.0],
                             config.CRITERION_COLUMNS['g2']: [1.0, 2.0, 0.0],
                             config.CRITERION_COLUMNS['g3']: [np.nan, np.nan, 0.0]})
    out = derive.status_fields(panel, criteria)
    assert out['core_data_status'].tolist() == ['PROD_YOY_MISSING', 'PROD_YOY_MISSING', 'COMPLETE']
    assert out['scorable'].tolist() == [False, False, True]
    assert out['unscorable_root_cause'].tolist()[:2] == ['2023Q4_PRODUCTION_SOURCE_MISSING'] * 2
    assert as_list(out['unscorable_propagation']) == [None, 'LAG4_FROM_2023Q4_SOURCE_MISSING', None]
    assert out['q1_routing_status'].tolist() == ['DATA_REVIEW', 'DATA_REVIEW', 'ROUTABLE_S1']
    assert out['residual_category'].tolist() == [False, False, True]
    assert out['routeability_status'].iloc[2] == 'REQUIRES_DISAGGREGATION'


# ---------------------------------------------------------------- PPI
def test_ppi_adjustment_is_ratio_not_subtraction():
    adjusted = ppi_aux.adjusted_production_yoy([10.0], [5.0])[0]
    assert adjusted == pytest.approx((1.10 / 1.05 - 1) * 100)
    assert abs(adjusted - (10.0 - 5.0)) > 0.1


def test_ppi_direction_status_cases():
    assert ppi_aux.direction_status(5, [3, 1]) == 'SAME_ALL'
    assert ppi_aux.direction_status(5, [-3, -1]) == 'OPPOSITE_ALL'
    assert ppi_aux.direction_status(5, [-3, 1]) == 'CANDIDATE_DEPENDENT'
    assert ppi_aux.direction_status(5, [0, 1]) == 'ZERO_BOUNDARY'


def test_multiple_ppi_candidates_keep_state_set():
    """복수 후보가 서로 다른 대안 상태를 만들면 단일값으로 축약하지 않는다."""
    industry = '전기전자'
    items = sorted({item for ind, _, item, _ in __import__('eda').config.PPI_MAPPING_ROWS if ind == industry})
    panel = pd.DataFrame({'industry': [industry], 'quarter': ['2025Q1'], 'production_yoy': [5.0],
                          'employment_yoy': [2.0]})
    candidates = pd.DataFrame({'quarter': ['2025Q1', '2025Q1'], 'industry': [industry, industry],
                               'ppi_item': items, 'ppi_yoy': [2.0, 10.0]})
    out = ppi_aux.ppi_fields(panel, candidates, require_all_candidates=False).iloc[0]
    assert out['ppi_alt_state_set'] == 'S1|S3'
    assert bool(out['ppi_alt_state_all_same']) is False
    assert out['ppi_direction_status'] == 'CANDIDATE_DEPENDENT'
    assert out['ppi_adjusted_prod_yoy_lower'] < 0 < out['ppi_adjusted_prod_yoy_upper']


def test_ppi_source_not_available_without_candidate_file():
    panel = pd.DataFrame({'industry': ['A', 'A'], 'quarter': ['2025Q4', '2026Q1'],
                          'production_yoy': [1.0, 2.0], 'employment_yoy': [1.0, 1.0]})
    out = ppi_aux.ppi_fields(panel, candidates=None, latest='2026Q1')
    assert out['ppi_direction_status'].tolist() == ['PPI_SOURCE_NOT_AVAILABLE'] * 2
    assert out['ppi_adjusted_prod_yoy_lower'].isna().all(), '과거 값을 추정·복원하지 않는다'
