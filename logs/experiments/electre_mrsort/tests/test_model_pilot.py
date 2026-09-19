# -*- coding: utf-8 -*-
"""05단계 고정 단순규칙과 안정성 검증."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import config, electre, pilot  # noqa: E402

B1 = {'g1': 100, 'g2': 2, 'g3': 5, 'g4': 2}
B2 = {'g1': 500, 'g2': 5, 'g3': 10, 'g4': 4}


def scenario():
    return electre.Scenario('기준', {'g1': .2, 'g2': .2, 'g3': .3, 'g4': .3},
                            B1, B2, .5, 0.0, True)


def frame(rows):
    return pd.DataFrame(rows, columns=config.CRITERIA, dtype=float)


def test_simple_rule_is_two_of_four_not_scenario_lambda():
    s = scenario()
    s = electre.Scenario(s.scenario_id, s.weights, s.b1, s.b2, .9, s.delta_emp, True)
    out = pilot.simple_rule(frame([[100, 2, 0, 0]]), {'b1': B1, 'b2': B2}).iloc[0]
    assert out.simple_rule_stage == 'CHECK' and out.rule_pass_count_b1 == 2


def test_simple_rule_boundary_equality_and_employment_gate():
    out = pilot.simple_rule(frame([[100, 0, 5, 0], [0, 0, 10, 0], [500, 5, 0, 0],
                                   [500, np.nan, 10, 4]]), {'b1': B1, 'b2': B2})
    assert out.simple_rule_stage.tolist() == ['CHECK', 'OBSERVE', 'PRIORITY', config.UNDETERMINED]


def test_electre_lambda_equality_and_weighted_sum():
    s = scenario()
    values = frame([[100, 0, 5, 0]])
    out = electre.evaluate(values, s).iloc[0]
    assert out.concordance_b1 == .5 and bool(out.outranks_b1)


def test_monotonicity_and_dominance_reports_have_zero_violations():
    s = scenario()
    mono = pilot.monotonicity_tests(s)
    assert mono.passed.all() and mono.n_violations.sum() == 0
    panel = pd.DataFrame({'industry': ['A', 'B'], 'quarter': ['2026Q1', '2026Q1']})
    dom = pilot.dominance_tests(panel, frame([[100, 2, 5, 2], [500, 5, 10, 4]]), s)
    assert dom.passed.all() and dom.n_violations.sum() == 0


def test_leave_one_out_keeps_base_complete_case_scope():
    s = scenario()
    panel = pd.DataFrame({'industry': ['A', 'B'], 'quarter': ['2026Q1', '2026Q1']})
    values = frame([[100, 2, np.nan, 2], [100, 2, 5, 2]])
    out = pilot.leave_one_out(panel, values, s)
    missing = out[out.industry == 'A']
    assert missing.base_stage.eq(config.UNDETERMINED).all()
    assert missing.removed_stage.eq(config.UNDETERMINED).all()
    assert set(out.removal_method) == set(config.CRITERION_REMOVAL_METHODS)
