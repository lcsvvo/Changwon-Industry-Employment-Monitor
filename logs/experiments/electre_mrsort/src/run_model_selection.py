# -*- coding: utf-8 -*-
"""최종 판단모형 선발 비교실험.

사용법:
    python src/run_model_selection.py --replicates 100

기존 outputs/independent_audit 결과는 읽기만 하고 수정하지 않는다.
모든 산출물은 outputs/model_selection/ 아래에만 쓴다.

비교 원칙
- 같은 입력 g(비교 가능한 과거 이력으로 재계산한 g4)를 모든 후보가 공유한다.
- 같은 180행 / 완전관측 160행 / 최신분기 10개 업종을 쓴다.
- 정확도는 계산하지 않는다. 현장 정답이 없으므로 성립하지 않는 개념이다.
"""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import audit_tools as a, config, electre, model_selection as ms  # noqa: E402
from model import qp_calibration as qp, revalidation_phase5 as p5  # noqa: E402
from model.revalidation_phase3 import reference_compatibility  # noqa: E402

OUT = ROOT / 'outputs/model_selection'
PARAMETER_SEED = 2026
REVISION_SEED = 99
BOX_DRAWS = 40000          # 허용 박스에서 뽑는 crisp (w, lambda) 표본 수(교란 반복용)

ACTION_OBSERVE = '현재 관찰군'
ACTION_CHECK = '확인 대상군'
ACTION_UNCERTAIN = '불확실 공동 점검군'
ACTION_MISSING = '자료 확인 대상'


def save(name, frame):
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT / (name + '.csv'), index=False, encoding='utf-8-sig')


def action_group(flags, ok):
    if not ok:
        return ACTION_MISSING
    s = set(ms.NAMES[np.asarray(flags, bool)])
    if s == {'OBSERVE'}:
        return ACTION_OBSERVE
    if 'OBSERVE' not in s and s:
        return ACTION_CHECK
    return ACTION_UNCERTAIN


def jaccard(x, y):
    inter = (x & y).sum(1)
    union = (x | y).sum(1)
    return np.divide(inter, union, out=np.full(len(x), np.nan, float), where=union > 0)


# ---------------------------------------------------------------- 공통 입력
def build_context():
    doc, current, panel, base, scenarios, candidates = p5._load_context(ROOT)  # noqa: SLF001
    profiles = base['scenarios'][0]['profiles']
    master = pd.read_csv(ROOT / config.PATHS['industry_master'])
    vintage = pd.read_csv(ROOT / doc['perturbation']['source'])
    zero_vintage = vintage.copy()
    zero_vintage[doc['perturbation']['value_column']] = 0.
    corrected = a.coherent_revision(panel, master, zero_vintage,
                                    np.random.default_rng(REVISION_SEED), mode='cell')
    values = qp.values_from_panel(corrected)
    return dict(doc=doc, panel=panel, profiles=profiles, scenarios=scenarios, candidates=candidates,
                master=master, vintage=vintage, corrected=corrected, values=values)


def box_samples(doc, n=BOX_DRAWS, seed=PARAMETER_SEED):
    """허용 박스에서 뽑은 crisp (w, lambda) 표본. q=p=0 으로 고정한다."""
    w_min, w_max, lam_min, lam_max = ms.space_bounds(doc)
    rng = np.random.default_rng(seed)
    kept = []
    while len(kept) < n:
        batch = rng.dirichlet(np.ones(4), size=n)
        kept.extend(batch[(batch >= w_min).all(1) & (batch <= w_max).all(1)].tolist())
    w = np.array(kept[:n])
    lam = rng.uniform(lam_min, lam_max, size=n)
    zero = dict.fromkeys(ms.CRIT, 0.)
    return [{'weights': dict(zip(ms.CRIT, row)), 'lambda': float(l), 'q': zero, 'p': zero}
            for row, l in zip(w, lam)]


