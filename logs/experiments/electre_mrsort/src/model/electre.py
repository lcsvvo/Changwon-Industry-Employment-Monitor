# -*- coding: utf-8 -*-
"""ELECTRE TRI-B 경계 프로파일 outranking과 할당 절차(초기형).

고정 설정: q_j=p_j=0, veto 없음, 할당 절차는 pessimistic assignment, 모든 기준 증가 방향.
결측 기준이 하나라도 있으면 concordance와 점검단계를 만들지 않는다(결측 처리: complete_case_no_renormalization).

q=p=0에서 부분 concordance c_j(a,b_h)는 I(g_j >= b_hj)이다. veto가 없어 불일치 지수가 없으므로
신뢰도 σ(a,b_h)는 전체 concordance C(a,b_h) = Σ w_j·I(g_j >= b_hj)와 정확히 같다.
대안 a가 경계 b_h를 outrank하는 조건은 σ(a,b_h) >= lambda이다.

고용증거 게이트(require_employment_evidence=True)는 outranking 위에 얹는 별도 규칙이며,
고용 기준(g1·g2·g4) 중 어느 것도 해당 경계를 충족하지 않으면 그 경계 통과를 인정하지 않는다.

기준 제외 민감도 분석은 결측 처리 규칙과 별개이며 두 방법을 method 컬럼으로 구분한다.
- criterion_support_removed_no_renormalization: 제외 기준의 지지를 0으로 두고 가중치는 그대로 둔다.
- criterion_removed_weights_renormalized: 제외 기준을 모형에서 제거하고 나머지 가중치를 합계 1로 재정규화한다.
두 방법 모두 기본 모형의 완전관측 행만 평가한다(표본 변화와 기준 변화를 섞지 않기 위함).
"""
import itertools
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config, derive

EPS = 1e-9  # 가중치 합산의 부동소수점 오차 허용치(판정 파라미터가 아님)
BOUNDARIES = ('b1', 'b2')
CLASS_RANK = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
IDENTITY_COLUMNS = ['industry', 'quarter', 'quarter_index', 'state', 'core_data_status', 'scorable']


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    weights: dict
    b1: dict
    b2: dict
    lam: float
    delta_emp: float
    require_employment_evidence: bool

    @classmethod
    def from_block(cls, block):
        gate = block['require_employment_evidence']
        if not isinstance(gate, bool):
            raise ValueError('require_employment_evidence는 true 또는 false여야 합니다.')
        return cls(scenario_id=block['scenario_id'], weights=dict(block['weights']),
                   b1=dict(block['profiles']['b1']), b2=dict(block['profiles']['b2']),
                   lam=float(block['lambda']), delta_emp=float(block['delta_emp']),
                   require_employment_evidence=gate)

    def profile(self, boundary):
        return {'b1': self.b1, 'b2': self.b2}[boundary]


# ---------------------------------------------------------------- 기본 연산
def partial_concordance(values, boundary):
    """q=p=0의 부분 concordance: g >= b이면 1, 아니면 0, 결측이면 NaN."""
    g = np.asarray(values, dtype=float)
    with np.errstate(invalid='ignore'):
        return np.where(np.isnan(g), np.nan, (g >= boundary).astype(float))


def pessimistic_assignment(outranks_b1, outranks_b2, scorable):
    """높은 경계 b2부터 검사: b2 outrank → PRIORITY, 아니고 b1 outrank → CHECK, 둘 다 아니면 OBSERVE."""
    o1 = np.asarray(outranks_b1, dtype=bool)
    o2 = np.asarray(outranks_b2, dtype=bool)
    ok = np.asarray(scorable, dtype=bool)
    if np.any(ok & o2 & ~o1):
        raise ValueError('b2를 outrank하지만 b1을 outrank하지 못하는 행이 있습니다(경계 순서 위반).')
    classes = np.empty(len(ok), dtype=object)
    for i in range(len(ok)):
        if not ok[i]:
            classes[i] = config.UNDETERMINED
        elif o2[i]:
            classes[i] = 'PRIORITY'
        elif o1[i]:
            classes[i] = 'CHECK'
        else:
            classes[i] = 'OBSERVE'
    return classes


