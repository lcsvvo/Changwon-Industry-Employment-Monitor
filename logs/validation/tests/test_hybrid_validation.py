"""Exhaustive stage algebra and independent fixed-sample export checks."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hybrid_validation', ROOT / 'scripts/run_hybrid_validation.py')
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)


class HybridTests(unittest.TestCase):
    def test_all_twelve_primary_and_strict_combinations(self):
        primary = {-1: [0, 1, 2], 0: [0, 0, 2], 1: [1, 1, 2], 2: [1, 1, 2]}
        strict = {-1: [0, 1, 2], 0: [0, 0, 0], 1: [1, 1, 2], 2: [1, 1, 2]}
        for e in [-1, 0, 1, 2]:
            for t in [0, 1, 2]:
                self.assertEqual(h.combine(e, t)[0], primary[e][t])
                self.assertEqual(h.combine(e, t, True)[0], strict[e][t])

    def test_priority_identity_is_algebra_not_new_evidence(self):
        for e in [-1, 0, 1, 2]:
            for t in [0, 1, 2]:
                self.assertEqual(h.combine(e, t)[0] == 2, t == 2)
                if e >= 0:
                    self.assertEqual(h.combine(e, t)[0] >= 1, e >= 1 or t == 2)
                    self.assertEqual(h.combine(e, t, True)[0] >= 1, e >= 1)

    def test_override_and_fallback_paths(self):
        self.assertEqual(h.combine(0, 2), (2, 'strong_signal_override'))
        self.assertEqual(h.combine(0, 2, True), (0, 'strict_gate_blocks_priority'))
        for t in [0, 1, 2]:
            self.assertEqual(h.combine(-1, t)[0], t)
            self.assertEqual(h.combine(-1, t, True)[0], t)

    def test_unsupported_core_missing_stops(self):
        for e, t in [(0, -1), (-1, -1), (3, 1), (1, 3), (np.nan, 2)]:
            with self.assertRaises(ValueError):
                h.combine(e, t)

    def test_pending_not_false_negative(self):
        f = pd.DataFrame({'industry': ['a'], 'quarter': ['2022Q1'], 'label': [1], 'electre_fixed': [-1]}).set_index(h.KEY)
        r = h.score(f, 'electre_fixed', 1)
        self.assertTrue(np.isnan(r['FN']))
        self.assertEqual(r['pending_positives'], 1)
        self.assertEqual(r['valid_N'], 0)

    def test_lock_and_original_outputs_unchanged(self):
        ex = json.loads((h.OUT / 'EXECUTION_LOCK.json').read_text(encoding='utf-8'))
        pl = json.loads((h.OUT / 'PREDICTION_LOCK.json').read_text(encoding='utf-8'))
        self.assertEqual(h.protected(), ex['protected_hashes'])
        self.assertEqual(h.sha(ROOT / 'scripts/run_hybrid_validation.py'), ex['script_sha256'])
        self.assertEqual(h.sha(h.OUT / 'hybrid_predictions.csv'), pl['prediction_sha256'])
        self.assertEqual(h.sha(h.OUT / 'hybrid_overlap.csv'), pl['overlap_sha256'])

    def test_exact_original_paired_rows_and_stages(self):
        p = h.read('hybrid_predictions.csv').set_index(h.KEY).sort_index()
        member = h.read('sample_membership.csv', h.ROLL).set_index(h.KEY).sort_index()
        self.assertTrue(np.array_equal(p.paired_primary_h2, member.paired_primary_h2))
        self.assertEqual(p.paired_primary_h2.sum(), 140)
        old = h.read('predictions_long.csv', h.ROLL)
        for model in h.MODELS[:2]:
            expected = old[old.model.eq(model)].set_index(h.KEY).stage_code.sort_index()
            self.assertTrue(np.array_equal(p[model], expected))

    def test_overlap_all_twelve_cells_and_counts(self):
        p = h.read('hybrid_predictions.csv')
        labels = h.primary_labels().reset_index()[h.KEY + ['label']]
        p = p.merge(labels, on=h.KEY, how='left', validate='one_to_one')
        exported = h.read('hybrid_overlap.csv')
        self.assertEqual(len(exported), 24)
        for scope, mask in [('MAIN_COMMON_140', p.paired_primary_h2), ('ALL_ORIGINS_160', p.origin_h2)]:
            rows = exported[exported.scope.eq(scope)]
            self.assertEqual(len(rows), 12)
            for r in rows.itertuples(index=False):
                f = p[mask & p.electre_fixed.eq(r.electre_stage) & p.triage_final.eq(r.triage_stage)]
                self.assertEqual(r.N, len(f))
                self.assertEqual(r.positives, f.label.eq(1).sum())
                if len(f):
                    self.assertAlmostEqual(r.positive_rate, f.label.mean())
                else:
                    self.assertTrue(np.isnan(r.positive_rate))

    def test_exported_metrics_independent_classification(self):
        if not (h.OUT / 'hybrid_metrics.csv').exists():
            self.skipTest('Metrics not calculated yet')
        p = h.read('hybrid_predictions.csv').set_index(h.KEY).sort_index()
        f = p[p.origin_h2].join(h.primary_labels()[['label']])
        m = h.read('hybrid_metrics.csv')
        for r in m[m.record_type.eq('performance')].itertuples(index=False):
            g = f[f.paired_primary_h2]
            if r.scope == 'EMP_LT300':
                g = g[g.employment < 300]
            elif r.scope == 'EMP_GE300':
                g = g[g.employment >= 300]
            elif r.scope == 'MISSING_PRODUCTION_OPERATION_20':
                g = f[f.electre_fixed == -1]
            elif r.scope.startswith('INDUSTRY_'):
                g = g[g.index.get_level_values('industry') == r.scope[len('INDUSTRY_'):]]
            elif r.scope.startswith('ORIGIN_'):
                g = g[g.index.get_level_values('quarter') == r.scope[len('ORIGIN_'):]]
            self.assertEqual(r.N, len(g))
            if g[r.model].lt(0).any():
                self.assertTrue(np.isnan(r.TP) and np.isnan(r.FN))
                continue
            ys = g.label.to_numpy(int)
            alerts = g[r.model].to_numpy(int) >= r.cutoff
            tp, fp, fn, tn = [int(x.sum()) for x in [alerts & (ys == 1), alerts & (ys == 0), ~alerts & (ys == 1), ~alerts & (ys == 0)]]
            self.assertEqual([r.TP, r.FP, r.FN, r.TN], [tp, fp, fn, tn])
            for field, a, b in [('recall', tp, tp + fn), ('precision', tp, tp + fp), ('FPR', fp, fp + tn), ('alert_rate', tp + fp, len(g))]:
                if b:
                    self.assertAlmostEqual(getattr(r, field), a / b)
                else:
                    self.assertTrue(np.isnan(getattr(r, field)))

    def test_all_exported_hybrid_stages_from_independent_algebra(self):
        f = h.read('hybrid_predictions.csv')
        for r in f.itertuples(index=False):
            e, t = r.electre_fixed, r.triage_final
            primary = t if e == -1 else (2 if t == 2 else int(e >= 1))
            strict = t if e == -1 else (0 if e == 0 else (2 if t == 2 else 1))
            self.assertEqual(r.hybrid_primary, primary)
            self.assertEqual(r.hybrid_strict_serial, strict)

    def test_operational_capture_uses_all_observed_positives(self):
        if not (h.OUT / 'hybrid_metrics.csv').exists():
            self.skipTest('Metrics not calculated yet')
        p = h.read('hybrid_predictions.csv').set_index(h.KEY)
        f = p[p.origin_h2].join(h.primary_labels()[['label']])
        m = h.read('hybrid_metrics.csv')
        for r in m[m.record_type.eq('operational_coverage')].itertuples(index=False):
            valid = f[r.model] >= 0
            pos = f.label == 1
            selected = (f[r.model] >= r.cutoff) & valid & pos
            self.assertEqual(r.positives, int(pos.sum()))
            self.assertEqual(r.pending_positives, int((pos & ~valid).sum()))
            self.assertEqual(r.observed_alerts, int(((f[r.model] >= r.cutoff) & valid).sum()))
            self.assertAlmostEqual(r.capture_all_positives, selected.sum() / pos.sum())

    def test_case_labels_reused_and_human_review_not_fabricated(self):
        if not (h.OUT / 'hybrid_case_comparison.csv').exists():
            self.skipTest('Cases not calculated yet')
        cases = h.read('hybrid_case_comparison.csv').set_index(h.KEY).sort_index()
        labels = h.primary_labels()
        self.assertEqual(len(cases), 160)
        self.assertTrue(cases.index.equals(labels.index))
        self.assertTrue(np.array_equal(cases.label, labels.label))
        self.assertTrue(cases.human_review_status.eq('NOT_PERFORMED').all())
        self.assertTrue(cases[['reviewer', 'field_evidence', 'support_review_result']].isna().all().all())
        raw = pd.read_csv(ROOT / 'data/processed/kicox/changwon_industry_master.csv').set_index(h.KEY)
        for r in cases.reset_index().itertuples(index=False):
            lag = str(pd.Period(r.quarter, freq='Q') - 4)
            expected = raw.at[(r.industry, r.quarter), 'employment'] - raw.at[(r.industry, lag), 'employment']
            self.assertEqual(r.observed_employment_delta, expected)


if __name__ == '__main__':
    unittest.main()
