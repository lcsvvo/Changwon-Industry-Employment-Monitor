# -*- coding: utf-8 -*-
"""검증 — V1~V6 패널 검증, fixture 대조, 표현 점검, 보조자료 격리 확인.

기대값(골든값)은 이 모듈에 두지 않는다. 구조적 조건(키 중복 0, 항등식 등)만 여기서 판정하고,
현재 자료의 기대 건수·수치는 tests/fixtures의 fixture 파일과 대조한다.
"""
import json
import re

import numpy as np
import pandas as pd

from . import config, derive

G = config.CRITERION_COLUMNS


# ---------------------------------------------------------------- V1~V6
def check_v1(panel, ctx):
    rows, dup = int(len(panel)), int(panel.duplicated(['industry', 'quarter']).sum())
    expected = len(ctx.industries) * len(ctx.quarters)
    per_industry = panel.groupby('industry').size()
    return {'label': 'V1 행 수·기본키 중복', 'rows': rows, 'expected_rows_balanced': expected,
            'duplicate_keys': dup, 'industries': int(panel['industry'].nunique()),
            'quarters': int(panel['quarter'].nunique()), 'first_quarter': ctx.quarters[0],
            'latest_quarter': ctx.latest,
            'passed': bool(rows == expected and dup == 0 and per_industry.eq(len(ctx.quarters)).all())}


def check_v2(panel):
    parts = [panel[G['g1']] > 0, panel[G['g2']] > 0, panel['g4_delta00'].astype(float) >= 1]
    na = panel[[G['g1'], G['g2'], 'g4_delta00']].isna().any(axis=1)
    violations = int((~na & ((parts[0] != parts[1]) | (parts[1] != parts[2]))).sum())
    return {'label': 'V2 (g1>0) == (g2>0) == (g4_delta00>=1)', 'rows_evaluated': int((~na).sum()),
            'rows_with_missing': int(na.sum()), 'violations': violations,
            'passed': bool(violations == 0 and not na.any())}


def check_v3(panel):
    g3_na = panel[G['g3']].isna()
    direct = g3_na & panel['unscorable_propagation'].isna()
    propagated = g3_na & panel['unscorable_propagation'].notna()

    def by_quarter(mask):
        return {str(q): int(n) for q, n in panel.loc[mask, 'quarter'].value_counts().sort_index().items()}

    src, prop = by_quarter(direct), by_quarter(propagated)
    root_quarters = sorted(set(panel.loc[g3_na, 'unscorable_root_cause'].dropna()
                               .str.replace('_PRODUCTION_SOURCE_MISSING', '', regex=False)))
    description = (
        f"원천 생산 결측은 {', '.join(f'{q} {n}행' for q, n in src.items()) or '없음'}이며, "
        f"이 값이 전년동기 기준으로 사용되는 {', '.join(f'{q} {n}행' for q, n in prop.items()) or '해당 없음'}까지 "
        f"파생 결측을 발생시켜 생산 YoY 결측은 총 {int(g3_na.sum())}행이다.")
    return {'label': 'V3 g3(명목 생산감소) 결측', 'g3_missing_rows': int(g3_na.sum()),
            'g3_available_rows': int((~g3_na).sum()), 'missing_by_quarter': by_quarter(g3_na),
            'source_missing_rows_by_quarter': src, 'propagated_missing_rows_by_quarter': prop,
            'root_cause_source_quarters': root_quarters,
            'root_causes': {k: int(v) for k, v in panel.loc[g3_na, 'unscorable_root_cause'].value_counts().items()},
            'propagation': {k: int(v) for k, v in panel.loc[g3_na, 'unscorable_propagation'].value_counts().items()},
            'description': description,
            'passed': bool(panel.loc[g3_na, 'production_yoy'].isna().all()
                           and panel.loc[g3_na, 'unscorable_root_cause'].notna().all()
                           and panel.loc[~g3_na, 'production_yoy'].notna().all())}


