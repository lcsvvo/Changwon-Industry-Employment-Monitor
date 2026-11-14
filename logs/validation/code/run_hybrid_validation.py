"""Fixed-output workflow audit; reuses CW-RBT-1.0 labels and sample verbatim."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/hybrid_validation'
ROLL = ROOT / 'outputs/rolling_backtest'
KEY = ['industry', 'quarter']
MODELS = ['electre_fixed', 'triage_final', 'hybrid_primary', 'hybrid_strict_serial']
NAMES = {0: 'OBSERVE', 1: 'ADDITIONAL_CHECK', 2: 'PRIORITY', -1: 'UNDETERMINED'}
OFFICIAL = '재구축 패널 기반 사후적 시간외 정합성 검증(retrospective reconstructed-panel temporal validation)'
METRICS = ['N', 'positives', 'TP', 'FP', 'FN', 'TN', 'recall', 'precision', 'FPR', 'balanced_accuracy', 'alert_rate']
sys.path.insert(0, str(ROOT / 'src'))
from model import triage_rule as tr


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(obj, name):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def save(frame, name):
    frame.to_csv(OUT / name, index=False, encoding='utf-8-sig', na_rep='NA')


def read(name, folder=OUT):
    return pd.read_csv(folder / name)


def protected():
    folders = ['outputs/rolling_backtest', 'outputs/rolling_backtest_protocol', 'outputs/decision_support_final',
               'logs/audits/independent_audit', 'logs/experiments/electre_mrsort',
               'data/reference/triage_history', 'data/reference/external_event_audit']
    paths = [p for folder in folders for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT / p for p in ['src/model/triage_rule.py', 'src/model/triage_delivery.py', 'src/run_triage_rule.py',
                               'README.md', 'notebooks/11_decision_support_final.ipynb']]
    paths += list((ROOT / 'docs/02_competition').glob('*.pdf'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(paths))}


def check_inputs():
    freeze = json.loads((ROOT / 'outputs/rolling_backtest_protocol/FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    for item in freeze['files']:
        if sha(ROOT / item['path']) != item['sha256']:
            raise RuntimeError('STOP: CW-RBT input changed: ' + item['path'])
    assert sha(ROOT / freeze['protocol_path']) == freeze['protocol_sha256_raw_bytes']
    lock = json.loads((ROLL / 'PREDICTION_LOCK.json').read_text(encoding='utf-8'))
    assert sha(ROLL / 'predictions_long.csv') == lock['prediction_sha256']
    assert sha(ROLL / 'sample_membership.csv') == lock['membership_sha256']
    meta = json.loads((ROLL / 'RUN_METADATA.json').read_text(encoding='utf-8'))
    for name, digest in meta['output_hashes'].items():
        assert sha(ROLL / name) == digest, 'STOP: rolling output changed: ' + name


def combine(e, t, strict=False):
    """No labels, axes or future values are accepted by this function."""
    if e not in (-1, 0, 1, 2) or t not in (0, 1, 2):
        raise ValueError('STOP: unsupported/unknown source stage; no new missing-core rule authorized')
    if e == -1:
        return t, 'triage_fallback_electre_undetermined'
    if strict and e == 0:
        return 0, 'strict_gate_blocks_priority' if t == 2 else ('triage_check_not_retained' if t == 1 else 'both_observe')
    if t == 2:
        return 2, 'strong_signal_override' if e == 0 else 'triage_priority_escalation'
    if e >= 1:
        return 1, 'electre_screening_candidate'
    return 0, 'triage_check_not_retained' if t == 1 else 'both_observe'


def sources():
    pred = read('predictions_long.csv', ROLL)
    base = pred[pred.model.eq('triage_final')].drop(columns=['model']).set_index(KEY).sort_index()
    e = pred[pred.model.eq('electre_fixed')].set_index(KEY).sort_index()
    assert len(base) == 180 and base.index.equals(e.index)
    assert base.stage_code.isin([0, 1, 2]).all(), 'STOP: missing Triage core'
    base['triage_final'] = base.stage_code.astype(int)
    base['electre_fixed'] = e.stage_code.astype(int)
    member = read('sample_membership.csv', ROLL).set_index(KEY).sort_index()
    assert base.index.equals(member.index)
    for field in ['origin_h2', 'paired_primary_h2', 'data_quality_production_missing']:
        if field in base:
            assert np.array_equal(base[field].to_numpy(), member[field].to_numpy())
        base[field] = member[field]
    oldeval = read('evaluation_long.csv', ROLL)
    for model in MODELS[:2]:
        old = oldeval[(oldeval.experiment == 'MAIN') & (oldeval.cutoff == 1) & (oldeval.model == model)].set_index(KEY).sort_index()
        assert old.index.equals(base.index)
        assert np.array_equal(old.included.to_numpy(), base.paired_primary_h2.to_numpy())
        assert np.array_equal(old.stage_code.to_numpy(), base[model].to_numpy())
    assert base.paired_primary_h2.sum() == 140 and base.origin_h2.sum() == 160
    return base


def primary_labels():
    old = read('outcomes_long.csv', ROLL)
    labels = old[(old.outcome == 'primary') & (old.horizon == 2)].set_index(KEY).sort_index()
    assert len(labels) == 160 and labels.label.notna().all()
    return labels


def prepare():
    if (OUT / 'EXECUTION_LOCK.json').exists():
        raise RuntimeError('Refusing to overwrite an existing Hybrid execution lock')
    check_inputs()
    snapshot = protected()
    base = sources()
    dump({'protocol_id': 'CW-HYB-1.0', 'analysis_name': OFFICIAL, 'design_exposure': 'post-CW-RBT-results workflow follow-up',
          'locked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'protocol_sha256': sha(OUT / 'PROTOCOL.md'),
          'script_sha256': sha(__file__), 'protected_hashes': snapshot,
          'models': MODELS, 'hybrid_candidates': 2, 'parameter_search': False,
          'new_outcomes': False, 'RC_VRC_used': False,
          'primary_sample': 'same CW-RBT-1.0 paired_primary_h2 140 rows', 'protocol_deviations': []}, 'EXECUTION_LOCK.json')
    labels = primary_labels()
    origin = base[base.origin_h2].join(labels[['label']], validate='one_to_one')
    overlap = []
    # MUST precede Hybrid performance, including case counts and empty cells.
    for scope, subset in [('MAIN_COMMON_140', origin[origin.paired_primary_h2]), ('ALL_ORIGINS_160', origin)]:
        for e in [-1, 0, 1, 2]:
            for t in [0, 1, 2]:
                cell = subset[(subset.electre_fixed == e) & (subset.triage_final == t)].sort_index(level=['quarter', 'industry'])
                overlap.append(dict(scope=scope, electre_stage=e, triage_stage=t, N=len(cell),
                    positives=int(cell.label.eq(1).sum()), positive_rate=cell.label.mean(),
                    representative_keys='|'.join(f'{ind}/{q}' for ind, q in cell.index[:3]),
                    selection_rule='first_three_by_quarter_then_industry_not_outcome'))
    save(pd.DataFrame(overlap), 'hybrid_overlap.csv')
    print('Overlap computed and saved BEFORE Hybrid performance.', flush=True)
    # Pair function accepts existing stages only, never the joined outcome.
    for name, strict in [('hybrid_primary', False), ('hybrid_strict_serial', True)]:
        decisions = [combine(e, t, strict) for e, t in zip(base.electre_fixed, base.triage_final)]
        base[name] = [v[0] for v in decisions]
        base[name + '_reason'] = [v[1] for v in decisions]
    assert np.array_equal(base.hybrid_primary.eq(2), base.triage_final.eq(2))
    columns = MODELS + ['hybrid_primary_reason', 'hybrid_strict_serial_reason', 'employment', 'e_yoy', 'p_yoy',
        'E', 'R', 'A', 'P', 'g1', 'g2', 'g3', 'g4', 'persist', 'stage_reason', 'q1_state', 'q1_run_to_t',
        'past_transition', 'data_quality_core_missing', 'data_quality_production_missing', 'max_observation_quarter',
        'origin_h2', 'paired_primary_h2']
    save(base[columns].reset_index(), 'hybrid_predictions.csv')
    events = pd.read_csv(ROOT / 'data/reference/external_event_audit/event_panel.csv')
    usable = events.label_usable.astype(str).str.lower().eq('true').sum()
    assert usable == 0, 'Unexpected external usable labels; they must not enter metrics regardless'
    assert protected() == snapshot
    dump({'prediction_sha256': sha(OUT / 'hybrid_predictions.csv'), 'overlap_sha256': sha(OUT / 'hybrid_overlap.csv'),
          'execution_lock_sha256': sha(OUT / 'EXECUTION_LOCK.json'), 'locked_before_hybrid_metrics': True,
          'external_label_usable_true_count': int(usable), 'outcome_join_used_for_overlap_only': True,
          'hybrid_combine_inputs': ['electre_fixed_stage', 'triage_final_stage']}, 'PREDICTION_LOCK.json')
    print('Hybrid predictions locked; no Hybrid performance calculated.', flush=True)


def div(a, b):
    return a / b if b else np.nan


def score(frame, model, cutoff):
    known = frame[model].ge(0)
    positives = frame.label.eq(1)
    pending = ~known
    pkeys = frame[positives].reset_index()
    warn = positives.sum() < 10 or pkeys.industry.nunique() < 3 or pkeys.quarter.nunique() < 3
    result = dict(N=len(frame), positives=int(positives.sum()), negatives=int((~positives).sum()),
                  valid_N=int(known.sum()), pending_N=int(pending.sum()),
                  pending_positives=int((pending & positives).sum()),
                  positive_industries=pkeys.industry.nunique(), positive_origin_quarters=pkeys.quarter.nunique(),
                  evidence_status='INSUFFICIENT_EVIDENCE' if warn else 'DESCRIPTIVE_ONLY_NO_GENERAL_WINNER')
    if pending.any():
        result.update({f: np.nan for f in ['TP', 'FP', 'FN', 'TN', 'recall', 'precision', 'FPR', 'balanced_accuracy', 'alert_count', 'alert_rate']})
        result['classification_status'] = 'UNDETERMINED_NOT_CONVERTED_TO_FN'
        return result
    alert = frame[model].ge(1) if cutoff == 1 else frame[model].eq(2)
    tp, fp, fn, tn = [int(v.sum()) for v in [alert & positives, alert & ~positives, ~alert & positives, ~alert & ~positives]]
    rec, fpr = div(tp, tp + fn), div(fp, fp + tn)
    result.update(TP=tp, FP=fp, FN=fn, TN=tn, recall=rec, precision=div(tp, tp + fp), FPR=fpr,
                  balanced_accuracy=(rec + 1 - fpr) / 2, alert_count=int(alert.sum()), alert_rate=div(int(alert.sum()), len(frame)),
                  classification_status='FULLY_SCORABLE')
    return result


def evaluate():
    if (OUT / 'hybrid_metrics.csv').exists():
        raise RuntimeError('Refusing to overwrite an existing Hybrid evaluation')
    check_inputs()
    ex = json.loads((OUT / 'EXECUTION_LOCK.json').read_text(encoding='utf-8'))
    pl = json.loads((OUT / 'PREDICTION_LOCK.json').read_text(encoding='utf-8'))
    assert sha(__file__) == ex['script_sha256'] and sha(OUT / 'PROTOCOL.md') == ex['protocol_sha256']
    assert protected() == ex['protected_hashes']
    assert sha(OUT / 'hybrid_predictions.csv') == pl['prediction_sha256']
    assert sha(OUT / 'hybrid_overlap.csv') == pl['overlap_sha256']
    assert sha(OUT / 'EXECUTION_LOCK.json') == pl['execution_lock_sha256']
    base = read('hybrid_predictions.csv').set_index(KEY).sort_index()
    origin = base[base.origin_h2].join(primary_labels(), validate='one_to_one')
    main = origin[origin.paired_primary_h2]
    old = read('metrics_long.csv', ROLL)
    # A/B reproduction is a hard gate BEFORE calculating Hybrid metrics.
    for model in MODELS[:2]:
        for cutoff, exp in [(1, 'MAIN'), (2, 'PRIORITY_CUTOFF')]:
            r = old[(old.record_type == 'model_metrics') & (old['groupby'] == 'pooled') & (old.experiment == exp) & (old.model == model)].iloc[0]
            calculated = score(main, model, cutoff)
            for field in METRICS:
                assert np.isclose(calculated[field], r[field], atol=1e-12, rtol=0, equal_nan=True), (model, field)
    metrics = []
    groups = [('MAIN_COMMON_140', main), ('EMP_LT300', main[main.employment < 300]), ('EMP_GE300', main[main.employment >= 300]),
              ('MISSING_PRODUCTION_OPERATION_20', origin[origin.electre_fixed == -1])]
    groups += [('INDUSTRY_' + name, frame) for name, frame in main.groupby(level='industry')]
    groups += [('ORIGIN_' + name, frame) for name, frame in main.groupby(level='quarter')]
    for scope, frame in groups:
        for cutoff in [1, 2]:
            for model in MODELS:
                metrics.append(dict(record_type='performance', scope=scope, model=model, cutoff=cutoff,
                                    outcome='primary', horizon=2, **score(frame, model, cutoff)))
    for model in MODELS:
        valid = origin[model].ge(0)
        for cutoff in [1, 2]:
            alert = origin[model].ge(1) if cutoff == 1 else origin[model].eq(2)
            positive = origin.label.eq(1)
            selected = alert & positive & valid
            metrics.append(dict(record_type='operational_coverage', scope='ALL_ORIGINS_160', model=model, cutoff=cutoff,
                outcome='primary', horizon=2, N=len(origin), positives=int(positive.sum()), valid_N=int(valid.sum()), pending_N=int((~valid).sum()),
                prediction_rate=float(valid.mean()), selected_positives=int(selected.sum()), pending_positives=int((positive & ~valid).sum()),
                observed_alerts=int((alert & valid).sum()), capture_all_positives=div(int(selected.sum()), int(positive.sum()))))
    save(pd.DataFrame(metrics), 'hybrid_metrics.csv')
    cases = origin.copy()
    e, t = cases.electre_fixed, cases.triage_final
    flags = {'electre_only_checkplus': e.ge(1) & t.eq(0), 'triage_priority_outside_electre_screen': e.eq(0) & t.eq(2),
        'both_screened_and_triage_priority': e.ge(1) & t.eq(2), 'both_priority': e.eq(2) & t.eq(2),
        'both_observe': e.eq(0) & t.eq(0), 'fallback': e.eq(-1), 'triage_check_not_retained': e.eq(0) & t.eq(1)}
    for name, flag in flags.items():
        cases[name] = flag
    cases['employment_stratum'] = np.where(cases.employment.lt(300), 'EMP_LT300', 'EMP_GE300')
    cases['screening_candidate'] = cases.hybrid_primary.ge(1)
    cases['priority_escalation'] = cases.hybrid_primary.eq(2)
    cases['diagnostic_question'] = cases.q1_state.map(tr.Q1_QUESTIONS)
    cases['responsible_function'] = cases.q1_state.map(tr.Q1_OWNER)
    actions = {0: '분기 모니터링; 관찰은 안전 확정이 아님', 1: '담당자 자료확인 후보 등록; 기업·현장 확인 필요성 검토',
               2: '담당자 우선 검토; 현장확인 우선순위 부여; 지원 선정 아님'}
    cases['proposed_action'] = cases.hybrid_primary.map(actions)
    cases['observed_employment_delta'] = cases.employment - cases.E_lag4
    cases['next_review_quarter'] = (pd.PeriodIndex(cases.reset_index().quarter, freq='Q') + 1).astype(str)
    cases['human_review_status'] = 'NOT_PERFORMED'
    cases['reviewer'] = cases['field_evidence'] = cases['support_review_result'] = ''
    cases['card_limit'] = '원인·기업별 위기·지원사업·예산은 결정하지 않음; outcome은 사후 audit용이며 당시 카드 입력 아님'
    save(cases.reset_index(), 'hybrid_case_comparison.csv')
    assert protected() == ex['protected_hashes']
    dump({'analysis_name': OFFICIAL, 'protocol_id': 'CW-HYB-1.0', 'protocol_deviations': [], 'new_labels': False,
          'model_tuning': False, 'parameter_search': False, 'RC_VRC_used': False, 'hybrid_candidates': 2,
          'base_model_metrics_reproduced': True, 'protected_files_unchanged': True, 'protected_file_count': len(ex['protected_hashes']),
          'python': sys.version, 'pandas': pd.__version__, 'numpy': np.__version__,
          'completed_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'executable_sha256': sha(__file__),
          'execution_lock_sha256': sha(OUT / 'EXECUTION_LOCK.json'), 'prediction_lock_sha256': sha(OUT / 'PREDICTION_LOCK.json'),
          'output_hashes': {p.name: sha(p) for p in OUT.glob('*.csv')}}, 'RUN_METADATA.json')
    print('Hybrid evaluation complete; source models, labels and outputs unchanged.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--evaluate', action='store_true')
    args = parser.parse_args()
    if args.prepare == args.evaluate:
        parser.error('Choose exactly one of --prepare or --evaluate')
    prepare() if args.prepare else evaluate()
