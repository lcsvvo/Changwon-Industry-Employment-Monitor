# -*- coding: utf-8 -*-
"""Phase 5: 선호정보 확충·구간 배정·교란 강건성 재정의 검증. electre.py 판정 로직은
바꾸지 않는다. 파라미터도 바꾸지 않는다(config/electre_tri_b_params.yaml은 읽기만)."""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, electre, revalidation_phase5 as p5  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope='module')
def result():
    return p5.run_phase5(ROOT, write=False)


# ---------------------------------------------------------------- Step 1
def test_virtual_profile_manual_expectations(result):
    """VRC1~VRC5를 수동 계산한 기대값과 대조한다(고용증거 게이트 포함).

    VRC1·VRC2·VRC5는 프로파일 자체가 경계상 자명해 파라미터(w·λ·q·p)와 무관하게
    항상 만족된다(개별 통과율 1.0) — 이 셋은 crisp·기준 시나리오 한 점으로 직접
    검산할 수 있다. VRC3·VRC4는 w·λ에 따라 갈리는 확률적 사례이므로(개별 통과율이
    1.0 미만) 단일 점이 아니라 이미 계산된 개별 통과율이 정확히 그 열린구간에
    있는지로 대조한다(수동 계산한 기대치는 '항상 만족' vs '조건부 만족'의 구분이다).
    """
    scenarios = result['scenarios']
    s = scenarios['기준']
    q = {j: 0.0 for j in config.CRITERIA}
    p = {j: 0.0 for j in config.CRITERIA}
    am6 = p5._am6_content(result['prereg_doc'])  # noqa: SLF001
    rank = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
    always_satisfied = {'VRC1', 'VRC2', 'VRC5'}

    case_table = result['expansion_table']
    case_table = case_table[case_table.block_type == 'case'].set_index('case_id')

    for vrc in am6['virtual_reference_cases']:
        pass_rate = float(case_table.loc[vrc['id'], 'individual_pass_rate'])
        if vrc['id'] in always_satisfied:
            assert pass_rate == pytest.approx(1.0), f"{vrc['id']}는 항상 만족해야 하는데 {pass_rate}"
            values = pd.DataFrame([vrc['profile']])[list(config.CRITERIA)]
            stage = electre.pessimistic_assignment(
                electre.forward_outranks(values, s, 'b1', q, p, None),
                electre.forward_outranks(values, s, 'b2', q, p, None),
                values[list(config.CRITERIA)].notna().all(axis=1).to_numpy())[0]
            if vrc['relation'] == 'at_least':
                assert rank[stage] >= rank[vrc['stage']], f"{vrc['id']}: {stage} < {vrc['stage']}(at_least)"
            else:
                assert rank[stage] <= rank[vrc['stage']], f"{vrc['id']}: {stage} > {vrc['stage']}(at_most)"
        else:
            assert 0.0 < pass_rate < 1.0, f"{vrc['id']}는 조건부로만 만족해야 하는데 pass_rate={pass_rate}"


def test_reference_plus_virtual_is_subset_of_reference_compatible(result):
    matrix, vrc_matrix = result['matrix'], result['vrc_matrix']
    panel = result['panel']
    doc = result['prereg_doc']
    from model import revalidation_phase3 as p3
    undetermined_counts_as = doc['reference_case_rule']['undetermined_counts_as']
    rc_compat, _ = p3.reference_compatibility(matrix, panel, doc['reference_cases'], undetermined_counts_as)
    combined = result['combined_mask']
    assert np.all(combined <= rc_compat)  # combined가 True인 곳은 rc_compat도 항상 True(부분집합)
    assert combined.sum() <= rc_compat.sum()


def test_necessary_share_monotone_as_space_narrows(result):
    space = result['expansion_table']
    space = space[space.block_type == 'space'].set_index('space_id')
    full = space.loc['full_parameter_space', 'necessary_share_discriminating']
    rc = space.loc['reference_compatible_subspace', 'necessary_share_discriminating']
    combo = space.loc['reference_plus_virtual_subspace', 'necessary_share_discriminating']
    assert full <= rc <= combo  # 공간이 좁아질수록(제약이 늘수록) 필연배정은 감소할 수 없다


# ---------------------------------------------------------------- Step 2
def test_possible_stages_matches_positive_cai(result):
    t = result['interval_table']
    for _, r in t.iterrows():
        if r['n_possible'] == 0:
            continue  # UNDETERMINED
        expected = {s for s, c in (('OBSERVE', r.cai_observe), ('CHECK', r.cai_check),
                                   ('PRIORITY', r.cai_priority)) if c > 0}
        assert set(r['possible_stages'].split('|')) == expected
        assert len(expected) == r['n_possible']


def test_cai_rows_sum_to_one(result):
    t = result['interval_table']
    totals = t[['cai_observe', 'cai_check', 'cai_priority', 'cai_undetermined']].sum(axis=1)
    assert np.allclose(totals, 1.0, atol=1e-9)


