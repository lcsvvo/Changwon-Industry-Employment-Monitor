# -*- coding: utf-8 -*-
"""Regression tests for src/model/model_selection.py.

These tests verify the NEW model_selection module against the incumbent
electre/audit_tools machinery and against hand-checked closed-form values.
They never modify model_selection.py; any assertion failure here should be
read as a report of a possible discrepancy in that module, not fixed here.

Run with:
    cd /home/claude/repo && python3 -m pytest tests/test_model_selection.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, 'src')

import numpy as np
import pandas as pd
import pytest

from model import audit_tools as a, config, qp_calibration as qp, revalidation_phase5 as p5
from model import model_selection as ms

ROOT = Path(__file__).resolve().parents[1]
CRIT = list(config.CRITERIA)


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope='module')
def ctx():
    doc, current, panel, base, scenarios, candidates = p5._load_context(ROOT)
    profiles = base['scenarios'][0]['profiles']
    master = pd.read_csv(ROOT / config.PATHS['industry_master'])
    vintage = pd.read_csv(ROOT / doc['perturbation']['source'])
    zv = vintage.copy()
    zv['수정율pct'] = 0.
    values = qp.values_from_panel(
        a.coherent_revision(panel, master, zv, np.random.default_rng(99), mode='cell'))
    return dict(doc=doc, panel=panel, profiles=profiles, values=values)


@pytest.fixture(scope='module')
def doc(ctx):
    return ctx['doc']


@pytest.fixture(scope='module')
def panel(ctx):
    return ctx['panel']


@pytest.fixture(scope='module')
def profiles(ctx):
    return ctx['profiles']


@pytest.fixture(scope='module')
def values(ctx):
    return ctx['values']


@pytest.fixture(scope='module')
def ok_mask(values):
    return values.notna().all(axis=1).to_numpy()


@pytest.fixture(scope='module')
def box(doc):
    return ms.space_bounds(doc)


# ---------------------------------------------------------------- 1. count_core_bounds
def test_count_core_bounds_table():
    w_min, w_max = 0.10, 0.40
    expected = {0: (0.0, 0.0), 1: (0.1, 0.4), 2: (0.2, 0.8), 3: (0.6, 0.9), 4: (1.0, 1.0)}
    for k, (lo_exp, hi_exp) in expected.items():
        lo, hi = ms.count_core_bounds(k, w_min, w_max)
        assert lo == pytest.approx(lo_exp), f'k={k} lo mismatch: {lo} vs {lo_exp}'
        assert hi == pytest.approx(hi_exp), f'k={k} hi mismatch: {hi} vs {hi_exp}'

    lam_min = 0.50
    lam_max = 0.75
    # k<=1 can never reach lambda_min (hi < lam_min for k=0,1)
    for k in (0, 1):
        _, hi = ms.count_core_bounds(k, w_min, w_max)
        assert hi < lam_min, f'k={k} hi={hi} unexpectedly reaches lambda_min={lam_min}'
    # k=4 always reaches lambda_max (lo >= lam_max)
    lo4, _ = ms.count_core_bounds(4, w_min, w_max)
    assert lo4 >= lam_max, f'k=4 lo={lo4} does not reach lambda_max={lam_max}'


# ---------------------------------------------------------------- 2. count_core vs LP extremes
def test_count_core_matches_lp_extremes(values, profiles, doc, ok_mask):
    cc = ms.count_core(values, profiles, doc)
    lp = ms.mrsort_crisp_sets(values, profiles, doc, cases=())

    for pos in range(len(values)):
        if not ok_mask[pos]:
            continue
        singleton_observe = bool(lp[pos, 0] and not lp[pos, 1] and not lp[pos, 2])
        singleton_priority = bool(lp[pos, 2] and not lp[pos, 0] and not lp[pos, 1])
        assert (cc.loc[pos, 'pass_b1'] == 'NECESSARY_FAIL') == singleton_observe, (
            f'row {pos}: pass_b1={cc.loc[pos, "pass_b1"]} but LP singleton_observe={singleton_observe}')
        assert (cc.loc[pos, 'pass_b2'] == 'NECESSARY_PASS') == singleton_priority, (
            f'row {pos}: pass_b2={cc.loc[pos, "pass_b2"]} but LP singleton_priority={singleton_priority}')


# ---------------------------------------------------------------- 3. LP contains empirical draws
def test_mrsort_lp_contains_random_draws(values, profiles, doc, ok_mask, box):
    w_min, w_max, lam_min, lam_max = box
    rng = np.random.default_rng(20260917)
    n_draws = 5000
    samples = []
    while len(samples) < n_draws:
        batch = rng.dirichlet(np.ones(len(CRIT)), size=n_draws)
        batch = batch[(batch >= w_min).all(1) & (batch <= w_max).all(1)]
        for w in batch:
            if len(samples) >= n_draws:
                break
            lam = float(rng.uniform(lam_min, lam_max))
            samples.append({'weights': dict(zip(CRIT, map(float, w))), 'lambda': lam,
                             'q': {j: 0.0 for j in CRIT}, 'p': {j: 0.0 for j in CRIT}})

    matrix = a.fast_matrix(values, profiles, samples)
    empirical = a.sets_from_matrix(matrix)
    lp_sets = ms.mrsort_crisp_sets(values, profiles, doc, cases=())

    violations = (empirical & ~lp_sets) & ok_mask[:, None]
    n_violations = int(violations.sum())
    assert n_violations == 0, (
        f'{n_violations} (row, stage) observed empirically but not in LP possible set: '
        f'rows={np.where(violations.any(axis=1))[0].tolist()[:20]}')


# ---------------------------------------------------------------- 4. reference layers nested
def test_reference_layers_are_nested(values, profiles, doc, panel, ok_mask):
    box_only = ms.mrsort_crisp_sets(values, profiles, doc, cases=())
    rc_cases = ms.reference_cases(doc, values, panel, include=('RC',))
    rc_vrc_cases = ms.reference_cases(doc, values, panel, include=('RC', 'VRC'))
    rc_only = ms.mrsort_crisp_sets(values, profiles, doc, cases=rc_cases)
    rc_vrc = ms.mrsort_crisp_sets(values, profiles, doc, cases=rc_vrc_cases)

    viol_rc = ((~box_only) & rc_only) & ok_mask[:, None]
    viol_rcvrc = ((~rc_only) & rc_vrc) & ok_mask[:, None]
    assert int(viol_rc.sum()) == 0, 'MRSort rc_only not subset of box_only'
    assert int(viol_rcvrc.sum()) == 0, 'MRSort rc_vrc not subset of rc_only'

    no_cases = ms.ror_sets(values, [])
    ror_rc_only = ms.ror_sets(values, rc_cases)
    ror_rc_vrc = ms.ror_sets(values, rc_vrc_cases)
    viol_ror1 = ((~no_cases) & ror_rc_only) & ok_mask[:, None]
    viol_ror2 = ((~ror_rc_only) & ror_rc_vrc) & ok_mask[:, None]
    assert int(viol_ror1.sum()) == 0, 'ROR rc_only not subset of no-cases'
    assert int(viol_ror2.sum()) == 0, 'ROR rc_vrc not subset of rc_only'


# ---------------------------------------------------------------- 5. no empty possible set
def test_no_empty_possible_set(values, profiles, doc, panel, ok_mask):
    box_only = ms.mrsort_crisp_sets(values, profiles, doc, cases=())
    rc_vrc_cases = ms.reference_cases(doc, values, panel, include=('RC', 'VRC'))
    rc_vrc = ms.mrsort_crisp_sets(values, profiles, doc, cases=rc_vrc_cases)
    ror_rc_vrc = ms.ror_sets(values, rc_vrc_cases)

    for name, flags in (('mrsort_box_only', box_only), ('mrsort_rc_vrc', rc_vrc), ('ror_rc_vrc', ror_rc_vrc)):
        empty_complete = (~flags[ok_mask].any(axis=1))
        assert not empty_complete.any(), f'{name}: {empty_complete.sum()} complete rows with empty possible set'
        all_false_incomplete = (~flags[~ok_mask]).all()
        assert all_false_incomplete, f'{name}: an incomplete row has a True flag'


# ---------------------------------------------------------------- 6. ROR preference info consistent
def test_ror_preference_information_is_consistent(values, doc, panel):
    rc_cases = ms.reference_cases(doc, values, panel, include=('RC',))
    rc_vrc_cases = ms.reference_cases(doc, values, panel, include=('RC', 'VRC'))

    ok, margin = ms.ror_base_feasible(values, rc_cases)
    assert ok and margin > 0, f'RC-only preference infeasible or non-positive margin: {ok}, {margin}'

    ok, margin = ms.ror_base_feasible(values, rc_vrc_cases)
    assert ok and margin > 0, f'RC+VRC preference infeasible or non-positive margin: {ok}, {margin}'

    ok, margin = ms.ror_base_feasible(values, rc_vrc_cases, share_bounds=(0.10, 0.40))
    assert ok and margin > 0, (
        f'RC+VRC + share_bounds preference infeasible or non-positive margin: {ok}, {margin}')


# ---------------------------------------------------------------- 7. ROR reproduces reference cases
def test_ror_reproduces_reference_cases(values, doc, panel):
    rc_vrc_cases = ms.reference_cases(doc, values, panel, include=('RC', 'VRC'))
    ror_rc_vrc = ms.ror_sets(values, rc_vrc_cases)

    def row_of(case_id):
        case = next(c for c in doc['reference_cases'] if c['id'] == case_id)
        pos = panel.index[(panel.industry == case['industry']) & (panel.quarter == case['quarter'])][0]
        return case, pos

    for cid in ('RC1', 'RC2'):
        case, pos = row_of(cid)
        assert case['relation'] == 'at_least' and case['stage'] == 'CHECK', f'{cid} unexpected shape: {case}'
        assert not ror_rc_vrc[pos, 0], (
            f'{cid} (row {pos}): ROR rc_vrc possible set still allows OBSERVE, contradicting at_least CHECK: '
            f'{ror_rc_vrc[pos]}')

    case, pos = row_of('RC3')
    assert case['relation'] == 'at_most' and case['stage'] == 'OBSERVE', f'RC3 unexpected shape: {case}'
    assert not ror_rc_vrc[pos, 2], (
        f'RC3 (row {pos}): ROR rc_vrc possible set still allows PRIORITY, contradicting at_most OBSERVE: '
        f'{ror_rc_vrc[pos]}')


# ---------------------------------------------------------------- 8. dominance strict partial order
def test_dominance_matrix_is_strict_partial_order(values, ok_mask):
    frame = values[ok_mask].reset_index(drop=True)
    dom = ms.dominance_matrix(frame)
    n = len(frame)
    assert not np.diagonal(dom).any(), 'dominance matrix not irreflexive'
    both = dom & dom.T
    assert not both.any(), f'{both.sum()} (i, j) pairs with mutual dominance (not antisymmetric)'


# ---------------------------------------------------------------- 9. partial order pair counts
def test_partial_order_counts_are_consistent(values, panel):
    frame = pd.concat([panel[['industry', 'quarter']].reset_index(drop=True),
                        values.reset_index(drop=True)], axis=1)
    latest_q = sorted(frame['quarter'].unique())[-1]
    sub = frame[frame.quarter == latest_q].dropna(subset=CRIT).reset_index(drop=True)
    sub10 = sub.iloc[:10]
    assert len(sub10) == 10, f'expected 10 industries at latest quarter, got {len(sub10)}'

    _, stats, _ = ms.partial_order_summary(sub10, ['industry', 'quarter'])
    n = stats['n']
    total = stats['n_comparable_pairs'] + stats['n_equal_pairs'] + stats['n_incomparable_pairs']
    expected = n * (n - 1) // 2
    assert total == expected, (
        f'comparable({stats["n_comparable_pairs"]}) + equal({stats["n_equal_pairs"]}) + '
        f'incomparable({stats["n_incomparable_pairs"]}) = {total} != n*(n-1)/2 = {expected}')
    assert stats['n_pairs'] == expected


# ---------------------------------------------------------------- 10. boundary dominance vs count_core
def test_boundary_dominance_agrees_with_count_core(values, profiles, doc, ok_mask):
    bd = ms.boundary_dominance(values, profiles)
    cc = ms.count_core(values, profiles, doc)

    for pos in range(len(values)):
        if not ok_mask[pos]:
            continue
        assert bool(bd.loc[pos, 'dominates_b2']) == (cc.loc[pos, 'k_b2'] == 4), (
            f'row {pos}: dominates_b2={bd.loc[pos, "dominates_b2"]} but k_b2={cc.loc[pos, "k_b2"]}')
        assert bool(bd.loc[pos, 'no_pass_b1']) == (cc.loc[pos, 'k_b1'] == 0), (
            f'row {pos}: no_pass_b1={bd.loc[pos, "no_pass_b1"]} but k_b1={cc.loc[pos, "k_b1"]}')


# ---------------------------------------------------------------- 11. changepoint detection
def test_single_changepoint_detects_planted_shift():
    rng = np.random.default_rng(7)
    y = np.r_[np.zeros(10), np.full(10, 5.0)] + rng.normal(0, 1e-6, 20)
    pos, stat, pval = ms.single_changepoint(y, seed=1)
    assert abs(pos - 10) <= 1, f'planted changepoint at 10, detected at {pos}'
    assert pval < 0.05, f'planted shift should be significant, got p={pval}'

    y_noise = rng.normal(0, 1, 20)
    pos_n, stat_n, pval_n = ms.single_changepoint(y_noise, seed=1)
    assert pval_n > 0.05, f'pure noise should not be significant, got p={pval_n}'
