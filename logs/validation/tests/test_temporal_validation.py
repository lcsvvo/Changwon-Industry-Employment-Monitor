"""Independent arithmetic/denominator and lock checks for CW-RBT-1.0."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('temporal_validation', ROOT / 'scripts/run_temporal_validation.py')
v = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v
spec.loader.exec_module(v)


class TemporalValidationTests(unittest.TestCase):
    def test_denominator_zero_stays_nan(self):
        keys = pd.DataFrame({'industry': ['a', 'b'], 'quarter': ['2022Q1', '2022Q2']})
        noalerts = v.score([1, 0], [False, False], keys)
        self.assertTrue(np.isnan(noalerts['precision']))
        self.assertEqual(noalerts['recall'], 0)
        nopos = v.score([0, 0], [True, False], keys)
        self.assertTrue(np.isnan(nopos['recall']))
        self.assertTrue(np.isnan(nopos['balanced_accuracy']))
        noneg = v.score([1, 1], [True, False], keys)
        self.assertTrue(np.isnan(noneg['FPR']))
        self.assertTrue(np.isnan(noneg['balanced_accuracy']))

    def test_counts_and_warning(self):
        keys = pd.DataFrame({'industry': ['a'] * 4, 'quarter': ['2022Q1'] * 4})
        result = v.score([1, 0, 1, 0], [True, True, False, False], keys)
        self.assertEqual([result[k] for k in ['TP', 'FP', 'FN', 'TN']], [1, 1, 1, 1])
        self.assertEqual(result['balanced_accuracy'], .5)
        self.assertEqual(result['evidence_status'], 'INSUFFICIENT_EVIDENCE')

    def synthetic(self):
        quarters = ['2021Q1', '2021Q3', '2022Q1', '2022Q3']
        raw = pd.DataFrame({'industry': ['a'] * 4, 'quarter': quarters,
                            'employment': [100, 110, 100, 99], 'production': [100, 110, 100, 120],
                            'classification_break': [0] * 4})
        member = pd.DataFrame({'industry': ['a'], 'quarter': ['2022Q1'], 'origin_h2': [True], 'origin_h1': [False],
                'primary_h2_levels_valid': [True], 'secondary_h2_levels_valid': [True],
                'primary_h2_reason': ['eligible'], 'secondary_h2_reason': ['eligible']})
        return raw, member

    def test_outcome_arithmetic_and_narrow_secondary(self):
        raw, member = self.synthetic()
        out = v.outcome_rows(raw, member).set_index('outcome')
        self.assertAlmostEqual(out.at['primary', 'u_E'], -1)
        self.assertAlmostEqual(out.at['primary', 'd_E'], -10)
        self.assertEqual(out.at['primary', 'label'], 1)
        self.assertEqual(out.at['magnitude_1pct', 'label'], 1)
        self.assertEqual(out.at['secondary', 'label'], 0)

    def test_seasonal_improvement_is_not_primary(self):
        raw, member = self.synthetic()
        raw.loc[raw.quarter.eq('2021Q3'), 'employment'] = 90
        out = v.outcome_rows(raw, member).set_index('outcome')
        self.assertEqual(out.at['primary', 'label'], 0)
        self.assertEqual(out.at['raw_employment_decline', 'label'], 1)

    def test_missing_secondary_not_zero(self):
        raw, member = self.synthetic()
        raw.loc[raw.quarter.eq('2022Q3'), 'production'] = np.nan
        member['secondary_h2_levels_valid'] = False
        member['secondary_h2_reason'] = 'missing'
        out = v.outcome_rows(raw, member).set_index('outcome')
        self.assertTrue(np.isnan(out.at['secondary', 'label']))
        self.assertEqual(out.at['primary', 'label'], 1)

    def test_zero_tolerance(self):
        self.assertEqual(v.normalize_zero(-1e-11), 0)
        self.assertEqual(v.normalize_zero(1e-10), 0)
        self.assertLess(v.normalize_zero(-2e-10), 0)

    def test_prediction_lock_and_paired_membership(self):
        lockpath = v.OUT / 'PREDICTION_LOCK.json'
        if not lockpath.exists():
            self.skipTest('Preflight has not finished')
        lock = json.loads(lockpath.read_text(encoding='utf-8'))
        self.assertEqual(v.sha(v.OUT / 'predictions_long.csv'), lock['prediction_sha256'])
        self.assertEqual(v.sha(v.OUT / 'sample_membership.csv'), lock['membership_sha256'])
        m = v.read('sample_membership.csv')
        self.assertEqual(m.paired_primary_h2.sum(), 140)
        self.assertEqual(m.paired_secondary_h2.sum(), 120)
        excluded = m[m.origin_h2 & ~m.paired_primary_h2]
        self.assertEqual(set(excluded.quarter), {'2023Q4', '2024Q4'})

    def test_all_exported_confusion_matrices_independently(self):
        if not (v.OUT / 'metrics_long.csv').exists():
            self.skipTest('Evaluation has not finished')
        detail = v.read('evaluation_long.csv')
        metrics = v.read('metrics_long.csv')
        ordinary = metrics[(metrics.record_type == 'model_metrics') & ~metrics.experiment.str.startswith('FINITE_SET_')]
        for row in ordinary.itertuples(index=False):
            group = detail[(detail.experiment == row.experiment) & (detail.model == row.model) &
                           (detail.cutoff == row.cutoff) & detail.included]
            if row.groupby != 'pooled':
                group = group[group[row.groupby].astype(str) == str(row.group_value)]
            counts = group.error_type.value_counts()
            tp, fp, fn, tn = [int(counts.get(k, 0)) for k in ['TP', 'FP', 'FN', 'TN']]
            self.assertEqual([row.TP, row.FP, row.FN, row.TN], [tp, fp, fn, tn])
            self.assertEqual(row.N, tp + fp + fn + tn)
            expected = {'recall': tp / (tp + fn) if tp + fn else np.nan,
                        'precision': tp / (tp + fp) if tp + fp else np.nan,
                        'FPR': fp / (fp + tn) if fp + tn else np.nan,
                        'alert_rate': (tp + fp) / row.N if row.N else np.nan}
            expected['balanced_accuracy'] = (expected['recall'] + 1 - expected['FPR']) / 2
            for field, number in expected.items():
                actual = getattr(row, field)
                if np.isnan(number):
                    self.assertTrue(np.isnan(actual), (row.experiment, field))
                else:
                    self.assertAlmostEqual(actual, number, places=12)

    def test_exported_outcomes_from_raw_levels_independently(self):
        if not (v.OUT / 'outcomes_long.csv').exists():
            self.skipTest('Evaluation has not finished')
        raw = pd.read_csv(ROOT / 'data/processed/kicox/changwon_industry_master.csv').set_index(v.KEY)
        out = v.read('outcomes_long.csv')
        self.assertEqual(len(out), 810)
        for row in out.itertuples(index=False):
            q, h = pd.Period(row.quarter, freq='Q'), row.horizon
            changes = {}
            for variable, symbol in [('employment', 'E'), ('production', 'P')]:
                levels = [raw.at[(row.industry, str(q + d)), variable] for d in [0, h, -4, h - 4]]
                if not all(np.isfinite(levels)) or not all(x > 0 for x in levels):
                    continue
                u = 100 * (levels[1] - levels[0]) / levels[0]
                d = 100 * (levels[1] * levels[2] - levels[0] * levels[3]) / (levels[0] * levels[3])
                u = 0 if abs(u) <= 1e-10 else u
                d = 0 if abs(d) <= 1e-10 else d
                self.assertAlmostEqual(getattr(row, 'u_' + symbol), u, places=10)
                self.assertAlmostEqual(getattr(row, 'd_' + symbol), d, places=10)
                changes[symbol] = (u, d)
            if not row.outcome_valid:
                self.assertTrue(np.isnan(row.label))
                continue
            u, d = changes['E']
            if row.outcome == 'magnitude_1pct':
                expected = int(u <= -1 + 1e-10 and d <= -1 + 1e-10)
            elif row.outcome == 'raw_employment_decline':
                expected = int(u < 0)
            else:
                expected = int(u < 0 and d < 0)
                if row.outcome == 'secondary':
                    expected *= int(changes['P'][0] < 0 and changes['P'][1] < 0)
            self.assertEqual(row.label, expected)

    def test_all_6003_parameters_independent_vector_evaluator(self):
        if not (v.OUT / 'parameter_robustness_long.csv').exists():
            self.skipTest('Evaluation has not finished')
        params, pred, member, labels = [v.read(n) for n in ['parameter_robustness_long.csv', 'predictions_long.csv', 'sample_membership.csv', 'outcomes_long.csv']]
        base = pred[pred.model.eq('triage_final')].set_index(v.KEY).sort_index()
        paired = member.set_index(v.KEY).paired_primary_h2.reindex(base.index).to_numpy()
        x = base.loc[paired, v.CRIT].to_numpy(float)
        w = params[['weights_' + j for j in v.CRIT]].to_numpy(float)
        p = params[['p_' + j for j in v.CRIT]].to_numpy(float)
        q = params[['q_' + j for j in v.CRIT]].to_numpy(float)
        self.assertEqual(len(params), 6003)
        self.assertTrue(np.allclose(w.sum(axis=1), 1))
        self.assertTrue(((w >= .1) & (w <= .4)).all())
        self.assertTrue(((q >= 0) & (q <= p / 2)).all())
        boundary = np.array([100, 2, 5, 2])
        support = np.empty((len(params), len(x), 4))
        # Scalar cases implemented independently of archived assignment_matrix.
        for j in range(4):
            crisp = p[:, j] == q[:, j]
            support[crisp, :, j] = x[None, :, j] >= boundary[j] - q[crisp, None, j]
            soft = ~crisp
            support[soft, :, j] = np.minimum(1, np.maximum(0,
                (x[None, :, j] - boundary[j] + p[soft, None, j]) / (p[soft, None, j] - q[soft, None, j])))
        alerts = ((support * w[:, None]).sum(axis=2) >= params.lambda_value.to_numpy()[:, None] - 1e-9)
        alerts &= (support[:, :, [0, 1, 3]] > 0).any(axis=2)
        y = labels[(labels.outcome == 'primary') & (labels.horizon == 2)].set_index(v.KEY).label.reindex(base.index).to_numpy()[paired]
        for field, counts in [('TP', (alerts & (y == 1)).sum(axis=1)), ('FP', (alerts & (y == 0)).sum(axis=1)),
                              ('FN', (~alerts & (y == 1)).sum(axis=1)), ('TN', (~alerts & (y == 0)).sum(axis=1))]:
            self.assertTrue(np.array_equal(params[field].to_numpy(), counts), field)


if __name__ == '__main__':
    unittest.main()
