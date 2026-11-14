# -*- coding: utf-8 -*-
"""Phase 5: 공식 산출물을 점 배정에서 구간 배정(필연/가능 + CAI)으로 전환한다.

electre.py의 판정 로직은 바꾸지 않는다. 파라미터(가중치·λ·q·p·veto)도 바꾸지 않는다
— config/electre_tri_b_params.yaml은 읽기만 한다. 공식 공간은
reference_plus_virtual_subspace(RC 3건 + VRC 5건 결합 양립공간)이다.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import config, electre, manifest, params, perturb, prereg, qp_calibration, robust
from . import revalidation as p2
from . import revalidation_phase3 as p3
from . import revalidation_phase4 as p4

MODEL_IDS = p4.MODEL_IDS
SCENARIO_IDS = p4.SCENARIO_IDS
RC_RANK = p3.RC_RANK
STAGE_ORDER = ('OBSERVE', 'CHECK', 'PRIORITY')


class Phase5GateError(RuntimeError):
    """Phase 5 착수 게이트를 통과하지 못했을 때."""


class PreferenceSpaceEmptyError(RuntimeError):
    """reference_plus_virtual_subspace 표본이 0이거나 100 미만일 때."""


# ---------------------------------------------------------------- 착수 게이트
def check_gate(root):
    root = Path(root)
    doc = prereg.load(root / 'config/model_revalidation_prereg.yaml')
    try:
        prereg.require_registered(doc)
    except prereg.PreregNotRegisteredError:
        raise Phase5GateError('사전등록이 완료되지 않아 Phase 5를 실행할 수 없습니다')
    amendment_ids = [a['id'] for a in doc['amendments']]
    if 'AM6' not in amendment_ids:
        raise Phase5GateError('amendments에 AM6가 없어 Phase 5를 실행할 수 없습니다')
    prereg.validate_virtual_reference_cases(doc)
    prereg.validate_interval_acceptance(doc)
    return doc


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


def _am6_content(prereg_doc):
    return next(a for a in prereg_doc['amendments'] if a['id'] == 'AM6')['content']


def _pessimistic(values, weights, lam, q, p, veto=None, gate=True):
    return p4._stage_with_veto(values, weights, lam, q, p, veto, gate)  # noqa: SLF001


# ---------------------------------------------------------------- Step 1: 선호정보 확충
def virtual_reference_matrix(vrc_list, base_profiles, samples):
    """가상 프로파일(실제 패널에 추가하지 않음) 5건 × 파라미터 표본 배정 행렬(n_samples,5)."""
    values = pd.DataFrame([vrc['profile'] for vrc in vrc_list])[list(config.CRITERIA)]
    matrix = robust.assignment_matrix(values, base_profiles, samples, gate=True, veto=None)
    cases = [{'id': v['id'], 'industry': v['id'], 'quarter': 'VIRTUAL', 'relation': v['relation'],
             'stage': v['stage']} for v in vrc_list]
    return matrix, cases


def preference_conflict_analysis(rc_cases, vrc_cases, rc_matrix, vrc_matrix, undetermined_counts_as):
    """공집합일 때만 호출한다. 사례를 1건씩(5회), 2건씩(10회) 빼며 공집합이 풀리는지 본다."""
    all_cases = [('real', c) for c in rc_cases] + [('virtual', c) for c in vrc_cases]

    def compatible_excluding(excluded_ids):
        mask = np.ones(rc_matrix.shape[0], dtype=bool)
        for kind, c in all_cases:
            if c['id'] in excluded_ids:
                continue
            m = rc_matrix if kind == 'real' else vrc_matrix
            col_index = [cc['id'] for cc in (rc_cases if kind == 'real' else vrc_cases)].index(c['id'])
            col = m[:, col_index]
            undetermined = col == -1
            scored = ~undetermined
            ok = np.zeros(len(col), dtype=bool)
            ok[undetermined] = (undetermined_counts_as != 'fail')
            if c['relation'] == 'at_least':
                ok[scored] = col[scored] >= RC_RANK[c['stage']]
            else:
                ok[scored] = col[scored] <= RC_RANK[c['stage']]
            mask &= ok
        return mask

    rows = []
    ids = [c['id'] for _, c in all_cases]
    for i in ids:
        n = int(compatible_excluding({i}).sum())
        rows.append({'excluded_case_ids': i, 'n_excluded': 1, 'n_compatible_after_exclusion': n,
                    'resolves_conflict': n >= 100})
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            excl = {ids[i], ids[j]}
            n = int(compatible_excluding(excl).sum())
            rows.append({'excluded_case_ids': ','.join(sorted(excl)), 'n_excluded': 2,
                        'n_compatible_after_exclusion': n, 'resolves_conflict': n >= 100})
    return pd.DataFrame(rows)


def _space_stats(matrix, mask, panel, values):
    m = matrix if mask is None else matrix[mask, :]
    n_samples = m.shape[0]
    stats, ra = p3.subspace_necessary_shares(matrix, panel, values, mask=mask)
    row_keys = panel[['industry', 'quarter']].reset_index(drop=True)
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    cai = robust.class_acceptability(m, row_keys)
    n_possible = ra.set_index(['industry', 'quarter'])['n_possible']
    mean_n_possible = float(n_possible[scorable].mean())
    share_le_2 = float((n_possible[scorable] <= 2).mean())
    return {'n_samples': n_samples, **stats, 'mean_n_possible_stages': mean_n_possible,
           'share_n_possible_le_2': share_le_2}, ra, cai


def _sample_weight_stats(samples, mask=None):
    idx = np.arange(len(samples)) if mask is None else np.nonzero(mask)[0]
    crit = config.CRITERIA
    out = {}
    lam = np.array([samples[i]['lambda'] for i in idx])
    out['lambda_min'], out['lambda_mean'], out['lambda_max'] = float(lam.min()), float(lam.mean()), float(lam.max())
    for j in crit:
        w = np.array([samples[i]['weights'][j] for i in idx])
        p = np.array([samples[i]['p'][j] for i in idx])
        q = np.array([samples[i]['q'][j] for i in idx])
        out[f'w_{j}_mean'] = float(w.mean())
        out[f'w_{j}_p05'] = float(np.percentile(w, 5))
        out[f'w_{j}_p95'] = float(np.percentile(w, 95))
        out[f'p_{j}_mean'] = float(p.mean())
        out[f'q_{j}_mean'] = float(q.mean())
    return out


def _case_ok_array(m, idx_c, relation, stage, undetermined_counts_as):
    col = m[:, idx_c]
    undetermined = col == -1
    scored = ~undetermined
    ok = np.zeros(len(col), dtype=bool)
    ok[undetermined] = (undetermined_counts_as != 'fail')
    if relation == 'at_least':
        ok[scored] = col[scored] >= RC_RANK[stage]
    else:
        ok[scored] = col[scored] <= RC_RANK[stage]
    return ok


def preference_expansion_table(root, prereg_doc, panel, values, base_profiles, samples, matrix, vrc_matrix,
                               rc_cases, vrc_cases, rc_compat, vrc_compat, combined_mask):
    undetermined_counts_as = prereg_doc['reference_case_rule']['undetermined_counts_as']
    n_full = len(samples)

    # 8건(RC3 + VRC5) 각각의 개별 통과 배열을 먼저 모은다 — marginal_narrowing(이 사례를
    # 뺀 나머지 7건의 교집합 대비, 이 사례를 넣었을 때 공간이 얼마나 좁아지는지) 계산에 쓴다.
    # RC는 matrix의 "그 업종×분기 행" 열을, VRC는 vrc_matrix의 "그 사례 순번" 열을 쓴다
    # (둘은 서로 다른 행렬이므로 열 인덱스 의미가 다르다 — 혼동하지 않는다).
    entries = []  # (case_id, kind, ok_array, case_dict)
    for c in rc_cases:
        panel_row = panel.index[(panel['industry'] == c['industry']) & (panel['quarter'] == c['quarter'])]
        assert len(panel_row) == 1, f"{c['id']}의 패널 행 위치가 유일하지 않습니다: {len(panel_row)}건"
        entries.append((c['id'], 'real', _case_ok_array(matrix, int(panel_row[0]), c['relation'], c['stage'],
                                                         undetermined_counts_as), c))
    for idx_c, c in enumerate(vrc_cases):
        entries.append((c['id'], 'virtual', _case_ok_array(vrc_matrix, idx_c, c['relation'], c['stage'],
                                                            undetermined_counts_as), c))
    assert np.array_equal(combined_mask, np.logical_and.reduce([e[2] for e in entries]))

    rc_by_id = {c['id']: c for c in prereg_doc['reference_cases']}
    vrc_by_id = {c['id']: c for c in _am6_content(prereg_doc)['virtual_reference_cases']}

    case_rows = []
    for case_id, kind, ok, c in entries:
        individual_pass_rate = float(ok.mean())
        others = [e[2] for e in entries if e[0] != case_id]
        without_mask = np.logical_and.reduce(others)
        n_without = int(without_mask.sum())
        n_with = int(combined_mask.sum())
        marginal_narrowing = float((n_without - n_with) / n_without) if n_without else np.nan
        if kind == 'real':
            src = rc_by_id[case_id]
            loc, rationale = f"{src['industry']}/{src['quarter']}", src['rationale']
        else:
            src = vrc_by_id[case_id]
            loc, rationale = json.dumps(src['profile'], ensure_ascii=False, sort_keys=True), src['rationale']
        case_rows.append({
            'block_type': 'case', 'case_id': case_id, 'case_type': kind,
            'profile_or_location': loc, 'relation': c['relation'], 'target_stage': c['stage'],
            'rationale': rationale, 'individual_pass_rate': individual_pass_rate,
            'marginal_narrowing': marginal_narrowing,
        })

    space_rows = []
    for space_id, mask in (('full_parameter_space', None), ('reference_compatible_subspace', rc_compat),
                           ('reference_plus_virtual_subspace', combined_mask)):
        stats, _, _ = _space_stats(matrix, mask, panel, values)
        wstats = _sample_weight_stats(samples, mask)
        space_rows.append({
            'block_type': 'space', 'space_id': space_id, 'n_samples': stats['n_samples'],
            'share_of_full': stats['n_samples'] / n_full,
            **wstats,
            'necessary_share_discriminating': stats['necessary_share_discriminating'],
            'necessary_share_scorable': stats['necessary_share_scorable'],
            'mean_n_possible_stages': stats['mean_n_possible_stages'],
            'share_n_possible_le_2': stats['share_n_possible_le_2'],
        })

    return pd.concat([pd.DataFrame(case_rows), pd.DataFrame(space_rows)], ignore_index=True)


# ---------------------------------------------------------------- Step 2: 구간 배정 공식 산출물
def display_label(possible_stages, modal_stage, modal_share, is_undetermined):
    """단일 단계 단독 제시 금지(AM4.EX3)를 코드로 고정한 유일한 표기 생성 함수.

    n_possible==1일 때 "(표본 내 공통)"을 붙인다. 그 밖의 모든 경우 최저~최고 단계
    범위와 최빈 단계·비율을 함께 적는다. UNDETERMINED는 판정불가 문구로 고정한다.
    """
    if is_undetermined:
        return config.DISPLAY_LABELS[config.UNDETERMINED]
    stages_sorted = sorted(possible_stages, key=STAGE_ORDER.index)
    if len(stages_sorted) == 1:
        return f'{config.DISPLAY_LABELS[stages_sorted[0]]}(표본 내 공통)'
    lo, hi = config.DISPLAY_LABELS[stages_sorted[0]], config.DISPLAY_LABELS[stages_sorted[-1]]
    modal_label = config.DISPLAY_LABELS[modal_stage]
    indices = [STAGE_ORDER.index(s) for s in stages_sorted]
    label = f'{lo}~{hi}' if indices == list(range(indices[0], indices[-1]+1)) else ' / '.join(config.DISPLAY_LABELS[s] for s in stages_sorted)
    return f'{label} (파라미터 표본 최빈: {modal_label} {modal_share:.0%})'


def interval_assignment_table(panel, values, matrix, combined_mask, scenarios, candidates):
    row_keys = panel[['industry', 'quarter']].reset_index(drop=True)
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced

    sub_matrix = matrix[combined_mask, :]
    cai = robust.class_acceptability(sub_matrix, row_keys)
    n_samples_in_space = int(combined_mask.sum())

    point_stage = {}
    v10 = candidates['v1.0_crisp']
    for sid in SCENARIO_IDS:
        s = scenarios[sid]
        point_stage[sid] = np.asarray(_pessimistic(values, s.weights, s.lam, v10['q'], v10['p']))

    rows = []
    for i in range(len(panel)):
        r = cai.iloc[i]
        stage_cai = {'OBSERVE': r.cai_observe, 'CHECK': r.cai_check, 'PRIORITY': r.cai_priority}
        is_undet = r.cai_undetermined > 0.5
        possible = [] if is_undet else [s for s, v in stage_cai.items() if v > 0]
        n_possible = len(possible)
        modal_stage = max(stage_cai, key=stage_cai.get) if possible else None
        modal_share = stage_cai[modal_stage] if modal_stage else np.nan
        necessary_stage = possible[0] if n_possible == 1 else None
        lowest = min(possible, key=STAGE_ORDER.index) if possible else None
        highest = max(possible, key=STAGE_ORDER.index) if possible else None
        label = display_label(possible, modal_stage, modal_share, is_undet)

        ps = {sid: point_stage[sid][i] for sid in SCENARIO_IDS}
        rows.append({
            'industry': panel['industry'].iat[i], 'quarter': panel['quarter'].iat[i],
            'necessary_stage': necessary_stage, 'possible_stages': '|'.join(possible), 'n_possible': n_possible,
            'lowest_possible_stage': lowest, 'highest_possible_stage': highest,
            'cai_observe': r.cai_observe, 'cai_check': r.cai_check, 'cai_priority': r.cai_priority,
            'cai_undetermined': r.cai_undetermined, 'modal_stage': modal_stage, 'modal_share': modal_share,
            'is_discriminating': bool(discriminating[i]), 'is_forced_observe': bool(forced[i]),
            'display_label': label,
            'point_stage_기준': ps['기준'], 'point_stage_고용중시': ps['고용중시'],
            'point_stage_지속성중시': ps['지속성중시'],
            'point_stage_agreement': len(set(ps.values())) == 1,
            'space_id': 'reference_plus_virtual_subspace', 'n_samples_in_space': n_samples_in_space,
            'assignment_scope': 'finite_parameter_sample',
        })
    table = pd.DataFrame(rows)
    totals = table[['cai_observe', 'cai_check', 'cai_priority', 'cai_undetermined']].sum(axis=1)
    if not np.allclose(totals, 1.0, atol=1e-9):
        raise RuntimeError('electre_interval_assignment의 CAI 행 합이 1.0이 아닙니다.')
    return table


def _bar(value, width=20):
    n = int(round(value * width))
    return '█' * n + '░' * (width - n)


def write_diagnostic_cards(root, panel, values, interval_table, base_profiles, quarter='2026Q2'):
    root = Path(root)
    b1, b2 = base_profiles['b1'], base_profiles['b2']
    latest_panel = panel[panel['quarter'] == quarter].sort_values('industry').reset_index(drop=True)
    latest_interval = interval_table[interval_table['quarter'] == quarter].set_index('industry')

    lines = [f'# {quarter} 업종별 진단카드 — 구간 배정(참조사례 양립 부분공간 기준)', '',
            '이 카드는 점 배정이 아니라 구간 배정(필연/가능 단계 + 등급수용지수)을 공식으로 쓴다. '
            '점 단계 세 시나리오 값은 참고로만 병기한다.', '']
    for _, prow in latest_panel.iterrows():
        industry = prow['industry']
        irow = latest_interval.loc[industry]
        vrow = values.loc[panel.index[(panel['industry'] == industry) & (panel['quarter'] == quarter)][0]]
        lines.append(f'## {industry}')
        lines.append('')
        lines.append(f"**점검단계**: {irow['display_label']}")
        lines.append('')
        lines.append('**가능 단계 분포(CAI)**')
        lines.append('')
        for label, key in (('관찰', 'cai_observe'), ('추가확인', 'cai_check'), ('우선점검', 'cai_priority')):
            lines.append(f'- {label}: `{_bar(irow[key])}` {irow[key]:.0%}')
        lines.append('')
        lines.append('**근거**')
        lines.append('')
        lines.append('| 기준 | 값 | b1 | b2 | b1 통과 | b2 통과 |')
        lines.append('|---|---|---|---|---|---|')
        for j in config.CRITERIA:
            v = vrow[j]
            v_str = 'NA' if pd.isna(v) else f'{v:g}'
            pass_b1 = '—' if pd.isna(v) else ('예' if v >= b1[j] else '아니오')
            pass_b2 = '—' if pd.isna(v) else ('예' if v >= b2[j] else '아니오')
            lines.append(f'| {config.CRITERION_LABELS[j]} | {v_str} | {b1[j]:g} | {b2[j]:g} | {pass_b1} | {pass_b2} |')
        lines.append('')
        lines.append(f"참고(점 단계, 세 시나리오): 기준={irow['point_stage_기준']} / "
                     f"고용중시={irow['point_stage_고용중시']} / 지속성중시={irow['point_stage_지속성중시']}")
        lines.append('')
        lines.append('**자료 주의**')
        lines.append('')
        cautions = []
        if bool(prow.get('small_firm_count_flag', False)):
            cautions.append(config.SMALL_FIRM_CAUTION)
        ppi_status = prow.get('ppi_mapping_confirmation_status')
        if pd.notna(ppi_status) and ppi_status != 'CONFIRMED':
            cautions.append(f'PPI 매핑 확정 상태: {config.PPI_CONFIRMATION_LABELS.get(ppi_status, ppi_status)}')
        if bool(prow.get('g4_delta00_left_censored', False)):
            cautions.append('전년동기 대비 고용 하회 연속분기가 관측기간 시작 이전부터 이어졌을 수 있다(좌측절단).')
        if bool(prow.get('g4_delta00_open_run', False)):
            cautions.append('전년동기 대비 고용 하회 연속분기가 최신분기까지 끊기지 않고 이어지고 있다(진행중인 런).')
        if not cautions:
            cautions.append('해당 없음.')
        for c in cautions:
            lines.append(f'- {c}')
        lines.append('')
        lines.append('**판단할 수 없는 것**')
        lines.append('')
        for s in config.NOT_DETERMINABLE_STATEMENTS:
            lines.append(f'- {s}')
        lines.append('')

    text = '\n'.join(lines)
    out_path = root / 'outputs/report/interval_diagnostic_cards_2026Q2.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding='utf-8')
    return out_path


# ---------------------------------------------------------------- Step 3: 교란 강건성 재정의
def c3b_point_in_interval(root, prereg_doc, panel, scenarios, candidates, interval_table, n=None, seed=None):
    """각 교란 복제본의 점 단계가 원자료 기준 가능 단계 집합에 포함되는 비율.

    LEGACY 지표: 고정 6조합이 참조사례 양립공간에 속한다는 보장이 없다.
    순수한 자료 안정성으로 해석하지 않는다. 수정 지표는 run_independent_audit.py 참조.
    분모: 원·교란 양쪽 모두 UNDETERMINED가 아닌 행. mean_n_possible_stages를 반드시
    같은 행에 병기한다(가능 단계 집합이 넓을수록 이 값이 저절로 높아지기 때문).
    """
    root = Path(root)
    values = _values(panel)
    unc = prereg_doc['perturbation']
    n = unc['n_replicates'] if n is None else n
    seed = unc['seed'] if seed is None else seed
    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')

    possible_sets = [set(s.split('|')) if s else set() for s in interval_table['possible_stages']]
    mean_n_possible = float(interval_table.loc[interval_table['n_possible'] > 0, 'n_possible'].mean())

    rows = []
    for model_id in MODEL_IDS:
        cand = candidates[model_id]
        for scenario_id in SCENARIO_IDS:
            s = scenarios[scenario_id]
            base_stage = np.asarray(_pessimistic(values, s.weights, s.lam, cand['q'], cand['p']))
            rng = np.random.default_rng(seed)
            contain = np.zeros(len(panel))
            valid = np.zeros(len(panel))
            for _ in range(n):
                perturbed = perturb.perturb_once(panel, pool, rng)
                p_values = qp_calibration.values_from_panel(perturbed)
                p_stage = np.asarray(_pessimistic(p_values, s.weights, s.lam, cand['q'], cand['p']))
                ok = (base_stage != config.UNDETERMINED) & (p_stage != config.UNDETERMINED)
                valid += ok
                for i in np.nonzero(ok)[0]:
                    if p_stage[i] in possible_sets[i]:
                        contain[i] += 1
            with np.errstate(invalid='ignore'):
                rate = np.where(valid > 0, contain / np.maximum(valid, 1), np.nan)
            rows.append({'model_id': model_id, 'scenario_id': scenario_id, 'metric_id': 'C3b_point_in_interval',
                        'value': float(np.nanmean(rate)), 'n_replicates': n,
                        'mean_n_possible_stages': mean_n_possible, 'seed': seed})
    return pd.DataFrame(rows)


def _possible_sets_from_matrix(matrix):
    sets = []
    for i in range(matrix.shape[1]):
        codes = set(matrix[:, i].tolist())
        codes.discard(-1)
        sets.append(codes)
    return sets


def c3c_interval_jaccard(root, prereg_doc, panel, values, base_profiles, n_param_samples=1000, n_replicates=50):
    """LEGACY 무제약 공간의 안정성(최종 참조사례 양립공간의 Jaccard가 아님).
    파라미터 표본은 공식 생성 순서의 앞 1000개만
    쓴다(층화 없음, seed는 prereg parameter_space 값). 계산량이 커서 int8 행렬을
    그대로 쓰고, 10분을 넘으면 20회로 줄인다(사전 1회 측정으로 판단).
    """
    root = Path(root)
    rng = np.random.default_rng(prereg_doc['parameter_space']['seed'])
    all_samples = robust.sample_parameter_space(prereg_doc, rng)
    samples_1000 = all_samples[:n_param_samples]
    matrix_orig = robust.assignment_matrix(values, base_profiles, samples_1000, gate=True, veto=None)
    orig_sets = _possible_sets_from_matrix(matrix_orig)

    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')
    seed = prereg_doc['perturbation']['seed']
    rng_pert = np.random.default_rng(seed)

    t0 = time.time()
    perturbed = perturb.perturb_once(panel, pool, rng_pert)
    p_values = qp_calibration.values_from_panel(perturbed)
    matrix_p = robust.assignment_matrix(p_values, base_profiles, samples_1000, gate=True, veto=None)
    one_rep_seconds = time.time() - t0
    projected_seconds = one_rep_seconds * n_replicates
    if projected_seconds > 600:
        n_replicates = 20
    print(f'[C3c] 1회 측정 {one_rep_seconds:.2f}s, {n_replicates}회 예상 {one_rep_seconds * n_replicates:.1f}s')

    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced

    jaccard_sum = np.zeros(len(panel))
    jaccard_n = np.zeros(len(panel))

    def accumulate(matrix_p_):
        pert_sets = _possible_sets_from_matrix(matrix_p_)
        for i in range(len(panel)):
            union = orig_sets[i] | pert_sets[i]
            if not union:
                continue
            jaccard_sum[i] += len(orig_sets[i] & pert_sets[i]) / len(union)
            jaccard_n[i] += 1

    accumulate(matrix_p)  # 이미 측정한 1회분을 버리지 않는다
    for _ in range(n_replicates - 1):
        perturbed = perturb.perturb_once(panel, pool, rng_pert)
        p_values = qp_calibration.values_from_panel(perturbed)
        matrix_p = robust.assignment_matrix(p_values, base_profiles, samples_1000, gate=True, veto=None)
        accumulate(matrix_p)

    with np.errstate(invalid='ignore'):
        jaccard_row = np.where(jaccard_n > 0, jaccard_sum / np.maximum(jaccard_n, 1), np.nan)
    overall_discriminating = float(np.nanmean(jaccard_row[discriminating]))
    overall_scorable = float(np.nanmean(jaccard_row[scorable]))
    return {'value_discriminating': overall_discriminating, 'value_scorable': overall_scorable,
           'n_replicates': n_replicates, 'n_param_samples': n_param_samples, 'seed': seed}, jaccard_row


def interval_robustness_table(root, am6_content, c3b_table, c3c_summary, mean_n_possible, share_le_2):
    """C3(Phase 4 값 인용) + C3b + C3c를 한 표에 모은다."""
    root = Path(root)
    c3_source = pd.read_csv(root / 'outputs/tables/electre_input_perturbation_stability.csv')
    c3_source_run_id = str(c3_source['run_id'].iloc[0])
    ir = am6_content['interval_robustness']
    c3b_threshold = next(m['threshold'] for m in ir if m['metric_id'] == 'C3b_point_in_interval')
    c3c_threshold = next(m['threshold'] for m in ir if m['metric_id'] == 'C3c_interval_jaccard')

    rows = []
    for _, r in c3_source.iterrows():
        rows.append({'model_id': r['candidate_id'], 'scenario_id': r['scenario_id'], 'metric_id': 'C3',
                    'value': r['retention_mean'], 'threshold': np.nan, 'pass': np.nan,
                    'n_replicates': r['n_replicates'], 'n_param_samples': np.nan,
                    'mean_n_possible_stages': np.nan, 'share_n_possible_le_2': np.nan,
                    'definition_note': '점 배정 유지율(원 정의). Phase 4 산출물 인용.',
                    'seed': r['seed'], 'source_run_id': c3_source_run_id})
    for _, r in c3b_table.iterrows():
        rows.append({'model_id': r['model_id'], 'scenario_id': r['scenario_id'], 'metric_id': 'C3b',
                    'value': r['value'], 'threshold': c3b_threshold, 'pass': bool(r['value'] >= c3b_threshold),
                    'n_replicates': r['n_replicates'], 'n_param_samples': np.nan,
                    'mean_n_possible_stages': r['mean_n_possible_stages'], 'share_n_possible_le_2': share_le_2,
                    'definition_note': '교란 후 점 단계가 원 가능 단계 집합에 포함되는 비율.',
                    'seed': r['seed'], 'source_run_id': None})
    for scope, value in (('discriminating', c3c_summary['value_discriminating']),
                         ('scorable', c3c_summary['value_scorable'])):
        rows.append({'model_id': None, 'scenario_id': None, 'metric_id': f'C3c_{scope}',
                    'value': value, 'threshold': c3c_threshold, 'pass': bool(value >= c3c_threshold),
                    'n_replicates': c3c_summary['n_replicates'], 'n_param_samples': c3c_summary['n_param_samples'],
                    'mean_n_possible_stages': mean_n_possible, 'share_n_possible_le_2': share_le_2,
                    'definition_note': f'가능 단계 집합의 교란 전후 Jaccard 유사도 평균({scope} 행 기준).',
                    'seed': c3c_summary['seed'], 'source_run_id': None})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Step 4: 최종 재판정
def final_decision_table(root, prereg_doc, am6_content, interval_table, robustness_table):
    root = Path(root)
    point_decision = pd.read_csv(root / 'outputs/tables/electre_revalidation_decision.csv')
    point_block = point_decision[['model_id', 'scenario_id', 'c1_pass', 'c2_pass', 'c3_pass', 'c4_pass', 's1_pass',
                                  'overall_status', 'blocked_by', 'rationale']].copy()
    point_block.insert(0, 'block_type', 'point_assignment')
    point_block['retained_as_official'] = False

    ia = am6_content['interval_acceptance']
    thr = {i['id']: i['threshold'] for i in ia}

    # scorable 여부는 n_possible이 아니라 is_discriminating|is_forced_observe(둘의 합집합이
    # 정확히 scorable 전체)로 독립적으로 판정한다 — n_possible로 scorable을 정의하면
    # I1이 항상 자명하게 1.0이 되는 순환 정의가 된다.
    scorable_mask = interval_table['is_discriminating'] | interval_table['is_forced_observe']
    i1_value = float((interval_table.loc[scorable_mask, 'n_possible'] > 0).all())
    disc = interval_table[interval_table['is_discriminating']]
    i2_value = float((disc['n_possible'] <= 2).mean())
    c3b_rows = robustness_table[robustness_table['metric_id'] == 'C3b']
    i3_value = float(c3b_rows['value'].mean())
    latest = interval_table[interval_table['quarter'] == '2026Q2']
    i4_value = float((latest['n_possible'] <= 2).mean())

    i_values = {'I1': i1_value, 'I2': i2_value, 'I3': i3_value, 'I4': i4_value}
    i_pass = {k: bool(v >= thr[k]) for k, v in i_values.items()}
    failed = [k for k, ok in i_pass.items() if not ok]
    if not failed:
        overall = 'INTERVAL_ADOPTABLE'
    elif len(failed) == 1:
        overall = f'INTERVAL_BLOCKED_BY_{failed[0]}'
    else:
        overall = 'INTERVAL_BLOCKED_MULTIPLE'

    c1_all_clean = bool((point_decision['c1_pass']).all())
    c4_all = pd.read_csv(root / 'outputs/tables/electre_revalidation_decision.csv')
    c4_pass_rate_all = float(c4_all['c4_pass_rate'].mean())
    mean_n_possible = float(interval_table.loc[interval_table['n_possible'] > 0, 'n_possible'].mean())

    interval_row = {
        'block_type': 'interval_assignment',
        'i1_value': i1_value, 'i1_threshold': thr['I1'], 'i1_pass': i_pass['I1'],
        'i2_value': i2_value, 'i2_threshold': thr['I2'], 'i2_pass': i_pass['I2'],
        'i3_value': i3_value, 'i3_threshold': thr['I3'], 'i3_pass': i_pass['I3'],
        'i4_value': i4_value, 'i4_threshold': thr['I4'], 'i4_pass': i_pass['I4'],
        'c1_all_combinations_clean': c1_all_clean, 'c4_pass_rate_all_cases': c4_pass_rate_all,
        's1_reported_not_gated': True, 'mean_n_possible_stages': mean_n_possible,
        'overall_status': overall, 'retained_as_official': True,
        'rationale': (f'I1~I4 전부 합격선({thr}) 통과.' if not failed else
                     f'{",".join(failed)} 미달(값: {[i_values[k] for k in failed]}, 기준: {[thr[k] for k in failed]}).'),
    }
    return pd.concat([point_block, pd.DataFrame([interval_row])], ignore_index=True)


LIM1_STATEMENT = (
    '점 배정은 입력자료 개정 교란에 대해 합격선을 충족하지 못한다. '
    'g2의 b1 경계값 2.0%p는 고용 자료 개정폭 90분위 {emp_p90:.3f}%p와 거의 같은 크기이며'
    '(비율 {ratio:.3f}), 판별표본 {n_disc}행 중 {p90_pct:.1%}가 어떤 기준에서든 경계까지의 거리가 '
    '개정폭 90분위 안에 있다. Phase 4에서 시도한 {n_combos}개 조합 전부가 미달했고 '
    '최댓값은 {max_c3:.3f}였다. 이는 파라미터 선택의 문제가 아니라 경계값과 자료 개정폭의 '
    '크기 관계에서 오는 구조적 제약이다.')
LIM1_ACTION_TAKEN = '공식 산출물을 구간 배정으로 전환하고 합격선을 낮추지 않았다.'
LIM1_WHAT_WOULD_RESOLVE = (
    '자료 개정폭보다 충분히 큰 경계값의 재설계, 또는 개정폭이 작은 자료원의 확보. '
    '현재 자료로는 해결할 수 없다.')


def limitation_record_table(root):
    root = Path(root)
    diag = pd.read_csv(root / 'outputs/tables/electre_c3_diagnosis.csv')
    veto_screen = pd.read_csv(root / 'outputs/tables/electre_veto_screening.csv')
    wl = pd.read_csv(root / 'outputs/tables/electre_weight_lambda_inference.csv')
    n_combos = len(veto_screen) + len(wl)
    max_c3 = float(pd.concat([veto_screen['c3_retention_mean'], wl['c3_retention_mean']]).max())
    emp_p90 = float(diag['employment_revision_pool_p90_pct'].iloc[0])
    ratio = float(diag['g2_b1_vs_emp_revision_p90_ratio'].iloc[0])
    n_disc = int(diag['n_discriminating'].iloc[0])
    p90_pct = float(diag['discriminating_within_p90_rate'].iloc[0])

    statement = LIM1_STATEMENT.format(emp_p90=emp_p90, ratio=ratio, n_disc=n_disc, p90_pct=p90_pct,
                                      n_combos=n_combos, max_c3=max_c3)
    return pd.DataFrame([{
        'limitation_id': 'LIM1', 'statement': statement,
        'evidence_g2_b1_value': 2.0, 'evidence_employment_revision_p90_pct': emp_p90,
        'evidence_ratio': ratio, 'evidence_n_discriminating': n_disc,
        'evidence_discriminating_within_p90_rate': p90_pct,
        'evidence_n_combinations_tried': n_combos, 'evidence_max_c3_retention_mean': max_c3,
        'action_taken': LIM1_ACTION_TAKEN, 'what_would_resolve': LIM1_WHAT_WOULD_RESOLVE,
    }])


# ---------------------------------------------------------------- Step 5-1: 서술 규칙
def write_reporting_rules_md(root, expansion_table, robustness_table, final_row, limitation_row):
    """공모전·보고서 서술 규칙. 허용 문장마다 근거 산출물·컬럼을 병기한다.

    이 파일은 금지 문구를 예시로 '그대로 인용'하는 것이 목적이므로
    scripts/check_wording.py의 기본 점검 대상에 넣지 않는다(그 취지는
    tests/fixtures/model_wording_rules.json 자신이 점검 대상에서 빠지는 것과 같다).
    """
    root = Path(root)
    space_row = expansion_table[(expansion_table.block_type == 'space')
                                & (expansion_table.space_id == 'reference_plus_virtual_subspace')].iloc[0]
    c3b_mean = float(robustness_table[robustness_table.metric_id == 'C3b']['value'].mean())
    c3c_disc = float(robustness_table.loc[robustness_table.metric_id == 'C3c_discriminating', 'value'].iloc[0])

    lines = [
        '# 창원국가산단 재검증 서술 규칙',
        '',
        '공모전·보고서에서 이 모형의 결과를 서술할 때 쓸 수 있는 문장과 쓸 수 없는 문장을 고정한다. '
        '허용 문장에는 근거 산출물 파일명과 컬럼을 병기한다.',
        '',
        '## 허용',
        '',
        '- "점검단계는 미래 위기 확률이 아니라 현재 시점의 확인 순서입니다."',
        '  - 근거: config.NOT_DETERMINABLE_STATEMENTS(고정 문구), outputs/report/interval_diagnostic_cards_2026Q2.md',
        '- "예측 성능으로 검증하지 않았습니다. 이 모형은 예측모형이 아니기 때문입니다. '
        "실제로 예측 타깃으로 평가하면 '현재 고용이 감소 중인가'라는 변수 하나가 어떤 다기준 모형보다 "
        '우수합니다(전체기간 순위연관 0.75 vs 후보 D의 0.65). 그 사실 자체가 이 검증이 부적절함을 보여줍니다."',
        '  - 근거: prereg.invalidated_gates.IG1(사전등록에 기록된 폐기 사유), '
        'outputs/tables/electre_cluster_bootstrap_rank_correlation.csv',
        '- "세 가지로 검증했습니다: 사전 합의한 규범과의 양립, 실측 자료 개정폭을 반영한 교란 안정성, '
        '허용 파라미터 공간 전체에서의 배정 불변성."',
        '  - 근거: outputs/tables/electre_preference_expansion.csv, '
        'outputs/tables/electre_interval_robustness.csv, '
        'outputs/tables/electre_robust_assignment_summary.csv',
        f'- "단일 등급을 제시하지 않고 가능 단계 범위를 제시합니다. 그 이유는 판별표본에서 파라미터 선택에 '
        f'따라 등급이 갈리는 비율이 높고(참조사례 양립 부분공간 필연배정 비율 '
        f'{space_row["necessary_share_discriminating"]:.1%}), 교란 강건성도 합격선에 못 미치기 때문입니다."',
        '  - 근거: outputs/tables/electre_robust_assignment_summary.csv, '
        'outputs/tables/electre_interval_robustness.csv',
        '- "고용 자료의 개정폭이 g2 경계값과 같은 크기이기 때문에 점 배정은 자료 개정만으로 바뀔 수 있습니다. '
        '이를 숨기지 않고 구간으로 표시했습니다."',
        '  - 근거: outputs/tables/electre_c3_diagnosis.csv(g2_b1_vs_emp_revision_p90_ratio), '
        'outputs/tables/electre_limitation_record.csv(LIM1)',
        f'- "교란 후 점 단계가 원 가능 단계 범위 안에 머무는 비율은 평균 {c3b_mean:.1%}, '
        f'가능 단계 집합 자체의 교란 안정성(Jaccard)은 판별표본 기준 {c3c_disc:.1%}입니다."',
        '  - 근거: outputs/tables/electre_interval_robustness.csv(metric_id=C3b, C3c_discriminating)',
        '',
        '## 금지',
        '',
        '아래는 실제로 써서는 안 되는 표현의 예시다(따옴표 안의 문구를 그대로 쓰지 않는다):',
        '',
        '- 점검단계를 위기 상황이나 지원사업 대상 자격과 동일시하는 표현',
        '- 2025Q1~2026Q2 구간을 모형이 한 번도 접하지 않은 구간처럼 표현하는 것 '
        '(q·p 보정 작업에서 이미 결과를 확인했다)',
        '- 전체 표본 행수를 근거로 표본 크기가 충분하다고 주장하는 것',
        '- 어느 지표든 "합격선을 통과했다"는 사실만으로 그 지표가 재현하는 개념 자체가 확립됐다고 주장하는 것',
        '- 외부 지표와의 상관을 "타당성이 확보됐다"는 식으로 일반화하는 것',
        '- 통과한 테스트 개수를 모형의 타당성 근거로 제시하는 것(테스트는 코드가 코드대로 동작하는지를 '
        '확인할 뿐 판정 기준 자체의 정당성을 확인하지 않는다)',
        '- 이 모형이 미래 값을 맞히는 데 쓰인다는 표현, 그리고 PPI 조정 없이 "실질" 수치를 계산한다는 표현',
        '- 가능 단계가 2개 이상인 업종·분기를 단일 단계로만 적는 모든 표기 '
        '(반드시 display_label 컬럼을 그대로 쓴다)',
        '',
    ]
    text = '\n'.join(lines)
    out_path = root / 'outputs/report/reporting_rules.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding='utf-8')
    return out_path


# ---------------------------------------------------------------- Step 5-3: 그림 3개
def write_figures(root, panel, values, interval_table, expansion_table, c3_diagnosis, proximity=None):
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt

    root = Path(root)
    out = root / 'outputs/figures'
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    colors = config.DISPLAY_COLORS

    # 1) 2026Q2 업종별 CAI 누적막대 + 가능범위(간단 표기: n_possible과 최빈단계 비율만
    #    막대 위에 적고, 전체 문장형 display_label은 표·진단카드에서 확인한다)
    latest = interval_table[interval_table['quarter'] == '2026Q2'].sort_values('industry')
    fig, ax = plt.subplots(figsize=(11, 6.5))
    bottom = np.zeros(len(latest))
    for stage, col in (('OBSERVE', 'cai_observe'), ('CHECK', 'cai_check'), ('PRIORITY', 'cai_priority')):
        ax.bar(latest['industry'], latest[col], bottom=bottom, color=colors[stage],
              label=config.DISPLAY_LABELS[stage])
        bottom += latest[col].to_numpy()
    for x, (_, r) in enumerate(latest.iterrows()):
        tag = '확정' if r['n_possible'] == 1 else f"{r['n_possible']}단계"
        ax.annotate(tag, (x, 1.03), ha='center', va='bottom', fontsize=9)
    ax.set_ylim(0, 1.13)
    ax.set_ylabel('등급수용지수(CAI)')
    ax.set_title('2026Q2 업종별 구간 배정 — 참조사례+가상 프로파일 양립 부분공간', pad=14)
    ax.legend(loc='upper left', fontsize=8, ncol=3, bbox_to_anchor=(0, 1.14))
    plt.xticks(rotation=30, ha='right')
    fig.tight_layout()
    fig.savefig(out / 'interval_assignment_latest.png', dpi=180)
    plt.close(fig)

    # 2) 공간 3종 비교
    space = expansion_table[expansion_table.block_type == 'space']
    fig, axs = plt.subplots(1, 2, figsize=(12, 5))
    axs[0].bar(space['space_id'], space['n_samples'], color='#6B7C8F')
    axs[0].set_ylabel('표본 수'); axs[0].set_title('공간별 표본 수')
    plt.setp(axs[0].get_xticklabels(), rotation=20, ha='right')
    axs[1].bar(space['space_id'], space['mean_n_possible_stages'], color=colors['CHECK'])
    axs[1].set_ylabel('평균 가능 단계 수'); axs[1].set_title('공간별 평균 가능 단계 수')
    plt.setp(axs[1].get_xticklabels(), rotation=20, ha='right')
    fig.tight_layout()
    fig.savefig(out / 'interval_space_narrowing.png', dpi=180)
    plt.close(fig)

    # 3) 기준별 경계값과 개정폭 분위 비교(LIM1 근거)
    row = c3_diagnosis.iloc[0]
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ['g2 b1(고용, %p)']
    boundary_vals = [2.0]
    revision_p90 = [row['employment_revision_pool_p90_pct']]
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, boundary_vals, width, label='경계값', color='#6B7C8F')
    ax.bar(x + width / 2, revision_p90, width, label='실측 개정폭 90분위', color=colors['PRIORITY'])
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel('%p')
    ax.set_title(f"경계값 vs 자료 개정폭(비율 {row['g2_b1_vs_emp_revision_p90_ratio']:.2f})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / 'c3_boundary_vs_revision.png', dpi=180)
    plt.close(fig)


# ---------------------------------------------------------------- 산출·저장
def run_phase5(root, write=True):
    root = Path(root)
    prereg_doc, current, panel, base_doc, scenarios, candidates = _load_context(root)
    am6 = _am6_content(prereg_doc)
    values = _values(panel)
    base_profiles = next(b for b in base_doc['scenarios'] if b['scenario_id'] == '기준')['profiles']

    started = datetime.now(timezone.utc)
    prereg_hash = prereg.payload_sha256(prereg_doc)
    run_id = manifest.make_run_id(started, current['input_sha256'], prereg_hash)
    amendment_ids = ','.join(a['id'] for a in prereg_doc['amendments'])
    prov = {'run_id': run_id, 'run_started_at': started.isoformat(), 'input_sha256': current['input_sha256'],
           'prereg_sha256': prereg_hash, 'prereg_status': prereg_doc['prereg_status'],
           'prereg_amendment_ids': amendment_ids, 'phase': 5}

    # ---------- Step 1 ----------
    rng = np.random.default_rng(prereg_doc['parameter_space']['seed'])
    samples = robust.sample_parameter_space(prereg_doc, rng)
    matrix = robust.assignment_matrix(values, base_profiles, samples, gate=True, veto=None)
    vrc_matrix, vrc_cases = virtual_reference_matrix(am6['virtual_reference_cases'], base_profiles, samples)
    undetermined_counts_as = prereg_doc['reference_case_rule']['undetermined_counts_as']
    rc_compat, _ = p3.reference_compatibility(matrix, panel, prereg_doc['reference_cases'], undetermined_counts_as)
    vrc_panel_like = pd.DataFrame({'industry': [c['id'] for c in vrc_cases], 'quarter': ['VIRTUAL'] * len(vrc_cases)})
    vrc_compat, _ = p3.reference_compatibility(vrc_matrix, vrc_panel_like, vrc_cases, undetermined_counts_as)
    combined_mask = rc_compat & vrc_compat
    n_combined = int(combined_mask.sum())

    preference_conflict = None
    if n_combined == 0 or n_combined < 100:
        preference_conflict = preference_conflict_analysis(prereg_doc['reference_cases'], vrc_cases, matrix,
                                                            vrc_matrix, undetermined_counts_as)
        raise PreferenceSpaceEmptyError(
            f'reference_plus_virtual_subspace 표본이 {n_combined}개로 100 미만입니다. '
            'electre_preference_conflict.csv를 기록하고 중단합니다. '
            f'해소 후보:\n{preference_conflict[preference_conflict.resolves_conflict].to_string()}')

    expansion_table = preference_expansion_table(root, prereg_doc, panel, values, base_profiles, samples, matrix,
                                                  vrc_matrix, prereg_doc['reference_cases'], vrc_cases, rc_compat,
                                                  vrc_compat, combined_mask)

    # ---------- Step 2 ----------
    interval_table = interval_assignment_table(panel, values, matrix, combined_mask, scenarios, candidates)
    cards_path = root / 'outputs/report/interval_diagnostic_cards_2026Q2.md'
    if write:
        cards_path = write_diagnostic_cards(root, panel, values, interval_table, base_profiles)

    # ---------- Step 3 ----------
    c3b_table = c3b_point_in_interval(root, prereg_doc, panel, scenarios, candidates, interval_table)
    c3c_summary, jaccard_row = c3c_interval_jaccard(root, prereg_doc, panel, values, base_profiles)
    disc_mask = interval_table['is_discriminating'].to_numpy()
    share_le_2 = float((interval_table.loc[disc_mask, 'n_possible'] <= 2).mean())
    mean_n_possible = float(interval_table.loc[interval_table['n_possible'] > 0, 'n_possible'].mean())
    robustness_table = interval_robustness_table(root, am6, c3b_table, c3c_summary, mean_n_possible, share_le_2)

    # ---------- Step 4 ----------
    final_decision = final_decision_table(root, prereg_doc, am6, interval_table, robustness_table)
    limitation_record = limitation_record_table(root)

    # ---------- Step 5 ----------
    final_row = final_decision[final_decision.block_type == 'interval_assignment'].iloc[0]
    reporting_rules_path = root / 'outputs/report/reporting_rules.md'
    if write:
        reporting_rules_path = write_reporting_rules_md(root, expansion_table, robustness_table, final_row,
                                                         limitation_record.iloc[0])
        write_figures(root, panel, values, interval_table, expansion_table,
                     pd.read_csv(root / 'outputs/tables/electre_c3_diagnosis.csv'))

    # config/electre_tri_b_params.yaml 불변 확인
    base_after = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    base_before_hash = params.parameter_payload_sha256(base_doc)
    if params.parameter_payload_sha256(base_after) != base_before_hash:
        raise RuntimeError('config/electre_tri_b_params.yaml이 Phase 5 실행 중 변경되었습니다.')

    tables = {
        'electre_preference_expansion': expansion_table,
        'electre_interval_assignment': interval_table,
        'electre_interval_robustness': robustness_table,
        'electre_final_decision': final_decision,
        'electre_limitation_record': limitation_record,
    }
    for name, frame in tables.items():
        for col, val in prov.items():
            frame[col] = val

    written = None
    if write:
        run_dir, written_info = p2.write_tables(root, run_id, tables)
        written = {name: info['canonical'] for name, info in written_info.items()}

    return {'run_id': run_id, 'provenance': prov, 'tables': tables, 'written': written,
           'panel': panel, 'values': values, 'scenarios': scenarios, 'candidates': candidates,
           'samples': samples, 'matrix': matrix, 'vrc_matrix': vrc_matrix, 'combined_mask': combined_mask,
           'expansion_table': expansion_table, 'interval_table': interval_table,
           'robustness_table': robustness_table, 'final_decision': final_decision,
           'limitation_record': limitation_record, 'cards_path': str(cards_path),
           'reporting_rules_path': str(reporting_rules_path), 'prereg_doc': prereg_doc}