def evaluate(values, scenario, support_removed=None):
    """행별 경계 비교와 점검단계.

    values : g1~g4 열을 가진 DataFrame(결측은 NaN)
    support_removed : criterion_support_removed_no_renormalization 분석에서 지지를 0으로 둘 기준.
                      가중치는 재정규화하지 않는다.
    """
    crit = config.CRITERIA
    index = values.index
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    unscorable = ~scorable
    out = pd.DataFrame(index=index)
    outranks = {}
    for h in BOUNDARIES:
        prof = scenario.profile(h)
        c = {}
        for j in crit:
            cj = partial_concordance(values[j], prof[j])
            if support_removed == j:
                cj = np.where(np.isnan(cj), np.nan, 0.0)
            c[j] = cj
            out[f'pass_{j}_{h}'] = derive.masked_bool(cj == 1, np.isnan(cj), index)
        concordance = np.where(scorable, sum(scenario.weights[j] * np.nan_to_num(c[j]) for j in crit), np.nan)
        credibility = concordance  # veto 없음: σ = C
        with np.errstate(invalid='ignore'):
            before_gate = scorable & (credibility >= scenario.lam - EPS)
        emp_evidence = scorable & np.any([c[j] == 1 for j in config.EMPLOYMENT_CRITERIA], axis=0)
        production_only = (scorable & (c['g3'] == 1) & (scenario.weights['g3'] >= scenario.lam - EPS)
                           & ~emp_evidence)
        if not np.array_equal(production_only, before_gate & ~emp_evidence):
            raise AssertionError('생산 단독 통과 조건이 outranking 결과와 일치하지 않습니다.')
        final = before_gate & (emp_evidence | (not scenario.require_employment_evidence))
        out[f'concordance_{h}'] = concordance
        out[f'outranks_{h}_before_gate'] = derive.masked_bool(before_gate, unscorable, index)
        out[f'emp_evidence_at_{h}'] = derive.masked_bool(emp_evidence, unscorable, index)
        out[f'production_only_pass_{h}'] = derive.masked_bool(production_only, unscorable, index)
        out[f'outranks_{h}'] = derive.masked_bool(final, unscorable, index)
        outranks[h] = final
    out['scorable'] = scorable
    out['display_class_by_scenario'] = pessimistic_assignment(outranks['b1'], outranks['b2'], scorable)
    return out


def renormalized_weights(scenario, removed):
    remaining = {j: w for j, w in scenario.weights.items() if j != removed}
    total = sum(remaining.values())
    return {j: w / total for j, w in remaining.items()}


def evaluate_without_criterion(values, scenario, removed, scope):
    """모형에서 기준 하나를 제거하고 나머지 가중치를 합계 1로 재정규화한 점검단계.

    scope : 평가할 행(기본 모형의 완전관측 행). 범위 밖 행은 UNDETERMINED로 둔다.
    """
    crit = [j for j in config.CRITERIA if j != removed]
    emp_crit = [j for j in config.EMPLOYMENT_CRITERIA if j != removed]
    weights = renormalized_weights(scenario, removed)
    scope = np.asarray(scope, dtype=bool) & values[crit].notna().all(axis=1).to_numpy()
    outranks = {}
    for h in BOUNDARIES:
        prof = scenario.profile(h)
        c = {j: np.nan_to_num(partial_concordance(values[j], prof[j])) for j in crit}
        concordance = sum(weights[j] * c[j] for j in crit)
        before_gate = scope & (concordance >= scenario.lam - EPS)
        emp_evidence = scope & np.any([c[j] == 1 for j in emp_crit], axis=0)
        outranks[h] = before_gate & (emp_evidence | (not scenario.require_employment_evidence))
    return pessimistic_assignment(outranks['b1'], outranks['b2'], scope), weights


