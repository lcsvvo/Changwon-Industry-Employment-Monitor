# -*- coding: utf-8 -*-
"""ELECTRE 경계분류·규칙 비교 단위 테스트(합성자료·합성 파라미터 전용).

여기의 가중치·경계·lambda는 알고리즘 성질을 확인하기 위한 값이며 실제 업종 판정에 쓰지 않는다.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import config, electre  # noqa: E402

EQUAL = {'g1': 0.25, 'g2': 0.25, 'g3': 0.25, 'g4': 0.25}
B1 = {'g1': 10, 'g2': 1, 'g3': 1, 'g4': 2}
B2 = {'g1': 20, 'g2': 2, 'g3': 2, 'g4': 3}


def scenario(weights=EQUAL, lam=0.5, gate=False, sid='T', b1=B1, b2=B2):
    return electre.Scenario(sid, dict(weights), dict(b1), dict(b2), lam, 0.0, gate)


def values(rows):
    return pd.DataFrame(rows, columns=list(config.CRITERIA), dtype=float)


def classes(rows, s):
    return electre.evaluate(values(rows), s)['display_class_by_scenario'].tolist()


# ---------------------------------------------------------------- 배정
def test_each_class_is_reachable_and_boundary_equality_passes():
    rows = [[0, 0, 0, 0], [10, 1, 0, 0], [20, 2, 2, 3], [10, 1, 1, 2]]
    assert classes(rows, scenario()) == ['OBSERVE', 'CHECK', 'PRIORITY', 'CHECK']


def test_concordance_equals_weighted_boundary_pass_sum():
    rng = np.random.default_rng(0)
    w = {'g1': 0.4, 'g2': 0.1, 'g3': 0.3, 'g4': 0.2}
    v = values(rng.uniform(0, 25, size=(200, 4)).round(0))
    out = electre.evaluate(v, scenario(weights=w))
    for h, prof in (('b1', B1), ('b2', B2)):
        expected = sum(w[j] * (v[j] >= prof[j]).astype(float) for j in config.CRITERIA)
        assert np.array_equal(out[f'concordance_{h}'].to_numpy(), expected.to_numpy())


def test_missing_criterion_is_not_zero_and_not_renormalized():
    out = electre.evaluate(values([[100, 100, np.nan, 100], [np.nan, 0, 0, 0]]), scenario())
    assert out['display_class_by_scenario'].tolist() == [config.UNDETERMINED, config.UNDETERMINED]
    assert out['concordance_b1'].isna().all() and out['concordance_b2'].isna().all()
    assert out['outranks_b1'].isna().all() and out['emp_evidence_at_b1'].isna().all()


def test_highest_boundary_checked_first():
    assert classes([[20, 2, 2, 3]], scenario(lam=1.0)) == ['PRIORITY']


def test_pessimistic_assignment_rejects_inconsistent_boundaries():
    with pytest.raises(ValueError):
        electre.pessimistic_assignment([False], [True], [True])


@pytest.mark.parametrize('gate', [False, True])
def test_monotonic_in_each_criterion(gate):
    rng = np.random.default_rng(1)
    w = {'g1': 0.35, 'g2': 0.15, 'g3': 0.3, 'g4': 0.2}
    s = scenario(weights=w, lam=0.5, gate=gate)
    base = values(rng.integers(0, 25, size=(400, 4)))
    rank = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
    before = electre.evaluate(base, s)['display_class_by_scenario'].map(rank)
    for j in config.CRITERIA:
        bumped = base.copy()
        bumped[j] = bumped[j] + rng.integers(0, 10, size=len(bumped))
        after = electre.evaluate(bumped, s)['display_class_by_scenario'].map(rank)
        assert (after >= before).all(), f'{j} 증가 시 점검단계가 하락함'


def test_row_order_does_not_change_results():
    rng = np.random.default_rng(2)
    v = values(rng.integers(0, 25, size=(100, 4)))
    v.index = [f'r{i}' for i in range(len(v))]
    s = scenario(weights={'g1': 0.4, 'g2': 0.1, 'g3': 0.3, 'g4': 0.2}, gate=True)
    base = electre.evaluate(v, s)
    shuffled = electre.evaluate(v.sample(frac=1, random_state=3), s).loc[base.index]
    pd.testing.assert_frame_equal(base, shuffled)


# ---------------------------------------------------------------- 생산 단독 통과·고용증거 게이트
PROD_HEAVY = {'g1': 0.15, 'g2': 0.15, 'g3': 0.55, 'g4': 0.15}


def test_production_only_pass_condition_and_gate_false():
    out = electre.evaluate(values([[0, 0, 5, 0]]), scenario(weights=PROD_HEAVY, gate=False)).iloc[0]
    for h in ('b1', 'b2'):
        assert out[f'production_only_pass_{h}'] and not out[f'emp_evidence_at_{h}']
    assert out['display_class_by_scenario'] == 'PRIORITY'


def test_gate_true_blocks_production_only_promotion():
    out = electre.evaluate(values([[0, 0, 5, 0]]), scenario(weights=PROD_HEAVY, gate=True)).iloc[0]
    assert out['production_only_pass_b1'] and out['outranks_b1_before_gate'] and not out['outranks_b1']
    assert out['display_class_by_scenario'] == 'OBSERVE'


def test_gate_true_allows_pass_with_employment_evidence_at_same_boundary():
    out = electre.evaluate(values([[10, 0, 5, 0]]), scenario(weights=PROD_HEAVY, gate=True)).iloc[0]
    assert out['emp_evidence_at_b1'] and not out['emp_evidence_at_b2']
    assert out['display_class_by_scenario'] == 'CHECK'


def test_production_only_requires_w3_at_least_lambda():
    out = electre.evaluate(values([[0, 0, 5, 0]]), scenario(weights=EQUAL, lam=0.5)).iloc[0]
    assert not out['production_only_pass_b1'] and out['display_class_by_scenario'] == 'OBSERVE'


# ---------------------------------------------------------------- 단순 개수규칙 비교
def assignments_for(rows, s):
    v = values(rows)
    ident = pd.DataFrame({'industry': [f'I{i}' for i in range(len(rows))], 'quarter': '2025Q1'})
    out = pd.concat([ident, electre.evaluate(v, s), electre.simple_count_rule(v, s)], axis=1)
    out.insert(0, 'scenario_id', s.scenario_id)
    return out


def test_observed_comparison_uses_union_not_intersection():
    rows = [[0, 0, 5, 0], [50, 0, 0, 0], [0, 0, 0, 0]]
    a = assignments_for(rows, scenario(weights={'g1': 0.1, 'g2': 0.1, 'g3': 0.7, 'g4': 0.1}, sid='A'))
    b = assignments_for(rows, scenario(weights={'g1': 0.7, 'g2': 0.1, 'g3': 0.1, 'g4': 0.1}, sid='B'))
    table, summary = electre.rule_comparison(pd.concat([a, b], ignore_index=True))
    disagree = {sid: set(g.loc[g.disagree, 'industry']) for sid, g in table.groupby('scenario_id')}
    assert disagree == {'A': {'I0'}, 'B': {'I1'}}
    assert not (disagree['A'] & disagree['B']), '교집합은 비어 있지만 채택 근거가 아니다'
    assert summary['union_n_rows'] == 2
    assert summary['identical_on_observed_data'] is False


def test_observed_identity_requires_zero_disagreement_everywhere():
    rng = np.random.default_rng(4)
    rows = rng.integers(0, 25, size=(50, 4)).tolist()
    _, summary = electre.rule_comparison(assignments_for(rows, scenario(weights=EQUAL)))
    assert summary['identical_on_observed_data'] is True and summary['union_n_rows'] == 0


def test_sixteen_coalitions_function_level_comparison():
    table, summary = electre.enumerate_coalitions([scenario(weights=EQUAL, sid='E'),
                                                   scenario(weights=PROD_HEAVY, sid='P')])
    assert len(table) == 16 * 2 * 2
    by = {(d['scenario_id'], d['boundary']): d for d in summary}
    assert by[('E', 'b1')]['logically_equivalent'] and by[('E', 'b2')]['n_combinations'] == 16
    assert not by[('P', 'b1')]['logically_equivalent'] and by[('P', 'b1')]['n_disagree'] > 0


def test_criterion_removal_methods_are_separated():
    impact = electre.criterion_removal_sensitivity(values([[10, 1, 1, 2]]), scenario(weights=EQUAL, lam=1.0))
    assert set(impact.method) == set(config.CRITERION_REMOVAL_METHODS)
    g1 = impact[impact.removed_criterion == 'g1'].set_index('method')
    support = g1.loc[config.REMOVAL_SUPPORT_ZERO]
    assert (support.from_class, support.to_class) == ('CHECK', 'OBSERVE')
    assert not support.weights_renormalized
    renorm = g1.loc[config.REMOVAL_RENORMALIZED]
    assert (renorm.from_class, renorm.to_class) == ('CHECK', 'CHECK')
    assert renorm.weights_renormalized


def test_removed_criterion_weights_sum_to_one():
    s = scenario(weights={'g1': 0.4, 'g2': 0.1, 'g3': 0.3, 'g4': 0.2})
    for j in config.CRITERIA:
        w = electre.renormalized_weights(s, j)
        assert j not in w and abs(sum(w.values()) - 1) < 1e-12
        assert w == pytest.approx({k: v / (1 - s.weights[j]) for k, v in s.weights.items() if k != j})


def test_removal_keeps_missing_rule_and_evaluation_scope():
    """g3 결측 행은 g3를 제거한 분석에서도 기본 모형 판정불가 범위로 유지한다."""
    v = values([[30, 5, np.nan, 5], [30, 5, 5, 5]])
    impact = electre.criterion_removal_sensitivity(v, scenario(weights=EQUAL, lam=0.5))
    renorm_g3 = impact[(impact.method == config.REMOVAL_RENORMALIZED) & (impact.removed_criterion == 'g3')]
    undetermined = renorm_g3[renorm_g3.from_class == config.UNDETERMINED]
    assert undetermined.to_class.tolist() == [config.UNDETERMINED]
    assert set(impact.evaluation_scope) == {config.REMOVAL_EVALUATION_SCOPE}
    classes, _ = electre.evaluate_without_criterion(v, scenario(weights=EQUAL), 'g3', [False, True])
    assert classes.tolist() == [config.UNDETERMINED, 'PRIORITY']


def test_removed_employment_criterion_leaves_gate_on_remaining_employment_criteria():
    s = scenario(weights={'g1': 0.2, 'g2': 0.2, 'g3': 0.4, 'g4': 0.2}, lam=0.5, gate=True)
    v = values([[10, 0, 5, 0]])
    classes, _ = electre.evaluate_without_criterion(v, s, 'g1', [True])
    assert classes.tolist() == ['OBSERVE'], 'g1 제거 후 남은 고용 기준 증거가 없으면 게이트가 막는다'


# ---------------------------------------------------------------- 요약·이력·PPI 가상단계
def test_scenario_summary_counts_and_text():
    a = pd.DataFrame({'scenario_id': ['기준', '고용중시', '지속성중시'], 'industry': 'X', 'quarter': '2026Q2',
                      'display_class_by_scenario': ['PRIORITY', 'PRIORITY', 'CHECK']})
    s = electre.scenario_summary(a).iloc[0]
    assert (s.priority_scenario_count, s.check_or_higher_scenario_count, s.valid_scenario_count) == (2, 3, 3)
    assert '3개 시나리오 중 2개에서 우선점검' in s.scenario_display_text
    assert '3개 시나리오 모두 추가확인 이상' in s.scenario_display_text
    assert 'display_class' not in s.index, '승인 전에는 단일 display_class를 만들지 않는다'


def test_recent_history_keeps_scenarios_separate():
    quarters = ['2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q2']
    a = pd.DataFrame([{'scenario_id': sid, 'industry': 'X', 'quarter': q, 'display_class_by_scenario': c}
                      for sid, c in (('A', 'CHECK'), ('B', 'OBSERVE')) for q in quarters])
    h = electre.recent_stage_history(a, quarters)
    assert set(h.scenario_id) == {'A', 'B'} and h.quarter.nunique() == 4
    assert h[h.scenario_id == 'B'].display_class_by_scenario.eq('OBSERVE').all()


def test_ppi_hypothetical_stage_does_not_change_official_stage():
    panel = pd.DataFrame({'industry': ['X'], 'quarter': ['2026Q2'], 'state': ['S2'], 'production_yoy': [1.0],
                          'ppi_adjusted_prod_yoy_lower': [-5.0], 'ppi_adjusted_prod_yoy_upper': [-5.0],
                          'ppi_direction_status': ['OPPOSITE_ALL'], 'ppi_alt_state_set': ['S4'],
                          'ppi_mapping_confirmation_status': ['NOT_CONFIRMED'], 'scorable': [True]})
    s = scenario(weights=PROD_HEAVY, gate=False)
    v = values([[0, 0, 0, 0]])
    base = electre.evaluate(v, s)['display_class_by_scenario']
    out = electre.ppi_stage_divergence(panel, v, s, base).iloc[0]
    assert out.nominal_display_class_by_scenario == 'OBSERVE'
    assert out.ppi_hypothetical_stage_lower == 'PRIORITY' and bool(out.ppi_stage_divergent)
    assert out.official_stage_changed is False or out.official_stage_changed == False  # noqa: E712
    assert v.loc[0, 'g3'] == 0, '공식 g3(명목)는 바뀌지 않는다'
