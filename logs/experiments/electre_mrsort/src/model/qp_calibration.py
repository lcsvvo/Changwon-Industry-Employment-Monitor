# -*- coding: utf-8 -*-
"""ELECTRE TRI-B v1.1 q·p 후보 보정과 시간 외 검증.

후보 선택은 보정구간만 사용한다. holdout은 선택이 끝난 뒤 평가하며 기존 v1.0
canonical 산출물과 current manifest를 수정하지 않는다.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import config, electre, inputs, manifest, params

CRIT = config.CRITERIA
RANK = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2, config.UNDETERMINED: np.nan}
SPLITS = {'CALIBRATION': ('2022Q1', '2024Q4'), 'HOLDOUT': ('2025Q1', '2026Q2'),
          'ALL': ('2022Q1', '2026Q2')}


def load_candidates(path):
    doc = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    errors = []
    for c in doc['candidates']:
        for g in CRIT:
            q, p = float(c['q'][g]), float(c['p'][g])
            if not 0 <= q <= p:
                errors.append(f"{c['candidate_id']}:{g}:0<=q<=p 위반")
    if errors:
        raise ValueError('; '.join(errors))
    return doc


def partial_concordance(values, boundary, q, p):
    """증가방향 pseudo-criterion. q=p=0이면 기존 crisp와 완전히 같다."""
    x = np.asarray(values, dtype=float)
    if not 0 <= q <= p:
        raise ValueError('0 <= q <= p 조건을 충족해야 합니다.')
    missing = np.isnan(x)
    if q == p:
        result = (x >= boundary - q).astype(float)
    else:
        lo, hi = boundary - p, boundary - q
        result = np.where(x <= lo, 0.0, np.where(x >= hi, 1.0, (x - lo) / (p - q)))
    result = np.where(missing, np.nan, np.clip(result, 0.0, 1.0))
    return result


def evaluate(values, scenario, candidate):
    scorable = values[list(CRIT)].notna().all(axis=1).to_numpy()
    out = pd.DataFrame(index=values.index)
    outranks = {}
    for h in electre.BOUNDARIES:
        cs = {}
        for g in CRIT:
            cs[g] = partial_concordance(values[g], scenario.profile(h)[g],
                                         float(candidate['q'][g]), float(candidate['p'][g]))
            out[f'c_{g}_{h}'] = cs[g]
            out[f'contribution_{g}_{h}'] = np.where(scorable, scenario.weights[g] * cs[g], np.nan)
        concordance = np.where(scorable, sum(scenario.weights[g] * np.nan_to_num(cs[g]) for g in CRIT), np.nan)
        # pseudo-criterion의 양의 지지가 있을 때 같은 경계의 고용증거로 인정한다.
        employment = scorable & np.any([cs[g] > 0 for g in config.EMPLOYMENT_CRITERIA], axis=0)
        before_gate = scorable & (concordance >= scenario.lam - electre.EPS)
        final = before_gate & (employment | (not scenario.require_employment_evidence))
        out[f'concordance_{h}'] = concordance
        out[f'emp_evidence_{h}'] = pd.Series(pd.array(employment, dtype='boolean'), index=values.index).mask(~scorable)
        out[f'outranks_{h}'] = pd.Series(pd.array(final, dtype='boolean'), index=values.index).mask(~scorable)
        outranks[h] = final
    out['scorable'] = scorable
    out['stage'] = electre.pessimistic_assignment(outranks['b1'], outranks['b2'], scorable)
    return out


def values_from_panel(panel):
    return pd.DataFrame({'g1': panel[config.CRITERION_COLUMNS['g1']].astype(float),
                         'g2': panel[config.CRITERION_COLUMNS['g2']].astype(float),
                         'g3': panel[config.CRITERION_COLUMNS['g3']].astype(float),
                         'g4': panel['g4_delta00'].astype(float)}, index=panel.index)


def temporal_targets(panel):
    out = panel[['industry', 'quarter', 'state', 'employment_yoy', 'production_yoy']].copy()
    by = panel.groupby('industry', sort=False)
    out['next_state'] = by['state'].shift(-1)
    out['next_quarter'] = by['quarter'].shift(-1)
    out['next_emp_yoy'] = by['employment_yoy'].shift(-1)
    out['next_prod_yoy'] = by['production_yoy'].shift(-1)
    out['state_t2'] = by['state'].shift(-2)
    out['quarter_t2'] = by['quarter'].shift(-2)
    valid_next = out['next_state'].isin(['S1','S2','S3','S4','N'])
    valid_t2 = out['state_t2'].isin(['S1','S2','S3','S4','N'])
    out['next_negative_state'] = out['next_state'].isin(['S2', 'S4']).where(valid_next)
    out['next_employment_decline'] = out['next_emp_yoy'].lt(0).where(out['next_emp_yoy'].notna())
    out['next_production_decline'] = out['next_prod_yoy'].lt(0).where(out['next_prod_yoy'].notna())
    out['negative_state_persisted'] = (out['state'].isin(['S2', 'S4']) & out['next_state'].isin(['S2', 'S4'])).where(valid_next)
    out['t2_negative_state'] = out['state_t2'].isin(['S2', 'S4']).where(valid_t2)
    return out


def _split_mask(quarters, split, require_next=False):
    start, end = SPLITS[split]
    q = quarters.astype(str)
    mask = q.between(start, end)
    if require_next:
        mask &= q.ne('2026Q2')
    return mask


def _spearman(stage, outcome):
    x = stage.map(RANK).astype(float)
    y = pd.to_numeric(outcome, errors='coerce')
    valid = x.notna() & y.notna()
    return float(x[valid].corr(y[valid], method='spearman')) if valid.sum() >= 3 else np.nan


def temporal_summary(rows, split):
    sub = rows[_split_mask(rows.quarter, split, require_next=True)
               & rows.stage.ne(config.UNDETERMINED) & rows.next_negative_state.notna()].copy()
    if split == 'CALIBRATION':
        sub = sub[sub.next_quarter.astype(str).le(SPLITS['CALIBRATION'][1])]
        sub.loc[sub.quarter_t2.astype(str).gt(SPLITS['CALIBRATION'][1]), 't2_negative_state'] = np.nan
    metrics = []
    for stage in ('OBSERVE', 'CHECK', 'PRIORITY'):
        g = sub[sub.stage == stage]
        rec = {'stage': stage, 'stage_rank': RANK[stage], 'n_rows': len(g)}
        for col in ('next_negative_state', 'next_employment_decline', 'next_production_decline',
                    'negative_state_persisted', 't2_negative_state'):
            valid = g[col].dropna()
            rec[f'{col}_numerator'] = int(valid.astype(bool).sum())
            rec[f'{col}_denominator'] = int(len(valid))
            rec[f'{col}_rate'] = float(valid.astype(float).mean()) if len(valid) else np.nan
        metrics.append(rec)
    table = pd.DataFrame(metrics)
    by_stage = table.set_index('stage')['next_negative_state_rate']
    ordered = bool(by_stage.get('PRIORITY', np.nan) > by_stage.get('CHECK', np.nan) > by_stage.get('OBSERVE', np.nan))
    overall = float(sub.next_negative_state.astype(float).mean()) if len(sub) else np.nan
    summary = {'n_rows': len(sub), 'ordered_next_negative': ordered,
               'spearman_next_negative': _spearman(sub.stage, sub.next_negative_state),
               'priority_minus_overall': float(by_stage.get('PRIORITY', np.nan) - overall),
               'overall_minus_observe': float(overall - by_stage.get('OBSERVE', np.nan)),
               'priority_minus_observe': float(by_stage.get('PRIORITY', np.nan) - by_stage.get('OBSERVE', np.nan))}
    return table, summary


def external_summary(rows, split):
    sub = rows[_split_mask(rows.quarter, split)].copy()
    records = []
    for stage in ('OBSERVE', 'CHECK', 'PRIORITY'):
        g = sub[sub.stage == stage]
        for name, col, condition in (
            ('operating_rate_worsened', 'op_rate_used_yoy_pp', lambda x: x < 0),
            ('firm_count_declined', 'firm_count_delta_yoy', lambda x: x < 0),
            ('ppi_direction_stable', 'ppi_direction_status', lambda x: x == 'SAME_ALL')):
            if col not in g:
                records.append({'stage': stage, 'metric': name, 'status': 'NOT_EVALUABLE', 'numerator': 0, 'denominator': 0, 'rate': np.nan})
                continue
            valid = g[col].dropna()
            hit = condition(valid)
            records.append({'stage': stage, 'metric': name, 'status': 'EVALUATED' if len(valid) else 'NOT_EVALUABLE',
                            'numerator': int(hit.sum()), 'denominator': int(len(valid)),
                            'rate': float(hit.mean()) if len(valid) else np.nan})
    return pd.DataFrame(records)


def constraints(values, scenario, candidate):
    ev = evaluate(values, scenario, candidate)
    range_bad = int(((ev.filter(regex='^c_') < 0) | (ev.filter(regex='^c_') > 1)).sum().sum())
    contradiction = int((ev.outranks_b2.fillna(False) & ~ev.outranks_b1.fillna(False)).sum())
    mono = dominance = 0
    for g in CRIT:
        bumped = values.copy(); bumped[g] = bumped[g] + max(float(candidate['p'][g]), 1e-6)
        after = evaluate(bumped, scenario, candidate).stage.map(RANK)
        before = ev.stage.map(RANK)
        mono += int((after.dropna() < before.dropna()).sum())
    complete = values[values.notna().all(axis=1)].reset_index(drop=True)
    stages = evaluate(complete, scenario, candidate).stage.map(RANK).to_numpy()
    arr = complete.to_numpy(float)
    for i in range(len(arr)):
        dominated = np.all(arr[i] >= arr, axis=1) & np.any(arr[i] > arr, axis=1)
        dominance += int(np.sum(stages[i] < stages[dominated]))
    shuffled = values.sample(frac=1, random_state=11)
    order_ok = evaluate(shuffled, scenario, candidate).stage.sort_index().equals(ev.stage.sort_index())
    return {'range_violations': range_bad, 'boundary_contradictions': contradiction,
            'monotonicity_violations': mono, 'dominance_violations': dominance,
            'row_order_independent': bool(order_ok), 'passed': range_bad + contradiction + mono + dominance == 0 and order_ok}


def scenario_rows(panel, values, scenario, candidate, targets):
    ev = evaluate(values, scenario, candidate)
    quality = [c for c in ('threshold_flag', 'ppi_direction_status', 'state', 'core_data_status',
                            'q1_routing_status', 'g4_delta00_left_censored', 'g4_delta00_open_run',
                            'g4_delta00_window_saturated', 'small_firm_count_flag', 'routeability_status',
                            'op_rate_used_yoy_pp', 'firm_count_delta_yoy') if c in panel]
    out = pd.concat([panel[['industry', 'quarter', *quality]].reset_index(drop=True), values.reset_index(drop=True),
                     ev.reset_index(drop=True)], axis=1)
    target_cols = [c for c in targets if c not in ('industry', 'quarter', 'state')]
    out = pd.concat([out, targets[target_cols].reset_index(drop=True)], axis=1)
    out.insert(0, 'scenario_id', scenario.scenario_id)
    out.insert(0, 'candidate_id', candidate['candidate_id'])
    return out


def partial_trace(rows, scenarios, candidates):
    traces = []
    for _, r in rows.iterrows():
        cand = candidates[r.candidate_id]; sc = scenarios[r.scenario_id]
        for h in electre.BOUNDARIES:
            rec = {'candidate_id': r.candidate_id, 'scenario_id': r.scenario_id,
                   'industry': r.industry, 'quarter': r.quarter, 'boundary': h,
                   'stage': r.stage, 'concordance': r[f'concordance_{h}'], 'lambda': sc.lam,
                   'outranks': r[f'outranks_{h}'],
                   'diagnostic_case': (r.industry, r.quarter) in {
                       ('기계','2022Q1'),('운송장비','2025Q1'),('전기전자','2025Q1')},
                   'next_state': r.get('next_state'), 'state_t2': r.get('state_t2'),
                   'op_rate_used_yoy_pp': r.get('op_rate_used_yoy_pp'),
                   'firm_count_delta_yoy': r.get('firm_count_delta_yoy')}
            for g in CRIT:
                rec.update({f'{g}_value': r[g], f'{g}_boundary': sc.profile(h)[g],
                            f'{g}_distance': r[g] - sc.profile(h)[g] if pd.notna(r[g]) else np.nan,
                            f'{g}_q': cand['q'][g], f'{g}_p': cand['p'][g], f'{g}_c': r[f'c_{g}_{h}']})
            traces.append(rec)
    return pd.DataFrame(traces)


def select_on_calibration(comparison):
    """필수제약→보정구간 방향성→단순성의 사전 명시된 사전식 선택."""
    eligible = comparison[(comparison.scenario_id == '기준') & comparison.constraints_passed].copy()
    eligible['ordered_rank'] = eligible.calibration_ordered_next_negative.astype(int)
    eligible = eligible.sort_values(['ordered_rank', 'calibration_spearman_next_negative',
                                     'calibration_priority_minus_observe', 'external_alignment_mean', 'p_total'],
                                    ascending=[False, False, False, False, True], kind='mergesort')
    return None if eligible.empty else str(eligible.iloc[0].candidate_id)


def run(root, write=True):
    root = Path(root)
    candidate_path = root / 'config/electre_tri_b_params.v1.1-candidates.yaml'
    doc = load_candidates(candidate_path)
    base_doc = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    if params.parameter_payload_sha256(base_doc) != doc['base_parameter_sha256']:
        raise RuntimeError('v1.0 파라미터 해시가 후보 등록값과 다릅니다.')
    current = manifest.load_manifest(root)
    panel = manifest.load_current_table(root, 'input_panel')
    if panel is None or set(panel.run_id.astype(str)) != {current['run_id']}:
        raise RuntimeError('현재 input panel과 manifest가 일치하지 않습니다.')
    values, targets = values_from_panel(panel), temporal_targets(panel)
    scenarios = {s.scenario_id: s for s in [electre.Scenario.from_block(x) for x in base_doc['scenarios']]}
    candidates = {c['candidate_id']: c for c in doc['candidates']}
    # 후보 실행 전 선행 감사: 단위/방향과 모든 v1.0 assignment를 행 단위로 대조한다.
    if set(doc['direction'].values()) != {'increasing'}:
        raise RuntimeError('모든 기준이 increasing 방향이어야 합니다.')
    if not np.allclose(values.g2, np.maximum(0,-panel.employment_yoy),equal_nan=True):
        raise RuntimeError('g2 저장 단위/정의가 고용 YoY 퍼센트포인트와 다릅니다.')
    if not np.allclose(values.g3, np.maximum(0,-panel.production_yoy),equal_nan=True):
        raise RuntimeError('g3 저장 단위/정의가 명목 생산 YoY 퍼센트포인트와 다릅니다.')
    old_assignments = manifest.load_current_table(root,'assignments')
    if old_assignments is None:
        raise RuntimeError('v1.0 재현 대조용 CURRENT assignment가 없습니다.')
    for sid,scenario in scenarios.items():
        reproduced=evaluate(values,scenario,candidates['v1.0_crisp']).stage.to_numpy()
        old=old_assignments[old_assignments.scenario_id==sid].set_index(['industry','quarter'])
        expected=old.loc[pd.MultiIndex.from_frame(panel[['industry','quarter']]),'display_class_by_scenario'].to_numpy()
        if not np.array_equal(reproduced,expected):
            raise RuntimeError(f'{sid} v1.0 재현 실패: q·p 후보 실행 차단')
    all_rows, comparisons, calibration_tables, holdout_tables, external_tables = [], [], [], [], []
    constraint_map = {}
    for cid, cand in candidates.items():
        for sid, scenario in scenarios.items():
            rows = scenario_rows(panel, values, scenario, cand, targets)
            all_rows.append(rows)
            cons = constraints(values, scenario, cand); constraint_map[(cid, sid)] = cons
            cal_table, cal = temporal_summary(rows, 'CALIBRATION')
            cal_table.insert(0, 'scenario_id', sid); cal_table.insert(0, 'candidate_id', cid); cal_table['split'] = 'CALIBRATION'
            calibration_tables.append(cal_table)
            for split in ('CALIBRATION','HOLDOUT'):
                if split == 'HOLDOUT': continue  # 선택 이후에만 계산한다.
                ext = external_summary(rows, split); ext.insert(0, 'scenario_id', sid); ext.insert(0, 'candidate_id', cid); ext['split']=split
                external_tables.append(ext)
            cal_rows = rows[_split_mask(rows.quarter, 'CALIBRATION')]
            op_align = _spearman(cal_rows.stage, cal_rows.op_rate_used_yoy_pp.lt(0).where(cal_rows.op_rate_used_yoy_pp.notna()))
            firm_align = _spearman(cal_rows.stage, cal_rows.firm_count_delta_yoy.lt(0).where(cal_rows.firm_count_delta_yoy.notna()))
            external_mean = float(np.nanmean([op_align, firm_align])) if not (np.isnan(op_align) and np.isnan(firm_align)) else np.nan
            counts = rows.stage.value_counts()
            partial_n = int(((rows.filter(regex='^c_') > 0) & (rows.filter(regex='^c_') < 1)).sum().sum())
            comparisons.append({'candidate_id': cid, 'scenario_id': sid, 'constraints_passed': cons['passed'], **cons,
                                **{f'n_{k.lower()}': int(counts.get(k, 0)) for k in ('OBSERVE','CHECK','PRIORITY','UNDETERMINED')},
                                'partial_concordance_n': partial_n,
                                **{f'calibration_{k}': v for k, v in cal.items()},
                                'external_operating_rate_spearman': op_align,
                                'external_firm_decline_spearman': firm_align,
                                'external_alignment_mean': external_mean,
                                'p_total': float(sum(cand['p'].values())), 'selection_uses_holdout': False})
    all_rows = pd.concat(all_rows, ignore_index=True)
    comparison = pd.DataFrame(comparisons)
    selected = select_on_calibration(comparison)
    # 이 지점 이후에만 holdout을 계산하며 선택 함수의 입력은 변경하지 않는다.
    for cid in candidates:
        for sid in scenarios:
            rows = all_rows[(all_rows.candidate_id==cid)&(all_rows.scenario_id==sid)]
            hold_table, _ = temporal_summary(rows, 'HOLDOUT')
            hold_table.insert(0,'scenario_id',sid); hold_table.insert(0,'candidate_id',cid); hold_table['split']='HOLDOUT'
            holdout_tables.append(hold_table)
            ext=external_summary(rows,'HOLDOUT'); ext.insert(0,'scenario_id',sid); ext.insert(0,'candidate_id',cid); ext['split']='HOLDOUT'
            external_tables.append(ext)

    baseline = all_rows[(all_rows.candidate_id == 'v1.0_crisp') & (all_rows.scenario_id == '기준')][['industry','quarter','stage']].rename(columns={'stage':'v1_0_stage'})
    changed = all_rows.merge(baseline, on=['industry','quarter'], how='left')
    changed['changed_from_v1_0'] = changed.stage.ne(changed.v1_0_stage)
    changed['stage_change'] = changed.v1_0_stage.astype(str) + '→' + changed.stage.astype(str)
    changed['aux_operating_rate_worsened'] = changed.op_rate_used_yoy_pp.lt(0).where(changed.op_rate_used_yoy_pp.notna())
    changed['aux_firm_count_declined'] = changed.firm_count_delta_yoy.lt(0).where(changed.firm_count_delta_yoy.notna())
    changed = changed[changed.changed_from_v1_0]

    # ±10% p 안정성: q는 고정, p는 q 이상으로 제한.
    stability = []
    for cid, cand in candidates.items():
        for sid, scenario in scenarios.items():
            base = all_rows[(all_rows.candidate_id == cid) & (all_rows.scenario_id == sid)].stage.reset_index(drop=True)
            for factor in (.9, 1.1):
                alt = json.loads(json.dumps(cand)); alt['p'] = {g: max(float(alt['q'][g]), float(alt['p'][g]) * factor) for g in CRIT}
                stage = evaluate(values, scenario, alt).stage.reset_index(drop=True)
                valid = base.ne(config.UNDETERMINED)
                stability.append({'candidate_id': cid, 'scenario_id': sid, 'p_factor': factor, 'n_complete': int(valid.sum()),
                                  'n_changed': int((base[valid] != stage[valid]).sum()),
                                  'stage_retention_rate': float((base[valid] == stage[valid]).mean())})
    stability = pd.DataFrame(stability)

    # 보정구간 업종 하나 제외 시 동일 선택 규칙을 적용한다(holdout 미사용).
    loio = []
    industries = sorted(panel.industry.unique())
    for excluded in industries:
        temp = []
        for cid in candidates:
            rows = all_rows[(all_rows.candidate_id == cid) & (all_rows.scenario_id == '기준') & (all_rows.industry != excluded)]
            _, cal = temporal_summary(rows, 'CALIBRATION')
            cal_rows = rows[_split_mask(rows.quarter, 'CALIBRATION')]
            op = _spearman(cal_rows.stage, cal_rows.op_rate_used_yoy_pp.lt(0).where(cal_rows.op_rate_used_yoy_pp.notna()))
            firm = _spearman(cal_rows.stage, cal_rows.firm_count_delta_yoy.lt(0).where(cal_rows.firm_count_delta_yoy.notna()))
            temp.append({'candidate_id': cid, 'scenario_id': '기준', 'constraints_passed': constraint_map[(cid,'기준')]['passed'],
                         'calibration_ordered_next_negative': cal['ordered_next_negative'],
                         'calibration_spearman_next_negative': cal['spearman_next_negative'],
                         'calibration_priority_minus_observe': cal['priority_minus_observe'],
                         'external_alignment_mean': float(np.nanmean([op,firm])),
                         'p_total': sum(candidates[cid]['p'].values())})
        chosen = select_on_calibration(pd.DataFrame(temp))
        loio.append({'excluded_industry': excluded, 'selected_candidate_id': chosen,
                     'same_as_full_calibration_selection': chosen == selected, 'selection_uses_holdout': False})
    loio = pd.DataFrame(loio)

    holdout = pd.concat(holdout_tables, ignore_index=True)
    calibration = pd.concat(calibration_tables, ignore_index=True)
    external = pd.concat(external_tables, ignore_index=True)
    selected_hold = comparison[comparison.candidate_id == selected].copy()
    # 선택 후 holdout 지표를 결합한다. 선택 함수 입력에는 포함되지 않는다.
    hold_summary = []
    for sid in scenarios:
        r = all_rows[(all_rows.candidate_id == selected) & (all_rows.scenario_id == sid)]
        _, hs = temporal_summary(r, 'HOLDOUT'); hold_summary.append({'scenario_id': sid, **hs})
    hs = pd.DataFrame(hold_summary).add_prefix('holdout_').rename(columns={'holdout_scenario_id':'scenario_id'})
    selected_hold = selected_hold.merge(hs, on='scenario_id')
    base_hold = comparison[(comparison.candidate_id == 'v1.0_crisp') & (comparison.scenario_id == '기준')].iloc[0]
    cand_hold = selected_hold[selected_hold.scenario_id == '기준'].iloc[0]
    # 실제 holdout 개선이 있어야 채택. 방향성/연관/격차 중 2개 이상 엄격 개선.
    base_rows = all_rows[(all_rows.candidate_id == 'v1.0_crisp') & (all_rows.scenario_id == '기준')]
    _, base_h = temporal_summary(base_rows, 'HOLDOUT')
    improvements = [cand_hold.holdout_ordered_next_negative and not base_h['ordered_next_negative'],
                    cand_hold.holdout_spearman_next_negative > base_h['spearman_next_negative'] + 1e-12,
                    cand_hold.holdout_priority_minus_observe > base_h['priority_minus_observe'] + 1e-12]
    selected_stability = float(stability[stability.candidate_id == selected].stage_retention_rate.min())
    loio_retention = float(loio.same_as_full_calibration_selection.mean())
    base_external = float(base_hold.external_alignment_mean)
    selected_external = float(cand_hold.external_alignment_mean)
    external_improved = selected_external > base_external + 1e-12
    external_direction_supported = (float(cand_hold.external_operating_rate_spearman) > 0
                                    and float(cand_hold.external_firm_decline_spearman) > 0)
    adopt = (selected != 'v1.0_crisp' and sum(map(bool, improvements)) >= 2 and external_improved
             and bool(cand_hold.holdout_ordered_next_negative) and external_direction_supported
             and selected_stability >= .95 and loio_retention >= .8)
    final_decision = ('ADOPT_V1_1_CANDIDATE' if adopt else
                      ('INSUFFICIENT_EVIDENCE' if sum(map(bool, improvements)) > 0 else 'KEEP_V1_0'))

    # 세 시나리오 견고성(선정 후보, 업종×분기).
    sr = all_rows[all_rows.candidate_id == selected][['industry','quarter','scenario_id','stage']]
    pivot = sr.pivot(index=['industry','quarter'], columns='scenario_id', values='stage').reset_index()
    for sid in config.SCENARIO_IDS:
        if sid not in pivot: pivot[sid] = config.UNDETERMINED
    def robust(r):
        stages = [r[s] for s in config.SCENARIO_IDS]
        if config.UNDETERMINED in stages: return pd.Series([np.nan,np.nan,np.nan,config.UNDETERMINED])
        ranks = [RANK[x] for x in stages]; spread=max(ranks)-min(ranks)
        return pd.Series([min(stages,key=RANK.get),max(stages,key=RANK.get),spread,
                          'ROBUST' if spread==0 else ('ADJACENT_SENSITIVE' if spread==1 else 'HIGHLY_SENSITIVE')])
    pivot[['lowest_stage','highest_stage','stage_range','robustness_status']] = pivot.apply(robust, axis=1)
    pivot['same_stage_count'] = pivot[list(config.SCENARIO_IDS)].nunique(axis=1).rsub(4)
    pivot.insert(0, 'candidate_id', selected)

    trace = partial_trace(all_rows, scenarios, candidates)
    registry = []
    for cid,c in candidates.items():
        for g in CRIT:
            registry.append({'candidate_id':cid,'label':c['label'],'criterion':g,'q_input':c['q'][g],'p_input':c['p'][g],
                             'input_unit':doc['units'][g],'q_model_unit':c['q'][g],'p_model_unit':c['p'][g],
                             'unit_conversion_factor':1.0,'origin':c['origin'],'selected_on_calibration':cid==selected})
    registry = pd.DataFrame(registry)
    selection = pd.DataFrame([{'selected_on_calibration': selected, 'final_decision': final_decision,
                               'holdout_used_for_selection': False, 'holdout_improvement_test_count': sum(map(bool, improvements)),
                               'external_alignment_improved': external_improved,
                               'external_direction_supported': external_direction_supported,
                               'holdout_ordered_next_negative': bool(cand_hold.holdout_ordered_next_negative),
                               'minimum_p_perturbation_retention': selected_stability,
                               'leave_one_industry_selection_retention': loio_retention,
                               'calibration_period':'2022Q1-2024Q4','holdout_period':'2025Q1-2026Q2',
                               'candidate_file_created': bool(adopt),
                               'adoption_status': 'CALIBRATED_CANDIDATE' if adopt else 'NO_QP_CANDIDATE_ADOPTED',
                               'reason': ('holdout·외적 정합성·안정성 채택 조건 충족' if adopt else
                                          '일부 holdout 지표는 개선됐으나 단계 순서와 양의 외적 정합성이 입증되지 않아 채택 근거 부족') }])
    tables = {'electre_qp_candidate_registry':registry,'electre_qp_candidate_comparison':comparison,
              'electre_qp_calibration_results':calibration,'electre_qp_holdout_validation':holdout,
              'electre_qp_changed_cases':changed,'electre_qp_partial_concordance_trace':trace,
              'electre_qp_scenario_robustness':pivot,'electre_qp_parameter_stability':stability,
              'electre_qp_leave_one_industry_out':loio,'electre_qp_selection_decision':selection,
              'electre_qp_external_validation':external}
    started=datetime.now(timezone.utc); digest=hashlib.sha256((current['run_id']+json.dumps(doc,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()[:8]
    run_id=started.strftime('%Y%m%dT%H%M%S%fZ')+'-'+digest
    prov={'run_id':run_id,'run_started_at':started.isoformat(),'source_run_id':current['run_id'],
          'input_sha256':current['input_sha256'],'base_parameter_sha256':doc['base_parameter_sha256'],
          'candidate_config_sha256':inputs.sha256_text_file(candidate_path),'model_spec_version':doc['model_spec_version']}
    for k,t in tables.items():
        for col,val in prov.items(): t[col]=val
    if write:
        run_dir=root/'outputs'/'qp_runs'/run_id; run_dir.mkdir(parents=True,exist_ok=True)
        files={}
        for k,t in tables.items():
            path=root/'outputs'/'tables'/f'{k}.csv'; t.to_csv(path,index=False,encoding='utf-8-sig'); t.to_csv(run_dir/path.name,index=False,encoding='utf-8-sig')
            files[k]={'canonical_path':path.relative_to(root).as_posix(),'run_path':(run_dir/path.name).relative_to(root).as_posix()}
        (run_dir/'qp_run_manifest.json').write_text(json.dumps({**prov,'final_decision':final_decision,'selected_on_calibration':selected,'files':files},ensure_ascii=False,indent=2),encoding='utf-8')
        write_figures(root,tables,all_rows,selected)
    return {'run_id':run_id,'selected':selected,'final_decision':final_decision,'tables':tables,'all_rows':all_rows,
            'base_doc':base_doc,'candidate_doc':doc,'provenance':prov}


def write_figures(root,tables,all_rows,selected):
    import matplotlib; matplotlib.use('Agg',force=True)
    import matplotlib.pyplot as plt
    out=Path(root)/'outputs'/'figures'; out.mkdir(parents=True,exist_ok=True)
    plt.rcParams['font.family']='Malgun Gothic'; plt.rcParams['axes.unicode_minus']=False
    colors=config.DISPLAY_COLORS
    # 1 분포
    split_rows=[]
    for split in SPLITS:
        sub=all_rows[_split_mask(all_rows.quarter,split)&all_rows.scenario_id.eq('기준')].copy(); sub['split']=split; split_rows.append(sub)
    counts=pd.concat(split_rows).groupby(['candidate_id','split','stage']).size().unstack(fill_value=0)
    counts[[c for c in ('OBSERVE','CHECK','PRIORITY','UNDETERMINED') if c in counts]].plot.bar(stacked=True,figsize=(12,5),color=[colors[c] for c in ('OBSERVE','CHECK','PRIORITY','UNDETERMINED')])
    plt.title('q·p 후보별 전체·보정·검증 구간 등급 분포(기준 시나리오)'); plt.tight_layout(); plt.savefig(out/'electre_qp_candidate_stage_distribution.png',dpi=180); plt.close()
    # 2 시간 결과
    cal=tables['electre_qp_calibration_results']; x=cal[cal.scenario_id=='기준'].pivot(index='candidate_id',columns='stage',values='next_negative_state_rate')
    x.plot.bar(figsize=(10,5),color=[colors.get(c,'#777') for c in x.columns]); plt.ylabel('다음 분기 부정 상태 비율'); plt.tight_layout(); plt.savefig(out/'electre_qp_next_negative_rates.png',dpi=180); plt.close()
    # 3 변경행
    ch=tables['electre_qp_changed_cases']; ch.groupby(['candidate_id','stage_change']).size().unstack(fill_value=0).plot.bar(stacked=True,figsize=(10,5)); plt.tight_layout(); plt.savefig(out/'electre_qp_changed_cases.png',dpi=180); plt.close()
    # 4 경계 구간
    fig,axs=plt.subplots(2,2,figsize=(11,8)); cand={c['candidate_id']:c for c in yaml.safe_load((Path(root)/'config/electre_tri_b_params.v1.1-candidates.yaml').read_text(encoding='utf-8'))['candidates']}[selected]
    base=all_rows[(all_rows.candidate_id==selected)&(all_rows.scenario_id=='기준')]
    boundaries={'g1':(100,500),'g2':(2,5),'g3':(5,10),'g4':(2,4)}
    for ax,g in zip(axs.ravel(),CRIT):
        ax.hist(base[g].dropna(),bins=18,color='#6B7C8F');
        for b in boundaries[g]: ax.axvspan(b-cand['p'][g],b-cand['q'][g],color=colors['CHECK'],alpha=.25); ax.axvline(b,color=colors['PRIORITY'])
        ax.set_title(config.CRITERION_LABELS[g])
    fig.tight_layout(); fig.savefig(out/'electre_qp_criterion_bands.png',dpi=180); plt.close(fig)
    # 5 부분 concordance
    tr=tables['electre_qp_partial_concordance_trace']; ids=list(tr.candidate_id.unique()); fig,axs=plt.subplots(1,len(ids),figsize=(15,4),sharey=True)
    for ax,cid in zip(axs,ids):
        sub=tr[(tr.candidate_id==cid)&tr.scenario_id.eq('기준')]; vals=pd.concat([sub[f'{g}_c'] for g in CRIT],ignore_index=True)
        ax.hist(vals.dropna(),bins=np.linspace(0,1,21),color='#6B7C8F'); ax.set_title(cid,fontsize=9)
    fig.suptitle('후보별 부분 concordance 분포'); fig.tight_layout(); fig.savefig(out/'electre_qp_partial_concordance_distribution.png',dpi=180); plt.close(fig)
    # 6 견고성
    rob=tables['electre_qp_scenario_robustness'].robustness_status.value_counts(); rob.plot.bar(figsize=(7,4),color='#6B7C8F'); plt.title(f'{selected} 세 시나리오 견고성'); plt.tight_layout(); plt.savefig(out/'electre_qp_scenario_robustness.png',dpi=180); plt.close()