def simple_count_rule(values, scenario):
    """비교용 고정 단순규칙: 4개 중 2개 이상 + 같은 경계의 고용증거."""
    crit = config.CRITERIA
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    index = values.index
    out = pd.DataFrame(index=index)
    outranks = {}
    for h in BOUNDARIES:
        prof = scenario.profile(h)
        c = {j: np.nan_to_num(partial_concordance(values[j], prof[j])) for j in crit}
        pass_count = sum(c[j] for j in crit)
        before_gate = scorable & (pass_count >= 2)
        emp_evidence = scorable & np.any([c[j] == 1 for j in config.EMPLOYMENT_CRITERIA], axis=0)
        final = before_gate & (emp_evidence | (not scenario.require_employment_evidence))
        out[f'simple_outranks_{h}_before_gate'] = derive.masked_bool(before_gate, ~scorable, index)
        out[f'simple_pass_count_{h}'] = np.where(scorable, pass_count, np.nan)
        out[f'simple_emp_evidence_at_{h}'] = derive.masked_bool(emp_evidence, ~scorable, index)
        out[f'simple_outranks_{h}'] = derive.masked_bool(final, ~scorable, index)
        outranks[h] = final
    out['simple_class'] = pessimistic_assignment(outranks['b1'], outranks['b2'], scorable)
    return out


# ---------------------------------------------------------------- 시나리오 입력
def scenario_values(panel, scenario, window_n, latest_quarter):
    """시나리오의 g1~g4 값과 g4 메타. delta_emp가 민감도 값이면 그 컬럼을 그대로 쓴다."""
    source = config.g4_column_for_delta(scenario.delta_emp)
    if source is not None:
        run = panel[source]
        flags = {f: panel[f'{source}_{f}'] for f in config.G4_FLAGS}
    else:
        g4 = derive.emp_yoy_below_run(panel, scenario.delta_emp, window_n, latest_quarter)
        run = g4['run']
        flags = {f: g4[f] for f in config.G4_FLAGS}
        source = f'computed_delta_{scenario.delta_emp}'
    values = pd.DataFrame({
        'g1': panel[config.CRITERION_COLUMNS['g1']].astype(float),
        'g2': panel[config.CRITERION_COLUMNS['g2']].astype(float),
        'g3': panel[config.CRITERION_COLUMNS['g3']].astype(float),
        'g4': run.astype(float),
    }, index=panel.index)
    meta = pd.DataFrame({config.CRITERION_COLUMNS['g4']: run, **{f'g4_{f}': v for f, v in flags.items()}},
                        index=panel.index)
    meta['g4_source_column'] = source
    return values, meta


def run_scenario(panel, scenario, window_n, latest_quarter, parameter_set_id=None):
    values, meta = scenario_values(panel, scenario, window_n, latest_quarter)
    evaluation = evaluate(values, scenario)
    simple = simple_count_rule(values, scenario)
    ident = panel[IDENTITY_COLUMNS].drop(columns='scorable').copy()
    result = pd.concat([ident, evaluation, simple, meta,
                        panel[[config.CRITERION_COLUMNS[g] for g in ('g1', 'g2', 'g3')]]], axis=1)
    if not np.array_equal(result['scorable'].to_numpy(), panel['scorable'].to_numpy(dtype=bool)):
        raise AssertionError('시나리오 판정가능 행이 입력 패널 scorable과 다릅니다.')
    result.insert(0, 'scenario_id', scenario.scenario_id)
    # 점검단계(OBSERVE·CHECK·PRIORITY). 판정불가 행은 UNDETERMINED로 표시하되 단계값은 NA로 둔다.
    result['inspection_stage'] = result['display_class_by_scenario'].where(result['scorable'])
    result['lambda'] = scenario.lam
    result['delta_emp'] = scenario.delta_emp
    result['require_employment_evidence'] = scenario.require_employment_evidence
    return result, values