def check_v4(panel):
    counts = panel['threshold_flag'].value_counts()
    labels = derive.threshold_flag_labels()
    unknown = sorted(set(counts.index) - set(labels))
    return {'label': 'V4 threshold 품질 플래그 건수',
            'counts': [{'label': lab, 'count': int(counts.get(lab, 0))} for lab in labels],
            'unknown_labels': unknown, 'total': int(counts.sum()),
            'passed': bool(not unknown and counts.sum() == len(panel))}


def check_v5(moves):
    s_to_s = int(moves.loc[moves['s_to_other_s'], 'n_rows'].sum()) if len(moves) else 0
    return {'label': 'V5 threshold 상향 시 S1~S4 간 직접 이동', 's_to_other_s_moves': s_to_s,
            'moves': moves.to_dict('records'), 'passed': s_to_s == 0}


def check_v6(panel, assignments=None):
    unscorable = ~panel['scorable'].astype(bool)
    stage_cols = [c for c in panel.columns if c.startswith(('concordance_', 'display_class', 'inspection_stage'))]
    result = {'label': 'V6 판정불가 행에서 concordance·점검단계 미생성',
              'unscorable_rows': int(unscorable.sum()), 'input_panel_stage_columns': stage_cols}
    if assignments is None:
        result.update({'electre_run': False, 'passed': not stage_cols,
                       'note': 'ELECTRE 미실행 — 입력 패널에 concordance·점검단계 컬럼을 만들지 않음'})
        return result
    sub = assignments[~assignments['scorable'].astype(bool)]
    ok = (sub['concordance_b1'].isna().all() and sub['concordance_b2'].isna().all()
          and sub['display_class_by_scenario'].eq(config.UNDETERMINED).all()
          and sub['inspection_stage'].isna().all()
          and len(sub) == int(unscorable.sum()) * assignments['scenario_id'].nunique())
    result.update({'electre_run': True, 'unscorable_assignment_rows': int(len(sub)), 'passed': bool(ok)})
    return result


def structural_observations(panel):
    """생산만 감소한 완전관측 행: 삭제하지 않고 구조적 관찰 대상으로 남긴다."""
    complete = panel['scorable'].astype(bool)
    only_prod = (complete & (panel[G['g3']] > 0) & (panel[G['g1']] == 0) & (panel[G['g2']] == 0)
                 & (panel['g4_delta00'].astype(float) == 0))
    return {
        'complete_rows': int(complete.sum()),
        'production_only_decline_rows': int(only_prod.sum()),
        'production_only_decline_state_counts': {k: int(v) for k, v in
                                                 panel.loc[only_prod, 'state'].value_counts().sort_index().items()},
        'note': ('명목 생산 YoY는 음수이고 고용 YoY는 0 이상인 행이다. 이 행이 경계를 통과하는지는 데이터가 아니라 '
                 '기준 구성(g1·g2·g4가 모두 고용 차원)과 파라미터 선택(w3, lambda, require_employment_evidence)에 '
                 '따라 결정된다. 행은 삭제하지 않는다.'),
    }


# ---------------------------------------------------------------- fixture 대조
def redundancy_actuals(redundancy, spec):
    """fixture가 요구한 범위·방법·기준쌍의 상관계수와 사용 행 수."""
    out = {}
    for scope, wanted in (spec or {}).items():
        sub = redundancy[redundancy['scope'] == scope]
        entry = {'n_rows_used': int(sub['n_rows_used'].iloc[0]) if len(sub) else None}
        for method, pairs in wanted.items():
            if method == 'n_rows_used':
                continue
            entry[method] = {}
            for pair in pairs:
                x, y = pair.split('_')
                hit = sub[(sub['method'] == method) & (sub['criterion_x'] == x) & (sub['criterion_y'] == y)]
                entry[method][pair] = float(hit['correlation'].iloc[0]) if len(hit) else None
        out[scope] = entry
    return out


