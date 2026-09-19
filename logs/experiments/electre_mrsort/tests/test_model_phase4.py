# -*- coding: utf-8 -*-
"""Phase 4: veto 대응 판정 함수·최대잉여법 이산화·W_nearest 탐색·착수 게이트 검증.

electre.py·qp_calibration.py 판정 로직은 바꾸지 않는다.
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, electre, prereg, qp_calibration, revalidation_phase4 as p4  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _panel():
    panel = pd.read_csv(ROOT / 'data/processed/model/electre_input_panel.csv')
    panel.columns = [str(c).lstrip('﻿') for c in panel.columns]
    return panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)


@pytest.fixture(scope='module')
def values():
    return qp_calibration.values_from_panel(_panel())


@pytest.fixture(scope='module')
def base_doc():
    return yaml.safe_load((ROOT / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def candidates():
    doc = yaml.safe_load((ROOT / 'config/electre_tri_b_params.v1.1-candidates.yaml').read_text(encoding='utf-8'))
    return {c['candidate_id']: c for c in doc['candidates']}


def test_constraints_with_veto_none_matches_qp_calibration(values, base_doc, candidates):
    n = 0
    for cid, cand in candidates.items():
        for block in base_doc['scenarios']:
            scenario = electre.Scenario.from_block(block)
            expected = qp_calibration.constraints(values, scenario, cand)
            got = p4.constraints_with_veto(values, scenario.weights, scenario.lam, cand['q'], cand['p'], None,
                                           gate=scenario.require_employment_evidence)
            assert expected == got, f'{cid}/{block["scenario_id"]} 불일치: {expected} vs {got}'
            n += 1
    assert n == 15  # 후보 5종 × 시나리오 3종


def test_veto_b2_only_preserves_b1_implication(values):
    veto = {'b2': {'g1': 30}}
    weights = {'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3}
    q = {j: 0.0 for j in config.CRITERIA}
    p = {j: 0.0 for j in config.CRITERIA}
    scenario = p4._scenario(weights, .5)  # noqa: SLF001
    b1 = electre.forward_outranks(values, scenario, 'b1', q, p, p4._boundary_veto(veto, 'b1'))  # noqa: SLF001
    b2 = electre.forward_outranks(values, scenario, 'b2', q, p, p4._boundary_veto(veto, 'b2'))  # noqa: SLF001
    assert not np.any(b2 & ~b1)


def test_veto_monotonicity_violations_zero(values, candidates):
    veto = {'b2': {'g1': 30}}
    D = candidates['D_small_indifference']
    weights = {'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3}
    cons = p4.constraints_with_veto(values, weights, .5, D['q'], D['p'], veto, gate=True)
    assert cons['monotonicity_violations'] == 0
    assert cons['boundary_contradictions'] == 0


def test_largest_remainder_discretize_reproduces_phase3_values():
    w_means = {'g1': 0.2850108094670422, 'g2': 0.2856994693851009, 'g3': 0.2046209235590398,
              'g4': 0.224668797588817}
    got = p4.largest_remainder_discretize(w_means)
    assert got == {'g1': 0.30, 'g2': 0.30, 'g3': 0.20, 'g4': 0.20}


def test_largest_remainder_discretize_sums_to_one_for_many_inputs():
    rng = np.random.default_rng(0)
    for _ in range(50):
        raw = rng.dirichlet(np.ones(4))
        w_means = dict(zip(config.CRITERIA, raw))
        out = p4.largest_remainder_discretize(w_means)
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-12)
        assert all(v >= 0 for v in out.values())


def test_w_nearest_search_is_deterministic(values):
    panel = _panel()
    reference_cases = [
        {'id': 'RC1', 'industry': '기계', 'quarter': '2022Q1', 'relation': 'at_least', 'stage': 'CHECK'},
        {'id': 'RC2', 'industry': '전기전자', 'quarter': '2025Q1', 'relation': 'at_least', 'stage': 'CHECK'},
        {'id': 'RC3', 'industry': '기타', 'quarter': '2026Q2', 'relation': 'at_most', 'stage': 'OBSERVE'},
    ]
    q = {j: 0.0 for j in config.CRITERIA}
    p = {j: 0.0 for j in config.CRITERIA}
    current = {'g1': 0.20, 'g2': 0.20, 'g3': 0.30, 'g4': 0.30}
    r1 = p4.search_w_nearest(reference_cases, 'fail', values, panel, 0.50, q, p, None, True, current)
    r2 = p4.search_w_nearest(reference_cases, 'fail', values, panel, 0.50, q, p, None, True, current)
    assert r1 == r2
    assert r1 is not None
    assert sum(r1.values()) == pytest.approx(1.0, abs=1e-9)


def test_phase4_gate_rejects_draft(tmp_path, monkeypatch):
    doc = yaml.safe_load((ROOT / 'config/model_revalidation_prereg.template.yaml').read_text(encoding='utf-8'))
    assert doc['prereg_status'] == 'DRAFT'
    bad_path = tmp_path / 'draft.yaml'
    bad_path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')

    original_load = prereg.load

    def fake_load(path):
        return original_load(bad_path)
    monkeypatch.setattr(prereg, 'load', fake_load)
    with pytest.raises(p4.Phase4GateError):
        p4.check_gate(ROOT)


def test_phase4_gate_passes_on_registered_yaml():
    doc = p4.check_gate(ROOT)  # 예외 없이 통과해야 한다(REGISTERED + AM4 존재)
    assert doc['prereg_status'] == 'REGISTERED'
    assert 'AM4' in [a['id'] for a in doc['amendments']]


def test_base_parameter_file_hash_unchanged_after_phase4_module_use(values, base_doc, candidates):
    """이 모듈의 함수를 호출해도 config/electre_tri_b_params.yaml은 읽기만 한다."""
    before = _sha(ROOT / 'config/electre_tri_b_params.yaml')
    scenario = electre.Scenario.from_block(base_doc['scenarios'][0])
    cand = candidates['D_small_indifference']
    p4.constraints_with_veto(values, scenario.weights, scenario.lam, cand['q'], cand['p'], None, gate=True)
    after = _sha(ROOT / 'config/electre_tri_b_params.yaml')
    assert before == after