def boundary_evidence(panel, values, scenario):
    """업종×분기×경계×기준 근거표: 기준값·경계값·부분 concordance·가중치·기여."""
    rows = []
    scorable = values[list(config.CRITERIA)].notna().all(axis=1)
    for h in BOUNDARIES:
        prof = scenario.profile(h)
        for j in config.CRITERIA:
            c = partial_concordance(values[j], prof[j])
            frame = panel[['industry', 'quarter']].copy()
            frame['scenario_id'] = scenario.scenario_id
            frame['boundary'] = h
            frame['criterion'] = j
            frame['criterion_label'] = config.CRITERION_LABELS[j]
            frame['criterion_value'] = values[j]
            frame['boundary_value'] = prof[j]
            frame['partial_concordance'] = c
            frame['weight'] = scenario.weights[j]
            frame['weighted_contribution'] = np.where(scorable, scenario.weights[j] * np.nan_to_num(c), np.nan)
            rows.append(frame)
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------- 규칙 비교
def rule_comparison(assignments):
    """관측자료에서 가중 경계규칙과 단순 개수규칙의 경계별 불일치.

    사람이 확인할 전체 대상은 모든 시나리오·경계 불일치 행의 합집합이다.
    두 규칙이 관측자료에서 같다고 하려면 모든 시나리오·경계에서 불일치가 0이어야 한다.
    """
    rows = []
    scorable = assignments[assignments['scorable']]
    for h in BOUNDARIES:
        frame = scorable[['scenario_id', 'industry', 'quarter', 'display_class_by_scenario', 'simple_class']].copy()
        frame['boundary'] = h
        frame['weighted_outranks'] = scorable[f'outranks_{h}'].astype(bool)
        frame['simple_outranks'] = scorable[f'simple_outranks_{h}'].astype(bool)
        frame['disagree'] = frame['weighted_outranks'] != frame['simple_outranks']
        rows.append(frame)
    table = pd.concat(rows, ignore_index=True)
    union = table[table['disagree']][['industry', 'quarter']].drop_duplicates()
    union_keys = set(map(tuple, union.to_numpy()))
    table['in_disagreement_union'] = [(i, q) in union_keys for i, q in zip(table.industry, table.quarter)]
    by = (table.groupby(['scenario_id', 'boundary'])['disagree'].sum().astype(int)
          .reset_index().rename(columns={'disagree': 'n_disagree_rows'}))
    summary = {
        'by_scenario_boundary': by.to_dict('records'),
        'union_n_rows': len(union_keys),
        'union_rows': sorted([{'industry': i, 'quarter': q} for i, q in union_keys],
                             key=lambda d: (d['industry'], d['quarter'])),
        'identical_on_observed_data': bool(by['n_disagree_rows'].sum() == 0),
        'adoption_note': '비교 결과만 제시하며 단순 개수규칙의 최종 채택은 사람의 정책 판단으로 남긴다.',
    }
    return table, summary


def enumerate_coalitions(scenarios):
    """4개 기준 경계통과 조합 16개를 전수 열거해 가중 규칙과 단순 개수규칙을 함수 수준에서 비교한다."""
    rows = []
    for s in scenarios:
        for h in BOUNDARIES:
            for combo in itertools.product((0, 1), repeat=len(config.CRITERIA)):
                c = dict(zip(config.CRITERIA, combo))
                weighted = sum(s.weights[j] * c[j] for j in config.CRITERIA)
                share = sum(combo) / len(config.CRITERIA)
                emp = any(c[j] for j in config.EMPLOYMENT_CRITERIA)
                gate_ok = emp or not s.require_employment_evidence
                w_raw, s_raw = weighted >= s.lam - EPS, sum(combo) >= 2
                rows.append({'scenario_id': s.scenario_id, 'boundary': h,
                             **{f'pass_{j}': bool(c[j]) for j in config.CRITERIA},
                             'emp_evidence': emp, 'weighted_concordance': weighted, 'pass_share': share,
                             'lambda': s.lam, 'require_employment_evidence': s.require_employment_evidence,
                             'weighted_pass_before_gate': w_raw, 'simple_pass_before_gate': s_raw,
                             'weighted_pass': w_raw and gate_ok, 'simple_pass': s_raw and gate_ok,
                             'agree': (w_raw and gate_ok) == (s_raw and gate_ok)})
    table = pd.DataFrame(rows)
    summary = [{'scenario_id': sid, 'boundary': h, 'n_combinations': int(len(g)),
                'n_disagree': int((~g['agree']).sum()), 'logically_equivalent': bool(g['agree'].all())}
               for (sid, h), g in table.groupby(['scenario_id', 'boundary'], sort=False)]
    return table, summary


