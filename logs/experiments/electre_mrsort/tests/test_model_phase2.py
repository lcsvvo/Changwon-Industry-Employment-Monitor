# -*- coding: utf-8 -*-
"""Phase 2: resample.py·perturb.py·robust.py 단위 검증(모형 판정 로직은 electre.py에 있고
여기서는 바꾸지 않는다 — 진단 유틸리티만 검증한다)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, electre, perturb, prereg, resample, robust  # noqa: E402


# ---------------------------------------------------------------- resample.py
def test_spearman_perfect_and_inverse_and_ties():
    assert resample.spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert resample.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    # 동순위가 있어도 계산된다(평균순위)
    got = resample.spearman([1, 1, 2, 3], [1, 2, 2, 3])
    assert not np.isnan(got)


def test_spearman_nan_on_few_pairs_or_zero_variance():
    assert np.isnan(resample.spearman([1, 2], [1, 2]))  # 유효쌍 2개 < 3
    assert np.isnan(resample.spearman([1, 1, 1, 1], [1, 2, 3, 4]))  # x 분산 0
    assert np.isnan(resample.spearman([1, 2, 3, 4], [5, 5, 5, 5]))  # y 분산 0
    assert np.isnan(resample.spearman([1, 2, np.nan, 4], [1, np.nan, 3, 4]))  # 유효쌍 2개 < 3


def test_cluster_bootstrap_diff_shape_and_direction():
    rng = np.random.default_rng(0)
    n = 60
    groups = np.repeat(np.arange(10), 6)
    outcome = rng.uniform(0, 1, n)
    stage_a = rng.uniform(0, 1, n)  # a는 outcome과 무관(약한 상관)
    stage_b = outcome + rng.normal(0, 0.05, n)  # b는 outcome과 강하게 상관
    mask = np.ones(n, dtype=bool)
    result = resample.cluster_bootstrap_diff(stage_a, stage_b, outcome, groups, mask, n=300, seed=1)
    assert set(result) == {'point_a', 'point_b', 'point_diff', 'ci_lo', 'ci_hi', 'p_diff_gt_0', 'n_effective'}
    assert result['point_diff'] == pytest.approx(result['point_b'] - result['point_a'])
    assert result['point_b'] > result['point_a']  # b가 outcome과 더 강하게 연관
    assert result['ci_lo'] <= result['ci_hi']
    assert result['n_effective'] <= 300


def test_blocked_leave_one_out_returns_all_groups_no_best_selection():
    rng = np.random.default_rng(0)
    n = 60
    groups = np.repeat(np.arange(10), 6)
    outcome = rng.uniform(0, 1, n)
    stage_a = rng.uniform(0, 1, n)
    stage_b = rng.uniform(0, 1, n)
    mask = np.ones(n, dtype=bool)
    loio = resample.blocked_leave_one_out(stage_a, stage_b, outcome, groups, mask)
    assert len(loio) == 10  # 군집 10개 전부, 최선값만 고르지 않는다
    assert set(loio['excluded_group']) == set(range(10))


# ---------------------------------------------------------------- perturb.py
def _real_panel():
    panel = pd.read_csv(ROOT / 'data/processed/model/electre_input_panel.csv')
    panel.columns = [str(c).lstrip('﻿') for c in panel.columns]
    return panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)


def _base_scenario():
    return electre.Scenario('기준', {'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3},
                            {'g1': 100, 'g2': 2, 'g3': 5, 'g4': 2},
                            {'g1': 500, 'g2': 5, 'g3': 10, 'g4': 4}, .5, 0, True)


def test_revision_pool_reads_real_vintage_file():
    pool = perturb.revision_pool(ROOT / 'outputs/tables/vintage_수정폭_실측.csv')
    assert set(pool) == {'employment', 'production'}
    assert len(pool['employment']) > 0 and len(pool['production']) > 0
    assert not np.isnan(pool['employment']).any()


def test_self_check_zero_perturbation_passes_on_real_panel():
    """필수 자가검증: 실제 패널에서 무교란(pool=0) 유지율은 정확히 1.0이어야 한다."""
    panel = _real_panel()
    q = {j: 0.0 for j in config.CRITERIA}
    result = perturb.self_check_zero_perturbation(panel, _base_scenario(), q, q, None)
    assert result['mean'] == 1.0
    assert result['min'] == 1.0


def test_self_check_raises_runtimeerror_when_retention_not_one(monkeypatch):
    """유지율이 1.0이 아니면 RuntimeError를 던진다(stability를 모의로 대체해 확인)."""
    def fake_stability(panel, scenario, q, p, veto, pool, n=3, seed=1):
        return {'mean': 0.5, 'p05': 0.5, 'min': 0.5, 'replicates': np.array([0.5, 0.5, 0.5])}
    monkeypatch.setattr(perturb, 'stability', fake_stability)
    with pytest.raises(RuntimeError):
        perturb.self_check_zero_perturbation(_real_panel(), _base_scenario(),
                                              {j: 0.0 for j in config.CRITERIA},
                                              {j: 0.0 for j in config.CRITERIA}, None)


def test_perturb_once_preserves_shape_and_recomputes_criteria():
    panel = _real_panel()
    pool = perturb.revision_pool(ROOT / 'outputs/tables/vintage_수정폭_실측.csv')
    rng = np.random.default_rng(5)
    out = perturb.perturb_once(panel, pool, rng)
    assert len(out) == len(panel)
    assert list(out.columns) == list(panel.columns)
    # g1~g4가 새로 계산된 employment_yoy/production_yoy와 일치한다
    assert np.allclose(out['g2_emp_rel_decline'], np.maximum(0.0, -out['employment_yoy']), equal_nan=True)
    assert np.allclose(out['g3_prod_decline_nominal'], np.maximum(0.0, -out['production_yoy']), equal_nan=True)


def test_stability_denominator_excludes_undetermined_both_sides():
    panel = _real_panel()
    pool = perturb.revision_pool(ROOT / 'outputs/tables/vintage_수정폭_실측.csv')
    q = {j: 0.0 for j in config.CRITERIA}
    result = perturb.stability(panel, _base_scenario(), q, q, None, pool, n=20, seed=7)
    assert 0.0 <= result['mean'] <= 1.0
    assert result['min'] <= result['mean']
    assert len(result['replicates']) == 20


# ---------------------------------------------------------------- robust.py
def _tiny_prereg_doc(n_samples, seed):
    return {'parameter_space': {
        'lambda': {'min': 0.5, 'max': 0.6}, 'weights': {'min': 0.10, 'max': 0.40},
        'p_upper': {'g1': 150, 'g2': 2.5, 'g3': 7.0, 'g4': 2.0}, 'n_samples': n_samples}}


def test_sample_parameter_space_respects_bounds():
    doc = _tiny_prereg_doc(200, 1)
    rng = np.random.default_rng(1)
    samples = robust.sample_parameter_space(doc, rng)
    assert len(samples) == 200
    for s in samples:
        w = np.array(list(s['weights'].values()))
        assert np.all(w >= 0.10 - 1e-9) and np.all(w <= 0.40 + 1e-9)
        assert abs(w.sum() - 1.0) < 1e-9
        assert 0.5 - 1e-9 <= s['lambda'] <= 0.6 + 1e-9
        for j in config.CRITERIA:
            assert 0.0 <= s['q'][j] <= s['p'][j] / 2.0 + 1e-9
            assert s['p'][j] <= doc['parameter_space']['p_upper'][j] + 1e-9


def test_assignment_matrix_dtype_and_shape():
    values = pd.DataFrame({'g1': [200.0, 50.0, np.nan], 'g2': [3.0, 1.0, 3.0],
                           'g3': [6.0, 2.0, 6.0], 'g4': [3.0, 1.0, 3.0]})
    profiles = {'b1': {'g1': 100, 'g2': 2, 'g3': 5, 'g4': 2}, 'b2': {'g1': 500, 'g2': 5, 'g3': 10, 'g4': 4}}
    doc = _tiny_prereg_doc(10, 2)
    rng = np.random.default_rng(2)
    samples = robust.sample_parameter_space(doc, rng)
    matrix = robust.assignment_matrix(values, profiles, samples, gate=True, veto=None)
    assert matrix.shape == (10, 3)
    assert matrix.dtype == np.int8
    assert np.all(matrix[:, 2] == -1)  # g1 결측 행은 모든 샘플에서 UNDETERMINED


def test_robust_assignment_necessary_stage_logic():
    # 3개 샘플, 2행: 1행은 항상 같은 코드(필연), 2행은 샘플마다 다름(필연 아님)
    matrix = np.array([[0, 1], [0, 2], [0, 0]], dtype=np.int8)
    row_keys = pd.DataFrame({'industry': ['A', 'B'], 'quarter': ['2022Q1', '2022Q1']})
    disc = np.array([True, True])
    out = robust.robust_assignment(matrix, row_keys, disc)
    row_a = out[out.industry == 'A'].iloc[0]
    row_b = out[out.industry == 'B'].iloc[0]
    assert row_a['necessary_stage'] == 'OBSERVE' and row_a['is_necessary'] and row_a['n_possible'] == 1
    # pandas가 문자열 열의 결측을 None 대신 NaN으로 표현할 수 있으므로 pd.isna로 확인한다
    assert pd.isna(row_b['necessary_stage']) and not row_b['is_necessary'] and row_b['n_possible'] == 3


def test_class_acceptability_rows_sum_to_one():
    matrix = np.array([[0, 1, -1], [0, 2, -1], [1, 2, -1]], dtype=np.int8)
    row_keys = pd.DataFrame({'industry': ['A', 'B', 'C'], 'quarter': ['2022Q1'] * 3})
    cai = robust.class_acceptability(matrix, row_keys)
    totals = cai[['cai_observe', 'cai_check', 'cai_priority', 'cai_undetermined']].sum(axis=1)
    assert np.allclose(totals, 1.0)
    assert cai.loc[cai.industry == 'C', 'cai_undetermined'].iloc[0] == 1.0


# ---------------------------------------------------------------- 실제 사전등록 문서로 통합 확인
def test_robust_pipeline_matches_crisp_subspace_reference():
    """전체 파라미터공간(q,p 포함)의 판별표본 필연배정 비율은 낮고, q=p=0으로 고정한
    부분공간(가중치·lambda만 변동)에서는 '참고: crisp 약 0.18'에 가까운 값이 나와야 한다
    — 두 계산이 서로 다른 스펙(공간의 폭)을 재는 것이지 어느 한쪽이 틀린 게 아님을 확인한다."""
    doc = prereg.load(ROOT / 'config/model_revalidation_prereg.yaml')
    panel = _real_panel()
    values = pd.DataFrame({'g1': panel['g1_emp_abs_decline'].astype(float),
                           'g2': panel['g2_emp_rel_decline'].astype(float),
                           'g3': panel['g3_prod_decline_nominal'].astype(float),
                           'g4': panel['g4_delta00'].astype(float)})
    profiles = {'b1': {'g1': 100, 'g2': 2, 'g3': 5, 'g4': 2}, 'b2': {'g1': 500, 'g2': 5, 'g3': 10, 'g4': 4}}
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced

    small_doc = dict(doc)
    small_doc['parameter_space'] = dict(doc['parameter_space'])
    small_doc['parameter_space']['n_samples'] = 800  # 전체 검증엔 느리므로 표본을 줄인 하위표집
    rng = np.random.default_rng(42)
    samples = robust.sample_parameter_space(small_doc, rng)
    crisp_samples = [{'weights': s['weights'], 'lambda': s['lambda'],
                      'p': {j: 0.0 for j in config.CRITERIA}, 'q': {j: 0.0 for j in config.CRITERIA}}
                     for s in samples]
    row_keys = panel[['industry', 'quarter']]

    matrix_full = robust.assignment_matrix(values, profiles, samples, gate=True, veto=None)
    ra_full = robust.robust_assignment(matrix_full, row_keys, discriminating)
    share_full = ra_full.loc[discriminating, 'is_necessary'].mean()

    matrix_crisp = robust.assignment_matrix(values, profiles, crisp_samples, gate=True, veto=None)
    ra_crisp = robust.robust_assignment(matrix_crisp, row_keys, discriminating)
    share_crisp = ra_crisp.loc[discriminating, 'is_necessary'].mean()

    assert share_full < share_crisp  # p,q까지 흔들면 필연배정이 더 줄어든다
    assert share_crisp == pytest.approx(0.18, abs=0.05)  # 참고값과 근접(표본 수가 작아 약간의 오차 허용)