def compatible_mask(samples, matrix, ctx):
    """참조사례(RC1~3)와 가상사례(VRC1~5) 양립 표본 마스크. 감사 구현을 그대로 쓴다."""
    doc, panel, profiles = ctx['doc'], ctx['panel'], ctx['profiles']
    vrc = ms._vrc_list(doc)  # noqa: SLF001
    vmatrix, vcases = p5.virtual_reference_matrix(vrc, profiles, samples)
    vpanel = pd.DataFrame({'industry': [c['id'] for c in vcases], 'quarter': 'VIRTUAL'})
    rc, _ = reference_compatibility(matrix, panel, doc['reference_cases'], 'fail')
    vall, _ = reference_compatibility(vmatrix, vpanel, vcases, 'fail')
    keep = [i for i, c in enumerate(vcases) if c['id'] != 'VRC4']
    vno4, _ = reference_compatibility(vmatrix[:, keep], vpanel.iloc[keep].reset_index(drop=True),
                                      [vcases[i] for i in keep], 'fail')
    return {'box_only': np.ones(len(samples), bool), 'rc': rc,
            'rc_vrc_no4': rc & vno4, 'rc_vrc': rc & vall}


# ---------------------------------------------------------------- 실행
def main(replicates=100, promethee_draws=20000):
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = build_context()
    doc, panel, profiles, values = ctx['doc'], ctx['panel'], ctx['profiles'], ctx['values']
    keys = panel[['industry', 'quarter']].reset_index(drop=True)
    ok = values.notna().all(axis=1).to_numpy()
    disc = ok & (values[['g1', 'g2', 'g4']].to_numpy() != 0).any(axis=1)
    latest = panel.quarter.max()
    latest_mask = (panel.quarter == latest).to_numpy()
    summary = {'rows': int(len(panel)), 'complete': int(ok.sum()), 'discriminating': int(disc.sum()),
               'latest_quarter': str(latest), 'replicates': int(replicates),
               'parameter_seed': PARAMETER_SEED, 'revision_seed': REVISION_SEED}

    common = keys.copy()
    common['q1_state'] = panel.state.to_numpy()
    for j in ms.CRIT:
        common[j] = values[j].to_numpy()
    common['complete_case'] = ok
    common['discriminating'] = disc
    save('common_input', common)

    # ---------------------------------------------------------- 1. MRSort 층별 연속공간 집합
    case_layers = {
        'box_only': [],
        'rc': ms.reference_cases(doc, values, panel, include=('RC',)),
        'rc_vrc_no4': ms.reference_cases(doc, values, panel, include=('RC', 'VRC'), exclude_ids=('VRC4',)),
        'rc_vrc': ms.reference_cases(doc, values, panel, include=('RC', 'VRC')),
    }
    mrsort = {}
    mrsort_frame = keys.copy()
    for label, cases in case_layers.items():
        flags = ms.mrsort_crisp_sets(values, profiles, doc, cases=cases)
        mrsort[label] = flags
        mrsort_frame['mrsort_' + label] = [ms.stage_text(f) if o else '' for f, o in zip(flags, ok)]
    mrsort_frame['note'] = 'q=p=0 crisp 공간에서 (w, lambda) 연속 전체를 LP로 정확히 푼 가능 단계'
    save('mrsort_layers', mrsort_frame)

    # ---------------------------------------------------------- 2. COUNT-CORE (가중치 무관)
    core = ms.count_core(values, profiles, doc)
    core_frame = pd.concat([keys, core.drop(columns='row')], axis=1)
    core_flags = mrsort['box_only']
    core_frame['possible_stages'] = [ms.stage_text(f) if o else '' for f, o in zip(core_flags, ok)]
    core_frame['weight_free_verdict'] = np.where(
        ~ok, 'UNDETERMINED',
        np.where(core.pass_b2 == 'NECESSARY_PASS', '어떤 허용 가중치에서도 우선점검',
                 np.where(core.pass_b1 == 'NECESSARY_FAIL', '어떤 허용 가중치에서도 관찰',
                          np.where(core.pass_b1 == 'NECESSARY_PASS', '어떤 허용 가중치에서도 추가확인 이상',
                                   '가중치·lambda 선택에 의존'))))
    save('count_core', core_frame)
    bounds = {k: ms.count_core_bounds(k, *ms.space_bounds(doc)[:2]) for k in range(5)}
    save('count_core_bounds', pd.DataFrame(
        [{'n_criteria_passing': k, 'min_concordance': lo, 'max_concordance': hi,
          'always_passes_any_lambda_in_box': bool(lo >= ms.space_bounds(doc)[3] - ms.EPS),
          'never_passes_any_lambda_in_box': bool(hi < ms.space_bounds(doc)[2] - ms.EPS)}
         for k, (lo, hi) in bounds.items()]))

    # ---------------------------------------------------------- 3. Pareto / 부분순서
    bd = ms.boundary_dominance(values, profiles)
    bd_frame = pd.concat([keys, bd.drop(columns='row')], axis=1)
    bd_frame['pareto_verdict'] = np.where(
        ~ok, 'UNDETERMINED',
        np.where(bd.dominates_b2.fillna(False), 'b2 프로파일 지배(모든 기준)',
                 np.where(bd.no_pass_b1.fillna(False), 'b1 프로파일에 모든 기준 미달',
                          '부분 통과 — 지배관계로 결정되지 않음')))
    save('pareto_boundary', bd_frame)

    order_rows, order_stats = [], []
    for label, frame, keycols in (('latest_quarter', common[latest_mask], ['industry']),
                                  ('all_complete', common[ok], ['industry', 'quarter'])):
        summary_frame, stats, _ = ms.partial_order_summary(frame, keycols)
        summary_frame.insert(0, 'scope', label)
        order_rows.append(summary_frame)
        order_stats.append({'scope': label, **stats})
    save('pareto_partial_order', pd.concat(order_rows, ignore_index=True))
    save('pareto_partial_order_stats', pd.DataFrame(order_stats))
    dec = []
    for label, frame in (('latest_quarter', common[latest_mask]), ('all_complete', common[ok])):
        d = ms.criterion_decisiveness(frame)
        d.insert(0, 'scope', label)
        dec.append(d)
    save('pareto_criterion_decisiveness', pd.concat(dec, ignore_index=True))

    # ---------------------------------------------------------- 4. ROR / UTADIS-GMS
    ror_specs = {
        'no_preference': dict(cases=[], share_bounds=None),
        'rc': dict(cases=case_layers['rc'], share_bounds=None),
        'rc_vrc': dict(cases=case_layers['rc_vrc'], share_bounds=None),
        'rc_vrc_no4': dict(cases=case_layers['rc_vrc_no4'], share_bounds=None),
        'rc_vrc_bounded': dict(cases=case_layers['rc_vrc'], share_bounds=(ms.space_bounds(doc)[0],
                                                                          ms.space_bounds(doc)[1])),
    }
    ror, ror_frame, feas_rows = {}, keys.copy(), []
    for label, spec in ror_specs.items():
        feasible, margin = (True, float('nan')) if not spec['cases'] else ms.ror_base_feasible(
            values, spec['cases'], spec['share_bounds'])
        feas_rows.append({'layer': label, 'n_preference_cases': len(spec['cases']),
                          'preference_information_consistent': feasible, 'max_margin_epsilon': margin})
        flags = ms.ror_sets(values, spec['cases'], spec['share_bounds'], ok_mask=ok)
        ror[label] = flags
        ror_frame['ror_' + label] = [ms.stage_text(f) if o else '' for f, o in zip(flags, ok)]
    ror_frame['note'] = 'UTADIS-GMS: 가법 비감소 가치함수 + 계급 문턱의 가능 배정(단일이면 필연)'
    save('ror_layers', ror_frame)
    save('ror_preference_consistency', pd.DataFrame(feas_rows))

    # ROR 가 고용증거 게이트를 표현하지 못하는 행 진단
    gate_blocked = np.array([False if not o else not ms._gate_ok(  # noqa: SLF001
        ms._pass_pattern(values.iloc[i], profiles['b1'])) for i, o in enumerate(ok)])  # noqa: SLF001
    gate_rows = keys.copy()
    gate_rows['gate_blocks_b1'] = gate_blocked
    gate_rows['mrsort_rc_vrc'] = mrsort_frame['mrsort_rc_vrc']
    gate_rows['ror_rc_vrc'] = ror_frame['ror_rc_vrc']
    gate_rows['ror_allows_check_or_higher'] = [bool(f[1] or f[2]) for f in ror['rc_vrc']]
    save('gate_representation_check', gate_rows[gate_blocked])
    summary['gate_blocked_rows'] = int(gate_blocked.sum())
    summary['gate_blocked_rows_ror_allows_check'] = int(
        (gate_blocked & np.array([bool(f[1] or f[2]) for f in ror['rc_vrc']])).sum())

    # ---------------------------------------------------------- 5. 점 규칙(비교 기준선)
    point = a.point_models(values, profiles, ctx['scenarios']['기준'], ctx['candidates'])
    point_frame = keys.copy()
    for name, codes in point.items():
        point_frame[name] = [ms.NAMES[c] if c >= 0 else '' for c in codes]
    save('point_rules', point_frame)

    # ---------------------------------------------------------- 6. 모형 간 비교표
    model_sets = {
        'MRSORT_box_only': mrsort['box_only'],
        'MRSORT_rc': mrsort['rc'],
        'MRSORT_rc_vrc': mrsort['rc_vrc'],
        'MRSORT_rc_vrc_no4': mrsort['rc_vrc_no4'],
        'ROR_no_preference': ror['no_preference'],
        'ROR_rc': ror['rc'],
        'ROR_rc_vrc': ror['rc_vrc'],
        'ROR_rc_vrc_bounded': ror['rc_vrc_bounded'],
    }
    pareto_flags = np.zeros((len(panel), 3), bool)
    for i in range(len(panel)):
        if not ok[i]:
            continue
        if bool(bd.dominates_b2[i]):
            pareto_flags[i] = [False, False, True]
        elif bool(bd.no_pass_b1[i]):
            pareto_flags[i] = [True, False, False]
        elif bool(bd.dominates_b1[i]):
            pareto_flags[i] = [False, True, True]
        else:
            pareto_flags[i] = [True, True, True]
    model_sets['PARETO_boundary'] = pareto_flags

    rows = []
    for name, flags in model_sets.items():
        width = flags[ok].sum(1)
        rows.append({
            'model': name,
            'singleton_share_complete': float((width == 1).mean()),
            'singleton_share_discriminating': float((flags[disc].sum(1) == 1).mean()),
            'mean_possible_stages': float(width.mean()),
            'n_observe_only': int((flags[ok] == [True, False, False]).all(1).sum()),
            'n_check_or_higher_only': int(((~flags[ok][:, 0]) & flags[ok].any(1)).sum()),
            'n_all_three': int((width == 3).sum()),
            'n_empty': int((width == 0).sum()),
        })
    discriminating_power = pd.DataFrame(rows)
    save('comparison_discriminating_power', discriminating_power)

    # 규범 의존성: 참조제약 층을 넣고 뺄 때 집합이 바뀌는 행 수
    norm_rows = []
    for family, layers in (('MRSORT', mrsort), ('ROR', ror)):
        base_layer = 'box_only' if family == 'MRSORT' else 'no_preference'
        for label, flags in layers.items():
            if label == base_layer:
                continue
            changed = (flags[ok] != layers[base_layer][ok]).any(1)
            norm_rows.append({'family': family, 'layer': label,
                              'rows_changed_vs_no_preference': int(changed.sum()),
                              'mean_width_no_preference': float(layers[base_layer][ok].sum(1).mean()),
                              'mean_width_layer': float(flags[ok].sum(1).mean())})
    if 'rc_vrc' in mrsort and 'rc_vrc_no4' in mrsort:
        norm_rows.append({'family': 'MRSORT', 'layer': 'vrc4_marginal_effect',
                          'rows_changed_vs_no_preference':
                              int((mrsort['rc_vrc'][ok] != mrsort['rc_vrc_no4'][ok]).any(1).sum()),
                          'mean_width_no_preference': float(mrsort['rc_vrc_no4'][ok].sum(1).mean()),
                          'mean_width_layer': float(mrsort['rc_vrc'][ok].sum(1).mean())})
    save('comparison_normative_dependence', pd.DataFrame(norm_rows))

    # ---------------------------------------------------------- 7. 최신분기 비교
    latest_frame = common[latest_mask].reset_index(drop=True)
    for name, flags in model_sets.items():
        latest_frame[name] = [ms.stage_text(f) for f in flags[latest_mask]]
    for name, codes in point.items():
        latest_frame['POINT_' + name] = [ms.NAMES[c] if c >= 0 else '' for c in codes[latest_mask]]
    for name, flags in model_sets.items():
        latest_frame['action_' + name] = [action_group(f, o)
                                          for f, o in zip(flags[latest_mask], ok[latest_mask])]
    save('latest_quarter_comparison', latest_frame)

    # 업종별 합의/불일치
    agree_rows = []
    keys_sets = ['MRSORT_box_only', 'MRSORT_rc_vrc', 'ROR_rc_vrc', 'PARETO_boundary']
    for i in np.flatnonzero(ok):
        groups = {k: action_group(model_sets[k][i], True) for k in keys_sets}
        agree_rows.append({'industry': panel.industry[i], 'quarter': panel.quarter[i],
                           **groups, 'n_distinct_action_groups': len(set(groups.values())),
                           'all_agree': len(set(groups.values())) == 1})
    save('model_agreement_by_row', pd.DataFrame(agree_rows))

    # ---------------------------------------------------------- 7b. 연구질문 표
    def singleton_stage(flags):
        return ms.NAMES[flags.argmax()] if flags.sum() == 1 else ''

    q_rows = []
    for i in np.flatnonzero(latest_mask):
        groups = {k: action_group(model_sets[k][i], ok[i]) for k in keys_sets}
        q_rows.append({'industry': panel.industry[i],
                       **{'action_' + k: v for k, v in groups.items()},
                       'n_models_check_only': sum(v == ACTION_CHECK for v in groups.values()),
                       'n_models_allow_check_or_higher':
                           sum(bool(model_sets[k][i][1] or model_sets[k][i][2]) for k in keys_sets),
                       'n_models_observe_only': sum(v == ACTION_OBSERVE for v in groups.values())})
    save('q1_latest_convergence', pd.DataFrame(q_rows))

    attribution = []
    for i in np.flatnonzero(ok):
        pref = not np.array_equal(mrsort['box_only'][i], mrsort['rc_vrc'][i])
        form = not np.array_equal(mrsort['rc_vrc'][i], ror['rc_vrc'][i])
        form_free = not np.array_equal(mrsort['box_only'][i], pareto_flags[i])
        attribution.append({'industry': panel.industry[i], 'quarter': panel.quarter[i],
                            'changed_by_preference_information': pref,
                            'changed_by_aggregation_form_same_preference': form,
                            'changed_by_aggregation_form_no_preference': form_free,
                            'mrsort_box_only': ms.stage_text(mrsort['box_only'][i]),
                            'mrsort_rc_vrc': ms.stage_text(mrsort['rc_vrc'][i]),
                            'ror_rc_vrc': ms.stage_text(ror['rc_vrc'][i]),
                            'pareto_boundary': ms.stage_text(pareto_flags[i])})
    attribution = pd.DataFrame(attribution)
    save('q23_difference_attribution', attribution)
    summary['rows_changed_by_preference'] = int(attribution.changed_by_preference_information.sum())
    summary['rows_changed_by_form_same_preference'] = int(
        attribution.changed_by_aggregation_form_same_preference.sum())

    added = []
    for i in np.flatnonzero(ok):
        pareto_undetermined = pareto_flags[i].sum() == 3
        added.append({'industry': panel.industry[i], 'quarter': panel.quarter[i],
                      'pareto_undetermined': pareto_undetermined,
                      'mrsort_box_only_singleton': bool(mrsort['box_only'][i].sum() == 1),
                      'mrsort_rc_vrc_singleton': bool(mrsort['rc_vrc'][i].sum() == 1),
                      'ror_rc_vrc_singleton': bool(ror['rc_vrc'][i].sum() == 1),
                      'point_v1_crisp': ms.NAMES[point['v1.0_crisp'][i]] if point['v1.0_crisp'][i] >= 0 else '',
                      'point_count2': ms.NAMES[point['count2'][i]] if point['count2'][i] >= 0 else '',
                      'point_rules_disagree': bool(point['v1.0_crisp'][i] != point['count2'][i])})
    added = pd.DataFrame(added)
    save('q4_added_value_over_pareto', added)
    summary['pareto_undetermined_but_mrsort_box_singleton'] = int(
        (added.pareto_undetermined & added.mrsort_box_only_singleton).sum())
    summary['pareto_undetermined_but_mrsort_rc_vrc_singleton'] = int(
        (added.pareto_undetermined & added.mrsort_rc_vrc_singleton).sum())
    summary['point_rule_v1_vs_count2_disagreements'] = int(added.point_rules_disagree.sum())

    stage_support = []
    for name, flags in model_sets.items():
        singles = [singleton_stage(flags[i]) for i in np.flatnonzero(ok)]
        stage_support.append({'model': name,
                              'necessary_OBSERVE': singles.count('OBSERVE'),
                              'necessary_CHECK': singles.count('CHECK'),
                              'necessary_PRIORITY': singles.count('PRIORITY'),
                              'not_determined': singles.count('')})
    save('q6_stage_support', pd.DataFrame(stage_support))

    reasons = common[latest_mask].reset_index(drop=True)
    for h in ('b1', 'b2'):
        for j in ms.CRIT:
            reasons[f'pass_{j}_{h}'] = [float(v) >= float(profiles[h][j])
                                        for v in common.loc[latest_mask, j]]
        reasons['k_' + h] = sum(reasons[f'pass_{j}_{h}'].astype(int) for j in ms.CRIT)
        reasons['employment_evidence_' + h] = [any(reasons.loc[r, f'pass_{j}_{h}'] for j in ms.EMP)
                                               for r in range(len(reasons))]
    save('latest_quarter_reasons', reasons)

    # ---------------------------------------------------------- 8. 교란 강건성
    samples = box_samples(doc)
    matrix = a.fast_matrix(values, profiles, samples)
    masks = compatible_mask(samples, matrix, ctx)
    summary['box_samples'] = len(samples)
    summary.update({'compatible_samples_' + k: int(v.sum()) for k, v in masks.items()})
    base_sample_sets = {k: a.sets_from_matrix(matrix[v]) for k, v in masks.items()}

    robustness = []
    variants = (('consistent_cells', 'cell', 'forward', 1),
                ('joint_blocks2', 'quarter_block', 'forward', 2))
    for label, mode, direction, block in variants:
        rng = np.random.default_rng(REVISION_SEED)
        acc = {k: [] for k in ('MRSORT_box_only', 'MRSORT_rc_vrc', 'ROR_rc_vrc', 'PARETO_boundary')}
        action_acc = {k: np.zeros(len(panel)) for k in acc}
        point_acc = {name: [] for name in point}
        for _ in range(replicates):
            revised = a.coherent_revision(ctx['corrected'], ctx['master'], ctx['vintage'], rng,
                                          mode=mode, direction=direction, block_length=block)
            rv = qp.values_from_panel(revised)
            rmatrix = a.fast_matrix(rv, profiles, samples)
            new = {'MRSORT_box_only': a.sets_from_matrix(rmatrix[masks['box_only']]),
                   'MRSORT_rc_vrc': a.sets_from_matrix(rmatrix[masks['rc_vrc']]),
                   'ROR_rc_vrc': ms.ror_sets(rv, case_layers['rc_vrc'], None, ok_mask=ok)}
            rbd = ms.boundary_dominance(rv, profiles)
            pf = np.zeros((len(panel), 3), bool)
            for i in np.flatnonzero(ok):
                if bool(rbd.dominates_b2[i]):
                    pf[i] = [False, False, True]
                elif bool(rbd.no_pass_b1[i]):
                    pf[i] = [True, False, False]
                elif bool(rbd.dominates_b1[i]):
                    pf[i] = [False, True, True]
                else:
                    pf[i] = [True, True, True]
            new['PARETO_boundary'] = pf
            reference = {'MRSORT_box_only': base_sample_sets['box_only'],
                         'MRSORT_rc_vrc': base_sample_sets['rc_vrc'],
                         'ROR_rc_vrc': model_sets['ROR_rc_vrc'],
                         'PARETO_boundary': model_sets['PARETO_boundary']}
            for k in acc:
                acc[k].append(np.nanmean(jaccard(reference[k], new[k])[ok]))
                action_acc[k] += np.array([action_group(new[k][i], ok[i]) == action_group(reference[k][i], ok[i])
                                           for i in range(len(panel))], float)
            rpoint = a.point_models(rv, profiles, ctx['scenarios']['기준'], ctx['candidates'])
            for name, codes in rpoint.items():
                point_acc[name].append(float((codes[ok] == point[name][ok]).mean()))
        for k in acc:
            robustness.append({'revision': label, 'model': k, 'metric': 'possible_set_jaccard',
                               'value': float(np.mean(acc[k])),
                               'action_group_retention': float((action_acc[k] / replicates)[ok].mean())})
        for name, vals in point_acc.items():
            robustness.append({'revision': label, 'model': 'POINT_' + name, 'metric': 'point_retention',
                               'value': float(np.mean(vals)), 'action_group_retention': np.nan})
        print('revision scenario complete:', label, flush=True)
    save('comparison_revision_robustness', pd.DataFrame(robustness))

    # ---------------------------------------------------------- 9. PROMETHEE-II + SMAA(서술용)
    smaa = ms.promethee_rank_acceptability(latest_frame[['industry'] + ms.CRIT], doc,
                                           n_draws=promethee_draws, seed=PARAMETER_SEED)
    save('promethee_smaa_latest', smaa)

    # ---------------------------------------------------------- 10. 변화점 탐지(보조)
    cp_rows = []
    master = ctx['master'].sort_values(['industry', 'quarter'])
    for industry, group in master.groupby('industry', sort=True):
        series = group['employment'].astype(float).to_numpy()
        quarters = group['quarter'].tolist()
        diff = np.diff(np.log(np.where(series > 0, series, np.nan)))
        pos, stat, pval = ms.single_changepoint(diff, n_perm=2000, seed=PARAMETER_SEED)
        cp_rows.append({'industry': industry, 'n_quarters': len(series),
                        'changepoint_quarter': quarters[int(pos) + 1] if np.isfinite(pos) else '',
                        'statistic': stat, 'permutation_p_value': pval,
                        'g4_latest': float(values.g4[(panel.industry == industry)
                                                     & (panel.quarter == latest)].iloc[0])
                        if ((panel.industry == industry) & (panel.quarter == latest)).any() else np.nan})
    changepoints = pd.DataFrame(cp_rows)
    changepoints['significant_at_0.05'] = changepoints['permutation_p_value'] < 0.05
    changepoints['scope'] = '분기 34개의 단일 평균이동 순열검정; 다중검정 보정 없음; 구조변화 확정 아님'
    save('changepoint_employment', changepoints)
    summary['changepoints_significant'] = int(changepoints['significant_at_0.05'].sum())

    # ---------------------------------------------------------- 메타데이터
    summary['elapsed_seconds'] = round(time.time() - started, 1)
    files = ['src/model/model_selection.py', 'src/run_model_selection.py', 'src/model/audit_tools.py',
             'src/model/electre.py', 'config/model_revalidation_prereg.yaml',
             'config/electre_tri_b_params.yaml', 'data/processed/model/electre_input_panel.csv',
             'data/processed/kicox/changwon_industry_master.csv']
    meta = {'generated_at': pd.Timestamp.now('UTC').isoformat(), 'python': platform.python_version(),
            'numpy': np.__version__, 'pandas': pd.__version__,
            'parameter_seed': PARAMETER_SEED, 'revision_seed': REVISION_SEED,
            'replicates': replicates, 'promethee_draws': promethee_draws,
            'result_scope': 'development_data_not_unseen_validation',
            'sha256': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
                       for f in files if (ROOT / f).exists()}}
    (OUT / 'run_metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--replicates', type=int, default=100)
    parser.add_argument('--promethee-draws', type=int, default=20000)
    args = parser.parse_args()
    main(args.replicates, args.promethee_draws)