def criterion_removal_sensitivity(values, scenario):
    """기준 하나씩 제외했을 때 점검단계 변화표. 두 방법을 method 컬럼으로 구분한다."""
    base_eval = evaluate(values, scenario)
    base = base_eval['display_class_by_scenario']
    scope = base_eval['scorable'].to_numpy()
    rows = []
    for method in config.CRITERION_REMOVAL_METHODS:
        for j in config.CRITERIA:
            if method == config.REMOVAL_SUPPORT_ZERO:
                alt = evaluate(values, scenario, support_removed=j)['display_class_by_scenario']
                weights = dict(scenario.weights)
            else:
                alt, weights = evaluate_without_criterion(values, scenario, j, scope)
            moved = pd.crosstab(pd.Series(np.asarray(base), name='from_class'),
                                pd.Series(np.asarray(alt), name='to_class'))
            for f in moved.index:
                for t in moved.columns:
                    if moved.loc[f, t]:
                        rows.append({'scenario_id': scenario.scenario_id, 'method': method,
                                     'removed_criterion': j,
                                     'evaluation_scope': config.REMOVAL_EVALUATION_SCOPE,
                                     'weights_used': json.dumps(weights, sort_keys=True),
                                     'weights_renormalized': method == config.REMOVAL_RENORMALIZED,
                                     'from_class': f, 'to_class': t, 'n_rows': int(moved.loc[f, t]),
                                     'changed': f != t})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 경계 도달가능성 진단
def reachability(panel, values, scenario):
    """기준별·경계별 통과 건수, 업종별 g1 경계 통과 관측 수, g1·g2·g4 통과 조합 교차표."""
    counts, industry_rows, combo_rows = [], [], []
    for h in BOUNDARIES:
        prof = scenario.profile(h)
        passes = {}
        for j in config.CRITERIA:
            available = values[j].notna()
            passes[j] = available & (values[j] >= prof[j])
            counts.append({'scenario_id': scenario.scenario_id, 'boundary': h, 'criterion': j,
                           'boundary_value': prof[j], 'n_available': int(available.sum()),
                           'n_pass': int(passes[j].sum())})
        g1 = pd.DataFrame({'industry': panel['industry'], 'available': values['g1'].notna(),
                           'passed': passes['g1']})
        for industry, g in g1.groupby('industry', sort=True):
            industry_rows.append({'scenario_id': scenario.scenario_id, 'boundary': h, 'industry': industry,
                                  'g1_boundary_value': prof['g1'], 'g1_observations': int(g['available'].sum()),
                                  'g1_pass_n': int(g['passed'].sum()),
                                  'never_passed': bool(g['passed'].sum() == 0)})
        all_three = values[['g1', 'g2', 'g4']].notna().all(axis=1)
        combos = pd.DataFrame({f'pass_{j}': passes[j][all_three] for j in ('g1', 'g2', 'g4')})
        for key, g in combos.groupby(list(combos.columns)):
            combo_rows.append({'scenario_id': scenario.scenario_id, 'boundary': h,
                               **dict(zip(combos.columns, map(bool, key))), 'n_rows': int(len(g))})
    industries = pd.DataFrame(industry_rows)
    never = {h: sorted(industries[(industries.boundary == h) & industries.never_passed].industry)
             for h in BOUNDARIES}
    return pd.DataFrame(counts), industries, pd.DataFrame(combo_rows), never


