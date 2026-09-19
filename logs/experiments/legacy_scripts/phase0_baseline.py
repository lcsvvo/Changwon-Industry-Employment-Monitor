# -*- coding: utf-8 -*-
"""Phase 0: 기준선 고정(재현 앵커 대조 및 동결 대상 파일 해시 기록).

읽기 전용 스크립트. src/model 아래 어떤 파일도 수정하지 않는다.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import config, electre, qp_calibration as qp  # noqa: E402

PANEL_PATH = ROOT / 'data/processed/model/electre_input_panel.csv'
BASE_PARAMS_PATH = ROOT / 'config/electre_tri_b_params.yaml'
CANDIDATES_PATH = ROOT / 'config/electre_tri_b_params.v1.1-candidates.yaml'
HASHES_OUT = ROOT / 'outputs/revalidation_baseline_hashes.json'


def load_panel():
    panel = pd.read_csv(PANEL_PATH)
    panel.columns = [str(c).lstrip('﻿') for c in panel.columns]
    panel = panel.sort_values(['industry', 'quarter'], kind='mergesort').reset_index(drop=True)
    values = pd.DataFrame({
        'g1': panel['g1_emp_abs_decline'].astype(float),
        'g2': panel['g2_emp_rel_decline'].astype(float),
        'g3': panel['g3_prod_decline_nominal'].astype(float),
        'g4': panel['g4_delta00'].astype(float),
    }, index=panel.index)
    return panel, values


def load_scenarios():
    doc = yaml.safe_load(BASE_PARAMS_PATH.read_text(encoding='utf-8'))
    return doc, [electre.Scenario.from_block(b) for b in doc['scenarios']]


def load_candidate_d():
    doc = yaml.safe_load(CANDIDATES_PATH.read_text(encoding='utf-8'))
    return next(c for c in doc['candidates'] if c['candidate_id'] == 'D_small_indifference')


def distribution(classes):
    order = ['OBSERVE', 'CHECK', 'PRIORITY', config.UNDETERMINED]
    counts = pd.Series(classes).value_counts()
    return {k: int(counts.get(k, 0)) for k in order}


def section(title):
    print('\n' + '=' * 78)
    print(title)
    print('=' * 78)


def step_b(values, scenarios):
    section('(b) electre.evaluate — 3개 시나리오 v1.0(q=p=0) 분포')
    results = {}
    for s in scenarios:
        ev = electre.evaluate(values, s)
        dist = distribution(ev['display_class_by_scenario'])
        results[s.scenario_id] = dist
        print(f'  {s.scenario_id:8s}: {dist}')
    return results


def step_c(values, scenarios, candidate_d):
    section('(c) qp_calibration.evaluate — 3개 시나리오 후보 D 분포')
    results = {}
    for s in scenarios:
        ev = qp.evaluate(values, s, candidate_d)
        dist = distribution(ev['stage'])
        results[s.scenario_id] = dist
        print(f'  {s.scenario_id:8s}: {dist}')
    return results


def step_d(panel, values):
    section('(d) 강제 OBSERVE 집합 == employment_yoy>=0 집합 (완전관측 범위)')
    complete_mask = values.notna().all(axis=1).to_numpy()
    n_complete = int(complete_mask.sum())
    forced_mask = complete_mask & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    n_forced = int(forced_mask.sum())
    emp_nonneg_mask = complete_mask & (panel['employment_yoy'].to_numpy(dtype=float) >= 0)
    n_emp_nonneg = int(emp_nonneg_mask.sum())
    sets_equal_within_complete = bool(np.array_equal(forced_mask, emp_nonneg_mask))
    forced_keys = set(map(tuple, panel.loc[forced_mask, ['industry', 'quarter']].to_numpy()))
    emp_keys = set(map(tuple, panel.loc[emp_nonneg_mask, ['industry', 'quarter']].to_numpy()))
    symmetric_diff = sorted(forced_keys.symmetric_difference(emp_keys))
    print(f'  완전관측 행수(n_complete)           : {n_complete}')
    print(f'  g1=g2=g4=0(완전관측 내) 행수(forced): {n_forced}')
    print(f'  employment_yoy>=0(완전관측 내) 행수 : {n_emp_nonneg}')
    print(f'  두 집합 완전히 동일(boolean mask)    : {sets_equal_within_complete}')
    print(f'  대칭차집합 개수                      : {len(symmetric_diff)}')
    if symmetric_diff:
        print(f'  대칭차집합 예시(최대10개)             : {symmetric_diff[:10]}')
    return {'n_complete': n_complete, 'n_forced': n_forced, 'n_emp_nonneg': n_emp_nonneg,
            'sets_equal': sets_equal_within_complete, 'symmetric_diff_n': len(symmetric_diff)}


def step_e(scenarios):
    section('(e) 16개 기준조합 전수 — 가중규칙 vs 단순개수규칙(2개 이상+고용증거) 불일치')
    table, summary = electre.enumerate_coalitions(scenarios)
    for row in summary:
        print(f"  scenario={row['scenario_id']:8s} boundary={row['boundary']} "
              f"n_combinations={row['n_combinations']} n_disagree={row['n_disagree']} "
              f"logically_equivalent={row['logically_equivalent']}")
    disagree = table[~table['agree']]
    cols = ['scenario_id', 'boundary', 'pass_g1', 'pass_g2', 'pass_g3', 'pass_g4',
            'weighted_concordance', 'lambda', 'weighted_pass', 'simple_pass']
    print('\n  불일치 조합 상세:')
    if disagree.empty:
        print('    (없음)')
    else:
        for _, r in disagree[cols].iterrows():
            print('   ', dict(r))
    per_scenario_total = disagree.groupby('scenario_id').size().to_dict()
    print(f'\n  시나리오별 전체(두 경계 합산) 불일치 조합 수: {per_scenario_total}')
    return summary, disagree[cols].to_dict('records'), per_scenario_total


def sha256_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def step_f():
    section('(f) 동결 대상 파일 SHA-256 기록')
    targets = []
    manifest_path = ROOT / 'outputs/current_run_manifest.json'
    if manifest_path.is_file():
        targets.append(manifest_path)
    tables_dir = ROOT / 'outputs/tables'
    targets += sorted(tables_dir.glob('electre_*.csv'))
    targets += sorted(tables_dir.glob('simple_rule_*.csv'))
    targets.append(BASE_PARAMS_PATH)
    targets.append(CANDIDATES_PATH)
    # 중복 제거(순서 보존)
    seen = set()
    unique_targets = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique_targets.append(t)
    hashes = {}
    missing = []
    for t in unique_targets:
        rel = t.relative_to(ROOT).as_posix()
        if not t.is_file():
            missing.append(rel)
            continue
        hashes[rel] = sha256_bytes(t)
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'purpose': 'Phase 0 동결 대상 파일 기준선 해시(재검증 파이프라인이 이 파일들을 읽기만 하는지 감시)',
        'n_files': len(hashes),
        'missing_files': missing,
        'hashes': hashes,
    }
    HASHES_OUT.parent.mkdir(parents=True, exist_ok=True)
    HASHES_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  기록된 파일 수: {len(hashes)}')
    if missing:
        print(f'  누락(파일 없음): {missing}')
    print(f'  출력: {HASHES_OUT.relative_to(ROOT).as_posix()}')
    return payload


def compare_anchors(b_dist, c_dist, d_result, coalition_summary, coalition_disagree):
    section('재현 앵커 대조')
    anchor_v10 = {'OBSERVE': 86, 'CHECK': 41, 'PRIORITY': 33, config.UNDETERMINED: 20}
    anchor_d = {'OBSERVE': 79, 'CHECK': 46, 'PRIORITY': 35, config.UNDETERMINED: 20}
    ok = []

    got_v10 = b_dist.get('기준')
    match_v10 = got_v10 == anchor_v10
    ok.append(('기준 시나리오 v1.0 분포', match_v10, anchor_v10, got_v10))

    got_d = c_dist.get('기준')
    match_d = got_d == anchor_d
    ok.append(('기준 시나리오 후보 D 분포', match_d, anchor_d, got_d))

    match_forced_71 = d_result['n_forced'] == 71
    ok.append(('완전관측 g1=g2=g4=0 행수=71', match_forced_71, 71, d_result['n_forced']))

    match_sets_equal = d_result['sets_equal'] is True
    ok.append(('forced 집합 == employment_yoy>=0 집합', match_sets_equal, True, d_result['sets_equal']))

    # 앵커는 "기준조합"을 b1·b2 구분 없는 고유 (g1,g2,g3,g4) 조합 개수로 정의한다.
    # (같은 조합이 b1·b2 양쪽에서 불일치로 나오면 조합 수는 여전히 1이다.)
    baseline_disagree_tuples = {(r['pass_g1'], r['pass_g2'], r['pass_g3'], r['pass_g4'])
                                 for r in coalition_disagree if r['scenario_id'] == '기준'}
    n_disagree_baseline = len(baseline_disagree_tuples)
    match_baseline_coalition = n_disagree_baseline == 1
    ok.append(('기준 시나리오 crisp 불일치 고유조합 수(경계무관)=1', match_baseline_coalition, 1, n_disagree_baseline))

    all_pass = True
    for label, matched, expected, actual in ok:
        status = 'OK' if matched else 'MISMATCH'
        print(f'  [{status}] {label} — expected={expected} actual={actual}')
        if not matched:
            all_pass = False
    print(f'\n  전체 일치 여부: {"모두 일치" if all_pass else "불일치 있음 — 즉시 중단"}')
    return all_pass


def main():
    panel, values = load_panel()
    base_doc, scenarios = load_scenarios()
    candidate_d = load_candidate_d()

    print(f'입력 패널: {PANEL_PATH.relative_to(ROOT).as_posix()} (행수={len(panel)})')
    print(f'기준파라미터: {BASE_PARAMS_PATH.relative_to(ROOT).as_posix()}')
    print(f'후보D 원본: {candidate_d}')

    b_dist = step_b(values, scenarios)
    c_dist = step_c(values, scenarios, candidate_d)
    d_result = step_d(panel, values)
    coalition_summary, coalition_disagree, per_scenario_total = step_e(scenarios)
    hash_payload = step_f()

    all_pass = compare_anchors(b_dist, c_dist, d_result, coalition_summary, coalition_disagree)

    section('요약(JSON)')
    summary = {
        'panel_rows': len(panel),
        'v1_0_distribution_by_scenario': b_dist,
        'candidate_d_distribution_by_scenario': c_dist,
        'forced_observe_vs_employment_yoy_nonneg': d_result,
        'coalition_disagreement_summary': coalition_summary,
        'coalition_disagreement_rows': coalition_disagree,
        'coalition_disagreement_per_scenario_total': per_scenario_total,
        'baseline_hashes_n_files': hash_payload['n_files'],
        'anchors_all_matched': all_pass,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