def regression_actuals(panel, ctx, moves, expected, redundancy=None):
    """fixture의 expected와 같은 구조로 현재 값을 모은다(fixture가 요구한 행만 조회)."""
    lat = panel[panel['quarter'] == ctx.latest].set_index('industry')
    g3_na = panel[G['g3']].isna()
    out = {
        'panel': {k: v for k, v in check_v1(panel, ctx).items() if k in (expected.get('panel') or {})},
        'state_counts': {s: int((panel['state'] == s).sum()) for s in config.STATES6},
        'production_yoy': {
            'computable': int(panel['production_yoy'].notna().sum()),
            'missing': int(panel['production_yoy'].isna().sum()),
            'missing_by_quarter': check_v3(panel)['missing_by_quarter'],
            'source_missing_by_quarter': check_v3(panel)['source_missing_rows_by_quarter'],
            'propagated_missing_by_quarter': check_v3(panel)['propagated_missing_rows_by_quarter'],
        },
        'employment_core_computable': int(panel[[G['g1'], G['g2'], 'g4_delta00', 'employment_yoy']]
                                          .notna().all(axis=1).sum()),
        'threshold_flag_counts': {d['label']: d['count'] for d in check_v4(panel)['counts']},
        'threshold_s_to_s_moves': check_v5(moves)['s_to_other_s_moves'],
        'unscorable_rows': int((~panel['scorable'].astype(bool)).sum()),
        'v2_identity_violations': check_v2(panel)['violations'],
        'criteria_ranges': {col: [float(np.nanmin(panel[col].astype(float))), float(np.nanmax(panel[col].astype(float)))]
                            for col in (expected.get('criteria_ranges') or {})},
        'production_only_decline_rows': structural_observations(panel)['production_only_decline_rows'],
    }
    out['golden_rows'] = []
    for row in expected.get('golden_rows', []):
        match = panel[(panel['industry'] == row['industry']) & (panel['quarter'] == row['quarter'])]
        actual = {'industry': row['industry'], 'quarter': row['quarter']}
        for key in row:
            if key not in ('industry', 'quarter') and len(match) == 1:
                value = match.iloc[0][key]
                actual[key] = (None if pd.isna(value) else
                               bool(value) if isinstance(row[key], bool) else float(value))
        out['golden_rows'].append(actual)
    for key, column in (('g4_delta00_latest', 'g4_delta00'),
                        ('g4_delta00_latest_left_censored', 'g4_delta00_left_censored')):
        wanted = expected.get(key) or {}
        out[key] = {ind: (bool(lat.loc[ind, column]) if column.endswith('censored') else int(lat.loc[ind, column]))
                    for ind in wanted if ind in lat.index}
    out['ppi_latest'] = {}
    for ind, fields in (expected.get('ppi_latest') or {}).items():
        if ind in lat.index:
            out['ppi_latest'][ind] = {f: (None if pd.isna(lat.loc[ind, f]) else
                                          int(lat.loc[ind, f]) if f == 'ppi_candidate_n' else lat.loc[ind, f])
                                      for f in fields}
    out['ppi_full_period_direction_status_counts'] = {
        k: int(v) for k, v in panel.loc[panel['ppi_direction_status'].isin(config.PPI_COMPARABLE_STATUSES),
                                        'ppi_direction_status'].value_counts().items()}
    out['q2_baseline_latest'] = {
        ind: {f: float(lat.loc[ind, f]) for f in fields}
        for ind, fields in (expected.get('q2_baseline_latest') or {}).items() if ind in lat.index}
    if redundancy is not None and 'criteria_redundancy' in expected:
        out['criteria_redundancy'] = redundancy_actuals(redundancy, expected['criteria_redundancy'])
    del g3_na
    return out