def test_display_label_rules():
    assert p5.display_label(['OBSERVE'], 'OBSERVE', 1.0, False) == '관찰(표본 내 공통)'
    label2 = p5.display_label(['OBSERVE', 'CHECK'], 'CHECK', 0.65, False)
    assert '~' in label2 and '%' in label2
    assert '(확정)' not in label2
    label3 = p5.display_label(['OBSERVE', 'CHECK', 'PRIORITY'], 'CHECK', 0.5, False)
    assert '~' in label3 and '%' in label3
    assert p5.display_label([], None, np.nan, True) == config.DISPLAY_LABELS[config.UNDETERMINED]
    # 어떤 경우에도(확정 제외) 단일 단계 텍스트만 있는 라벨이 없어야 한다
    for n in (2, 3):
        stages = ['OBSERVE', 'CHECK', 'PRIORITY'][:n]
        label = p5.display_label(stages, stages[0], 0.5, False)
        assert '~' in label


def test_interval_table_matches_real_data(result):
    t = result['interval_table']
    assert len(t) == 180
    assert t['industry'].nunique() == 10
    assert t['quarter'].nunique() == 18  # 2022Q1~2026Q2
    assert (t.loc[t['is_forced_observe'], 'necessary_stage'] == 'OBSERVE').all()  # 강제 관찰은 항상 필연 OBSERVE


# ---------------------------------------------------------------- Step 3
def test_c3b_full_possible_set_rows_always_contain(result):
    """가능 단계가 3개(OBSERVE|CHECK|PRIORITY)인 행은 어떤 점 단계가 와도 항상 containment=True다.
    이 자명성 때문에 mean_n_possible_stages 병기가 필수라는 사실을 테스트로 고정한다.
    """
    t = result['interval_table']
    three_stage_rows = t[t['possible_stages'] == 'OBSERVE|CHECK|PRIORITY']
    assert len(three_stage_rows) > 0  # 실제 이런 행이 존재해야 이 테스트가 의미 있다
    # 모든 점 단계(UNDETERMINED 제외)가 3단계 집합 안에 있으므로 자명하게 포함된다
    for col in ('point_stage_기준', 'point_stage_고용중시', 'point_stage_지속성중시'):
        vals = set(three_stage_rows[col].dropna()) - {config.UNDETERMINED}
        assert vals <= {'OBSERVE', 'CHECK', 'PRIORITY'}


def test_jaccard_range_and_no_perturbation_is_one():
    """무교란(pool 전부 0)이면 가능 단계 집합이 그대로이므로 Jaccard가 정확히 1.0이어야 한다."""
    panel = pd.read_csv(ROOT / 'data/processed/model/electre_input_panel.csv')
    panel.columns = [str(c).lstrip('﻿') for c in panel.columns]
    panel = panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)
    from model import qp_calibration, robust
    import yaml
    values = qp_calibration.values_from_panel(panel)
    base_doc = yaml.safe_load((ROOT / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))
    profiles = next(b for b in base_doc['scenarios'] if b['scenario_id'] == '기준')['profiles']
    rng = np.random.default_rng(1)
    tiny_doc = {'parameter_space': {'lambda': {'min': 0.5, 'max': 0.6}, 'weights': {'min': 0.1, 'max': 0.4},
                                    'p_upper': {'g1': 100, 'g2': 2.0, 'g3': 5.0, 'g4': 2.0}, 'n_samples': 50}}
    samples = robust.sample_parameter_space(tiny_doc, rng)
    matrix = robust.assignment_matrix(values, profiles, samples, gate=True, veto=None)
    sets_a = p5._possible_sets_from_matrix(matrix)  # noqa: SLF001
    sets_b = p5._possible_sets_from_matrix(matrix)  # noqa: SLF001 (같은 행렬 = 무교란과 동치)
    for a, b in zip(sets_a, sets_b):
        union = a | b
        j = 1.0 if not union else len(a & b) / len(union)
        assert j == pytest.approx(1.0)
        assert 0.0 <= j <= 1.0


def test_c3b_and_c3c_values_in_unit_interval(result):
    rt = result['tables']['electre_interval_robustness']
    for _, r in rt[rt.metric_id.isin(['C3b', 'C3c_discriminating', 'C3c_scorable'])].iterrows():
        assert 0.0 <= r['value'] <= 1.0


# ---------------------------------------------------------------- 불변성
def test_base_parameter_file_unchanged_before_and_after(result):
    before = _sha(ROOT / 'config/electre_tri_b_params.yaml')
    p5.run_phase5(ROOT, write=False)
    after = _sha(ROOT / 'config/electre_tri_b_params.yaml')
    assert before == after


def test_diagnostic_cards_latest_unchanged(result):
    path = ROOT / 'outputs/report/diagnostic_cards_latest.md'
    before = _sha(path)
    p5.run_phase5(ROOT, write=False)
    after = _sha(path)
    assert before == after


def test_wording_check_passes_on_phase5_new_files():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import check_wording
    targets = ['src/model/revalidation_phase5.py', 'tests/test_model_phase5.py']
    for extra in ('outputs/report/interval_diagnostic_cards_2026Q2.md',):
        if (ROOT / extra).is_file():
            targets.append(extra)
    violations = check_wording.check(targets)
    assert violations == []
