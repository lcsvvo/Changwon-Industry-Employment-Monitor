# -*- coding: utf-8 -*-
"""Phase 1: electre.py 낙관적 배정·veto 추가분, prereg.py 사전등록 게이트 검증.

prereg 관련 테스트는 합성 dict와 실제 config/electre_tri_b_params.yaml(읽기 전용)만
사용하며 config/model_revalidation_prereg*.yaml의 실제 내용은 검증하지 않는다
(그 파일의 스키마 검증은 tests/test_model_prereg.py에 있다).
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, electre, params, prereg  # noqa: E402
from model import qp_calibration as qp  # noqa: E402

RANK = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2, config.UNDETERMINED: -1}


def scenario(lam=.5, gate=True):
    return electre.Scenario('기준', {'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3},
                            {'g1': 100, 'g2': 2, 'g3': 5, 'g4': 2},
                            {'g1': 500, 'g2': 5, 'g3': 10, 'g4': 4}, lam, 0, gate)


def load_panel_values():
    panel = pd.read_csv(ROOT / 'data/processed/model/electre_input_panel.csv')
    panel.columns = [str(c).lstrip('﻿') for c in panel.columns]
    panel = panel.sort_values(['industry', 'quarter'], kind='mergesort').reset_index(drop=True)
    values = pd.DataFrame({
        'g1': panel['g1_emp_abs_decline'].astype(float),
        'g2': panel['g2_emp_rel_decline'].astype(float),
        'g3': panel['g3_prod_decline_nominal'].astype(float),
        'g4': panel['g4_delta00'].astype(float),
    }, index=panel.index)
    return panel, values


# ---------------------------------------------------------------- optimistic_assignment
def test_optimistic_matches_pessimistic_at_qp_zero_on_full_panel():
    """앵커: 비관적·낙관적 배정은 v1.0에서 160/160 완전 일치, UNDETERMINED 20."""
    _, values = load_panel_values()
    s = scenario()
    pess = electre.evaluate(values, s)['display_class_by_scenario'].tolist()
    opt = electre.optimistic_assignment(values, s).tolist()
    assert opt == pess  # 180행 전체(UNDETERMINED 포함) 완전 일치
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).tolist()
    n_scorable = sum(scorable)
    n_scorable_match = sum(a == b for a, b, ok in zip(opt, pess, scorable) if ok)
    assert n_scorable == 160
    assert n_scorable_match == 160  # 완전관측 160행 중 160행 일치(앵커: 160/160)
    assert pess.count(config.UNDETERMINED) == 20
    assert opt.count(config.UNDETERMINED) == 20


def test_optimistic_rank_never_below_pessimistic():
    """일반 q·p(veto 없음)에서 낙관적 배정 등급은 항상 비관적 배정 등급 이상이다."""
    rng = np.random.default_rng(7)
    crit = config.CRITERIA
    s = electre.Scenario('T', {'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3},
                         {'g1': 5, 'g2': 5, 'g3': 5, 'g4': 5},
                         {'g1': 15, 'g2': 15, 'g3': 15, 'g4': 15}, .5, 0, True)
    for _ in range(30):
        v = pd.DataFrame(rng.uniform(0, 20, (50, 4)), columns=crit)
        v = v.mask(rng.random((50, 4)) < 0.08)
        q = {j: 0.0 for j in crit}
        p = {j: float(rng.uniform(0, 4)) for j in crit}
        scorable = v[list(crit)].notna().all(axis=1).to_numpy()
        pess_b1 = electre.forward_outranks(v, s, 'b1', q, p, None)
        pess_b2 = electre.forward_outranks(v, s, 'b2', q, p, None)
        pess = electre.pessimistic_assignment(pess_b1, pess_b2, scorable)
        opt = electre.optimistic_assignment(v, s, q, p, None)
        for a, b, ok in zip(opt, pess, scorable):
            if not ok:
                assert a == config.UNDETERMINED and b == config.UNDETERMINED
            else:
                assert RANK[a] >= RANK[b]


# ---------------------------------------------------------------- reverse_partial_concordance
def test_reverse_partial_concordance_boundary_values():
    crisp = electre.reverse_partial_concordance(np.array([10.0, 10.0 + 1e-6]), 10.0, 0.0, 0.0)
    assert crisp[0] == 1.0
    assert crisp[1] == 0.0
    linear = electre.reverse_partial_concordance(np.array([10.0, 11.0, 12.0]), 10.0, 0.0, 2.0)
    assert np.allclose(linear, [1.0, 0.5, 0.0])
    assert np.isnan(electre.reverse_partial_concordance(np.array([np.nan]), 10.0, 0.0, 2.0)[0])
    with pytest.raises(ValueError):
        electre.reverse_partial_concordance([1], 10, 2, 1)


# ---------------------------------------------------------------- veto_blocked
def test_veto_blocked_examples():
    """veto_blocked(values, threshold): threshold는 절대 문턱값(오프셋이 아니다)."""
    values = pd.DataFrame({'g1': [9.0, 10.0, np.nan]})
    threshold = {'g1': 10}  # b2 g1=500, v=490일 때의 문턱값(=500-490)을 절대값으로 직접 지정
    blocked = electre.veto_blocked(values, threshold)
    assert blocked.tolist() == [True, False, False]
    assert electre.veto_blocked(values, None).tolist() == [False, False, False]
    assert electre.veto_blocked(values, {}).tolist() == [False, False, False]


def test_veto_on_b2_only_preserves_b1_implication():
    """b1에는 veto를 적용하지 않고 b2에만 적용해도 outranks_b2 => outranks_b1이 유지된다."""
    _, values = load_panel_values()
    s = scenario()
    veto = {'g1': 450}  # b2 전용 절대 문턱값(고전 표기 v=50에 해당하는 기록용 오프셋은 쓰지 않음)
    b1 = electre.forward_outranks(values, s, 'b1', None, None, None)
    b2 = electre.forward_outranks(values, s, 'b2', None, None, veto)
    assert not np.any(b2 & ~b1)


def test_veto_monotonicity_on_criterion_increase():
    """veto 적용 시 각 기준을 max(p_j, 1.0)만큼 증가시켜도 optimistic_assignment 등급은
    내려가지 않는다(증가방향 기준의 단조성)."""
    rng = np.random.default_rng(3)
    crit = config.CRITERIA
    s = scenario()
    v = pd.DataFrame(rng.uniform(0, 20, (40, 4)), columns=crit)
    q = {j: 0.0 for j in crit}
    p = {'g1': 100.0, 'g2': 1.0, 'g3': 2.0, 'g4': 2.0}
    veto = {'g1': 10.0, 'g2': 10.0, 'g3': 10.0, 'g4': 10.0}  # 절대 문턱값(합성 테스트 값 범위 [0,20] 중간)
    before = electre.optimistic_assignment(v, s, q, p, veto)
    before_rank = np.array([RANK[c] for c in before])
    for j in crit:
        bumped = v.copy()
        bumped[j] = bumped[j] + max(p[j], 1.0)
        after = electre.optimistic_assignment(bumped, s, q, p, veto)
        after_rank = np.array([RANK[c] for c in after])
        assert np.all(after_rank >= before_rank), f'{j} 증가 후 등급이 내려간 행이 있습니다.'


# ---------------------------------------------------------------- 중복 구현 드리프트 차단
def test_forward_outranks_matches_qp_calibration_on_real_panel():
    """electre.forward_outranks와 qp_calibration.evaluate의 outranking 공식이 갈라지지 않았는지.

    실제 패널 180행에 대해 후보 5종 × 시나리오 3종 × 경계 2개 = 30조합에서
    outranks_{h}와 concordance_{h}가 완전히 일치해야 한다(veto는 qp_calibration에 없으므로
    양쪽 모두 veto=None으로 비교한다). 하나라도 다르면 실패한다.
    """
    _, values = load_panel_values()
    base_doc = yaml.safe_load((ROOT / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))
    scenarios = {s.scenario_id: s for s in [electre.Scenario.from_block(b) for b in base_doc['scenarios']]}
    cand_doc = yaml.safe_load(
        (ROOT / 'config/electre_tri_b_params.v1.1-candidates.yaml').read_text(encoding='utf-8'))
    candidates = {c['candidate_id']: c for c in cand_doc['candidates']}
    assert set(candidates) == {'v1.0_crisp', 'A_narrow', 'B_medium', 'C_wide', 'D_small_indifference'}

    mismatches = []
    n_checked = 0
    for cid, cand in candidates.items():
        for sid, s in scenarios.items():
            qp_ev = qp.evaluate(values, s, cand)
            for h in electre.BOUNDARIES:
                n_checked += 1
                mine_outranks = electre.forward_outranks(values, s, h, cand['q'], cand['p'], None)
                their_outranks_raw = qp_ev[f'outranks_{h}']
                their_outranks = np.array([False if pd.isna(x) else bool(x) for x in their_outranks_raw])
                if not np.array_equal(mine_outranks, their_outranks):
                    mismatches.append((cid, sid, h, 'outranks',
                                       int(np.sum(mine_outranks != their_outranks))))

                crit = config.CRITERIA
                prof = s.profile(h)
                c = {j: electre._pseudo_partial_concordance(  # noqa: SLF001 (같은 모듈 내부 공식 대조)
                    values[j], prof[j], float(cand['q'][j]), float(cand['p'][j])) for j in crit}
                scorable = values[list(crit)].notna().all(axis=1).to_numpy()
                mine_concordance = np.where(
                    scorable, sum(s.weights[j] * np.nan_to_num(c[j]) for j in crit), np.nan)
                their_concordance = qp_ev[f'concordance_{h}'].to_numpy()
                if not np.allclose(mine_concordance, their_concordance, equal_nan=True):
                    mismatches.append((cid, sid, h, 'concordance', None))

    assert n_checked == 30, f'30조합(5후보×3시나리오×2경계)이어야 하는데 {n_checked}건 검사됨'
    assert not mismatches, f'electre.forward_outranks와 qp_calibration.evaluate가 갈라졌습니다: {mismatches}'


# ---------------------------------------------------------------- prereg.py
def draft_doc(status='DRAFT', prereg_sha256=None):
    doc = {
        'prereg_spec_version': 'test/1.0', 'prereg_status': status,
        'base_parameter_sha256': 'placeholder', 'reference_cases': [], 'parameter_space': {},
        'qp_derivation': {}, 'veto_candidates': {}, 'perturbation': {}, 'acceptance': {},
        'registration': {'prereg_sha256': prereg_sha256},
    }
    return doc


def test_prereg_require_registered_raises_on_draft():
    with pytest.raises(prereg.PreregNotRegisteredError):
        prereg.require_registered(draft_doc())


def test_prereg_require_registered_passes_when_status_and_hash_match():
    doc = draft_doc(status='REGISTERED', prereg_sha256=None)
    correct_hash = prereg.payload_sha256(doc)  # registration은 해시 대상에서 제외되므로 이후에 채워도 된다
    doc['registration']['prereg_sha256'] = correct_hash
    prereg.require_registered(doc)  # 예외 없이 통과해야 한다


def test_prereg_require_registered_raises_when_hash_stale():
    doc = draft_doc(status='REGISTERED', prereg_sha256=None)
    correct_hash = prereg.payload_sha256(doc)
    doc['registration']['prereg_sha256'] = correct_hash
    doc['parameter_space'] = {'changed': True}  # 등록 후 본문이 바뀜 -> 해시가 더 이상 일치하지 않음
    with pytest.raises(prereg.PreregNotRegisteredError):
        prereg.require_registered(doc)


def test_prereg_load_requires_all_keys(tmp_path):
    incomplete = tmp_path / 'incomplete.yaml'
    incomplete.write_text('prereg_spec_version: t\nprereg_status: DRAFT\n', encoding='utf-8')
    with pytest.raises(prereg.PreregSchemaError):
        prereg.load(incomplete)


def test_prereg_payload_sha256_excludes_registration():
    doc_a = draft_doc(prereg_sha256=None)
    doc_b = draft_doc(prereg_sha256='different-does-not-matter')
    assert prereg.payload_sha256(doc_a) == prereg.payload_sha256(doc_b)


def test_prereg_check_base_parameter_matches_real_config_and_detects_mismatch():
    base_doc = params.load_parameter_file(ROOT / 'config/electre_tri_b_params.yaml')
    correct_hash = params.parameter_payload_sha256(base_doc)
    prereg.check_base_parameter({'base_parameter_sha256': correct_hash}, ROOT)  # 통과
    with pytest.raises(prereg.BaseParameterMismatchError):
        prereg.check_base_parameter({'base_parameter_sha256': 'deadbeef'}, ROOT)


# ---------------------------------------------------------------- electre.py append-only 증명
def _norm(s):
    return s.replace('\r\n', '\n').rstrip('\n')


def test_electre_py_is_append_only_since_head():
    """src/model/electre.py의 HEAD 버전이 현재 파일 내용의 접두사인지 확인한다.

    git이 없거나 HEAD에 이 파일이 없으면(예: 아직 한 번도 커밋되지 않은 경우) 증명
    자체가 불가능하므로 skip한다 — 실패가 아니라 '증명 불가'를 뜻한다.
    """
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip(f'git rev-parse HEAD 실패(git 저장소가 아닐 수 있음): {head.stderr.strip()}')
    old = subprocess.run(['git', 'show', 'HEAD:src/model/electre.py'], cwd=ROOT,
                         capture_output=True, text=True, encoding='utf-8')
    if old.returncode != 0:
        pytest.skip(f'git show HEAD:src/model/electre.py 실패(HEAD에 없는 파일): {old.stderr.strip()}')
    new_text = (ROOT / 'src/model/electre.py').read_text(encoding='utf-8')
    assert _norm(new_text).startswith(_norm(old.stdout)), 'electre.py가 HEAD 대비 추가-전용이 아닙니다.'
