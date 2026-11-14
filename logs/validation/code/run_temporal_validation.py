"""CW-RBT-1.0 execution: immutable preflight/prediction lock, then evaluation.

Only this module's separate output directory is writable. No legacy runners,
RC/VRC filters, fitting, threshold selection or imputation are invoked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import platform
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/rolling_backtest'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'src'))
from model import triage_rule as tr

# Load only the config/panel modules needed by the archived pure functions;
# eda.__init__ otherwise eagerly imports plotting backends not needed here.
eda_pkg = types.ModuleType('eda')
eda_pkg.__path__ = [str(ROOT / 'src/eda')]
sys.modules['eda'] = eda_pkg
# Namespace package isolates archived model from the current model package.
pkg = types.ModuleType('temporal_legacy')
pkg.__path__ = [str(ROOT / 'logs/experiments/electre_mrsort/src/model')]
sys.modules['temporal_legacy'] = pkg
electre = importlib.import_module('temporal_legacy.electre')
derive = importlib.import_module('temporal_legacy.derive')
robust = importlib.import_module('temporal_legacy.robust')

NAME = '재구축 패널 기반 사후적 시간외 정합성 검증(retrospective reconstructed-panel temporal validation)'
KEY = ['industry', 'quarter']
ALLOW = KEY + ['employment', 'production', 'classification_break']
CRIT = ['g1', 'g2', 'g3', 'g4']
B1 = dict(zip(CRIT, [100, 2, 5, 2]))
B2 = dict(zip(CRIT, [500, 5, 10, 4]))
NAMED = [('electre_fixed', [.2, .2, .3, .3], .5),
         ('electre_employment', [.3, .3, .2, .2], .6),
         ('electre_persistence', [.2, .2, .2, .4], .6)]
VARIANTS = {'triage_final': {}, 'triage_A_half': {'abs_entry': .5, 'abs_up': 1},
            'triage_A_double': {'abs_entry': 2, 'abs_up': 4},
            'triage_A_removed': {'abs_entry': np.inf, 'abs_up': np.inf},
            'triage_scale_200': {'scale_min': 200}, 'triage_scale_500': {'scale_min': 500},
            'triage_no_scale': {'gate': 'none'}, 'triage_no_Q3': {'use_persist': False},
            'triage_no_P': {'use_prod': False}}
STAGE = {'관찰': 0, '추가확인': 1, '우선점검': 2, '자료확인': -1,
         'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2, 'UNDETERMINED': -1}
FIELDS = ['TP', 'FP', 'FN', 'TN', 'recall', 'precision', 'FPR', 'balanced_accuracy', 'alert_rate']
TOL = 1e-10


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(obj, path):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def save(frame, name):
    frame.to_csv(OUT / name, index=False, encoding='utf-8-sig', na_rep='NA')


def read(name):
    return pd.read_csv(OUT / name, keep_default_na=True)


def verify_freeze():
    m = json.loads((ROOT / 'outputs/rolling_backtest_protocol/FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    items = m['files'] + [{'path': m['protocol_path'], 'sha256': m['protocol_sha256_raw_bytes']}]
    bad = [i['path'] for i in items if sha(ROOT / i['path']) != i['sha256']]
    if bad:
        raise RuntimeError('STOP: frozen input/protocol hash mismatch: ' + repr(bad))
    lock = json.loads((OUT / 'EXECUTION_LOCK.json').read_text(encoding='utf-8'))
    assert lock['analysis_name'] == NAME and lock['protocol_sha256_raw_bytes'] == m['protocol_sha256_raw_bytes']
    return {i['path']: i['sha256'] for i in items}


def protected_hashes():
    folders = ['outputs/decision_support_final', 'logs/audits/independent_audit',
               'logs/experiments/electre_mrsort', 'data/reference/triage_history',
               'outputs/rolling_backtest_protocol']
    return {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p)
            for folder in folders for p in sorted((ROOT / folder).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def scenario(name, weights, lam):
    return electre.Scenario(name, dict(zip(CRIT, weights)), B1, B2, lam, 0, True)


def samples():
    space = {'parameter_space': {'lambda': {'min': .50, 'max': .75},
             'weights': {'min': .10, 'max': .40}, 'p_upper': dict(zip(CRIT, [100, 2, 5, 2])),
             'n_samples': 6000, 'seed': 2026}}
    draws = robust.sample_parameter_space(space, np.random.default_rng(2026))
    draws += [{'weights': dict(zip(CRIT, w)), 'lambda': lam,
               'p': dict.fromkeys(CRIT, 0), 'q': dict.fromkeys(CRIT, 0)} for _, w, lam in NAMED]
    return draws


def sample_hash(draws):
    return hashlib.sha256(json.dumps(draws, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rebuild(raw):
    """Pure causal rebuild; caller must supply raw prefix, never saved derivatives."""
    a = tr.compute_axes(raw[ALLOW])
    a['quarter_index'] = derive.calendar_ordinal(a.quarter)
    history = a[KEY + ['quarter_index']].assign(employment_yoy=a.e_yoy)
    risk = np.zeros(len(a), bool)
    ords = a.quarter_index.to_numpy()
    for pos in a.groupby('industry', sort=False).indices.values():
        for event in ords[pos][a.classification_break.to_numpy()[pos].astype(bool)]:
            risk[pos] |= (ords[pos] >= event) & (ords[pos] < event + 4)
    history.loc[risk, 'employment_yoy'] = np.nan
    a['g4'] = derive.emp_yoy_below_run(history, 0, a.quarter.nunique(), a.quarter.max())['run'].astype(float)
    mainhist = history[history.quarter.ge('2022Q1')].reset_index(drop=True)
    orig = derive.emp_yoy_below_run(mainhist, 0, len(mainhist), a.quarter.max())['run'].astype(float)
    orig.index = pd.MultiIndex.from_frame(mainhist[KEY])
    a['g4_original'] = orig.reindex(pd.MultiIndex.from_frame(a[KEY])).to_numpy()
    a['g1'] = (-a.emp_delta).clip(lower=0)
    a['g2'] = a.E
    a['g3'] = a.P
    # Q1 explanation: main-window state run, ending at t; never total-run/next-state.
    valid = np.isfinite(a[['e_yoy', 'p_yoy']]).all(axis=1) & ~risk
    a['q1_state'] = np.select([~valid, a.e_yoy.eq(0) | a.p_yoy.eq(0),
        a.p_yoy.gt(0) & a.e_yoy.gt(0), a.p_yoy.gt(0) & a.e_yoy.lt(0),
        a.p_yoy.lt(0) & a.e_yoy.gt(0)], ['INVALID', 'N', 'S1', 'S2', 'S3'], default='S4')
    a['q1_run_to_t'] = np.nan
    a['past_transition'] = '이전 또는 현재 상태 미확인'
    for pos in a.groupby('industry', sort=False).indices.values():
        previous, lastord, run = None, None, 0
        for j in pos:
            if a.at[j, 'quarter'] < '2022Q1':
                continue
            current = a.at[j, 'q1_state']
            if current not in ('S1', 'S2', 'S3', 'S4'):
                previous, lastord, run = None, None, 0
                continue
            contiguous = lastord is not None and ords[j] == lastord + 1
            run = run + 1 if contiguous and current == previous else 1
            a.at[j, 'q1_run_to_t'] = run
            if contiguous:
                a.at[j, 'past_transition'] = previous + '->' + current
            previous, lastord = current, ords[j]
    return a


def predict(raw, quarter, variants=True):
    prefix = raw.loc[raw.quarter.le(quarter), ALLOW].copy()
    assert prefix.quarter.max() == quarter
    a = rebuild(prefix)
    rows = []
    for model, kwargs in (VARIANTS if variants else {'triage_final': {}}).items():
        p = tr.apply_rule(a, **kwargs)
        p = p[p.quarter.eq(quarter)].copy()
        p['model'] = model
        p['stage_code'] = p.stage.map(STAGE).astype(int)
        p['max_observation_quarter'] = prefix.quarter.max()
        cols = KEY + ['model', 'stage_code', 'stage', 'stage_reason', 'employment', 'production',
            'employment_lag4', 'production_lag4', 'e_yoy', 'p_yoy', 'E', 'R', 'A', 'P',
            'g1', 'g2', 'g3', 'g4', 'g4_original', 'persist', 'emp_entry', 'emp_up',
            'data_quality_core_missing', 'data_quality_production_missing', 'q1_state',
            'q1_run_to_t', 'past_transition', 'max_observation_quarter']
        rows.append(p[cols])
    current = a[a.quarter.eq(quarter)].copy()
    for name, w, lam in NAMED:
        for original in ([False, True] if name == 'electre_fixed' and variants else [False]):
            values = current[CRIT].copy()
            if original:
                values['g4'] = current.g4_original
            e = electre.evaluate(values, scenario(name, w, lam))
            r = current.copy()
            r['model'] = 'electre_original_history' if original else name
            r['stage'] = e.display_class_by_scenario
            r['stage_code'] = r.stage.map(STAGE).astype(int)
            r['max_observation_quarter'] = prefix.quarter.max()
            rows.append(r[KEY + ['model', 'stage', 'stage_code', 'g1', 'g2', 'g3', 'g4', 'g4_original', 'max_observation_quarter']])
    for name, codes in [('always_none', np.zeros(len(current), int)), ('always_all', np.ones(len(current), int)),
                        ('current_negative_e_yoy', current.e_yoy.lt(0).astype(int).to_numpy())]:
        r = current[KEY].copy()
        r['model'], r['stage_code'] = name, codes
        rows.append(r)
    return pd.concat(rows, ignore_index=True)


def eligibility(raw, origins, h, production=False):
    lookup = raw.set_index(KEY)
    result = np.ones(len(origins), bool)
    reasons = [[] for _ in range(len(origins))]
    for k, row in enumerate(origins.itertuples(index=False)):
        qs = [str(pd.Period(row.quarter, freq='Q') + delta) for delta in [0, h, -4, h - 4]]
        for var in ['employment'] + (['production'] if production else []):
            for q in qs:
                value = lookup.at[(row.industry, q), var] if (row.industry, q) in lookup.index else np.nan
                if not np.isfinite(value) or value <= 0:
                    reasons[k].append(var + ':' + q + ':missing_or_nonpositive')
        events = raw[(raw.industry == row.industry) & raw.quarter.gt(min(qs)) & raw.quarter.le(max(qs))]
        if events.classification_break.fillna(0).astype(bool).any():
            reasons[k].append('classification_break_across_required_levels')
        result[k] = not reasons[k]
    return result, ['|'.join(r) if r else 'eligible' for r in reasons]


def preflight():
    if (OUT / 'PREDICTION_LOCK.json').exists():
        raise RuntimeError('Prediction lock already exists; refusing to overwrite it.')
    frozen, protected = verify_freeze(), protected_hashes()
    raw = pd.read_csv(ROOT / 'data/processed/kicox/changwon_industry_master.csv')
    if raw.duplicated(KEY).any() or (raw[['employment', 'production']] < 0).any().any():
        raise RuntimeError('STOP: invalid raw keys/negative levels')
    assert raw.shape[0] == 340 and raw.industry.nunique() == 10
    for _, group in raw.groupby('industry'):
        assert list(sorted(group.quarter)) == list(pd.period_range('2018Q1', '2026Q2', freq='Q').astype(str))
    # Quality flags cannot be silently treated as observed usable levels.
    badquality = []
    for var in ['employment', 'production']:
        for suffix in ['masked', 'invalid_source']:
            col = var + '_' + suffix
            if col in raw and (raw[col].fillna(0).astype(bool) & raw[var].notna()).any():
                badquality.append(col)
    if badquality:
        raise RuntimeError('STOP: unresolved raw quality flags ' + repr(badquality))
    quarters = list(pd.period_range('2022Q1', '2026Q2', freq='Q').astype(str))
    frames = []
    for quarter in quarters:
        p = predict(raw, quarter)
        frames.append(p)
        # Rebuild from altered full raw data, not a saved derived panel.
        original = rebuild(raw)
        at = original[original.quarter.eq(quarter)].reset_index(drop=True)
        cols = CRIT + ['E', 'R', 'A', 'P', 'q1_state', 'q1_run_to_t', 'past_transition']
        prefix = rebuild(raw[raw.quarter.le(quarter)])
        pd.testing.assert_frame_equal(at[cols], prefix[prefix.quarter.eq(quarter)][cols].reset_index(drop=True))
        for mode in ['zero', 'multiply']:
            altered = raw.copy()
            altered.loc[altered.quarter.gt(quarter), ['employment', 'production']] = 0 if mode == 'zero' else altered.loc[altered.quarter.gt(quarter), ['employment', 'production']] * 7.13
            rebuilt = rebuild(altered)
            pd.testing.assert_frame_equal(at[cols], rebuilt[rebuilt.quarter.eq(quarter)][cols].reset_index(drop=True))
            before = tr.apply_rule(original)
            after = tr.apply_rule(rebuilt)
            causal = ['industry', 'persist', 'stage', 'stage_reason', 'emp_entry', 'emp_up']
            pd.testing.assert_frame_equal(before[before.quarter.eq(quarter)][causal].reset_index(drop=True),
                                          after[after.quarter.eq(quarter)][causal].reset_index(drop=True))
        print('causal prefix passed:', quarter, flush=True)
    predictions = pd.concat(frames, ignore_index=True).sort_values(['quarter', 'industry', 'model']).reset_index(drop=True)
    base = predictions[predictions.model.eq('triage_final')].set_index(KEY).sort_index()
    old = pd.read_csv(ROOT / 'outputs/decision_support_final/decision_panel.csv').set_index(KEY).sort_index()
    for col in ['E', 'R', 'A', 'P', 'persist', 'stage', 'stage_reason']:
        if col in ['E', 'R', 'A', 'P']:
            assert np.allclose(base[col].astype(float), old[col], atol=1e-10, rtol=0, equal_nan=True), col
        else:
            assert (base[col] == old[col]).all(), col
    point = predictions[predictions.model.eq('electre_fixed')].set_index(KEY).sort_index()
    saved = pd.read_csv(ROOT / 'data/reference/triage_history/legacy_point.csv').set_index(KEY).sort_index()
    assert (point.stage_code == saved['v1.0_crisp']).all(), 'STOP: corrected crisp reproduction mismatch'
    original = pd.read_csv(ROOT / 'logs/experiments/electre_mrsort/data/processed/model/electre_input_panel.csv').set_index(KEY).sort_index()
    assert np.allclose(base.g4_original, original.g4_delta00, equal_nan=True), 'original g4 mismatch'
    assert base.loc[('기계', '2022Q1'), 'g4'] == 3
    assert base.loc[('기계', '2022Q1'), 'persist']
    membership = base.reset_index()[KEY + ['employment', 'data_quality_core_missing', 'data_quality_production_missing']].copy()
    membership['triage_valid'] = base.stage_code.to_numpy() >= 0
    membership['electre_valid'] = point.stage_code.to_numpy() >= 0
    for h in [1, 2]:
        membership[f'origin_h{h}'] = membership.quarter.between('2022Q1', '2026Q1' if h == 1 else '2025Q4')
        for kind, prod in [('primary', False), ('secondary', True)]:
            ok, reasons = eligibility(raw, membership[KEY], h, prod)
            membership[f'{kind}_h{h}_levels_valid'] = ok
            membership[f'{kind}_h{h}_reason'] = reasons
            membership[f'paired_{kind}_h{h}'] = membership[f'origin_h{h}'] & ok & membership.triage_valid & membership.electre_valid
    expected = {'origin_h2': 160, 'paired_primary_h2': 140, 'paired_secondary_h2': 120,
                'origin_h1': 170, 'paired_primary_h1': 150, 'paired_secondary_h1': 130}
    assert {k: int(membership[k].sum()) for k in expected} == expected
    # Assignment set is a prediction-only object, locked before outcome generation.
    draws = samples()
    values = base.reset_index()[CRIT].astype(float)
    matrix = robust.assignment_matrix(values, {'b1': B1, 'b2': B2}, draws, True, None)
    for j, (name, _, _) in enumerate(NAMED):
        p = predictions[predictions.model.eq(name)].set_index(KEY).sort_index()
        assert np.array_equal(matrix[6000 + j], p.stage_code.to_numpy())
    for i in [0, 1, 999, 3000, 5999]:
        s = draws[i]
        sc = electre.Scenario(str(i), s['weights'], B1, B2, s['lambda'], 0, True)
        a = electre.forward_outranks(values, sc, 'b1', s['q'], s['p'], None)
        b = electre.forward_outranks(values, sc, 'b2', s['q'], s['p'], None)
        direct = electre.pessimistic_assignment(a, b, values.notna().all(axis=1))
        assert np.array_equal(matrix[i], [STAGE[v] for v in direct])
    sets = base.reset_index()[KEY].copy()
    sets['model'] = 'electre_finite_parameter_set'
    sets['observed_stages'] = ['|'.join(map(str, sorted(set(matrix[:, j])))) if matrix[0, j] >= 0 else 'UNDETERMINED' for j in range(len(base))]
    sets['set_width'] = [len(set(matrix[:, j])) if matrix[0, j] >= 0 else np.nan for j in range(len(base))]
    sets['set_group'] = np.where(matrix[0] < 0, 'UNDETERMINED', np.where((matrix >= 1).all(axis=0), 'common_positive', np.where((matrix < 1).all(axis=0), 'common_negative', 'ambiguous')))
    for code in [0, 1, 2]:
        sets[f'cai_stage_{code}'] = (matrix == code).mean(axis=0)
    sets['assignment_scope'] = 'finite_6003_parameter_sample_not_continuous_certificate'
    predictions = pd.concat([predictions, sets], ignore_index=True)
    assert protected_hashes() == protected
    save(predictions, 'predictions_long.csv')
    save(membership, 'sample_membership.csv')
    dump({'analysis_name': NAME, 'frozen_hashes': frozen, 'protected_hashes': protected,
          'script_sha256': sha(__file__), 'execution_lock_sha256': sha(OUT / 'EXECUTION_LOCK.json'),
          'prediction_sha256': sha(OUT / 'predictions_long.csv'), 'membership_sha256': sha(OUT / 'sample_membership.csv'),
          'parameter_samples_sha256': sample_hash(draws), 'locked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
          'checks': {'freeze_18_hashes': 'PASS', 'raw_calendar_quality': 'PASS', 'triage_reproduction_rows': 180,
                     'corrected_electre_reproduction_rows': 180, 'original_g4_reproduction_rows': 180,
                     'prefix_invariance_origins': 18, 'future_mutations_per_origin': 2,
                     'initial_history_machine_2022Q1': 'g4=3,persist=True', 'RC_VRC_usage': 'NONE',
                     'max_available_at': 'UNVERIFIABLE', 'structural_sample_counts': expected},
          'protocol_deviations': [], 'performance_computed': False}, OUT / 'PREDICTION_LOCK.json')
    print('PREFLIGHT PASS; predictions and structural membership locked. No outcomes/metrics computed.', flush=True)


def normalize_zero(x):
    return 0.0 if np.isfinite(x) and abs(x) <= TOL else x


def outcome_rows(raw, membership):
    lookup = raw.set_index(KEY)
    rows = []
    for h in [2, 1]:
        for row in membership[membership[f'origin_h{h}']].itertuples(index=False):
            q = pd.Period(row.quarter, freq='Q')
            r = {'industry': row.industry, 'quarter': row.quarter, 'horizon': h, 'future_quarter': str(q + h)}
            for var, symbol in [('employment', 'E'), ('production', 'P')]:
                vals = [lookup.at[(row.industry, str(q + d)), var] for d in [0, h, -4, h - 4]]
                for suffix, v in zip(['t', 'future', 'lag4', 'future_lag4'], vals):
                    r[f'{symbol}_{suffix}'] = v
                if all(np.isfinite(vals)) and all(v > 0 for v in vals):
                    r['u_' + symbol] = normalize_zero(100 * (vals[1] / vals[0] - 1))
                    r['d_' + symbol] = normalize_zero(100 * ((vals[1] / vals[0]) / (vals[3] / vals[2]) - 1))
                else:
                    r['u_' + symbol] = r['d_' + symbol] = np.nan
            for kind in (['primary', 'secondary', 'magnitude_1pct', 'raw_employment_decline'] if h == 2 else ['primary']):
                prod = kind == 'secondary'
                valid = getattr(row, f'{"secondary" if prod else "primary"}_h{h}_levels_valid')
                if not valid:
                    y = np.nan
                elif kind == 'magnitude_1pct':
                    y = int((r['u_E'] <= -1 or abs(r['u_E'] + 1) <= TOL) and (r['d_E'] <= -1 or abs(r['d_E'] + 1) <= TOL))
                elif kind == 'raw_employment_decline':
                    y = int(r['u_E'] < 0)
                else:
                    y = int(r['u_E'] < 0 and r['d_E'] < 0 and (not prod or (r['u_P'] < 0 and r['d_P'] < 0)))
                rows.append(dict(r, outcome=kind, label=y, outcome_valid=bool(valid),
                                 invalid_reason=getattr(row, f'{"secondary" if prod else "primary"}_h{h}_reason')))
    return pd.DataFrame(rows)


def ratio(num, den):
    return num / den if den else np.nan


def score(y, alert, keys):
    y, alert = np.asarray(y, int), np.asarray(alert, bool)
    tp, fp, fn, tn = [int(v.sum()) for v in [alert & (y == 1), alert & (y == 0), ~alert & (y == 1), ~alert & (y == 0)]]
    positive = keys.loc[y == 1]
    recall, fpr = ratio(tp, tp + fn), ratio(fp, fp + tn)
    pi, pq = positive.industry.nunique(), positive.quarter.nunique()
    warning = len(positive) < 10 or pi < 3 or pq < 3
    return dict(N=len(y), positives=tp + fn, negatives=fp + tn, TP=tp, FP=fp, FN=fn, TN=tn,
                recall=recall, precision=ratio(tp, tp + fp), FPR=fpr,
                balanced_accuracy=(recall + 1 - fpr) / 2 if np.isfinite(recall) and np.isfinite(fpr) else np.nan,
                alert_count=tp + fp, alert_rate=ratio(tp + fp, len(y)),
                positive_industries=int(pi), positive_origin_quarters=int(pq),
                evidence_status='INSUFFICIENT_EVIDENCE' if warning else 'DESCRIPTIVE_ONLY_NO_GENERAL_WINNER')


def evaluate():
    verify_freeze()
    lock = json.loads((OUT / 'PREDICTION_LOCK.json').read_text(encoding='utf-8'))
    for file, key in [('predictions_long.csv', 'prediction_sha256'), ('sample_membership.csv', 'membership_sha256'), ('EXECUTION_LOCK.json', 'execution_lock_sha256')]:
        assert sha(OUT / file) == lock[key], 'STOP: prediction lock changed'
    assert sha(__file__) == lock['script_sha256'], 'STOP: executable changed after prediction lock'
    assert protected_hashes() == lock['protected_hashes']
    if (OUT / 'metrics_long.csv').exists():
        raise RuntimeError('Evaluation already exists; refusing to overwrite results.')
    predictions, member = read('predictions_long.csv'), read('sample_membership.csv')
    raw = pd.read_csv(ROOT / 'data/processed/kicox/changwon_industry_master.csv')
    labels = outcome_rows(raw, member)
    save(labels, 'outcomes_long.csv')
    numeric = predictions[predictions.stage_code.notna()].copy()
    numeric.stage_code = numeric.stage_code.astype(int)
    mindex = pd.MultiIndex.from_frame(member[KEY])
    metrics, evaluations, flow = [], [], []

    def experiment(name, kind='primary', h=2, mask=None, models=None, cutoffs=(1, 2), subgroups=False, scope='paired'):
        if mask is None:
            mask = member.paired_primary_h2
        models = models or ['electre_fixed', 'triage_final']
        yframe = labels[(labels.outcome == kind) & (labels.horizon == h)]
        joined = numeric[numeric.model.isin(models)].merge(yframe[KEY + ['label']], on=KEY, how='left', validate='many_to_one')
        selected = pd.Series(np.asarray(mask, bool), index=mindex)
        joined['included'] = selected.reindex(pd.MultiIndex.from_frame(joined[KEY])).to_numpy()
        joined['exclusion_reason'] = np.where(~joined.included, 'outside_locked_experiment_sample', np.where(joined.label.isna(), 'outcome_unavailable', np.where(joined.stage_code.lt(0), 'model_undetermined', 'included')))
        if joined.loc[joined.included, 'label'].isna().any() or joined.loc[joined.included, 'stage_code'].lt(0).any():
            raise RuntimeError('STOP: locked sample contains undefined label/prediction: ' + name)
        for cutoff in cutoffs:
            detail = joined[KEY + ['model', 'stage_code', 'label', 'included', 'exclusion_reason']].copy()
            detail['experiment'], detail['outcome'], detail['horizon'], detail['cutoff'], detail['scope'] = name, kind, h, cutoff, scope
            detail['alert'] = (detail.stage_code >= cutoff).where(detail.stage_code >= 0)
            detail['error_type'] = np.where(~detail.included, 'NOT_EVALUATED', np.where(detail.alert.astype(bool), np.where(detail.label.eq(1), 'TP', 'FP'), np.where(detail.label.eq(1), 'FN', 'TN')))
            evaluations.append(detail)
            groups = [('pooled', 'ALL', joined[joined.included])]
            if subgroups:
                groups += [(field, str(value), group) for field in KEY for value, group in joined[joined.included].groupby(field)]
            for groupby, value, group in groups:
                calculated = {}
                for model in models:
                    g = group[group.model.eq(model)]
                    s = score(g.label, g.stage_code >= cutoff, g[KEY].reset_index(drop=True))
                    r = dict(record_type='model_metrics', experiment=name, outcome=kind, horizon=h, cutoff=cutoff,
                             scope=scope, groupby=groupby, group_value=value, model=model, **s)
                    metrics.append(r)
                    calculated[model] = r
                if 'electre_fixed' in calculated:
                    for model in [x for x in models if x.startswith('triage')]:
                        a, b = calculated[model], calculated['electre_fixed']
                        delta = {k: a[k] - b[k] for k in FIELDS + ['alert_count']}
                        metrics.append(dict(record_type='paired_delta', experiment=name, outcome=kind, horizon=h,
                            cutoff=cutoff, scope=scope, groupby=groupby, group_value=value,
                            model=model + '_minus_electre_fixed', N=a['N'], positives=a['positives'], negatives=a['negatives'],
                            evidence_status=a['evidence_status'], **delta))

    # First and only primary comparison: fixed representative crisp vs final triage.
    experiment('MAIN', cutoffs=(1,), subgroups=True)
    print('Primary fixed-crisp vs final-triage comparison computed first.', flush=True)
    experiment('PRIORITY_CUTOFF', cutoffs=(2,), subgroups=True)
    experiment('BENCHMARKS', models=['always_none', 'always_all', 'current_negative_e_yoy'], cutoffs=(1,))
    for kind in ['magnitude_1pct', 'raw_employment_decline']:
        experiment(kind, kind=kind)
    experiment('SECONDARY', kind='secondary', mask=member.paired_secondary_h2)
    experiment('PRIMARY_SAME_SECONDARY_SAMPLE', mask=member.paired_secondary_h2)
    experiment('H1_SAME_H2_SAMPLE', h=1)
    experiment('H1_FULL_RANGE', h=1, mask=member.paired_primary_h1)
    for model in [n for n, _, _ in NAMED[1:]] + ['electre_original_history']:
        experiment(model, models=[model, 'triage_final'])
    for model in list(VARIANTS)[1:]:
        experiment(model, models=['electre_fixed', model])
    paired = member.paired_primary_h2
    for industry in sorted(member.industry.unique()):
        experiment('LEAVE_OUT_' + industry, mask=paired & member.industry.ne(industry))
    for name, extra in [('EMP_LT300', member.employment.lt(300)), ('EMP_GE300', member.employment.ge(300)),
        ('ORIGINS_2022_2023', member.quarter.le('2023Q4')), ('ORIGINS_2024_2025', member.quarter.ge('2024Q1')),
        ('NONOVERLAP_START_Q1', (pd.PeriodIndex(member.quarter, freq='Q').asi8 - pd.Period('2022Q1', freq='Q').ordinal) % 2 == 0),
        ('NONOVERLAP_START_Q2', (pd.PeriodIndex(member.quarter, freq='Q').asi8 - pd.Period('2022Q1', freq='Q').ordinal) % 2 == 1),
        ('KNOWN_ERROR_EXPOSURE_EXCLUDED', ~member.quarter.between('2024Q1', '2025Q4'))]:
        experiment(name, mask=paired & extra)
    # Operational coverage has its own scope, never substitutes for paired comparison.
    missing = member.origin_h2 & member.primary_h2_levels_valid & member.triage_valid & ~member.electre_valid
    experiment('MISSING_PRODUCTION_OPERATION', mask=missing, models=['triage_final'], scope='operational_missing_production')
    experiment('TRIAGE_ALL_ORIGINS_OPERATION', mask=member.origin_h2 & member.primary_h2_levels_valid & member.triage_valid,
               models=['triage_final'], scope='operational_all_origins')
    y = labels[(labels.outcome == 'primary') & (labels.horizon == 2)].set_index(KEY).label.reindex(mindex)
    for model in ['electre_fixed', 'triage_final']:
        stages = numeric[numeric.model.eq(model)].set_index(KEY).stage_code.reindex(mindex).to_numpy()
        allorig = member.origin_h2.to_numpy()
        valid = stages >= 0
        positive = y.eq(1).to_numpy() & allorig
        for cutoff in [1, 2]:
            flow.append(dict(scope='operational_all_origins', model=model, horizon=2, cutoff=cutoff,
                origins=int(allorig.sum()), prediction_valid=int((valid & allorig).sum()),
                prediction_pending=int((~valid & allorig).sum()), production_missing=int((member.data_quality_production_missing & member.origin_h2).sum()),
                core_missing=int((member.data_quality_core_missing & member.origin_h2).sum()),
                outcome_valid=int((y.notna().to_numpy() & allorig).sum()), paired_primary=int(paired.sum()),
                paired_secondary=int(member.paired_secondary_h2.sum()), observed_positives=int(positive.sum()),
                selected_positives=int((positive & valid & (stages >= cutoff)).sum()),
                pending_positives=int((positive & ~valid).sum()),
                capture_all_observed_positives=ratio(int((positive & valid & (stages >= cutoff)).sum()), int(positive.sum()))))
    # Supplemental finite parameter sensitivity, without RC/VRC conditioning.
    base = numeric[numeric.model.eq('triage_final')].set_index(KEY).sort_index().reset_index()
    draws = samples()
    assert sample_hash(draws) == lock['parameter_samples_sha256']
    matrix = robust.assignment_matrix(base[CRIT], {'b1': B1, 'b2': B2}, draws, True, None)
    samplemap = member.set_index(KEY).paired_primary_h2.reindex(pd.MultiIndex.from_frame(base[KEY])).to_numpy()
    ybase = labels[(labels.outcome == 'primary') & (labels.horizon == 2)].set_index(KEY).label.reindex(pd.MultiIndex.from_frame(base[KEY])).to_numpy()[samplemap]
    keys = base.loc[samplemap, KEY].reset_index(drop=True)
    parameter_rows = []
    for i, s in enumerate(draws):
        params = {f'{block}_{j}': s[block][j] for block in ['weights', 'p', 'q'] for j in CRIT}
        parameter_rows.append(dict(draw_id=i, draw_kind='random_fixed_space' if i < 6000 else NAMED[i - 6000][0],
                                   lambda_value=s['lambda'], cutoff=1, **params,
                                   **score(ybase, matrix[i, samplemap] >= 1, keys)))
    save(pd.DataFrame(parameter_rows), 'parameter_robustness_long.csv')
    sets = predictions[predictions.model.eq('electre_finite_parameter_set')].set_index(KEY).reindex(pd.MultiIndex.from_frame(base[KEY]))
    for setgroup in ['common_positive', 'ambiguous', 'common_negative']:
        sel = samplemap & sets.set_group.eq(setgroup).to_numpy()
        ys = labels[(labels.outcome == 'primary') & (labels.horizon == 2)].set_index(KEY).label.reindex(pd.MultiIndex.from_frame(base[KEY])).to_numpy()[sel]
        metrics.append(dict(record_type='set_group', experiment='FINITE_PARAMETER_SET', model='electre_finite_parameter_set',
                            scope='auxiliary_parameter_set', outcome='primary', horizon=2, cutoff=1, groupby='set_group', group_value=setgroup,
                            N=int(sel.sum()), positives=int((ys == 1).sum()), prevalence=ratio(int((ys == 1).sum()), int(sel.sum())),
                            mean_set_width=sets.loc[sel, 'set_width'].mean(), ambiguous_fraction=ratio(int((samplemap & sets.set_group.eq('ambiguous').to_numpy()).sum()), int(samplemap.sum()))))
    for policy, alert in [('conservative_common_positive', (matrix >= 1).all(axis=0)), ('aggressive_any_positive', (matrix >= 1).any(axis=0))]:
        metrics.append(dict(record_type='model_metrics', experiment='FINITE_SET_' + policy, model=policy,
                            scope='auxiliary_parameter_set', outcome='primary', horizon=2, cutoff=1, groupby='pooled', group_value='ALL',
                            **score(ybase, alert[samplemap], keys)))
    save(pd.DataFrame(metrics), 'metrics_long.csv')
    save(pd.concat(evaluations, ignore_index=True), 'evaluation_long.csv')
    save(pd.DataFrame(flow), 'operational_coverage.csv')
    assert protected_hashes() == lock['protected_hashes']
    verify_freeze()
    metadata = dict(analysis_name=NAME, protocol_id='CW-RBT-1.0', protocol_deviations=[], performance_computed=True,
                    prediction_lock_sha256=sha(OUT / 'PREDICTION_LOCK.json'), executable_sha256=sha(__file__),
                    python=sys.version, platform=platform.platform(), pandas=pd.__version__, numpy=np.__version__,
                    completed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), protected_files_unchanged=True,
                    protected_file_count=len(lock['protected_hashes']), source_provenance=raw.groupby(['employment_source', 'production_source']).size().to_dict())
    metadata['source_provenance'] = [{'employment_source': k[0], 'production_source': k[1], 'rows': int(v)} for k, v in metadata['source_provenance'].items()]
    metadata['output_hashes'] = {p.name: sha(p) for p in sorted(OUT.glob('*.csv'))}
    dump(metadata, OUT / 'RUN_METADATA.json')
    make_report()
    print('Evaluation complete. All undefined values retained as NA; protected artifacts unchanged.', flush=True)


def md_table(frame, cols):
    def fmt(v):
        if pd.isna(v):
            return 'NA'
        if isinstance(v, (float, np.floating)):
            return str(int(v)) if v.is_integer() else f'{v:.4f}'
        return str(v).replace('|', '/')
    return '\n'.join(['| ' + ' | '.join(cols) + ' |', '| ' + ' | '.join(['---'] * len(cols)) + ' |'] +
                     ['| ' + ' | '.join(fmt(v) for v in row) + ' |' for row in frame[cols].itertuples(index=False, name=None)])


def make_report():
    m, flow, params, outcomes, member = [read(n) for n in ['metrics_long.csv', 'operational_coverage.csv', 'parameter_robustness_long.csv', 'outcomes_long.csv', 'sample_membership.csv']]
    pooled = m[(m.record_type == 'model_metrics') & (m['groupby'] == 'pooled')]
    cols = ['experiment', 'cutoff', 'model', 'N', 'positives', 'TP', 'FP', 'FN', 'TN', 'recall', 'precision', 'FPR', 'balanced_accuracy', 'alert_rate', 'evidence_status']
    main = pooled[pooled.experiment.eq('MAIN')]
    mainout = outcomes[(outcomes.outcome == 'primary') & (outcomes.horizon == 2)].merge(member[KEY + ['paired_primary_h2']], on=KEY)
    positive = mainout[mainout.paired_primary_h2 & mainout.label.eq(1)]
    qrows = []
    for field in ['precision', 'recall', 'alert_rate']:
        v = params[field]
        qrows.append(dict(metric=field, defined=int(v.notna().sum()), undefined=int(v.isna().sum()), minimum=v.min(), p10=v.quantile(.1), median=v.quantile(.5), p90=v.quantile(.9), maximum=v.max()))
    undefined = pooled[pooled[['recall', 'precision', 'FPR', 'balanced_accuracy']].isna().any(axis=1)]
    text = f'''# {NAME}

CW-RBT-1.0 / 사용자 승인 후 2단계 실행 / 2026-09-18

## 1. 해석 범위와 동결 준수

공식 분석명은 위 제목이다. 2026년 고정 사양을 현재 재구축된 패널에 순차 적용한 분석이며, 당시 공표 vintage·가용시각을 복원하지 못했다. 실제 위기·지원 필요의 정답을 평가하지 않으며 일반적 모형 우열을 선언하지 않는다. 기존 자료·모형·감사 산출물과 PROTOCOL은 변경하지 않았다. PROTOCOL과 17개 입력/코드 해시, 180행 최종 트리아지 및 180행 감사 보정 ELECTRE crisp 판정을 대조하여 통과했다. 18개 origin에서 원 수준 prefix 재생성과 미래 제거·0값·배율 변경 불변성을 확인했다. 기계/2022Q1은 고용 하회 런 3, 트리아지 반복 True를 재현했다. RC/VRC는 사용하지 않았다. 입력은 업종·분기·고용·생산·classification_break만 허용했다. 미래 런·전환·저장된 파생값은 판정 입력에서 제외했다. 판정과 구조적 평가행 파일을 먼저 해시 잠금한 뒤 미래 outcome을 생성했다.

Primary/Secondary, 2022Q1~2025Q4, h=2, CHECK 이상 cutoff, 모든 민감도는 승인한 계획 그대로다. 실행상 프로토콜 이탈은 없다. 과거 설계·감사 결과에 대한 개발자의 사후지식과 연간보정본 선택은 제거하지 못한다. PROTOCOL/manifest의 '승인 대기' 표시는 1단계 역사기록으로 그대로 보존했고 2단계 승인은 EXECUTION_LOCK에 별도 기록했다.

## 2. 주 비교 — 고정 대표 crisp vs 최종 트리아지

공통 paired sample 140행, 10업종·14 유효 origin 분기. 양성 {len(positive)}행, 양성 업종 {positive.industry.nunique()}개, 양성 origin 분기 {positive.quarter.nunique()}개. 140행은 독립 사건 140개가 아니다. CHECK/추가확인 이상을 주 비교로 먼저 계산했다. 아래 비율은 0~1이다.

{md_table(main, cols)}

트리아지−고정 ELECTRE paired 차이:

{md_table(m[(m.record_type == 'paired_delta') & m.experiment.eq('MAIN') & m['groupby'].eq('pooled')], ['model'] + FIELDS)}

## 3. 참고선·우선점검 cutoff

항상 비선별의 precision은 NA이며 0으로 채우지 않았다. 현재 음의 고용 YoY 참고선은 새 운영모형으로 채택하지 않는다. 우선점검 cutoff=2는 주 비교와 별개다.

{md_table(pooled[pooled.experiment.isin(['BENCHMARKS', 'PRIORITY_CUTOFF'])], cols)}

## 4. 모든 고정 민감도 — 유리·불리·정의불가 결과 포함

변형은 각각 한 조건만 변경했다. 업종 삭제는 이미 잠근 판정/라벨의 재집계이며 R/A의 10업종 분모를 다시 계산하지 않았다. secondary는 동일 120행 primary와 함께, h=1은 동일 140행 및 확장 150행과 함께 제시한다. 알려진 원파일 오류 노출 제외는 사전 지정 2024Q1~2025Q4 origins를 제외하고 초기 이력을 유지했다. 최선 사양이나 outcome을 선택하지 않았다.

{md_table(pooled[~pooled.experiment.isin(['MAIN', 'BENCHMARKS', 'PRIORITY_CUTOFF', 'MISSING_PRODUCTION_OPERATION', 'TRIAGE_ALL_ORIGINS_OPERATION']) & ~pooled.experiment.str.startswith('FINITE_SET_')], cols)}

## 5. 사건 분산·업종 및 분기별 오류

희소/집중 경고 기준은 양성<10 또는 양성 업종<3 또는 양성 origin<3이다. 해당 경우 INSUFFICIENT_EVIDENCE를 유지한다. 기준을 넘더라도 DESCRIPTIVE_ONLY_NO_GENERAL_WINNER이며 일반적 충분성을 뜻하지 않는다. 기타는 잔여집계다.

{md_table(m[(m.record_type == 'model_metrics') & m.experiment.eq('MAIN') & ~m['groupby'].eq('pooled')], ['groupby', 'group_value', 'model', 'N', 'positives', 'TP', 'FP', 'FN', 'TN', 'recall', 'precision', 'alert_rate', 'evidence_status'])}

## 6. 부분결측 운영 포괄성 — 공통 성능과 분리

2023Q4는 생산 원 수준 결측, 2024Q4는 전년동기 생산 결측으로 YoY 계산불가다. ELECTRE 보류 20행을 관찰로 바꾸거나 FN에 섞지 않았다. 전체 origin 양성 capture의 분모는 outcome 관측 양성 전체이며 보류 양성을 별도로 기록한다.

{md_table(flow, list(flow.columns))}

{md_table(pooled[pooled.experiment.isin(['MISSING_PRODUCTION_OPERATION', 'TRIAGE_ALL_ORIGINS_OPERATION'])], cols)}

## 7. 보조 parameter-space / 유한 표본 관측 배정집합

seed=2026, 가중치 .10~.40 simplex, lambda .50~.75, p 상한 (100,2,5,2), q~U(0,p/2), 6000개 draw+3개 named crisp=6003개. 동일 theta를 전체 행에 적용했다. RC1/RC2/RC3 및 VRC 필터 없음. 연속 허용공간 전체를 인증한 possible set이 아니라 유한 표본에서 관측된 집합이다. CAI는 outcome 확률·신뢰도·신뢰구간이 아니다. 모호 행을 제외하지 않은 보수/적극 정책 둘 다 보고한다. 행별 정답 맞춤 oracle은 계산하지 않았다.

{md_table(m[m.record_type.eq('set_group')], ['group_value', 'N', 'positives', 'prevalence', 'mean_set_width', 'ambiguous_fraction'])}

{md_table(pooled[pooled.experiment.str.startswith('FINITE_SET_')], cols)}

전체 paired 140행에서 각 theta의 기술적 민감도 분포 (정책사양 분포이지 표본오차 분포 아님):

{md_table(pd.DataFrame(qrows), ['metric', 'defined', 'undefined', 'minimum', 'p10', 'median', 'p90', 'maximum'])}

## 8. 정의불가 결과

분모 0의 precision/recall/FPR/balanced accuracy는 CSV에서 NA로 보존했다. pooled 표에서 하나 이상 NA인 행 {len(undefined)}개이며 아래에 모두 포함한다. 모든 업종/분기별 NA도 metrics_long에 남겼다. parameter draw별 정의불가 수는 위 표에 공개했다. outcome 미확인은 outcomes_long의 invalid_reason에 기록했으며 비악화로 채우지 않았다.

{md_table(undefined, cols)}

## 9. 자료·결론의 한계

Primary는 u_E<0 AND d_E<0, secondary는 여기에 u_P<0 AND d_P<0를 요구한다. d는 전년 동일 이동구간의 단순 준거이며 공식 계절조정이 아니다. 입력과 outcome은 같은 고용 계열을 공유한다. 생산은 미래 단일 분기 명목 flow로 물가/물량을 분리하지 못하며 생산 단독 위축은 이 outcome에 포함되지 않는다. 순고용 감소는 개인 해고/실업 수가 아니다. 공표시각 cutoff와 실제 선행기간은 검증불가다. 중첩 horizon, 업종 반복, 분기 공통충격, 자료 보정 및 알려진 오류정정 때문에 독립표본 검정·CI·bootstrap·통상 정확도·F1·AUC·실제 lead time을 제시하지 않았다. proxy상 FP는 실제 불필요한 점검, FN은 실제 정책 실패를 의미하지 않는다.

## 10. 산출물·재현

핵심 CSV는 7개로 통합했고 parameter draw별 파일은 생성하지 않았다.

- predictions_long.csv: 18개 origin의 고정 판정·축·인과적 설명 및 유한 표본 관측 집합. 자료보류는 stage_code=-1, 집합행 stage_code=NA.
- sample_membership.csv: outcome 부호를 보기 전에 잠근 h1/h2 origin·필수 수준 가용성·paired mask와 제외 사유.
- outcomes_long.csv: 모든 h2 outcome 및 h1 primary, 필수 수준·u/d·라벨·NA 사유.
- evaluation_long.csv: 실험·모형·cutoff별 포함 여부·보류·라벨·오류 유형. NOT_EVALUATED를 FN으로 세지 않는다.
- metrics_long.csv: 주/보조/민감도·업종/분기 건수, paired_delta(트리아지−ELECTRE), set_group. paired_delta의 TP/FP/FN/TN은 차이이며 N/양성/음성은 공통 표본 수다.
- operational_coverage.csv: 전체 origins 판정률·보류 양성·capture, paired 성능과 별개.
- parameter_robustness_long.csv: 6003개 theta의 파라미터 및 각 theta 전체140행 cutoff1 결과; 개별 draw 파일 없음.

EXECUTION_LOCK.json은 승인조건, PREDICTION_LOCK.json은 라벨 생성 전 판정·평가행·표본 파라미터 해시와 검사기록, RUN_METADATA.json은 환경·출처·완료 해시·기존 산출물 불변 확인이다. 코드: scripts/run_temporal_validation.py. 실행 순서: --preflight, 검사 후 --evaluate. 기존 lock/결과가 있으면 덮어쓰기를 거부한다. PROTOCOL 원본: outputs/rolling_backtest_protocol/PROTOCOL.md. 최종모형/기존 감사 결과는 보존했다.
'''
    (OUT / 'REPORT.md').write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--evaluate', action='store_true')
    args = parser.parse_args()
    if args.preflight == args.evaluate:
        parser.error('Choose exactly one of --preflight or --evaluate')
    preflight() if args.preflight else evaluate()