# ---------------------------------------------------------------- 시나리오 요약·이력·PPI 가상단계
def scenario_summary(assignments, approved_scenario_id=None):
    """업종×분기별 시나리오 요약. APPROVED일 때만 단일 display_class를 붙인다."""
    rows = []
    for (industry, quarter), g in assignments.groupby(['industry', 'quarter'], sort=True):
        valid = g[g['display_class_by_scenario'] != config.UNDETERMINED]
        n_valid = int(len(valid))
        n_priority = int((valid['display_class_by_scenario'] == 'PRIORITY').sum())
        n_check_up = int(valid['display_class_by_scenario'].isin(['CHECK', 'PRIORITY']).sum())
        if n_valid == 0:
            text = '판정불가(데이터 검토)'
        else:
            p_text = (f'{n_valid}개 시나리오 모두 우선점검' if n_priority == n_valid
                      else f'{n_valid}개 시나리오 중 {n_priority}개에서 우선점검')
            c_text = (f'{n_valid}개 시나리오 모두 추가확인 이상' if n_check_up == n_valid
                      else f'{n_valid}개 시나리오 중 {n_check_up}개에서 추가확인 이상')
            text = f'{p_text}; {c_text}'
        row = {'industry': industry, 'quarter': quarter, 'priority_scenario_count': n_priority,
               'check_or_higher_scenario_count': n_check_up, 'valid_scenario_count': n_valid,
               'scenario_display_text': text}
        if approved_scenario_id is not None:
            chosen = g[g['scenario_id'] == approved_scenario_id]['display_class_by_scenario']
            row['display_class'] = chosen.iloc[0] if len(chosen) else None
        rows.append(row)
    return pd.DataFrame(rows)


def recent_stage_history(assignments, quarters, n=config.RECENT_HISTORY_N):
    """최근 n분기 시나리오별 점검단계 이력. 시나리오를 하나의 등급 이력으로 합치지 않는다."""
    recent = list(quarters[-n:])
    sub = assignments[assignments['quarter'].isin(recent)]
    rows = []
    for (sid, industry), g in sub.groupby(['scenario_id', 'industry'], sort=False):
        g = g.set_index('quarter').reindex(recent)
        classes = g['display_class_by_scenario'].tolist()
        scored = [c for c in classes if c in CLASS_RANK]
        for q, c in zip(recent, classes):
            rows.append({'scenario_id': sid, 'industry': industry, 'quarter': q,
                         'display_class_by_scenario': c,
                         'window_quarters': ' → '.join(recent),
                         'window_class_path': ' → '.join(map(str, classes)),
                         'n_distinct_scored_classes': len(set(scored)),
                         'n_undetermined': sum(c == config.UNDETERMINED for c in classes),
                         'title': config.RECENT_HISTORY_TITLE})
    return pd.DataFrame(rows)


def ppi_stage_divergence(panel, values, scenario, base_classes):
    """PPI 조정 생산 YoY 하한·상한을 g3 자리에 넣은 가상 점검단계. 공식 점검단계를 바꾸지 않는다."""
    comparable = (panel['ppi_direction_status'].isin(config.PPI_COMPARABLE_STATUSES)
                  & panel['scorable'].astype(bool)).to_numpy()
    out = panel[['industry', 'quarter', 'state', 'production_yoy', 'ppi_adjusted_prod_yoy_lower',
                 'ppi_adjusted_prod_yoy_upper', 'ppi_direction_status', 'ppi_alt_state_set',
                 'ppi_mapping_confirmation_status']].copy()
    out.insert(0, 'scenario_id', scenario.scenario_id)
    out['nominal_display_class_by_scenario'] = np.asarray(base_classes, dtype=object)
    stages = {}
    for bound in ('lower', 'upper'):
        alt = values.copy()
        g3 = derive.clean_negative_zero(np.maximum(0.0, -panel[f'ppi_adjusted_prod_yoy_{bound}'].astype(float)))
        alt['g3'] = np.where(comparable, g3, np.nan)
        classes = evaluate(alt, scenario)['display_class_by_scenario']
        stages[bound] = np.where(comparable, classes, None)
        out[f'ppi_hypothetical_stage_{bound}'] = stages[bound]
    base = out['nominal_display_class_by_scenario'].to_numpy()
    divergent = comparable & ((stages['lower'] != base) | (stages['upper'] != base))
    out['ppi_stage_divergent'] = derive.masked_bool(divergent, ~comparable, panel.index)
    out['official_stage_changed'] = False
    return out


