# -*- coding: utf-8 -*-
"""05단계 시범모형 비교·안정성 검증·시각화.

핵심 분류는 :mod:`model.electre`를 재사용한다. 이 모듈은 동일한 경계의
고정 단순규칙, 설명 가능한 비교표, 기준제거/단조성/dominance 검증과
05단계 전용 출력 형식만 담당한다.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, electre

RANK = {config.UNDETERMINED: -1, 'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
QUALITY_COLUMNS = (
    'state', 'q1_routing_status', 'threshold_flag', 'ppi_direction_status',
    'core_data_status', 'unscorable_reason', 'g4_delta00_left_censored',
    'g4_delta00_open_run', 'g4_delta00_window_saturated', 'small_firm_count_flag',
    'residual_category', 'routeability_status',
)


def _direction(before, after):
    if before == after:
        return 'SAME'
    if before == config.UNDETERMINED or after == config.UNDETERMINED:
        return 'NOT_COMPARABLE'
    return 'UP' if RANK[after] > RANK[before] else 'DOWN'


def simple_rule(values, profiles):
    """동일 b1·b2에서 2개 이상 + 같은 경계의 고용근거를 요구하는 고정 규칙."""
    idx = values.index
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    out = pd.DataFrame(index=idx)
    outranks = {}
    for boundary in electre.BOUNDARIES:
        passed = {g: (values[g] >= profiles[boundary][g]).to_numpy() for g in config.CRITERIA}
        count = sum(passed.values())
        employment = np.any([passed[g] for g in config.EMPLOYMENT_CRITERIA], axis=0)
        final = scorable & (count >= 2) & employment
        for g in config.CRITERIA:
            out[f'rule_pass_{g}_{boundary}'] = pd.Series(
                pd.array(passed[g], dtype='boolean'), index=idx).mask(~scorable)
        out[f'rule_pass_count_{boundary}'] = np.where(scorable, count, np.nan)
        out[f'rule_employment_evidence_{boundary}'] = pd.Series(
            pd.array(employment, dtype='boolean'), index=idx).mask(~scorable)
        out[f'rule_outranks_{boundary}'] = pd.Series(
            pd.array(final, dtype='boolean'), index=idx).mask(~scorable)
        outranks[boundary] = final
    out['simple_rule_stage'] = electre.pessimistic_assignment(
        outranks['b1'], outranks['b2'], scorable)
    out['simple_rule_decisive_rule'] = np.select(
        [~scorable, outranks['b2'], outranks['b1']],
        ['CORE_CRITERION_MISSING', 'B2_TWO_OF_FOUR_WITH_EMPLOYMENT',
         'B1_TWO_OF_FOUR_WITH_EMPLOYMENT'], default='NO_BOUNDARY_PASSED')
    out['simple_rule_undetermined_reason'] = np.where(
        scorable, None, values.apply(lambda r: 'MISSING:' + ','.join(r.index[r.isna()]), axis=1))
    return out


def simple_rule_latest(panel, values, profiles, latest_quarter):
    rule = simple_rule(values, profiles)
    keep = panel['quarter'].astype(str).eq(str(latest_quarter))
    cols = ['industry', 'quarter', *[c for c in QUALITY_COLUMNS if c in panel.columns]]
    out = pd.concat([panel.loc[keep, cols].reset_index(drop=True),
                     values.loc[keep].reset_index(drop=True), rule.loc[keep].reset_index(drop=True)], axis=1)
    for h in electre.BOUNDARIES:
        for g in config.CRITERIA:
            out[f'{h}_{g}_boundary'] = profiles[h][g]
    return out


def assignment_trace(panel, values, scenario, evaluation):
    rows = []
    quality = [c for c in QUALITY_COLUMNS if c in panel.columns]
    scorable = values[list(config.CRITERIA)].notna().all(axis=1)
    for h in electre.BOUNDARIES:
        block = panel[['industry', 'quarter', *quality]].copy()
        block.insert(0, 'scenario_id', scenario.scenario_id)
        block['boundary'] = h
        for g in config.CRITERIA:
            block[f'{g}_value'] = values[g]
            block[f'{g}_boundary'] = scenario.profile(h)[g]
            block[f'{g}_partial_concordance'] = np.where(
                scorable, (values[g] >= scenario.profile(h)[g]).astype(float), np.nan)
            block[f'{g}_weight'] = scenario.weights[g]
            block[f'{g}_weighted_contribution'] = (
                block[f'{g}_partial_concordance'] * scenario.weights[g])
        block['concordance'] = evaluation[f'concordance_{h}']
        block['lambda'] = scenario.lam
        block['concordance_meets_lambda'] = evaluation[f'outranks_{h}_before_gate']
        block['employment_evidence_gate'] = evaluation[f'emp_evidence_at_{h}']
        block['outranks'] = evaluation[f'outranks_{h}']
        block['electre_stage'] = evaluation['display_class_by_scenario']
        block['undetermined_reason'] = np.where(
            scorable, None, values.apply(lambda r: 'MISSING:' + ','.join(r.index[r.isna()]), axis=1))
        rows.append(block)
    return pd.concat(rows, ignore_index=True)


def comparison_table(panel, values, scenario, evaluation, rule):
    out = panel[['industry', 'quarter']].copy()
    out.insert(0, 'scenario_id', scenario.scenario_id)
    out['simple_rule_stage'] = rule['simple_rule_stage'].to_numpy()
    out['electre_stage'] = evaluation['display_class_by_scenario'].to_numpy()
    out['stage_agrees'] = out['simple_rule_stage'].eq(out['electre_stage'])
    out['stage_difference_direction'] = [
        _direction(a, b) for a, b in zip(out.simple_rule_stage, out.electre_stage)]
    disagreement_boundary, drivers, explanation = [], [], []
    for i in range(len(out)):
        if evaluation.iloc[i]['display_class_by_scenario'] == config.UNDETERMINED:
            disagreement_boundary.append(None)
            drivers.append(None)
            explanation.append('핵심 기준 결측으로 두 모형 모두 판정불가')
            continue
        diffs = [h for h in electre.BOUNDARIES
                 if bool(rule.iloc[i][f'rule_outranks_{h}']) != bool(evaluation.iloc[i][f'outranks_{h}'])]
        disagreement_boundary.append('|'.join(diffs) if diffs else None)
        terms = []
        for h in diffs:
            passed = [g for g in config.CRITERIA if values.iloc[i][g] >= scenario.profile(h)[g]]
            terms.append(f"{h}:" + ','.join(f'{g}(w={scenario.weights[g]:.2f})' for g in passed))
        drivers.append('; '.join(terms) if terms else None)
        if not diffs:
            explanation.append('두 모형의 최종 단계와 경계 통과가 동일')
        else:
            reason = []
            for h in diffs:
                rp = bool(rule.iloc[i][f'rule_outranks_{h}'])
                ep = bool(evaluation.iloc[i][f'outranks_{h}'])
                c = evaluation.iloc[i][f'concordance_{h}']
                n = rule.iloc[i][f'rule_pass_count_{h}']
                if rp and not ep:
                    reason.append(f'{h}: 단순규칙은 {int(n)}개 기준으로 통과했으나 가중합 {c:.2f}가 lambda {scenario.lam:.2f} 미만')
                elif ep and not rp:
                    reason.append(f'{h}: ELECTRE 가중합 {c:.2f}가 lambda {scenario.lam:.2f} 이상이나 단순규칙 충족 기준은 {int(n)}개')
            explanation.append('; '.join(reason))
    out['disagreement_boundary'] = disagreement_boundary
    out['disagreement_drivers'] = drivers
    out['disagreement_explanation'] = explanation
    return out


def latest_classification(panel, assignments, latest_quarter):
    latest = assignments[assignments['quarter'].astype(str).eq(str(latest_quarter))].copy()
    cols = ['scenario_id', 'industry', 'quarter', 'inspection_stage', 'display_class_by_scenario',
            'concordance_b1', 'concordance_b2', 'outranks_b1', 'outranks_b2', 'lambda', 'delta_emp']
    out = latest[cols].rename(columns={'display_class_by_scenario': 'electre_stage'})
    q = panel[panel['quarter'].astype(str).eq(str(latest_quarter))][
        ['industry', *[c for c in QUALITY_COLUMNS if c in panel.columns]]]
    return out.merge(q, on='industry', how='left', validate='many_to_one')


def leave_one_out(panel, values, scenario):
    base_eval = electre.evaluate(values, scenario)
    scope = base_eval['scorable'].to_numpy()
    rows = []
    for method in config.CRITERION_REMOVAL_METHODS:
        for removed in config.CRITERIA:
            if method == config.REMOVAL_SUPPORT_ZERO:
                alt_eval = electre.evaluate(values, scenario, support_removed=removed)
                weights = dict(scenario.weights)
            else:
                alt_eval = _evaluate_removed(values, scenario, removed, scope, True)
                weights = electre.renormalized_weights(scenario, removed)
            for i in range(len(values)):
                before = base_eval.iloc[i]['display_class_by_scenario']
                after = alt_eval.iloc[i]['display_class_by_scenario']
                rows.append({'scenario_id': scenario.scenario_id, 'industry': panel.iloc[i]['industry'],
                             'quarter': panel.iloc[i]['quarter'], 'removed_criterion': removed,
                             'removal_method': method, 'evaluation_scope': config.REMOVAL_EVALUATION_SCOPE,
                             'weights_used': json.dumps(weights, ensure_ascii=False, sort_keys=True),
                             'base_stage': before, 'removed_stage': after, 'changed': before != after,
                             'change_direction': _direction(before, after),
                             'base_concordance_b1': base_eval.iloc[i]['concordance_b1'],
                             'base_concordance_b2': base_eval.iloc[i]['concordance_b2'],
                             'removed_concordance_b1': alt_eval.iloc[i]['concordance_b1'],
                             'removed_concordance_b2': alt_eval.iloc[i]['concordance_b2']})
    return pd.DataFrame(rows)


def _evaluate_removed(values, scenario, removed, scope, renormalize):
    weights = electre.renormalized_weights(scenario, removed) if renormalize else dict(scenario.weights)
    out = pd.DataFrame(index=values.index)
    active = [g for g in config.CRITERIA if g != removed]
    emp = [g for g in config.EMPLOYMENT_CRITERIA if g != removed]
    outranks = {}
    for h in electre.BOUNDARIES:
        passes = {g: (values[g] >= scenario.profile(h)[g]).to_numpy() for g in active}
        concordance = sum(weights[g] * passes[g] for g in active)
        gate = np.any([passes[g] for g in emp], axis=0)
        outranks[h] = scope & (concordance >= scenario.lam - electre.EPS) & gate
        out[f'concordance_{h}'] = np.where(scope, concordance, np.nan)
    out['display_class_by_scenario'] = electre.pessimistic_assignment(
        outranks['b1'], outranks['b2'], scope)
    return out


def monotonicity_tests(scenario):
    """경계 인접값·결측·순서/이름 독립성을 포함한 실행 가능한 검증표."""
    rows = []
    for g in config.CRITERIA:
        for h in electre.BOUNDARIES:
            b = float(scenario.profile(h)[g])
            eps = max(abs(b) * 1e-9, 1e-9)
            base = {k: 0.0 for k in config.CRITERIA}
            samples = []
            for label, value in [('below', b - eps), ('equal', b), ('above', b + eps)]:
                row = dict(base); row[g] = value; samples.append((label, row))
            stages = electre.evaluate(pd.DataFrame([x[1] for x in samples]), scenario)['display_class_by_scenario'].tolist()
            passed = all(RANK[stages[i]] <= RANK[stages[i + 1]] for i in range(2))
            rows.append({'scenario_id': scenario.scenario_id, 'test_type': 'BOUNDARY_MONOTONICITY',
                         'criterion': g, 'boundary': h, 'n_cases': 3, 'n_violations': 0 if passed else 1,
                         'passed': passed, 'details': json.dumps(dict(zip([x[0] for x in samples], stages)), ensure_ascii=False)})
    missing = pd.DataFrame([{g: np.nan if g == 'g3' else 999.0 for g in config.CRITERIA}])
    stage = electre.evaluate(missing, scenario)['display_class_by_scenario'].iloc[0]
    rows.append({'scenario_id': scenario.scenario_id, 'test_type': 'MISSING_NOT_ADVERSE', 'criterion': 'g3',
                 'boundary': None, 'n_cases': 1, 'n_violations': int(stage != config.UNDETERMINED),
                 'passed': stage == config.UNDETERMINED, 'details': stage})
    v = pd.DataFrame([{g: float(i + j) for j, g in enumerate(config.CRITERIA)} for i in range(8)],
                     index=[f'업종{i}' for i in range(8)])
    base = electre.evaluate(v, scenario)['display_class_by_scenario']
    renamed = v.sample(frac=1, random_state=7); renamed.index = [f'명칭{i}' for i in range(len(renamed))]
    same_multiset = sorted(base.tolist()) == sorted(electre.evaluate(renamed, scenario)['display_class_by_scenario'].tolist())
    rows.append({'scenario_id': scenario.scenario_id, 'test_type': 'ROW_ORDER_AND_NAME_INDEPENDENCE',
                 'criterion': None, 'boundary': None, 'n_cases': len(v),
                 'n_violations': 0 if same_multiset else 1, 'passed': same_multiset, 'details': None})
    return pd.DataFrame(rows)


def dominance_tests(panel, values, scenario):
    """합성자료와 실제 완전관측 패널의 dominance 위반을 전수 확인한다."""
    synth = []
    for mask in range(16):
        synth.append({g: (scenario.b2[g] if mask & (1 << i) else 0.0)
                      for i, g in enumerate(config.CRITERIA)})
    scopes = [('SYNTHETIC', pd.DataFrame(synth)),
              ('ACTUAL_COMPLETE_CASE', values[values.notna().all(axis=1)].reset_index(drop=True))]
    rows = []
    for label, frame in scopes:
        stages = electre.evaluate(frame, scenario)['display_class_by_scenario'].map(RANK).to_numpy()
        arr = frame[list(config.CRITERIA)].to_numpy(float)
        comparisons, violations, examples = 0, 0, []
        for a in range(len(arr)):
            dominates = np.all(arr[a] >= arr, axis=1) & np.any(arr[a] > arr, axis=1)
            for b in np.flatnonzero(dominates):
                comparisons += 1
                if stages[a] < stages[b]:
                    violations += 1
                    if len(examples) < 5:
                        examples.append({'a': arr[a].tolist(), 'a_stage': int(stages[a]),
                                         'b': arr[b].tolist(), 'b_stage': int(stages[b])})
        rows.append({'scenario_id': scenario.scenario_id, 'test_scope': label,
                     'n_rows': len(frame), 'n_comparisons': comparisons,
                     'n_violations': violations, 'passed': violations == 0,
                     'violation_examples': json.dumps(examples, ensure_ascii=False)})
    return pd.DataFrame(rows)


def scenario_summary(assignments, comparisons, latest_quarter):
    rows = []
    for sid, g in assignments.groupby('scenario_id', sort=False):
        comp = comparisons[comparisons.scenario_id == sid]
        latest = g[g.quarter.astype(str).eq(str(latest_quarter))]
        counts = g['display_class_by_scenario'].value_counts()
        latest_counts = latest['display_class_by_scenario'].value_counts()
        rows.append({'scenario_id': sid, 'n_rows': len(g), 'n_complete': int(g.scorable.sum()),
                     'n_undetermined': int((~g.scorable).sum()),
                     **{f'n_{k.lower()}': int(counts.get(k, 0)) for k in ('OBSERVE', 'CHECK', 'PRIORITY')},
                     **{f'latest_n_{k.lower()}': int(latest_counts.get(k, 0)) for k in ('OBSERVE', 'CHECK', 'PRIORITY')},
                     'agreement_rate_complete': float(comp.loc[comp.simple_rule_stage != config.UNDETERMINED, 'stage_agrees'].mean()),
                     'n_disagreements_complete': int((~comp.loc[comp.simple_rule_stage != config.UNDETERMINED, 'stage_agrees']).sum())})
    return pd.DataFrame(rows)


def parameter_registry(doc, validation):
    rows = []
    reg = doc['registration']
    for s in doc['scenarios']:
        rows.append({'scenario_id': s['scenario_id'], **{f'weight_{g}': s['weights'][g] for g in config.CRITERIA},
                     **{f'{h}_{g}': s['profiles'][h][g] for h in electre.BOUNDARIES for g in config.CRITERIA},
                     'lambda': s['lambda'], 'delta_emp': s['delta_emp'],
                     'require_employment_evidence': s['require_employment_evidence'],
                     'q': doc['fixed']['q'], 'p': doc['fixed']['p'], 'veto': doc['fixed']['veto'],
                     'assignment_rule': doc['fixed']['assignment_rule'], 'missing_rule': doc['fixed']['missing_rule'],
                     'parameter_status': validation.effective_status, 'registered_at': reg['registered_at'],
                     'registered_by': reg['registered_by'], 'parameter_file_sha256': reg['parameter_file_sha256'],
                     'briefing_doc_sha256': reg['briefing_doc_sha256'],
                     'decision_basis_document': 'ELECTRE_파라미터_결정_보고서.md',
                     'administratively_approved': False})
    return pd.DataFrame(rows)


def write_figures(output_root, latest, rule_latest, removal):
    """요청된 세 종류의 동적 시각화만 저장한다."""
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts = ['Malgun Gothic', 'NanumGothic', 'AppleGothic']
    available = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams['font.family'] = next((f for f in fonts if f in available), 'sans-serif')
    plt.rcParams['axes.unicode_minus'] = False
    fig_dir = Path(output_root) / 'outputs' / 'figures'
    fig_dir.mkdir(parents=True, exist_ok=True)
    colors = config.DISPLAY_COLORS
    order = ['OBSERVE', 'CHECK', 'PRIORITY', config.UNDETERMINED]
    rank = {x: i for i, x in enumerate(order)}

    base_rule = rule_latest[['industry', 'simple_rule_stage']].drop_duplicates().assign(scenario_id='단순규칙')
    e = latest[['industry', 'scenario_id', 'electre_stage']].rename(columns={'electre_stage': 'simple_rule_stage'})
    grid = pd.concat([base_rule, e], ignore_index=True)
    pivot = grid.pivot(index='industry', columns='scenario_id', values='simple_rule_stage')
    cols = [c for c in ['단순규칙', *config.SCENARIO_IDS] if c in pivot]
    arr = pivot[cols].map(rank.get).to_numpy()
    from matplotlib.colors import ListedColormap, BoundaryNorm
    cmap = ListedColormap([colors[x] for x in order]); norm = BoundaryNorm(np.arange(-.5, 4.5), cmap.N)
    fig, ax = plt.subplots(figsize=(9, max(4, .45 * len(pivot))))
    ax.imshow(arr, aspect='auto', cmap=cmap, norm=norm)
    ax.set(xticks=range(len(cols)), xticklabels=cols, yticks=range(len(pivot)), yticklabels=pivot.index)
    ax.set_title('최신분기 단순 규칙과 ELECTRE 시나리오 점검단계 비교')
    fig.tight_layout(); fig.savefig(fig_dir / 'electre_latest_stage_comparison.png', dpi=180); plt.close(fig)

    vals = rule_latest.set_index('industry')[[*config.CRITERIA]]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    for ax, g in zip(axes.ravel(), config.CRITERIA):
        vals[g].sort_values().plot.barh(ax=ax, color='#6B7C8F')
        ax.axvline(rule_latest[f'b1_{g}_boundary'].iloc[0], color=colors['CHECK'], label='b1')
        ax.axvline(rule_latest[f'b2_{g}_boundary'].iloc[0], color=colors['PRIORITY'], label='b2')
        ax.set_title(config.CRITERION_LABELS[g]); ax.legend()
    fig.suptitle('최신분기 기준값과 b1·b2 경계')
    fig.savefig(fig_dir / 'electre_latest_criteria_boundaries.png', dpi=180); plt.close(fig)

    complete = removal[removal.base_stage != config.UNDETERMINED]
    rates = complete.groupby(['scenario_id', 'removal_method', 'removed_criterion'])['changed'].mean().unstack('removed_criterion')
    fig, ax = plt.subplots(figsize=(10, 5)); rates.plot.bar(ax=ax, color=['#506784', '#7C8C6B', '#B08B57', '#775B73'])
    ax.set_ylabel('단계 변화율'); ax.set_title('기준 제거 전후 단계 변화'); ax.legend(title='제거 기준')
    fig.tight_layout(); fig.savefig(fig_dir / 'electre_leave_one_out_changes.png', dpi=180); plt.close(fig)