def _compare(actual, expected, path, tolerance, mismatches):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            mismatches.append({'path': path, 'expected': expected, 'actual': actual})
            return
        for key, value in expected.items():
            if key not in actual:
                mismatches.append({'path': f'{path}.{key}', 'expected': value, 'actual': 'MISSING'})
            else:
                _compare(actual[key], value, f'{path}.{key}', tolerance, mismatches)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            mismatches.append({'path': path, 'expected': expected, 'actual': actual})
            return
        for i, (a, e) in enumerate(zip(actual, expected)):
            _compare(a, e, f'{path}[{i}]', tolerance, mismatches)
    elif isinstance(expected, bool) or expected is None or isinstance(expected, str):
        if actual != expected:
            mismatches.append({'path': path, 'expected': expected, 'actual': actual})
    elif isinstance(expected, (int, float)):
        if actual is None or isinstance(actual, str) or abs(float(actual) - float(expected)) > tolerance:
            mismatches.append({'path': path, 'expected': expected, 'actual': actual})


def compare_to_fixture(actuals, fixture, current_meta):
    """입력 해시가 같으면 불일치를 IMPLEMENTATION_REGRESSION, 다르면 FIXTURE_REFRESH_REQUIRED로 구분한다."""
    if fixture is None:
        return {'status': 'FIXTURE_NOT_FOUND', 'mismatches': []}
    meta = fixture.get('fixture_metadata', {})
    tolerances = fixture.get('tolerances', {})
    mismatches = []
    for key, expected in fixture.get('expected', {}).items():
        _compare(actuals.get(key), expected, key, float(tolerances.get(key, tolerances.get('default', 1e-9))),
                 mismatches)
    same_input = meta.get('input_sha256') == current_meta.get('input_sha256')
    if not same_input:
        status = 'FIXTURE_REFRESH_REQUIRED'
    elif mismatches:
        status = 'IMPLEMENTATION_REGRESSION'
    else:
        status = 'MATCH'
    return {'status': status, 'input_hash_matches_fixture': same_input,
            'preprocess_config_hash_matches_fixture':
                meta.get('preprocess_config_sha256') == current_meta.get('preprocess_config_sha256'),
            'fixture_input_sha256': meta.get('input_sha256'),
            'current_input_sha256': current_meta.get('input_sha256'),
            'n_mismatches': len(mismatches), 'mismatches': _jsonable(mismatches)}


# ---------------------------------------------------------------- 표현 점검
def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def wording_audit(named_texts, rules):
    """금지 표현 점검. 규칙은 tests/fixtures/model_wording_rules.json에서 읽는다."""
    if rules is None:
        return {'status': 'RULES_NOT_AVAILABLE', 'passed': None, 'violations': []}
    violations = []
    for name, text in named_texts.items():
        for literal in rules.get('forbidden_literals', []):
            if literal in text:
                violations.append({'source': name, 'rule_type': 'literal', 'rule_index':
                                   rules['forbidden_literals'].index(literal)})
        for i, pattern in enumerate(rules.get('forbidden_patterns', [])):
            if re.search(pattern, text):
                violations.append({'source': name, 'rule_type': 'pattern', 'rule_index': i})
    return {'status': 'CHECKED', 'n_sources': len(named_texts), 'violations': violations,
            'passed': not violations}


def eis_isolation_check(panel):
    eis_cols = [c for c in panel.columns if 'eis' in c.lower()]
    return {'label': 'EIS가 업종×분기 패널·점수에 들어가지 않음', 'eis_columns_in_panel': eis_cols,
            'passed': not eis_cols}


def firm_count_isolation(panel_columns, criterion_columns_used):
    firm_cols = [c for c in panel_columns if c.startswith(('firm_', 'firms_', 'emp_per_firm', 'small_firm'))]
    leaked = sorted(set(firm_cols) & set(criterion_columns_used))
    return {'label': '업체 수 관련 값이 ELECTRE 기준·점검단계에 쓰이지 않음',
            'firm_columns': firm_cols, 'criterion_columns_used': list(criterion_columns_used),
            'leaked': leaked, 'passed': not leaked}


# ---------------------------------------------------------------- JSON 변환
def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


jsonable = _jsonable