# ---------------------------------------------------------------- Phase 1(재검증): 낙관적 배정·veto
# 이 절의 함수는 모두 추가분이다. 위쪽의 기존 함수는 시그니처·동작을 바꾸지 않았다.
# veto는 사전등록(prereg) 문서가 REGISTERED 상태로 확정되기 전에는 공식 파이프라인에서 쓰지 않는다.
def veto_blocked(values, threshold):
    """거부권(veto) 차단 여부. threshold는 기준 척도 위의 절대 문턱값이다(오프셋이 아니다).

    blocked = OR_j [ g_j < threshold[j] ]   (엄격부등호)

    threshold : {criterion: value} 또는 None/빈 dict. 값은 이미 특정 경계 h에 대해
        해석된 절대 문턱값이며, 호출자가 경계별로 어떤 threshold를 쓸지 고른다
        (같은 함수로 b1·b2 어느 경계든 처리한다 — profile 인자를 받지 않는다).
    결측(NaN)은 차단하지 않는다(veto는 게이트이지 불일치 판정이 아니므로).
    numpy 비교에서 NaN < x가 자연히 False가 되는 성질을 그대로 쓴다(별도 마스킹 불필요).
    고전 ELECTRE 표기의 v_j = b_hj - threshold[j](경계로부터의 오프셋)는 방법론 서술용
    기록일 뿐이며 이 함수의 계산에는 쓰지 않는다(이중 뺄셈 방지).
    반환: numpy bool 배열(행마다 하나라도 차단되는 기준이 있으면 True).
    """
    index = values.index
    if not threshold:
        return np.zeros(len(index), dtype=bool)
    blocked = np.zeros(len(index), dtype=bool)
    with np.errstate(invalid='ignore'):
        for j, t_j in threshold.items():
            g = values[j].to_numpy(dtype=float)
            blocked |= g < float(t_j)
    return blocked


def reverse_partial_concordance(values, boundary, q=0.0, p=0.0):
    """c_j(b_h, a): 경계가 대안을 outrank하는 정도(증가방향 기준의 역방향 pseudo-criterion).

    1 if g <= b + q ; 0 if g >= b + p ; 그 사이는 선형 보간 (b + p - g) / (p - q).
    q == p이면 (g <= b + q) 지시함수. 결측이면 NaN.
    """
    if not 0 <= q <= p:
        raise ValueError('0 <= q <= p 조건을 충족해야 합니다.')
    x = np.asarray(values, dtype=float)
    missing = np.isnan(x)
    with np.errstate(invalid='ignore'):
        if q == p:
            result = (x <= boundary + q).astype(float)
        else:
            lo, hi = boundary + q, boundary + p
            result = np.where(x <= lo, 1.0, np.where(x >= hi, 0.0, (hi - x) / (p - q)))
    return np.where(missing, np.nan, np.clip(result, 0.0, 1.0))


def _pseudo_partial_concordance(values, boundary, q, p):
    """a S b_h(대안이 경계를 outrank) 판정용 증가방향 pseudo-criterion.

    qp_calibration.partial_concordance와 정확히 같은 공식이다. electre.py는 순환 import를
    피하기 위해 qp_calibration을 import하지 않으므로 이 비공개 함수로 같은 공식을 재구현한다.
    q=p=0이면 이 모듈의 partial_concordance(크리스프 I(g>=b))와 정확히 같다.
    """
    if not 0 <= q <= p:
        raise ValueError('0 <= q <= p 조건을 충족해야 합니다.')
    x = np.asarray(values, dtype=float)
    missing = np.isnan(x)
    with np.errstate(invalid='ignore'):
        if q == p:
            result = (x >= boundary - q).astype(float)
        else:
            lo, hi = boundary - p, boundary - q
            result = np.where(x <= lo, 0.0, np.where(x >= hi, 1.0, (x - lo) / (p - q)))
    return np.where(missing, np.nan, np.clip(result, 0.0, 1.0))


