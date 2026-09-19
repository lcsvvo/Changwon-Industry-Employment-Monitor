# -*- coding: utf-8 -*-
"""Phase 3: 참조사례 양립성·재판정 파이프라인 검증. electre.py 판정 로직은 바꾸지 않는다."""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, revalidation_phase3 as p3  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tiny_panel():
    return pd.DataFrame({'industry': ['A', 'A', 'B'], 'quarter': ['2022Q1', '2022Q2', '2022Q1']})


# ---------------------------------------------------------------- reference_compatibility
def test_reference_compatibility_at_least_at_most_and_undetermined():
    panel = _tiny_panel()
    # 열0=A/2022Q1, 열1=A/2022Q2, 열2=B/2022Q1
    matrix = np.array([
        [1, 0, 2],   # 표본0: at_least CHECK(열0, 1>=1 통과) / at_most OBSERVE(열2, 2<=0 실패) -> 비양립
        [2, 0, 0],   # 표본1: at_least CHECK(열0, 2>=1 통과) / at_most OBSERVE(열2, 0<=0 통과) -> 양립
        [-1, 0, 0],  # 표본2: 열0 UNDETERMINED -> undetermined_counts_as='fail'이면 비양립
    ], dtype=np.int8)
    reference_cases = [
        {'id': 'RC_A', 'industry': 'A', 'quarter': '2022Q1', 'relation': 'at_least', 'stage': 'CHECK'},
        {'id': 'RC_B', 'industry': 'B', 'quarter': '2022Q1', 'relation': 'at_most', 'stage': 'OBSERVE'},
    ]
    compatible, per_case = p3.reference_compatibility(matrix, panel, reference_cases, 'fail')
    assert compatible.tolist() == [False, True, False]
    assert set(per_case['case_id']) == {'RC_A', 'RC_B'}

    # undetermined_counts_as != 'fail'이면 표본2의 UNDETERMINED가 통과로 처리된다
    compatible2, _ = p3.reference_compatibility(matrix, panel, reference_cases, 'pass')
    assert compatible2.tolist() == [False, True, True]


def test_reference_compatibility_raises_on_duplicate_or_missing_row():
    panel = _tiny_panel()
    matrix = np.zeros((2, 3), dtype=np.int8)
    missing = [{'id': 'RC_X', 'industry': '없는업종', 'quarter': '2022Q1', 'relation': 'at_least', 'stage': 'CHECK'}]
    with pytest.raises(ValueError):
        p3.reference_compatibility(matrix, panel, missing, 'fail')

    dup_panel = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)  # A/2022Q1 중복
    dup_matrix = np.zeros((2, 4), dtype=np.int8)
    dup_case = [{'id': 'RC_Y', 'industry': 'A', 'quarter': '2022Q1', 'relation': 'at_least', 'stage': 'CHECK'}]
    with pytest.raises(ValueError):
        p3.reference_compatibility(dup_matrix, dup_panel, dup_case, 'fail')


# ---------------------------------------------------------------- 전체 파이프라인(느림 — 실제 패널 사용)
@pytest.fixture(scope='module')
def phase3_result():
    return p3.decision_and_outputs(ROOT, write=False)


def test_fixed_model_anchor_base_scenario(phase3_result):
    """결정론적 앵커: 기준 시나리오에서 v1.0_crisp 비양립, D_small_indifference 양립."""
    results_v1, _ = phase3_result['fixed_model_rc'][('v1.0_crisp', '기준')]
    results_d, _ = phase3_result['fixed_model_rc'][('D_small_indifference', '기준')]
    assert all(results_v1.values()) is False
    assert all(results_d.values()) is True


def test_cai_compatible_rows_sum_to_one(phase3_result):
    cai = phase3_result['tables']['electre_class_acceptability_index_compatible']
    totals = cai[['cai_observe', 'cai_check', 'cai_priority', 'cai_undetermined']].sum(axis=1)
    assert np.allclose(totals, 1.0, atol=1e-9)
    assert len(cai) == 180


def test_subspace_necessary_share_in_range_and_ordering(phase3_result):
    summary = phase3_result['tables']['electre_robust_assignment_summary'].set_index('space_id')
    for space_id in ('reference_compatible_subspace', 'full_parameter_space', 'crisp_subspace'):
        v = summary.loc[space_id, 'necessary_share_discriminating']
        assert 0.0 <= v <= 1.0
    # 공간이 좁아지면(참조사례 양립 부분공간) 필연배정은 전체공간보다 줄어들 수 없다
    assert (summary.loc['reference_compatible_subspace', 'necessary_share_discriminating']
           >= summary.loc['full_parameter_space', 'necessary_share_discriminating'])


def test_overall_status_is_allowed_enum(phase3_result):
    decision = phase3_result['tables']['electre_revalidation_decision']
    assert set(decision['overall_status']) <= set(p3.OVERALL_STATUSES)
    assert len(decision) == 6


def test_s1_scope_is_parameter_space_level_for_all_rows(phase3_result):
    decision = phase3_result['tables']['electre_revalidation_decision']
    assert (decision['s1_scope'] == 'parameter_space_level').all()
    # S1은 공간 수준 지표이므로 model_id·scenario_id에 의존하지 않는다(6행 모두 같은 값)
    assert decision['s1_reference_compatible_subspace'].nunique() == 1


def test_c2_c3_sourced_from_phase2_outputs_after_am1(phase3_result):
    decision = phase3_result['tables']['electre_revalidation_decision']
    assert decision['c2_source_run_id'].nunique() == 1
    assert decision['c3_source_run_id'].nunique() == 1
    for run_id in (decision['c2_source_run_id'].iloc[0], decision['c3_source_run_id'].iloc[0]):
        p3._verify_am1_applied(ROOT, run_id)  # 예외 없이 통과해야 한다(AM1 이후 run)


def test_prior_decision_csv_hash_unchanged_after_phase3():
    path = ROOT / 'outputs/tables/electre_qp_selection_decision.csv'
    before = _sha(path)
    p3.decision_and_outputs(ROOT, write=False)
    after = _sha(path)
    assert before == after


def test_wording_check_passes_on_phase3_new_files():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import check_wording
    violations = check_wording.check([
        'src/model/revalidation_phase3.py', 'tests/test_model_phase3.py',
    ])
    assert violations == []
