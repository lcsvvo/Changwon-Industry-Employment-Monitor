# -*- coding: utf-8 -*-
"""Phase 3: 검증 설계 교체와 재판정.

electre.py의 판정 로직은 바꾸지 않는다. 계산을 새로 하는 부분(C1·C4·S1·V1·V2·V4)과
Phase 2 산출물을 읽기만 하는 부분(C2·V3)을 명확히 나눈다. veto는 전부 None —
veto는 Phase 4 항목이다.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import config, electre, manifest, prereg, qp_calibration, resample, robust
from . import revalidation as p2

RC_RANK = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
MODEL_IDS = ('v1.0_crisp', 'D_small_indifference')
SCENARIO_IDS = ('기준', '고용중시', '지속성중시')
HOUYONG_CAVEAT_DECISION = (
    '고용중시 시나리오(λ=0.60)는 v1.0 0.800 / D 0.913 으로 C2 미달. '
    'D 가 v1.0 대비 배정절차 강건성에서 개선되며, 이는 예측 타깃과 무관한 구조적 증거다.')
HOUYONG_CAVEAT_CONSENSUS = (
    '고용중시 시나리오(λ=0.60)는 비관적·낙관적 배정 일치율이 v1.0 0.800 / '
    'D 0.913 으로, 배정절차라는 임의 선택에 결과의 일부가 좌우된다. '
    '이 시나리오의 단계는 단독 근거로 쓰지 않는다.')
OVERALL_STATUSES = ('ADOPTABLE', 'BLOCKED_BY_C1', 'BLOCKED_BY_C2', 'BLOCKED_BY_C3', 'BLOCKED_BY_C4',
                    'BLOCKED_BY_S1', 'BLOCKED_MULTIPLE', 'NOT_EVALUABLE')


class NotEvaluableError(RuntimeError):
    """S1의 참조사례 양립 부분공간이 비어 있거나 표본이 100개 미만일 때."""


# ---------------------------------------------------------------- 공통 준비
def _values(panel):
    return p2._values_from_panel(panel)


def _load_panel_and_context(root):
    root = Path(root)
    current = manifest.load_manifest(root)
    if current is None:
        raise RuntimeError('outputs/current_run_manifest.json이 없습니다.')
    panel = manifest.load_current_table(root, 'input_panel')
    if panel is None or set(panel['run_id'].astype(str)) != {current['run_id']}:
        raise RuntimeError('현재 input panel과 manifest가 일치하지 않습니다.')
    panel = panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)
    base_doc = yaml.safe_load((root / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))
    scenarios = p2._load_scenarios(base_doc)
    candidates = p2._load_candidates(root)
    prereg_doc = prereg.load(root / 'config/model_revalidation_prereg.yaml')
    prereg.check_base_parameter(prereg_doc, root)
    prereg.check_parameter_space_bounds(prereg_doc, root)
    # Phase 3는 등록(REGISTERED)을 요구하지 않는다(그건 Phase 4부터다) — 단 등록됐다고
    # 실행을 거부하지도 않는다. DRAFT·REGISTERED 둘 다 유효한 상태이며 그 밖의 값만 오류다.
    if prereg_doc['prereg_status'] not in ('DRAFT', prereg.REGISTERED_STATUS):
        raise RuntimeError(f"prereg_status가 유효한 값이 아닙니다: {prereg_doc['prereg_status']!r}")
    amendment_ids = [a['id'] for a in prereg_doc['amendments']]
    if not {'AM1', 'AM2', 'AM3'} <= set(amendment_ids):
        raise RuntimeError(f'amendments에 AM1·AM2·AM3가 모두 있어야 합니다: {amendment_ids}')
    return current, panel, base_doc, scenarios, candidates, prereg_doc


def _pessimistic_stage(values, scenario, candidate):
    return p2._pessimistic(values, scenario, candidate['q'], candidate['p'], None)


# ---------------------------------------------------------------- 3-A. V1 참조사례 양립성
def reference_compatibility(matrix, panel, reference_cases, undetermined_counts_as):
    """부분공간 정의: 표본별로 모든 참조사례를 동시에 만족하는지.

    반환: (compatible_mask(n_samples,), per_case_table[case_id, sample_pass_rate])
    """
    n_samples = matrix.shape[0]
    row_of = {}
    for rc in reference_cases:
        idx = panel.index[(panel['industry'] == rc['industry']) & (panel['quarter'] == rc['quarter'])]
        if len(idx) != 1:
            raise ValueError(
                f"참조사례 {rc['id']}({rc['industry']}, {rc['quarter']})의 패널 행 위치가 "
                f'유일하지 않습니다({len(idx)}건).')
        row_of[rc['id']] = int(idx[0])

    compatible = np.ones(n_samples, dtype=bool)
    per_case_pass = {}
    for rc in reference_cases:
        col = matrix[:, row_of[rc['id']]]
        undetermined = col == -1
        scored = ~undetermined
        case_pass = np.zeros(n_samples, dtype=bool)
        case_pass[undetermined] = (undetermined_counts_as != 'fail')
        if rc['relation'] == 'at_least':
            case_pass[scored] = col[scored] >= RC_RANK[rc['stage']]
        elif rc['relation'] == 'at_most':
            case_pass[scored] = col[scored] <= RC_RANK[rc['stage']]
        else:
            raise ValueError(f"알 수 없는 relation: {rc['relation']!r}")
        per_case_pass[rc['id']] = case_pass
        compatible &= case_pass
    per_case_table = pd.DataFrame({'case_id': list(per_case_pass.keys()),
                                   'sample_pass_rate': [float(v.mean()) for v in per_case_pass.values()]})
    return compatible, per_case_table


def fixed_model_reference_pass(stage_array, panel, reference_cases, undetermined_counts_as):
    """고정모형(파라미터 표본이 아닌 단일 배정)의 참조사례 만족 여부."""
    ranks = pd.Series(stage_array).map(RC_RANK)
    results, observed = {}, {}
    for rc in reference_cases:
        idx = panel.index[(panel['industry'] == rc['industry']) & (panel['quarter'] == rc['quarter'])]
        if len(idx) != 1:
            raise ValueError(
                f"참조사례 {rc['id']}({rc['industry']}, {rc['quarter']})의 패널 행 위치가 "
                f'유일하지 않습니다({len(idx)}건).')
        pos = int(idx[0])
        observed[rc['id']] = stage_array[pos]
        r = ranks.iloc[pos]
        if pd.isna(r):
            results[rc['id']] = (undetermined_counts_as != 'fail')
        elif rc['relation'] == 'at_least':
            results[rc['id']] = bool(r >= RC_RANK[rc['stage']])
        elif rc['relation'] == 'at_most':
            results[rc['id']] = bool(r <= RC_RANK[rc['stage']])
        else:
            raise ValueError(f"알 수 없는 relation: {rc['relation']!r}")
    return results, observed


def parameter_space_matrices(panel, values, prereg_doc, base_profiles):
    """전체공간 표본·행렬과 crisp 부분공간 행렬(같은 w·λ 표집열)을 만든다."""
    rng = np.random.default_rng(prereg_doc['parameter_space']['seed'])
    samples = robust.sample_parameter_space(prereg_doc, rng)
    matrix = robust.assignment_matrix(values, base_profiles, samples, gate=True, veto=None)
    crisp_matrix = robust.assignment_matrix(values, base_profiles, p2._crisp_samples(samples), gate=True, veto=None)
    return samples, matrix, crisp_matrix


def subspace_necessary_shares(matrix, panel, values, mask=None):
    """주어진 표본 마스크(None이면 전체) 안에서 판별표본·scorable 필연배정 비율과
    n_possible 분포(1/2/3)를 계산한다."""
    m = matrix if mask is None else matrix[mask, :]
    n_samples = m.shape[0]
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced
    row_keys = panel[['industry', 'quarter']].reset_index(drop=True)
    ra = robust.robust_assignment(m, row_keys, discriminating)
    n_possible_counts = ra.loc[discriminating, 'n_possible'].value_counts()
    return {
        'n_samples': int(n_samples),
        'necessary_share_discriminating': float(ra.loc[discriminating, 'is_necessary'].mean()),
        'necessary_share_scorable': float(ra.loc[scorable, 'is_necessary'].mean()),
        'n_possible_1': int(n_possible_counts.get(1, 0)),
        'n_possible_2': int(n_possible_counts.get(2, 0)),
        'n_possible_3': int(n_possible_counts.get(3, 0)),
    }, ra


# ---------------------------------------------------------------- 3-B. V2 동시점 독립지표
def _series_value(item, key_primary, key_fallback=None):
    if key_primary in item:
        return item[key_primary]
    if key_fallback and key_fallback in item:
        return item[key_fallback]
    return None


def _discrimination_status(medians):
    m = list(medians)
    if any(pd.isna(v) for v in m):
        return 'NON_MONOTONE'  # 판정 불가능한 경우도 단조성을 주장할 수 없으므로 보수적으로 처리
    if m[0] == m[1] == m[2]:
        return 'NO_DISCRIMINATION'
    non_decreasing = m[0] <= m[1] <= m[2]
    non_increasing = m[0] >= m[1] >= m[2]
    return 'MONOTONE' if (non_decreasing or non_increasing) else 'NON_MONOTONE'


def _dist_string(series):
    counts = series.value_counts(dropna=False)
    return json.dumps({('null' if pd.isna(k) else str(k)): int(v) for k, v in counts.items()},
                      ensure_ascii=False, sort_keys=True)


def concurrent_external_validation(panel, values, scenarios, candidates, indicators):
    rows = []
    for model_id, cand in candidates.items():
        for scenario_id in SCENARIO_IDS:
            stage = _pessimistic_stage(values, scenarios[scenario_id], cand)
            stage_rank = pd.Series(stage).map(RC_RANK)
            for item in indicators:
                col = item['column']
                role = item['role']
                indicator = panel[col] if col in panel else pd.Series([np.nan] * len(panel))
                valid = stage_rank.notna() & indicator.notna()
                sp = resample.spearman(stage_rank[valid], indicator[valid])
                medians = [indicator[valid & (stage_rank == r)].median() for r in (0, 1, 2)]
                expected_sign = item.get('expected_sign')
                if role == 'supporting' and expected_sign is not None and not pd.isna(sp):
                    sign_matches = bool((sp < 0) if expected_sign == 'negative' else (sp > 0))
                else:
                    sign_matches = None
                is_ppi = col in ('ppi_adjusted_prod_yoy_upper', 'ppi_adjusted_prod_yoy_lower')
                rows.append({
                    'model_id': model_id, 'scenario_id': scenario_id, 'indicator_column': col,
                    'role': role, 'expected_sign': expected_sign, 'spearman': sp,
                    'n_valid': int(valid.sum()), 'n_missing': int((~indicator.notna()).sum()),
                    'median_observe': medians[0], 'median_check': medians[1], 'median_priority': medians[2],
                    'discrimination_status': _discrimination_status(medians),
                    'sign_matches_expectation': sign_matches, 'used_as_gate': False,
                    'caveat': item.get('caveat') or item.get('reason'),
                    'ppi_direction_status_dist': _dist_string(panel['ppi_direction_status']) if is_ppi else None,
                    'ppi_mapping_confirmation_status_dist':
                        _dist_string(panel['ppi_mapping_confirmation_status']) if is_ppi else None,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3-C/3-D. V3(읽기)·V4(신규)
def _verify_am1_applied(root, run_id):
    """그 run이 AM1(p_upper<=b1) 적용 이후 산출물인지, 저장된 per-run 표집요약으로 확인한다."""
    path = Path(root) / 'outputs/revalidation_runs' / str(run_id) / 'electre_parameter_space_summary.csv'
    if not path.is_file():
        raise RuntimeError(f'{run_id}의 electre_parameter_space_summary.csv가 보존되어 있지 않습니다.')
    sp = pd.read_csv(path)
    p_g1_max = sp.loc[sp['parameter'] == 'p_g1', 'defined_max']
    if p_g1_max.empty or float(p_g1_max.iloc[0]) > 100.0 + 1e-9:
        raise RuntimeError(f'{run_id}는 AM1(p_upper<=b1) 적용 이전 run으로 보입니다(p_g1 defined_max={p_g1_max}).')


def load_phase2_optimistic_vs_pessimistic(root):
    path = Path(root) / 'outputs/tables/electre_optimistic_vs_pessimistic.csv'
    df = pd.read_csv(path)
    run_id = str(df['run_id'].iloc[0])
    _verify_am1_applied(root, run_id)
    return df, run_id


def load_phase2_perturbation_stability(root):
    path = Path(root) / 'outputs/tables/electre_input_perturbation_stability.csv'
    df = pd.read_csv(path)
    run_id = str(df['run_id'].iloc[0])
    _verify_am1_applied(root, run_id)
    return df, run_id


def supporting_temporal_targets(panel, values, scenarios, candidates, prereg_doc, split='HOLDOUT'):
    """V4: T1·T2(비포화, 보조)와 기존 next_negative_state(retired_gate=True)를 같은 방식으로.

    스코프: 기준 시나리오, HOLDOUT 구간(2025Q1~2026Q2) — Phase 2에서 이미 보고한 유일한
    결정 관련 수치와 같은 절편이다. bootstrap 1행 + blocked LOIO 10행 = 타깃당 11행.
    """
    v1_stage = _pessimistic_stage(values, scenarios['기준'], candidates['v1.0_crisp'])
    d_stage = _pessimistic_stage(values, scenarios['기준'], candidates['D_small_indifference'])
    v1_rank = pd.Series(v1_stage).map(RC_RANK).astype(float)
    d_rank = pd.Series(d_stage).map(RC_RANK).astype(float)

    targets = p2.build_bootstrap_targets(panel)
    ig1_id = next(g['id'] for g in prereg_doc['invalidated_gates']
                 if 'next_negative_state' in g['retired'])
    definitions = {
        'T1': ('next_decline_depth', 'max(0, -다음분기 employment_yoy)', False, None),
        'T2': ('next2_both_negative', '(다음분기 employment_yoy < 0) and (2분기 후 employment_yoy < 0)',
              False, None),
        'next_negative_state': ('next_negative_state', '다음분기 state가 S2 또는 S4', True, ig1_id),
    }
    unc = prereg_doc['uncertainty_reporting']
    split_mask = p2._split_mask(panel['quarter'], split).to_numpy()

    rows = []
    for target_id, (col, definition, retired, gate_id) in definitions.items():
        outcome = targets[col]
        mask = split_mask & v1_rank.notna().to_numpy() & d_rank.notna().to_numpy() & outcome.notna().to_numpy()
        boot = resample.cluster_bootstrap_diff(v1_rank, d_rank, outcome, panel['industry'], mask,
                                                n=unc['n_bootstrap'], seed=unc['seed'])
        rows.append({'target_id': target_id, 'target_definition': definition, 'method': 'bootstrap',
                    'excluded_industry': None, 'split': split, 'spearman_v1_0': boot['point_a'],
                    'spearman_d': boot['point_b'], 'diff': boot['point_diff'], 'ci_lo': boot['ci_lo'],
                    'ci_hi': boot['ci_hi'], 'p_diff_gt_0': boot['p_diff_gt_0'],
                    'n_effective': boot['n_effective'], 'retired_gate': retired, 'invalidated_gate_id': gate_id})
        loio = resample.blocked_leave_one_out(v1_rank, d_rank, outcome, panel['industry'], mask)
        for _, r in loio.iterrows():
            rows.append({'target_id': target_id, 'target_definition': definition, 'method': 'loio',
                        'excluded_industry': r['excluded_group'], 'split': split,
                        'spearman_v1_0': r['point_a'], 'spearman_d': r['point_b'], 'diff': r['point_diff'],
                        'ci_lo': np.nan, 'ci_hi': np.nan, 'p_diff_gt_0': np.nan, 'n_effective': np.nan,
                        'retired_gate': retired, 'invalidated_gate_id': gate_id})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3-E. C1
def c1_logical_violations(values, scenarios, candidates):
    rows = []
    for model_id, cand in candidates.items():
        for scenario_id in SCENARIO_IDS:
            cons = qp_calibration.constraints(values, scenarios[scenario_id], cand)
            rows.append({'model_id': model_id, 'scenario_id': scenario_id, **cons})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3-F. 합격 판정 + 3-G 산출물
def decision_and_outputs(root, write=True):
    root = Path(root)
    current, panel, base_doc, scenarios, candidates, prereg_doc = _load_panel_and_context(root)
    values = _values(panel)
    acceptance = prereg_doc['acceptance']

    started = datetime.now(timezone.utc)
    prereg_hash = prereg.payload_sha256(prereg_doc)
    run_id = manifest.make_run_id(started, current['input_sha256'], prereg_hash)
    amendment_ids = ','.join(a['id'] for a in prereg_doc['amendments'])
    prov = {'run_id': run_id, 'run_started_at': started.isoformat(), 'input_sha256': current['input_sha256'],
           'prereg_sha256': prereg_hash, 'prereg_status': prereg_doc['prereg_status'],
           'prereg_amendment_ids': amendment_ids, 'phase': 3}

    # ---------- 파라미터 표본·배정행렬(전체공간 + crisp 부분공간) ----------
    base_profiles = next(b for b in base_doc['scenarios'] if b['scenario_id'] == '기준')['profiles']
    samples, matrix, crisp_matrix = parameter_space_matrices(panel, values, prereg_doc, base_profiles)

    # ---------- V1: 참조사례 양립성 ----------
    reference_cases = prereg_doc['reference_cases']
    undetermined_counts_as = prereg_doc['reference_case_rule']['undetermined_counts_as']
    compatible_mask, per_case_table = reference_compatibility(matrix, panel, reference_cases, undetermined_counts_as)
    n_compatible = int(compatible_mask.sum())
    if n_compatible == 0 or n_compatible < 100:
        raise NotEvaluableError(
            f'참조사례 양립 부분공간이 너무 작습니다(n_compatible={n_compatible}). '
            'S1을 NOT_EVALUABLE로 기록하고 중단합니다.')

    fixed_model_rc = {}
    for model_id, cand in candidates.items():
        for scenario_id in SCENARIO_IDS:
            stage = _pessimistic_stage(values, scenarios[scenario_id], cand)
            results, observed = fixed_model_reference_pass(stage, panel, reference_cases, undetermined_counts_as)
            fixed_model_rc[(model_id, scenario_id)] = (results, observed)
    # 결정론적 앵커
    anchor_v1 = fixed_model_rc[('v1.0_crisp', '기준')][0]
    anchor_d = fixed_model_rc[('D_small_indifference', '기준')][0]
    if all(anchor_v1.values()) is not False or not all(anchor_d.values()):
        raise RuntimeError(
            f'결정론적 앵커 불일치: v1.0_crisp(기준) 양립={all(anchor_v1.values())}(기대 False), '
            f'D_small_indifference(기준) 양립={all(anchor_d.values())}(기대 True). 중단합니다.')

    # ---------- S1: 공간 3종 ----------
    space_full, ra_full = subspace_necessary_shares(matrix, panel, values, mask=None)
    space_crisp, ra_crisp = subspace_necessary_shares(crisp_matrix, panel, values, mask=None)
    space_compat, ra_compat = subspace_necessary_shares(matrix, panel, values, mask=compatible_mask)
    s1_threshold = acceptance['S1_necessary_share_min_on_discriminating']
    s1_value = space_compat['necessary_share_discriminating']
    s1_pass = bool(s1_value >= s1_threshold)

    # ---------- C1 ----------
    c1 = c1_logical_violations(values, scenarios, candidates)

    # ---------- C2(Phase 2 산출물 읽기) ----------
    opt_pess, c2_run_id = load_phase2_optimistic_vs_pessimistic(root)
    opt_pess_scorable = opt_pess[opt_pess['pessimistic_stage'] != config.UNDETERMINED]
    c2_threshold = acceptance['C2_pess_opt_agreement_min']
    c2_group = opt_pess_scorable.groupby(['candidate_id', 'scenario_id']).agg(
        c2_agreement_rate=('agree', 'mean'), c2_denominator_n=('agree', 'size')).reset_index()

    # ---------- C3(Phase 2 산출물 읽기) ----------
    stability, c3_run_id = load_phase2_perturbation_stability(root)
    c3_mean_threshold = acceptance['C3_retention_mean_min']
    c3_p05_threshold = acceptance['C3_retention_p05_min']

    # ---------- C4 + 6행 조립 ----------
    c4_pass_rate_required = acceptance['C4_reference_case_pass_rate']
    decision_rows = []
    for model_id in MODEL_IDS:
        for scenario_id in SCENARIO_IDS:
            c1_row = c1[(c1.model_id == model_id) & (c1.scenario_id == scenario_id)].iloc[0]
            c1_violation_sum = int(c1_row.range_violations + c1_row.boundary_contradictions
                                   + c1_row.monotonicity_violations + c1_row.dominance_violations)
            c1_pass = bool(c1_violation_sum == 0 and c1_row.row_order_independent)

            c2_row = c2_group[(c2_group.candidate_id == model_id) & (c2_group.scenario_id == scenario_id)].iloc[0]
            c2_pass = bool(c2_row.c2_agreement_rate >= c2_threshold)

            c3_row = stability[(stability.candidate_id == model_id)
                              & (stability.scenario_id == scenario_id)].iloc[0]
            c3_pass = bool(c3_row.retention_mean >= c3_mean_threshold and c3_row.retention_p05 >= c3_p05_threshold)

            rc_results, rc_observed = fixed_model_rc[(model_id, scenario_id)]
            cases_passed = sum(rc_results.values())
            cases_total = len(rc_results)
            c4_pass_rate = cases_passed / cases_total
            c4_pass = bool(c4_pass_rate == c4_pass_rate_required)
            failed_case_ids = ','.join(cid for cid, ok in rc_results.items() if not ok)

            pass_map = {'C1': c1_pass, 'C2': c2_pass, 'C3': c3_pass, 'C4': c4_pass, 'S1': s1_pass}
            failed = [k for k, v in pass_map.items() if not v]
            if not failed:
                overall_status, blocked_by = 'ADOPTABLE', ''
            elif len(failed) == 1:
                overall_status, blocked_by = f'BLOCKED_BY_{failed[0]}', failed[0]
            else:
                overall_status, blocked_by = 'BLOCKED_MULTIPLE', ','.join(failed)

            if scenario_id == '고용중시':
                rationale = HOUYONG_CAVEAT_DECISION
            else:
                if failed:
                    detail = '; '.join(f'{k} 미통과' for k in failed)
                    rationale = f'{model_id}/{scenario_id}: {detail}.'
                else:
                    rationale = f'{model_id}/{scenario_id}: C1~C4·S1 전부 통과.'

            decision_rows.append({
                'model_id': model_id, 'scenario_id': scenario_id,
                'c1_range_violations': int(c1_row.range_violations),
                'c1_boundary_contradictions': int(c1_row.boundary_contradictions),
                'c1_monotonicity_violations': int(c1_row.monotonicity_violations),
                'c1_dominance_violations': int(c1_row.dominance_violations),
                'c1_row_order_independent': bool(c1_row.row_order_independent),
                'c1_pass': c1_pass,
                'c2_agreement_rate': float(c2_row.c2_agreement_rate),
                'c2_denominator_n': int(c2_row.c2_denominator_n), 'c2_threshold': c2_threshold,
                'c2_pass': c2_pass, 'c2_source_run_id': c2_run_id,
                'c3_retention_mean': float(c3_row.retention_mean), 'c3_retention_p05': float(c3_row.retention_p05),
                'c3_retention_min': float(c3_row.retention_min),
                'c3_threshold_mean': c3_mean_threshold, 'c3_threshold_p05': c3_p05_threshold,
                'c3_pass': c3_pass, 'c3_source_run_id': c3_run_id,
                'c4_cases_total': cases_total, 'c4_cases_passed': cases_passed,
                'c4_pass_rate': c4_pass_rate, 'c4_pass': c4_pass, 'c4_failed_case_ids': failed_case_ids,
                's1_reference_compatible_subspace': s1_value,
                's1_full_space': space_full['necessary_share_discriminating'],
                's1_crisp_subspace': space_crisp['necessary_share_discriminating'],
                's1_threshold': s1_threshold, 's1_pass': s1_pass, 's1_scope': 'parameter_space_level',
                'overall_status': overall_status, 'blocked_by': blocked_by, 'rationale': rationale,
            })
    decision = pd.DataFrame(decision_rows)
    assert set(decision['overall_status']) <= set(OVERALL_STATUSES)

    # ---------- electre_reference_case_compatibility.csv ----------
    per_case_block = per_case_table.copy()
    per_case_block['block_type'] = 'per_case'
    rc_by_id = {rc['id']: rc for rc in reference_cases}
    per_case_block['industry'] = per_case_block['case_id'].map(lambda c: rc_by_id[c]['industry'])
    per_case_block['quarter'] = per_case_block['case_id'].map(lambda c: rc_by_id[c]['quarter'])
    per_case_block['relation'] = per_case_block['case_id'].map(lambda c: rc_by_id[c]['relation'])
    per_case_block['target_stage'] = per_case_block['case_id'].map(lambda c: rc_by_id[c]['stage'])
    per_case_block['rationale'] = per_case_block['case_id'].map(lambda c: rc_by_id[c]['rationale'])

    fixed_rows = []
    for model_id in MODEL_IDS:
        for scenario_id in SCENARIO_IDS:
            results, observed = fixed_model_rc[(model_id, scenario_id)]
            fixed_rows.append({
                'block_type': 'fixed_model', 'model_id': model_id, 'scenario_id': scenario_id,
                'rc1_pass': results.get('RC1'), 'rc2_pass': results.get('RC2'), 'rc3_pass': results.get('RC3'),
                'all_pass': all(results.values()),
                'observed_stages': json.dumps(observed, ensure_ascii=False, sort_keys=True),
            })
    fixed_block = pd.DataFrame(fixed_rows)

    crit = config.CRITERIA
    compat_samples = [s for s, ok in zip(samples, compatible_mask) if ok]
    w_arr = {j: np.array([s['weights'][j] for s in compat_samples]) for j in crit}
    p_arr = {j: np.array([s['p'][j] for s in compat_samples]) for j in crit}
    q_arr = {j: np.array([s['q'][j] for s in compat_samples]) for j in crit}
    lam_arr = np.array([s['lambda'] for s in compat_samples])
    subspace_row = {'block_type': 'subspace', 'n_samples_total': len(samples), 'n_compatible': n_compatible,
                    'compatible_rate': n_compatible / len(samples), 'lambda_min': float(lam_arr.min()),
                    'lambda_max': float(lam_arr.max()), 'lambda_mean': float(lam_arr.mean())}
    for j in crit:
        subspace_row[f'w_{j}_mean'] = float(w_arr[j].mean())
        subspace_row[f'w_{j}_p05'] = float(np.percentile(w_arr[j], 5))
        subspace_row[f'w_{j}_p95'] = float(np.percentile(w_arr[j], 95))
        subspace_row[f'p_{j}_mean'] = float(p_arr[j].mean())
        subspace_row[f'q_{j}_mean'] = float(q_arr[j].mean())
    subspace_block = pd.DataFrame([subspace_row])

    per_case_block = per_case_block.rename(columns={'case_id': 'case_id'})
    reference_case_compatibility = pd.concat([per_case_block, fixed_block, subspace_block], ignore_index=True)

    # ---------- electre_robust_assignment_summary.csv ----------
    robust_summary = pd.DataFrame([
        {'space_id': 'reference_compatible_subspace', **space_compat, 'used_for_acceptance': True,
         'threshold': s1_threshold, 'pass': s1_pass},
        {'space_id': 'full_parameter_space', **space_full, 'used_for_acceptance': False,
         'threshold': s1_threshold, 'pass': bool(space_full['necessary_share_discriminating'] >= s1_threshold)},
        {'space_id': 'crisp_subspace', **space_crisp, 'used_for_acceptance': False,
         'threshold': s1_threshold, 'pass': bool(space_crisp['necessary_share_discriminating'] >= s1_threshold)},
    ])

    # ---------- electre_class_acceptability_index_compatible.csv ----------
    row_keys = panel[['industry', 'quarter']].reset_index(drop=True)
    cai_compat = robust.class_acceptability(matrix[compatible_mask, :], row_keys)
    totals = cai_compat[['cai_observe', 'cai_check', 'cai_priority', 'cai_undetermined']].sum(axis=1)
    if not np.allclose(totals, 1.0, atol=1e-9):
        raise RuntimeError('CAI 행 합이 1.0이 아닙니다(reference_compatible_subspace).')
    cai_compat = cai_compat.merge(ra_compat[['industry', 'quarter', 'necessary_stage', 'possible_stages',
                                             'n_possible', 'is_discriminating']], on=['industry', 'quarter'])
    v1_base_stage = _pessimistic_stage(values, scenarios['기준'], candidates['v1.0_crisp'])
    d_base_stage = _pessimistic_stage(values, scenarios['기준'], candidates['D_small_indifference'])
    cai_compat['v1_0_stage'] = v1_base_stage
    cai_compat['d_stage'] = d_base_stage

    # ---------- electre_concurrent_external_validation.csv (V2) ----------
    concurrent = concurrent_external_validation(panel, values, scenarios, candidates, prereg_doc['concurrent_indicators'])

    # ---------- electre_supporting_temporal_targets.csv (V4) ----------
    temporal = supporting_temporal_targets(panel, values, scenarios, candidates, prereg_doc, split='HOLDOUT')

    # ---------- electre_scenario_consensus_caveat.csv ----------
    consensus_rows = []
    for scenario_id in SCENARIO_IDS:
        lam = scenarios[scenario_id].lam
        r_v1 = c2_group[(c2_group.candidate_id == 'v1.0_crisp') & (c2_group.scenario_id == scenario_id)].iloc[0]
        r_d = c2_group[(c2_group.candidate_id == 'D_small_indifference')
                      & (c2_group.scenario_id == scenario_id)].iloc[0]
        c2_pass_both = bool(r_v1.c2_agreement_rate >= c2_threshold and r_d.c2_agreement_rate >= c2_threshold)
        consensus_rows.append({
            'scenario_id': scenario_id, 'lambda': lam,
            'c2_agreement_v1_0': float(r_v1.c2_agreement_rate), 'c2_agreement_d': float(r_d.c2_agreement_rate),
            'c2_pass': c2_pass_both,
            'caveat': HOUYONG_CAVEAT_CONSENSUS if scenario_id == '고용중시' else '',
        })
    scenario_consensus_caveat = pd.DataFrame(consensus_rows)

    # ---------- electre_prior_decision_supersession.csv ----------
    prior_path = root / 'outputs/tables/electre_qp_selection_decision.csv'
    prior = pd.read_csv(prior_path)
    prior_hash_before = p2._sha_bytes(prior_path)
    supersession = prior.iloc[[0]].copy().reset_index(drop=True)
    gates_by_id = {g['id']: g for g in prereg_doc['invalidated_gates']}
    for i, gid in enumerate(('IG1', 'IG2', 'IG3'), start=1):
        g = gates_by_id[gid]
        supersession[f'invalidated_gate_{i}_id'] = g['id']
        supersession[f'invalidated_gate_{i}_retired'] = g['retired']
        supersession[f'invalidated_gate_{i}_reason'] = g['reason']
    supersession['superseded_by_run_id'] = run_id
    supersession['new_status'] = prereg_doc['new_status_label']
    prior_hash_after = p2._sha_bytes(prior_path)
    if prior_hash_before != prior_hash_after:
        raise RuntimeError('electre_qp_selection_decision.csv 원본이 읽는 도중 변경되었습니다.')

    # ---------- electre_boundary_profile_findings.csv ----------
    boundary_findings = boundary_profile_findings(root, panel, values, prereg_doc)

    tables = {
        'electre_revalidation_decision': decision,
        'electre_reference_case_compatibility': reference_case_compatibility,
        'electre_robust_assignment_summary': robust_summary,
        'electre_class_acceptability_index_compatible': cai_compat,
        'electre_concurrent_external_validation': concurrent,
        'electre_supporting_temporal_targets': temporal,
        'electre_scenario_consensus_caveat': scenario_consensus_caveat,
        'electre_prior_decision_supersession': supersession,
        'electre_boundary_profile_findings': boundary_findings,
    }
    for name, frame in tables.items():
        for col, val in prov.items():
            frame[col] = val

    written = None
    if write:
        run_dir = p2.write_tables(root, run_id, tables)[0]
        written = {name: str(run_dir / f'{name}.csv') for name in tables}

    return {'run_id': run_id, 'provenance': prov, 'tables': tables, 'written': written,
           'panel': panel, 'values': values, 'scenarios': scenarios, 'candidates': candidates,
           'compatible_mask': compatible_mask, 'matrix': matrix, 'crisp_matrix': crisp_matrix,
           'space_full': space_full, 'space_crisp': space_crisp, 'space_compat': space_compat,
           'per_case_table': per_case_table, 'fixed_model_rc': fixed_model_rc,
           'v1_base_stage': v1_base_stage, 'd_base_stage': d_base_stage}


def boundary_profile_findings(root, panel, values, prereg_doc):
    root = Path(root)
    vintage = pd.read_csv(root / 'outputs/tables/vintage_수정폭_실측.csv', encoding='utf-8-sig')
    vintage.columns = [str(c).lstrip('﻿') for c in vintage.columns]
    comparable = panel['ppi_direction_status'].isin(config.PPI_COMPARABLE_STATUSES) & panel['scorable'].astype(bool)
    gap_upper = (panel['production_yoy'] - panel['ppi_adjusted_prod_yoy_upper']).abs().where(comparable)

    def pct(q):
        return float(gap_upper.quantile(q))

    g3_note = prereg_doc['qp_derivation']['g3']['p_constraint_note']
    bp1 = {'finding_id': 'BP1', 'criterion': 'g3',
          'nominal_ppi_adjusted_gap_p50': pct(0.50), 'nominal_ppi_adjusted_gap_p75': pct(0.75),
          'nominal_ppi_adjusted_gap_p90': pct(0.90), 'b1_value': 5.0, 'b2_value': 10.0,
          'p_constraint_applied': True, 'p_upper_after_constraint': 5.0, 'note': g3_note}

    g1_pass = panel['g1_emp_abs_decline'].notna() & (panel['g1_emp_abs_decline'] >= 100)
    g1_available = panel['g1_emp_abs_decline'].notna()
    by_industry = pd.DataFrame({'industry': panel['industry'], 'available': g1_available, 'passed': g1_pass})
    counts, medians, never = {}, {}, []
    for industry, g in by_industry.groupby('industry', sort=True):
        counts[industry] = {'n_observations': int(g['available'].sum()), 'n_pass': int(g['passed'].sum())}
        med_emp = panel.loc[panel['industry'] == industry, 'employment'].median()
        medians[industry] = float(med_emp) if pd.notna(med_emp) else None
        if g['passed'].sum() == 0:
            never.append(industry)
    bp2 = {'finding_id': 'BP2', 'criterion': 'g1',
          'g1_b1_pass_counts_by_industry': json.dumps(counts, ensure_ascii=False, sort_keys=True),
          'median_employment_by_industry': json.dumps(medians, ensure_ascii=False, sort_keys=True),
          'never_passed_industries': json.dumps(never, ensure_ascii=False),
          'n_industries_never_passed': len(never)}

    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    forced_g3_ge_10 = forced & (values['g3'].to_numpy() >= 10)
    discriminating = scorable & ~forced
    bp3 = {'finding_id': 'BP3', 'criterion': 'all', 'n_forced_observe': int(forced.sum()),
          'n_forced_observe_with_g3_ge_10': int(forced_g3_ge_10.sum()),
          'n_discriminating': int(discriminating.sum()), 'n_scorable': int(scorable.sum()),
          'n_total': int(len(panel))}
    return pd.DataFrame([bp1, bp2, bp3])


# ---------------------------------------------------------------- 3-H 그림 2개
def write_figures(root, result):
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt

    root = Path(root)
    out = root / 'outputs/figures'
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    colors = config.DISPLAY_COLORS

    # 1) reference_compatible_subspace 기준 2026Q2 업종별 CAI 누적막대
    cai = result['tables']['electre_class_acceptability_index_compatible']
    latest = cai[cai['quarter'] == '2026Q2'].sort_values('industry')
    fig, ax = plt.subplots(figsize=(10, 5))
    bottom = np.zeros(len(latest))
    for stage, col in (('OBSERVE', 'cai_observe'), ('CHECK', 'cai_check'),
                       ('PRIORITY', 'cai_priority'), (config.UNDETERMINED, 'cai_undetermined')):
        ax.bar(latest['industry'], latest[col], bottom=bottom, color=colors[stage],
              label=config.DISPLAY_LABELS[stage])
        bottom += latest[col].to_numpy()
    ax.set_ylabel('등급수용지수(CAI)')
    ax.set_title('2026Q2 업종별 등급수용지수 — 참조사례 양립 부분공간 기준')
    ax.legend(loc='upper right', fontsize=8)
    plt.xticks(rotation=30, ha='right')
    fig.tight_layout()
    fig.savefig(out / 'revalidation_cai_compatible_latest.png', dpi=180)
    plt.close(fig)

    # 2) 공간 3종 비교: 필연배정 비율 + n_possible 분포
    summary = result['tables']['electre_robust_assignment_summary']
    fig, axs = plt.subplots(1, 2, figsize=(13, 5))
    axs[0].bar(summary['space_id'], summary['necessary_share_discriminating'], color='#6B7C8F')
    axs[0].axhline(float(summary['threshold'].iloc[0]), color=colors['PRIORITY'], linestyle='--',
                  label='S1 합격선')
    axs[0].set_ylabel('판별표본 필연배정 비율'); axs[0].set_title('공간별 필연배정 비율')
    axs[0].legend(fontsize=8)
    plt.setp(axs[0].get_xticklabels(), rotation=20, ha='right')

    width = 0.25
    xpos = np.arange(len(summary))
    for i, (col, label) in enumerate((('n_possible_1', '1(필연)'), ('n_possible_2', '2'), ('n_possible_3', '3'))):
        axs[1].bar(xpos + (i - 1) * width, summary[col], width=width, label=label)
    axs[1].set_xticks(xpos); axs[1].set_xticklabels(summary['space_id'], rotation=20, ha='right')
    axs[1].set_ylabel('판별표본 행수(89행 중)'); axs[1].set_title('공간별 가능단계 수 분포')
    axs[1].legend(fontsize=8, title='n_possible')
    fig.tight_layout()
    fig.savefig(out / 'revalidation_subspace_comparison.png', dpi=180)
    plt.close(fig)