def _expand_qp(val, crit):
    """q 또는 p 인자를 기준별 dict로 정규화한다. None이면 전부 0."""
    if val is None:
        return {j: 0.0 for j in crit}
    if isinstance(val, dict):
        return {j: float(val[j]) for j in crit}
    return {j: float(val) for j in crit}


def forward_outranks(values, scenario, boundary, q=None, p=None, veto=None):
    """a S b_h(대안이 경계를 outrank) 여부. 고용증거 게이트와 veto를 적용한다.

    q, p는 {criterion: 값} dict, 스칼라, 또는 None(=모든 기준 0, v1.0과 동일)을 받는다.
    veto는 {criterion: threshold} 절대 문턱값 dict(veto_blocked와 같은 규약)이며, 이 boundary
    호출에 적용할 문턱값을 호출자가 골라 넘긴다(이 함수 자신은 profile에서 문턱값을 빼지 않는다).
    q=p=0·veto=None이면 evaluate(...)[f'outranks_{boundary}']와 정확히 같다.
    반환: numpy bool 배열(완전관측이 아닌 행은 False).
    """
    crit = config.CRITERIA
    q, p = _expand_qp(q, crit), _expand_qp(p, crit)
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    prof = scenario.profile(boundary)
    c = {j: _pseudo_partial_concordance(values[j], prof[j], q[j], p[j]) for j in crit}
    concordance = np.where(scorable, sum(scenario.weights[j] * np.nan_to_num(c[j]) for j in crit), np.nan)
    with np.errstate(invalid='ignore'):
        before_gate = scorable & (concordance >= scenario.lam - EPS)
    emp_evidence = scorable & np.any([c[j] > 0 for j in config.EMPLOYMENT_CRITERIA], axis=0)
    gated = before_gate & (emp_evidence | (not scenario.require_employment_evidence))
    if veto:
        gated = gated & ~veto_blocked(values, veto)
    return gated


def boundary_outranks(values, scenario, boundary, q=None, p=None):
    """b_h S a(경계가 대안을 outrank) 여부. 고용증거 게이트와 veto를 적용하지 않는다.

    q, p는 forward_outranks와 같은 방식으로 해석한다(None이면 모든 기준 0).
    반환: numpy bool 배열(완전관측이 아닌 행은 False).
    """
    crit = config.CRITERIA
    q, p = _expand_qp(q, crit), _expand_qp(p, crit)
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    prof = scenario.profile(boundary)
    c = {j: reverse_partial_concordance(values[j], prof[j], q[j], p[j]) for j in crit}
    concordance = np.where(scorable, sum(scenario.weights[j] * np.nan_to_num(c[j]) for j in crit), np.nan)
    with np.errstate(invalid='ignore'):
        return scorable & (concordance >= scenario.lam - EPS)


def optimistic_assignment(values, scenario, q=None, p=None, veto=None):
    """낙관적 배정. 낮은 경계 b1부터 검사해
    (b_h가 a를 outrank) and not (a가 b_h를 outrank) 인 최초 h에서
    b1이면 OBSERVE, b2면 CHECK, 둘 다 아니면 PRIORITY.
    a S b_h 판정에는 고용증거 게이트와 veto를 적용하고,
    b_h S a 판정에는 적용하지 않는다.
    완전관측이 아니면 UNDETERMINED.
    q, p 가 None이면 q=p=0 (v1.0과 동일).
    veto는 {criterion: threshold} 절대 문턱값 dict(veto_blocked 규약)이며, 이 함수는
    b1·b2 양쪽 forward_outranks 호출에 같은 veto dict를 그대로 전달한다 — 경계별로
    다른 veto를 쓰려면(예: b2에만 적용) forward_outranks를 boundary별로 직접 호출한다."""
    crit = config.CRITERIA
    scorable = values[list(crit)].notna().all(axis=1).to_numpy()
    a_s = {h: forward_outranks(values, scenario, h, q, p, veto) for h in BOUNDARIES}
    b_s = {h: boundary_outranks(values, scenario, h, q, p) for h in BOUNDARIES}
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
