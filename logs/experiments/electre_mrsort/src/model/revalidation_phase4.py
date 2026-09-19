# -*- coding: utf-8 -*-
"""Phase 4: 모형 변경(veto 확정, 가중치·λ 재추론)과 C3 원인 진단.

사전등록이 REGISTERED일 때만 실행된다. config/electre_tri_b_params.yaml은 바꾸지
않는다 — 변경 후보는 config/electre_tri_b_params.v1.2-candidates.yaml에만 기록한다.
qp_calibration.constraints는 veto를 지원하지 않으므로(Phase 3 TODO), 이 모듈의
constraints_with_veto가 그 자리를 대신한다. qp_calibration.py는 고치지 않는다.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import config, electre, manifest, params, perturb, prereg, qp_calibration, resample
from . import revalidation as p2
from . import revalidation_phase3 as p3

RANK = qp_calibration.RANK
MODEL_IDS = ('v1.0_crisp', 'D_small_indifference')
SCENARIO_IDS = ('기준', '고용중시', '지속성중시')
# 세 시나리오의 b1·b2는 항상 동일하다(prereg.check_parameter_space_bounds가 매번 확인한다).
BASE_B1 = {'g1': 100, 'g2': 2.0, 'g3': 5.0, 'g4': 2}
BASE_B2 = {'g1': 500, 'g2': 5.0, 'g3': 10.0, 'g4': 4}


class Phase4GateError(RuntimeError):
    """Phase 4 착수 게이트(사전등록 REGISTERED, AM4 존재)를 통과하지 못했을 때."""


# ---------------------------------------------------------------- 착수 게이트
def check_gate(root):
    root = Path(root)
    doc = prereg.load(root / 'config/model_revalidation_prereg.yaml')
    amendment_ids = [a['id'] for a in doc['amendments']]
    if 'AM4' not in amendment_ids:
        raise Phase4GateError('amendments에 AM4가 없어 Phase 4를 실행할 수 없습니다')
    try:
        prereg.require_registered(doc)
    except prereg.PreregNotRegisteredError:
        raise Phase4GateError('사전등록이 완료되지 않아 Phase 4를 실행할 수 없습니다')
    return doc


# ---------------------------------------------------------------- constraints_with_veto
def _scenario(weights, lam, gate=True):
    return electre.Scenario('cwv', dict(weights), BASE_B1, BASE_B2, float(lam), 0.0, bool(gate))


def _boundary_veto(veto, boundary):
    """veto 인자 규약: None(어느 경계에도 veto 없음) 또는
    {'b1': {criterion:threshold}|None, 'b2': {criterion:threshold}|None}(경계별 지정).
    veto_candidates는 boundary 필드로 단일 경계만 지정하므로, 그 경계에만 적용하고
    다른 경계는 건드리지 않는다(Phase 1의 electre.veto_blocked 규약 그대로 재사용).
    """
    if veto is None:
        return None
    return veto.get(boundary)


def _stage_with_veto(values, weights, lam, q, p, veto, gate=True):
    scenario = _scenario(weights, lam, gate)
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    b1 = electre.forward_outranks(values, scenario, 'b1', q, p, _boundary_veto(veto, 'b1'))
    b2 = electre.forward_outranks(values, scenario, 'b2', q, p, _boundary_veto(veto, 'b2'))
    return electre.pessimistic_assignment(b1, b2, scorable)


def _optimistic_stage_with_veto(values, weights, lam, q, p, veto, gate=True):
    """electre.optimistic_assignment과 같은 절차이나, 이 모듈의 경계별 veto 규약을 쓴다
    (electre.optimistic_assignment은 veto를 b1·b2에 동일하게 전달하므로 여기서는 쓸 수 없다)."""
    scenario = _scenario(weights, lam, gate)
    crit = config.CRITERIA
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    a_s = {h: electre.forward_outranks(values, scenario, h, q, p, _boundary_veto(veto, h))
          for h in electre.BOUNDARIES}
    b_s = {h: electre.boundary_outranks(values, scenario, h, q, p) for h in electre.BOUNDARIES}
    classes = np.empty(len(scorable), dtype=object)
    for i in range(len(scorable)):
        if not scorable[i]:
            classes[i] = config.UNDETERMINED
        elif b_s['b1'][i] and not a_s['b1'][i]:
            classes[i] = 'OBSERVE'
        elif b_s['b2'][i] and not a_s['b2'][i]:
            classes[i] = 'CHECK'
        else:
            classes[i] = 'PRIORITY'
    return classes


def constraints_with_veto(values, weights, lam, q, p, veto, gate=True):
    """qp_calibration.constraints와 동일한 4종 검사 + 행순서 독립성, veto 지원.

    veto=None이면 qp_calibration.constraints(values, scenario, candidate)와
    (같은 weights/lam/q/p/gate로 만든 scenario·candidate에 대해) 완전히 일치한다.
    veto가 dict이면 {'b1': ..., 'b2': ...} 경계별 규약을 따른다(_boundary_veto 참조).
    """
    crit = config.CRITERIA
    scenario = _scenario(weights, lam, gate)

    range_bad = 0
    for prof in (BASE_B1, BASE_B2):
        for j in crit:
            cj = electre._pseudo_partial_concordance(values[j], prof[j], float(q[j]), float(p[j]))  # noqa: SLF001
            valid = ~np.isnan(cj)
            range_bad += int(((cj[valid] < 0) | (cj[valid] > 1)).sum())

    b1_out = electre.forward_outranks(values, scenario, 'b1', q, p, _boundary_veto(veto, 'b1'))
    b2_out = electre.forward_outranks(values, scenario, 'b2', q, p, _boundary_veto(veto, 'b2'))
    contradiction = int(np.sum(b2_out & ~b1_out))

    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    base_stage = electre.pessimistic_assignment(b1_out, b2_out, scorable)
    base_rank = pd.Series(base_stage).map(RANK)
    mono = 0
    for g in crit:
        bumped = values.copy()
        bumped[g] = bumped[g] + max(float(p[g]), 1e-6)
        after_stage = _stage_with_veto(bumped, weights, lam, q, p, veto, gate)
        after_rank = pd.Series(after_stage).map(RANK)
        mono += int((after_rank.dropna() < base_rank.dropna()).sum())

    complete = values[values.notna().all(axis=1)].reset_index(drop=True)
    complete_stage = _stage_with_veto(complete, weights, lam, q, p, veto, gate)
    stages = pd.Series(complete_stage).map(RANK).to_numpy()
    arr = complete.to_numpy(float)
    dominance = 0
    for i in range(len(arr)):
        dominated = np.all(arr[i] >= arr, axis=1) & np.any(arr[i] > arr, axis=1)
        dominance += int(np.sum(stages[i] < stages[dominated]))

    shuffled = values.sample(frac=1, random_state=11)
    shuffled_stage = pd.Series(_stage_with_veto(shuffled, weights, lam, q, p, veto, gate), index=shuffled.index)
    base_stage_series = pd.Series(base_stage, index=values.index)
    order_ok = bool(shuffled_stage.sort_index().equals(base_stage_series.sort_index()))

    return {'range_violations': range_bad, 'boundary_contradictions': contradiction,
           'monotonicity_violations': mono, 'dominance_violations': dominance,
           'row_order_independent': order_ok,
           'passed': (range_bad + contradiction + mono + dominance == 0) and order_ok}


# ---------------------------------------------------------------- 공통 준비
def _values(panel):
    return qp_calibration.values_from_panel(panel)


def _load_context(root):
    root = Path(root)
    prereg_doc = check_gate(root)
    current = manifest.load_manifest(root)
    if current is None:
        raise RuntimeError('outputs/current_run_manifest.json이 없습니다.')
    panel = manifest.load_current_table(root, 'input_panel')
    if panel is None or set(panel['run_id'].astype(str)) != {current['run_id']}:
        raise RuntimeError('현재 input panel과 manifest가 일치하지 않습니다.')
    panel = panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)
    base_doc = yaml.safe_load((root / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))
    scenarios = p2._load_scenarios(base_doc)  # noqa: SLF001
    candidates = p2._load_candidates(root)  # noqa: SLF001
    return prereg_doc, current, panel, base_doc, scenarios, candidates


def _admin_stats(panel, values, stage):
    stage = pd.Series(np.asarray(stage), index=panel.index)
    pri_mask = (stage == 'PRIORITY').to_numpy()
    return {
        'n_observe': int((stage == 'OBSERVE').sum()), 'n_check': int((stage == 'CHECK').sum()),
        'n_priority': int(pri_mask.sum()),
        'priority_median_employment': float(panel.loc[pri_mask, 'employment'].median()) if pri_mask.any() else np.nan,
        'priority_small_firm_flag_rate':
            float(panel.loc[pri_mask, 'small_firm_count_flag'].astype(bool).mean()) if pri_mask.any() else np.nan,
        'priority_median_g1': float(values.loc[pri_mask, 'g1'].median()) if pri_mask.any() else np.nan,
    }


def _c4(stage, panel, reference_cases, undetermined_counts_as):
    results, _ = p3.fixed_model_reference_pass(stage, panel, reference_cases, undetermined_counts_as)
    cases_total = len(results)
    cases_passed = sum(results.values())
    failed_ids = ','.join(cid for cid, ok in results.items() if not ok)
    return cases_passed / cases_total, cases_passed == cases_total, failed_ids


# ---------------------------------------------------------------- Step 1: veto만 적용
def veto_screening(root, prereg_doc, panel, base_doc, scenarios, candidates):
    root = Path(root)
    values = _values(panel)
    acceptance = prereg_doc['acceptance']
    undetermined_counts_as = prereg_doc['reference_case_rule']['undetermined_counts_as']
    reference_cases = prereg_doc['reference_cases']
    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')
    unc_p = prereg_doc['perturbation']
    targets = p2.build_bootstrap_targets(panel)
    t2 = targets['next2_both_negative']
    ppi_upper = panel['ppi_adjusted_prod_yoy_upper']
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()

    base_stage_cache, base_c3_mean_cache = {}, {}
    rows = []
    for vc in prereg_doc['veto_candidates']:
        is_v0 = not vc.get('enabled')
        veto_dict = None if is_v0 else {vc['boundary']: {vc['criterion']: vc['threshold_value']}}
        classical_v = None if is_v0 else (BASE_B2 if vc['boundary'] == 'b2' else BASE_B1)[vc['criterion']] - vc['threshold_value']
        veto_row_discarded = False

        for model_id in MODEL_IDS:
            cand = candidates[model_id]
            for scenario_id in SCENARIO_IDS:
                scenario = scenarios[scenario_id]
                gate = scenario.require_employment_evidence
                stage = _stage_with_veto(values, scenario.weights, scenario.lam, cand['q'], cand['p'], veto_dict, gate)
                cons = constraints_with_veto(values, scenario.weights, scenario.lam, cand['q'], cand['p'], veto_dict, gate)
                c1_pass = bool(cons['passed'])

                opt = _optimistic_stage_with_veto(values, scenario.weights, scenario.lam, cand['q'], cand['p'],
                                                  veto_dict, gate)
                pess_s = pd.Series(np.asarray(stage))[scorable]
                opt_s = pd.Series(np.asarray(opt))[scorable]
                c2_rate = float((pess_s.to_numpy() == opt_s.to_numpy()).mean())
                c2_pass = bool(c2_rate >= acceptance['C2_pess_opt_agreement_min'])

                stab = perturb.stability(panel, scenario, cand['q'], cand['p'], veto_dict, pool,
                                         n=unc_p['n_replicates'], seed=unc_p['seed'])
                c3_pass = bool(stab['mean'] >= acceptance['C3_retention_mean_min']
                              and stab['p05'] >= acceptance['C3_retention_p05_min'])

                c4_rate, c4_pass, c4_failed = _c4(stage, panel, reference_cases, undetermined_counts_as)

                admin = _admin_stats(panel, values, stage)
                key = (model_id, scenario_id)
                if is_v0:
                    base_stage_cache[key] = stage
                    base_c3_mean_cache[key] = stab['mean']
                base_stage = base_stage_cache.get(key)
                n_changed = int(np.sum(np.asarray(stage) != np.asarray(base_stage))) if base_stage is not None else 0
                c3_delta = stab['mean'] - base_c3_mean_cache[key] if key in base_c3_mean_cache else np.nan

                stage_rank = pd.Series(np.asarray(stage)).map(RANK).astype(float)
                ppi_sp = resample.spearman(stage_rank, ppi_upper)
                t2_sp = resample.spearman(stage_rank, t2)

                discard_reasons = []
                if not is_v0:
                    viol_sum = (cons['range_violations'] + cons['boundary_contradictions']
                               + cons['monotonicity_violations'] + cons['dominance_violations'])
                    if viol_sum > 0 or not cons['row_order_independent']:
                        discard_reasons.append('C1_VIOLATION')
                    if admin['n_priority'] <= 5:
                        discard_reasons.append('N_PRIORITY_TOO_LOW')
                    if not np.isnan(c3_delta) and c3_delta <= -0.02:
                        discard_reasons.append('C3_WORSE_THAN_BASE')
                if discard_reasons:
                    veto_row_discarded = True

                failed = [k for k, ok in (('C1', c1_pass), ('C2', c2_pass), ('C3', c3_pass), ('C4', c4_pass))
                         if not ok]
                if discard_reasons:
                    verdict = 'DISCARDED_' + '_'.join(discard_reasons)
                elif not failed:
                    verdict = 'PASS_ALL'
                elif len(failed) == 1:
                    verdict = f'BLOCKED_BY_{failed[0]}'
                else:
                    verdict = 'BLOCKED_MULTIPLE'

                rows.append({
                    'veto_id': vc['id'], 'veto_boundary': vc.get('boundary'), 'veto_criterion': vc.get('criterion'),
                    'veto_threshold_value': vc.get('threshold_value'), 'veto_relation': prereg_doc['veto_relation'],
                    'classical_v_j': classical_v, 'model_id': model_id, 'scenario_id': scenario_id,
                    'c1_range': cons['range_violations'], 'c1_boundary': cons['boundary_contradictions'],
                    'c1_mono': cons['monotonicity_violations'], 'c1_dominance': cons['dominance_violations'],
                    'c1_row_order_independent': cons['row_order_independent'], 'c1_pass': c1_pass,
                    'c2_agreement_rate': c2_rate, 'c2_pass': c2_pass,
                    'c3_retention_mean': stab['mean'], 'c3_retention_p05': stab['p05'],
                    'c3_retention_min': stab['min'], 'c3_pass': c3_pass, 'c3_delta_vs_base': c3_delta,
                    'c4_pass_rate': c4_rate, 'c4_pass': c4_pass, 'c4_failed_case_ids': c4_failed,
                    's1_applicable': False,
                    'n_observe': admin['n_observe'], 'n_check': admin['n_check'], 'n_priority': admin['n_priority'],
                    'n_changed_from_base': n_changed,
                    'priority_median_employment': admin['priority_median_employment'],
                    'priority_small_firm_flag_rate': admin['priority_small_firm_flag_rate'],
                    'priority_median_g1': admin['priority_median_g1'],
                    'ppi_upper_spearman': ppi_sp, 't2_spearman': t2_sp,
                    'verdict': verdict, 'is_v0_baseline': is_v0,
                })
        for r in rows:
            if r['veto_id'] == vc['id']:
                r['veto_candidate_discarded'] = veto_row_discarded

    table = pd.DataFrame(rows)

    # V0 자기대조: Phase 3 decision.csv의 C1~C4 값과 일치해야 한다(재계산이되 값은 같아야 함)
    phase3_decision_path = root / 'outputs/tables/electre_revalidation_decision.csv'
    if phase3_decision_path.is_file():
        phase3_decision = pd.read_csv(phase3_decision_path)
        for _, r in table[table.veto_id == 'V0'].iterrows():
            ref = phase3_decision[(phase3_decision.model_id == r.model_id)
                                  & (phase3_decision.scenario_id == r.scenario_id)]
            if len(ref):
                ref = ref.iloc[0]
                mismatch = (bool(ref.c1_pass) != bool(r.c1_pass)
                           or not np.isclose(ref.c2_agreement_rate, r.c2_agreement_rate, atol=1e-9)
                           or bool(ref.c4_pass) != bool(r.c4_pass))
                if mismatch:
                    raise RuntimeError(
                        f'V0 재계산값이 Phase 3 결과와 다릅니다({r.model_id}/{r.scenario_id}): '
                        f'phase3 c1={ref.c1_pass},c2={ref.c2_agreement_rate},c4={ref.c4_pass} vs '
                        f'phase4 c1={r.c1_pass},c2={r.c2_agreement_rate},c4={r.c4_pass}')

    # 선택: prereg.veto_selection_rule — V1이 C1~C4 전부 통과하고 폐기되지 않았으면 채택
    enabled_ids = [vc['id'] for vc in prereg_doc['veto_candidates'] if vc.get('enabled')]
    selected_id = 'V0'
    for vid in enabled_ids:
        sub = table[table.veto_id == vid]
        discarded = bool(sub['veto_candidate_discarded'].iloc[0])
        all_pass = bool(sub[['c1_pass', 'c2_pass', 'c3_pass', 'c4_pass']].all().all())
        if not discarded and all_pass:
            selected_id = vid
            break
    table['selected'] = table['veto_id'] == selected_id

    decision_row = {
        'selected_veto_id': selected_id, 'selection_rule': prereg_doc['veto_selection_rule'],
        'enabled_candidates': ','.join(enabled_ids),
        'n_candidates_evaluated': len(enabled_ids),
        'reason': (f'{selected_id}가 모든 (model,scenario) 조합에서 C1~C4를 통과하고 폐기 조건에 걸리지 않았다.'
                  if selected_id != 'V0' else
                  '평가된 veto 후보 중 폐기되지 않고 C1~C4를 전부 통과한 후보가 없어 V0(veto 없음)을 유지한다.'),
    }
    return table, pd.DataFrame([decision_row])


# ---------------------------------------------------------------- Step 2: 가중치·λ 재추론
def largest_remainder_discretize(w_means, total_slots=20):
    """Dirichlet 표집 평균 가중치를 0.05 단위(20분의 1)로 최대잉여법 이산화한다.

    동률이면 g1 < g2 < g3 < g4 순으로 잔여를 배분한다(결과를 보고 조정하지 않는
    결정론적 규칙). 반환 합은 항상 정확히 1.0이다.
    """
    crit = config.CRITERIA
    slots = {j: float(w_means[j]) * total_slots for j in crit}
    base = {j: int(np.floor(slots[j])) for j in crit}
    remainder = int(total_slots - sum(base.values()))
    frac = {j: slots[j] - base[j] for j in crit}
    order = sorted(crit, key=lambda j: (-frac[j], crit.index(j)))
    alloc = dict(base)
    for j in order[:remainder]:
        alloc[j] += 1
    return {j: alloc[j] / total_slots for j in crit}


def search_w_nearest(reference_cases, undetermined_counts_as, values, panel, lam, q, p, veto_dict, gate,
                     current_weights, grid_step=0.05, grid_min=0.10, grid_max=0.40):
    """참조사례 3건을 모두 만족하는 w 중 current_weights로부터 L1 거리 최소인 점을
    0.05 격자 전수탐색으로 찾는다. 복수 최소해면 사전순(g1,g2,g3,g4 오름차순)으로
    첫 번째를 택한다. 없으면 None을 돌려준다(NOT_FOUND).
    """
    crit = config.CRITERIA
    n_steps = round((grid_max - grid_min) / grid_step) + 1
    grid_values = [round(grid_min + i * grid_step, 10) for i in range(n_steps)]
    best = None
    for g1 in grid_values:
        for g2 in grid_values:
            for g3 in grid_values:
                g4 = round(1.0 - g1 - g2 - g3, 10)
                if g4 < grid_min - 1e-9 or g4 > grid_max + 1e-9:
                    continue
                w = {'g1': g1, 'g2': g2, 'g3': g3, 'g4': g4}
                stage = _stage_with_veto(values, w, lam, q, p, veto_dict, gate)
                _, all_pass, _ = _c4(stage, panel, reference_cases, undetermined_counts_as)
                if not all_pass:
                    continue
                l1 = sum(abs(w[j] - current_weights[j]) for j in crit)
                key = (l1, tuple(w[j] for j in crit))
                if best is None or key < best[0]:
                    best = (key, dict(w))
    return None if best is None else best[1]


def _evaluate_combo(panel, values, weights, lam, model_id, cand, veto_dict, gate, prereg_doc, pool,
                    ppi_upper, t2, scorable, reference_cases, undetermined_counts_as, acceptance):
    """C1~C4 + 행정지표 + 동시점/보조타깃 spearman. Step 1·2가 공유하는 핵심 계산."""
    stage = _stage_with_veto(values, weights, lam, cand['q'], cand['p'], veto_dict, gate)
    cons = constraints_with_veto(values, weights, lam, cand['q'], cand['p'], veto_dict, gate)
    c1_pass = bool(cons['passed'])

    opt = _optimistic_stage_with_veto(values, weights, lam, cand['q'], cand['p'], veto_dict, gate)
    pess_s = pd.Series(np.asarray(stage))[scorable]
    opt_s = pd.Series(np.asarray(opt))[scorable]
    c2_rate = float((pess_s.to_numpy() == opt_s.to_numpy()).mean())
    c2_pass = bool(c2_rate >= acceptance['C2_pess_opt_agreement_min'])

    scenario = _scenario(weights, lam, gate)
    stab = perturb.stability(panel, scenario, cand['q'], cand['p'], veto_dict, pool,
                             n=prereg_doc['perturbation']['n_replicates'], seed=prereg_doc['perturbation']['seed'])
    c3_pass = bool(stab['mean'] >= acceptance['C3_retention_mean_min']
                  and stab['p05'] >= acceptance['C3_retention_p05_min'])

    c4_rate, c4_pass, c4_failed = _c4(stage, panel, reference_cases, undetermined_counts_as)
    admin = _admin_stats(panel, values, stage)
    stage_rank = pd.Series(np.asarray(stage)).map(RANK).astype(float)
    ppi_sp = resample.spearman(stage_rank, ppi_upper)
    t2_sp = resample.spearman(stage_rank, t2)

    return {
        'model_id': model_id,
        'c1_range': cons['range_violations'], 'c1_boundary': cons['boundary_contradictions'],
        'c1_mono': cons['monotonicity_violations'], 'c1_dominance': cons['dominance_violations'],
        'c1_row_order_independent': cons['row_order_independent'], 'c1_pass': c1_pass,
        'c2_agreement_rate': c2_rate, 'c2_pass': c2_pass,
        'c3_retention_mean': stab['mean'], 'c3_retention_p05': stab['p05'], 'c3_retention_min': stab['min'],
        'c3_pass': c3_pass,
        'c4_pass_rate': c4_rate, 'c4_pass': c4_pass, 'c4_failed_case_ids': c4_failed,
        'n_observe': admin['n_observe'], 'n_check': admin['n_check'], 'n_priority': admin['n_priority'],
        'priority_median_employment': admin['priority_median_employment'],
        'priority_small_firm_flag_rate': admin['priority_small_firm_flag_rate'],
        'priority_median_g1': admin['priority_median_g1'],
        'ppi_upper_spearman': ppi_sp, 't2_spearman': t2_sp, 'stage': stage,
    }


def weight_lambda_inference(root, prereg_doc, panel, base_doc, scenarios, candidates, selected_veto_id):
    root = Path(root)
    values = _values(panel)
    acceptance = prereg_doc['acceptance']
    undetermined_counts_as = prereg_doc['reference_case_rule']['undetermined_counts_as']
    reference_cases = prereg_doc['reference_cases']
    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')
    targets = p2.build_bootstrap_targets(panel)
    t2 = targets['next2_both_negative']
    ppi_upper = panel['ppi_adjusted_prod_yoy_upper']
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()

    selected_vc = next(v for v in prereg_doc['veto_candidates'] if v['id'] == selected_veto_id)
    veto_dict = (None if not selected_vc.get('enabled')
                else {selected_vc['boundary']: {selected_vc['criterion']: selected_vc['threshold_value']}})

    lam_min = prereg_doc['parameter_space']['lambda']['min']
    if lam_min > 0.50 + 1e-12:
        raise RuntimeError(f'prereg lambda 하한({lam_min})이 0.50을 넘어 λ=0.50 후보를 평가할 수 없습니다.')

    current_weights = {'g1': 0.20, 'g2': 0.20, 'g3': 0.30, 'g4': 0.30}
    employment_weights = next(dict(b['weights']) for b in base_doc['scenarios'] if b['scenario_id'] == '고용중시')

    rcc_path = root / 'outputs/tables/electre_reference_case_compatibility.csv'
    rcc = pd.read_csv(rcc_path)
    subspace_row = rcc[rcc.block_type == 'subspace'].iloc[0]
    w_means = {j: float(subspace_row[f'w_{j}_mean']) for j in config.CRITERIA}
    w_inferred = largest_remainder_discretize(w_means)

    w_nearest = search_w_nearest(reference_cases, undetermined_counts_as, values, panel, 0.50,
                                 candidates['v1.0_crisp']['q'], candidates['v1.0_crisp']['p'], veto_dict, True,
                                 current_weights)

    candidate_defs = [('a', 'W_current', current_weights), ('b', 'W_inferred', w_inferred),
                      ('c', 'W_nearest', w_nearest)]

    rows = []
    for cid, label, w in candidate_defs:
        for model_id in MODEL_IDS:
            cand = candidates[model_id]
            if w is None:
                rows.append({'candidate_id': cid, 'candidate_label': label, 'model_id': model_id,
                            'w_g1': None, 'w_g2': None, 'w_g3': None, 'w_g4': None, 'lambda': 0.50,
                            'status': 'NOT_FOUND', 's1_invariant_note': None,
                            's1_reference_compatible_subspace': None,
                            'l1_distance_to_current': None, 'l1_distance_to_employment_scenario': None,
                            'equals_employment_scenario_weights': None})
                continue
            metrics = _evaluate_combo(panel, values, w, 0.50, model_id, cand, veto_dict, True, prereg_doc, pool,
                                      ppi_upper, t2, scorable, reference_cases, undetermined_counts_as, acceptance)
            base_stage_v0 = metrics.pop('stage')
            l1_current = sum(abs(w[j] - current_weights[j]) for j in config.CRITERIA)
            l1_emp = sum(abs(w[j] - employment_weights[j]) for j in config.CRITERIA)
            equals_emp = all(abs(w[j] - employment_weights[j]) < 1e-9 for j in config.CRITERIA)
            rows.append({
                'candidate_id': cid, 'candidate_label': label,
                'w_g1': w['g1'], 'w_g2': w['g2'], 'w_g3': w['g3'], 'w_g4': w['g4'], 'lambda': 0.50,
                'status': 'EVALUATED',
                # S1은 파라미터 공간 수준 지표이고 가중치 선택과 무관하다(같은 공간의 어느 점이든 공간 자체는
                # 안 변한다) — 값과 무관함을 컬럼으로 명시하고 Phase 3 값을 그대로 인용한다.
                's1_invariant_note': 'S1은 파라미터 공간 수준 지표이며 가중치 후보와 무관하다(Phase 3 값 인용)',
                's1_reference_compatible_subspace': np.nan,  # 아래에서 Phase 3 값으로 일괄 채운다
                'l1_distance_to_current': l1_current, 'l1_distance_to_employment_scenario': l1_emp,
                'equals_employment_scenario_weights': equals_emp,
                **metrics,
            })
    table = pd.DataFrame(rows)

    # S1(Phase 3의 electre_robust_assignment_summary.csv에서 인용, 후보와 무관하게 동일값)
    ras_path = root / 'outputs/tables/electre_robust_assignment_summary.csv'
    ras = pd.read_csv(ras_path)
    s1_value = float(ras.loc[ras.space_id == 'reference_compatible_subspace', 'necessary_share_discriminating'].iloc[0])
    s1_threshold = acceptance['S1_necessary_share_min_on_discriminating']
    is_evaluated = (table['status'] == 'EVALUATED').to_numpy()
    table['s1_reference_compatible_subspace'] = np.where(is_evaluated, s1_value, np.nan)
    table['s1_pass'] = pd.Series(np.where(is_evaluated, s1_value >= s1_threshold, False),
                                 dtype='boolean').mask(~is_evaluated)

    return table, w_means, w_inferred, w_nearest


# ---------------------------------------------------------------- Step 3: C3 원인 진단(모형 변경 아님)
STAGE_CODE = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2, config.UNDETERMINED: -1}
STAGE_NAME = {v: k for k, v in STAGE_CODE.items()}


def boundary_proximity(panel, values, pool):
    """완전관측 행 × 기준 × 경계의 경계까지 거리와, 실측 개정폭 분포에서 그 거리가
    차지하는 분위. g1은 그 행의 employment_lag4로 개정폭(비율)을 인원수로 환산해
    비교하고, g2·g3는 둘 다 %p 단위라 개정폭(비율)×100과 직접 비교한다. g4는
    연속분기 정수 카운트라 %p·인원 개정폭과 단위가 근본적으로 달라 분위를 매기지
    않는다(quantile_of_abs_distance=NaN으로 두고 그 사실을 그대로 남긴다).
    """
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    emp_pool_pct = np.abs(pool['employment']) * 100.0  # %p
    prod_pool_pct = np.abs(pool['production']) * 100.0  # %p
    emp_lag4 = panel['employment_lag4'].to_numpy(dtype=float)

    rows = []
    for h, prof in (('b1', BASE_B1), ('b2', BASE_B2)):
        for j in config.CRITERIA:
            g = values[j].to_numpy(dtype=float)
            b = prof[j]
            distance = g - b
            abs_distance_for_quantile = np.abs(distance)
            if j == 'g1':
                # 행마다 그 행의 employment_lag4로 개정율(비율) 풀을 인원수로 환산한
                # 행별 기준분포(50개 값)와 비교한다 — 전체를 하나로 합치지 않는다.
                revision_pool_label = 'employment_abs_persons_row_scaled'
                comparable = scorable & (emp_lag4 > 0)
                q = np.full(len(panel), np.nan)
                pool_ratio_abs = np.abs(pool['employment'])
                for i in range(len(panel)):
                    if not comparable[i]:
                        continue
                    row_ref = np.sort(pool_ratio_abs * emp_lag4[i])
                    q[i] = np.searchsorted(row_ref, abs_distance_for_quantile[i], side='right') / len(row_ref)
            elif j in ('g2', 'g3'):
                ref_dist_abs = emp_pool_pct if j == 'g2' else prod_pool_pct
                revision_pool_label = 'employment_pct' if j == 'g2' else 'production_pct'
                comparable = scorable
                ref_sorted = np.sort(ref_dist_abs[~np.isnan(ref_dist_abs)])
                q = np.searchsorted(ref_sorted, abs_distance_for_quantile, side='right') / len(ref_sorted)
                q = np.where(comparable, q, np.nan)
            else:  # g4
                revision_pool_label = 'not_applicable_integer_run_count'
                comparable = scorable
                q = np.full(len(panel), np.nan)

            within_p50 = np.where(comparable & ~np.isnan(q), q <= 0.50, False)
            within_p90 = np.where(comparable & ~np.isnan(q), q <= 0.90, False)
            rows.append(pd.DataFrame({
                'industry': panel['industry'], 'quarter': panel['quarter'], 'criterion': j, 'boundary': h,
                'criterion_value': g, 'boundary_value': b, 'distance': distance,
                'abs_distance': np.abs(distance), 'revision_pool': revision_pool_label,
                'quantile_of_abs_distance': q, 'within_p50': within_p50, 'within_p90': within_p90,
            }))
    return pd.concat(rows, ignore_index=True)


def perturbation_instability_by_row(root, prereg_doc, panel, scenarios, candidates, veto_dict, discriminating,
                                    n=400, seed=99):
    root = Path(root)
    values = _values(panel)
    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')
    rows = []
    for model_id in MODEL_IDS:
        cand = candidates[model_id]
        for scenario_id in SCENARIO_IDS:
            s = scenarios[scenario_id]
            base_stage = np.asarray(_stage_with_veto(values, s.weights, s.lam, cand['q'], cand['p'],
                                                      veto_dict, s.require_employment_evidence))
            base_code = np.array([STAGE_CODE[c] for c in base_stage])
            rng = np.random.default_rng(seed)
            matrix = np.full((n, len(panel)), -1, dtype=np.int8)
            for k in range(n):
                perturbed = perturb.perturb_once(panel, pool, rng)
                p_values = qp_calibration.values_from_panel(perturbed)
                p_stage = _stage_with_veto(p_values, s.weights, s.lam, cand['q'], cand['p'], veto_dict,
                                           s.require_employment_evidence)
                matrix[k, :] = np.array([STAGE_CODE[c] for c in p_stage], dtype=np.int8)
            valid = (matrix != -1) & (base_code[None, :] != -1)
            changed = valid & (matrix != base_code[None, :])
            n_valid = valid.sum(axis=0)
            n_changed = changed.sum(axis=0)
            with np.errstate(invalid='ignore'):
                instability_rate = np.where(n_valid > 0, n_changed / np.maximum(n_valid, 1), np.nan)
            for i in range(len(panel)):
                alt_vals = matrix[changed[:, i], i]
                most_common = STAGE_NAME[int(pd.Series(alt_vals).mode().iat[0])] if len(alt_vals) else None
                rows.append({
                    'model_id': model_id, 'scenario_id': scenario_id,
                    'industry': panel['industry'].iat[i], 'quarter': panel['quarter'].iat[i],
                    'base_stage': base_stage[i], 'n_replicates': int(n_valid[i]), 'n_changed': int(n_changed[i]),
                    'instability_rate': instability_rate[i], 'most_common_alternative_stage': most_common,
                    'is_discriminating': bool(discriminating[i]),
                })
    table = pd.DataFrame(rows)
    return table


def c3_diagnosis(proximity, instability, panel, values, pool, discriminating):
    n_criteria_within_p90 = (proximity.groupby(['industry', 'quarter'])['within_p90']
                             .apply(lambda s: int(s.fillna(False).sum())).rename('n_criteria_within_p90'))
    instability = instability.merge(n_criteria_within_p90, on=['industry', 'quarter'], how='left')

    overall_mean = float(instability['instability_rate'].mean())
    top10 = (instability.sort_values('instability_rate', ascending=False)
            .head(10)[['model_id', 'scenario_id', 'industry', 'quarter', 'instability_rate']])
    top10_json = json.dumps(top10.to_dict('records'), ensure_ascii=False, default=float)

    valid = instability['instability_rate'].notna() & instability['n_criteria_within_p90'].notna()
    sp = resample.spearman(instability.loc[valid, 'instability_rate'], instability.loc[valid, 'n_criteria_within_p90'])

    emp_pool_p90 = float(np.percentile(np.abs(pool['employment']) * 100.0, 90))

    disc_keys = panel.loc[discriminating, ['industry', 'quarter']]
    disc_proximity = proximity.merge(disc_keys, on=['industry', 'quarter'])
    disc_any_p90 = (disc_proximity.groupby(['industry', 'quarter'])['within_p90']
                    .apply(lambda s: bool(s.fillna(False).any())))
    n_disc = len(disc_keys)
    n_disc_any_p90 = int(disc_any_p90.sum())

    summary = pd.DataFrame([{
        'overall_instability_rate_mean': overall_mean,
        'top10_unstable_rows_json': top10_json,
        'spearman_instability_vs_n_criteria_within_p90': sp,
        'g2_b1_value': BASE_B1['g2'], 'employment_revision_pool_p90_pct': emp_pool_p90,
        'g2_b1_vs_emp_revision_p90_ratio': BASE_B1['g2'] / emp_pool_p90 if emp_pool_p90 else np.nan,
        'n_discriminating': n_disc, 'n_discriminating_with_any_criterion_within_p90': n_disc_any_p90,
        'discriminating_within_p90_rate': (n_disc_any_p90 / n_disc) if n_disc else np.nan,
    }])
    return summary, instability


# ---------------------------------------------------------------- 변경 후보 기록(v1.2-candidates.yaml)
def write_v12_candidates(root, prereg_doc, veto_decision, weight_table):
    root = Path(root)
    base_doc = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    base_sha = params.parameter_payload_sha256(base_doc)
    wl_candidates = []
    for cid, sub in weight_table.groupby('candidate_id', sort=False):
        r = sub.iloc[0]
        wl_candidates.append({
            'candidate_id': cid, 'label': r['candidate_label'], 'status': str(r['status']),
            'weights': (None if r['status'] == 'NOT_FOUND'
                       else {j: float(r[f'w_{j}']) for j in config.CRITERIA}),
            'lambda': None if r['status'] == 'NOT_FOUND' else float(r['lambda']),
            'model_verdicts': {row['model_id']: {'c1_pass': bool(row['c1_pass']), 'c2_pass': bool(row['c2_pass']),
                                                 'c3_pass': bool(row['c3_pass']), 'c4_pass': bool(row['c4_pass']),
                                                 's1_pass': (None if pd.isna(row['s1_pass']) else bool(row['s1_pass']))}
                              for _, row in sub.iterrows()},
        })
    doc = {
        'status': 'REVALIDATION_CANDIDATES',
        'base_parameter_file': 'config/electre_tri_b_params.yaml',
        'base_parameter_sha256': base_sha,
        'prereg_sha256': prereg_doc['registration']['prereg_sha256'],
        'selected_veto': veto_decision.iloc[0].to_dict(),
        'weight_lambda_candidates': wl_candidates,
        'adoption_status': None,  # 사람이 결정한다 — 코드가 채택 여부를 쓰지 않는다
    }
    path = root / 'config/electre_tri_b_params.v1.2-candidates.yaml'
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False),
                    encoding='utf-8')
    return path


# ---------------------------------------------------------------- 산출·저장
OUTPUT_NAMES = ('electre_veto_screening', 'electre_veto_decision', 'electre_weight_lambda_inference',
               'electre_boundary_proximity', 'electre_perturbation_instability_by_row', 'electre_c3_diagnosis')


def run_phase4(root, write=True, instability_n=400, instability_seed=99):
    root = Path(root)
    prereg_doc, current, panel, base_doc, scenarios, candidates = _load_context(root)
    base_params_before = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    base_params_sha_before = params.parameter_payload_sha256(base_params_before)

    started = datetime.now(timezone.utc)
    prereg_hash = prereg.payload_sha256(prereg_doc)
    run_id = manifest.make_run_id(started, current['input_sha256'], prereg_hash)
    amendment_ids = ','.join(a['id'] for a in prereg_doc['amendments'])
    prov = {'run_id': run_id, 'run_started_at': started.isoformat(), 'input_sha256': current['input_sha256'],
           'prereg_sha256': prereg_hash, 'prereg_status': prereg_doc['prereg_status'],
           'prereg_amendment_ids': amendment_ids, 'phase': 4}

    # Step 1
    screening, veto_decision = veto_screening(root, prereg_doc, panel, base_doc, scenarios, candidates)
    selected_veto_id = veto_decision.iloc[0]['selected_veto_id']
    selected_vc = next(v for v in prereg_doc['veto_candidates'] if v['id'] == selected_veto_id)
    selected_veto_dict = (None if not selected_vc.get('enabled')
                          else {selected_vc['boundary']: {selected_vc['criterion']: selected_vc['threshold_value']}})

    # Step 2
    weight_table, w_means, w_inferred, w_nearest = weight_lambda_inference(
        root, prereg_doc, panel, base_doc, scenarios, candidates, selected_veto_id)

    # Step 3(모형 변경 아님, 진단 전용) — 선택된 veto를 고정하고 세 시나리오·두 모형 전부 진단
    values = _values(panel)
    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced
    proximity = boundary_proximity(panel, values, pool)
    instability = perturbation_instability_by_row(root, prereg_doc, panel, scenarios, candidates,
                                                   selected_veto_dict, discriminating,
                                                   n=instability_n, seed=instability_seed)
    diagnosis, instability = c3_diagnosis(proximity, instability, panel, values, pool, discriminating)

    # config/electre_tri_b_params.yaml 불변 확인
    base_params_after = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    if params.parameter_payload_sha256(base_params_after) != base_params_sha_before:
        raise RuntimeError('config/electre_tri_b_params.yaml이 Phase 4 실행 중 변경되었습니다.')

    v12_path = root / 'config/electre_tri_b_params.v1.2-candidates.yaml'
    if write:
        v12_path = write_v12_candidates(root, prereg_doc, veto_decision, weight_table)

    tables = {
        'electre_veto_screening': screening, 'electre_veto_decision': veto_decision,
        'electre_weight_lambda_inference': weight_table, 'electre_boundary_proximity': proximity,
        'electre_perturbation_instability_by_row': instability, 'electre_c3_diagnosis': diagnosis,
    }
    for name, frame in tables.items():
        for col, val in prov.items():
            frame[col] = val

    written = None
    if write:
        run_dir, written_info = p2.write_tables(root, run_id, tables)
        written = {name: info['canonical'] for name, info in written_info.items()}

    return {'run_id': run_id, 'provenance': prov, 'tables': tables, 'written': written,
           'v12_candidates_path': str(v12_path), 'selected_veto_id': selected_veto_id,
           'w_means': w_means, 'w_inferred': w_inferred, 'w_nearest': w_nearest,
           'panel': panel, 'values': values, 'scenarios': scenarios, 'candidates': candidates,
           'prereg_doc': prereg_doc}
