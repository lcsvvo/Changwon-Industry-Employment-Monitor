# -*- coding: utf-8 -*-
"""Phase 6: 최종 검증·기록·제출물. 모형·합격선·가상 참조사례를 바꾸지 않는다.

VRC4 의존성을 최우선으로 검증하고(근거 수집은 사람이 판단할 자료만 모은다),
I3 미달의 구조를 기록하고, 전체 이력 문서와 공모전 수치 세트를 만든다.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import config, electre, manifest, params, perturb, prereg, qp_calibration, resample, robust
from . import revalidation as p2
from . import revalidation_phase3 as p3
from . import revalidation_phase4 as p4
from . import revalidation_phase5 as p5

MODEL_IDS = p4.MODEL_IDS
SCENARIO_IDS = p4.SCENARIO_IDS
VRC4_KEYWORDS = ('지속', '기간', '연속', 'Q3', '시간')
VRC4_SOURCE_FILES = (
    'docs/01_planning/methodology/창원국가산단_산업고용전환진단_방법론및EDA계획.md',
    'docs/01_planning/최종 기획안(0909).txt',
    'docs/01_planning/수정 기획안(0907).txt',
    'README.md',
)


class Phase6GateError(RuntimeError):
    """Phase 6 착수 게이트를 통과하지 못했을 때."""


# ---------------------------------------------------------------- 착수 게이트
def check_gate(root):
    root = Path(root)
    doc = prereg.load(root / 'config/model_revalidation_prereg.yaml')
    try:
        prereg.require_registered(doc)
    except prereg.PreregNotRegisteredError:
        raise Phase6GateError('사전등록이 완료되지 않아 Phase 6를 실행할 수 없습니다')
    amendment_ids = [a['id'] for a in doc['amendments']]
    if len(amendment_ids) != 6 or amendment_ids[-1] != 'AM6':
        raise Phase6GateError(f'amendments가 6건(AM1~AM6)이어야 합니다: {amendment_ids}')
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


# ---------------------------------------------------------------- Step 1-1: 근거 문단 수집
def extract_provenance_paragraphs(root, files=VRC4_SOURCE_FILES, keywords=VRC4_KEYWORDS):
    """문단(빈 줄로 구분) 단위로 키워드 포함 여부만 수집한다. 판정하지 않는다."""
    root = Path(root)
    rows = []
    for relpath in files:
        path = root / relpath
        if not path.is_file():
            rows.append({'source_file': relpath, 'line_start': None, 'line_end': None,
                        'matched_keyword': None, 'excerpt': '(파일을 찾을 수 없음)',
                        'supports_independent_duration_criterion': None})
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        lines = text.split('\n')
        paragraphs, buf, start = [], [], None
        for i, line in enumerate(lines, start=1):
            if line.strip() == '':
                if buf:
                    paragraphs.append((start, i - 1, '\n'.join(buf)))
                    buf, start = [], None
                continue
            if start is None:
                start = i
            buf.append(line)
        if buf:
            paragraphs.append((start, len(lines), '\n'.join(buf)))
        for start_l, end_l, para in paragraphs:
            matched = [k for k in keywords if k in para]
            if matched:
                rows.append({'source_file': relpath, 'line_start': start_l, 'line_end': end_l,
                            'matched_keyword': ','.join(matched), 'excerpt': para[:500],
                            'supports_independent_duration_criterion': None})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Step 1-2/1-3 공통 재료
def _regenerate_space(prereg_doc, panel, values, base_profiles, exclude_vrc_ids=()):
    """전체 표본·행렬·RC/VRC 양립 마스크를 재생성한다(공식 seed 그대로).
    exclude_vrc_ids에 있는 VRC는 결합 판정에서 제외한다(선호정보 자체를 지우지 않고
    민감도 계산에서만 제외 — prereg의 virtual_reference_cases는 그대로 둔다).
    """
    rng = np.random.default_rng(prereg_doc['parameter_space']['seed'])
    samples = robust.sample_parameter_space(prereg_doc, rng)
    matrix = robust.assignment_matrix(values, base_profiles, samples, gate=True, veto=None)
    am6 = _am6_content(prereg_doc)
    vrc_matrix, vrc_cases = p5.virtual_reference_matrix(am6['virtual_reference_cases'], base_profiles, samples)
    undetermined_counts_as = prereg_doc['reference_case_rule']['undetermined_counts_as']
    rc_compat, _ = p3.reference_compatibility(matrix, panel, prereg_doc['reference_cases'], undetermined_counts_as)

    keep_idx = [i for i, c in enumerate(vrc_cases) if c['id'] not in exclude_vrc_ids]
    vrc_cases_kept = [vrc_cases[i] for i in keep_idx]
    vrc_matrix_kept = vrc_matrix[:, keep_idx]
    vrc_panel_like = pd.DataFrame({'industry': [c['id'] for c in vrc_cases_kept],
                                   'quarter': ['VIRTUAL'] * len(vrc_cases_kept)})
    vrc_compat, _ = p3.reference_compatibility(vrc_matrix_kept, vrc_panel_like, vrc_cases_kept,
                                               undetermined_counts_as)
    combined_mask = rc_compat & vrc_compat
    return {'samples': samples, 'matrix': matrix, 'vrc_matrix': vrc_matrix, 'vrc_cases': vrc_cases,
           'rc_compat': rc_compat, 'vrc_compat': vrc_compat, 'combined_mask': combined_mask}


def _full_metrics(root, prereg_doc, panel, values, base_profiles, scenarios, candidates, space, label):
    """공간 하나에 대해 Phase 5와 동일한 지표 세트를 계산한다(I1~I4, C3b, mean_n_possible 등)."""
    matrix, combined_mask = space['matrix'], space['combined_mask']
    interval_table = p5.interval_assignment_table(panel, values, matrix, combined_mask, scenarios, candidates)
    scorable_mask = interval_table['is_discriminating'] | interval_table['is_forced_observe']
    i1 = float((interval_table.loc[scorable_mask, 'n_possible'] > 0).all())
    disc = interval_table[interval_table['is_discriminating']]
    i2 = float((disc['n_possible'] <= 2).mean())
    latest = interval_table[interval_table['quarter'] == '2026Q2']
    i4 = float((latest['n_possible'] <= 2).mean())
    mean_np = float(interval_table.loc[interval_table['n_possible'] > 0, 'n_possible'].mean())
    share_le2_all = float((interval_table.loc[interval_table['n_possible'] > 0, 'n_possible'] <= 2).mean())

    c3b_table = p5.c3b_point_in_interval(root, prereg_doc, panel, scenarios, candidates, interval_table)
    i3 = float(c3b_table['value'].mean())

    n_confirmed_2026q2 = int((latest['n_possible'] == 1).sum())
    return {
        'label': label, 'n_samples': int(combined_mask.sum()),
        'necessary_share_discriminating': float(disc['n_possible'].eq(1).mean()),
        'mean_n_possible_stages': mean_np, 'share_n_possible_le_2': share_le2_all,
        'i1': i1, 'i2': i2, 'i3': i3, 'i4': i4,
        'n_industries_확정_2026Q2': n_confirmed_2026q2,
    }, interval_table, c3b_table


# ---------------------------------------------------------------- Step 1-2: VRC4 제외 민감도
def vrc4_sensitivity_table(root, prereg_doc, panel, values, base_profiles, scenarios, candidates,
                           space_with, space_without, c3c_summary):
    root = Path(root)
    metrics_with, interval_with, _ = _full_metrics(root, prereg_doc, panel, values, base_profiles,
                                                    scenarios, candidates, space_with, 'with_vrc4')
    metrics_without, interval_without, _ = _full_metrics(root, prereg_doc, panel, values, base_profiles,
                                                          scenarios, candidates, space_without, 'without_vrc4')

    latest_with = interval_with[interval_with['quarter'] == '2026Q2'].set_index('industry')['display_label']
    latest_without = interval_without[interval_without['quarter'] == '2026Q2'].set_index('industry')['display_label']
    changes = {ind: {'with_vrc4': latest_with[ind], 'without_vrc4': latest_without[ind]}
              for ind in latest_with.index if latest_with[ind] != latest_without[ind]}

    rows = []
    for label, metrics in (('with_vrc4', metrics_with), ('without_vrc4', metrics_without)):
        rows.append({
            'variant': label, 'n_samples': metrics['n_samples'],
            'necessary_share_discriminating': metrics['necessary_share_discriminating'],
            'mean_n_possible_stages': metrics['mean_n_possible_stages'],
            'share_n_possible_le_2': metrics['share_n_possible_le_2'],
            'i1': metrics['i1'], 'i2': metrics['i2'], 'i3': metrics['i3'], 'i4': metrics['i4'],
            'c3b': metrics['i3'], 'c3c_discriminating': c3c_summary['value_discriminating'],
            'c3c_scorable': c3c_summary['value_scorable'],
            'n_industries_확정_2026Q2': metrics['n_industries_확정_2026Q2'],
            'display_label_changes_2026Q2': json.dumps(changes, ensure_ascii=False, sort_keys=True),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Step 1-3: 배제 영역 특성화
def vrc4_excluded_region_table(prereg_doc, base_doc, samples, vrc_matrix, vrc_cases):
    idx4 = [c['id'] for c in vrc_cases].index('VRC4')
    col = vrc_matrix[:, idx4]
    RANK = {'OBSERVE': 0, 'CHECK': 1, 'PRIORITY': 2}
    pass_actual = (col != -1) & (col >= RANK['CHECK'])
    lam = np.array([s['lambda'] for s in samples])
    sum_w = np.array([s['weights']['g2'] + s['weights']['g4'] for s in samples])
    pass_analytic = sum_w >= lam - 1e-9
    verified = bool(np.array_equal(pass_actual, pass_analytic))

    rows = [{
        'constraint_form': 'w_g2 + w_g4 >= lambda', 'verified_analytically': verified,
        'scenario_id': None, 'w_g2': None, 'w_g4': None, 'sum': None, 'lambda': None,
        'satisfies_vrc4': None,
        'note': (f'g2=2.0(=b1_g2)·g4=4(>=b2_g4)는 q,p 범위 전체에서 부분concordance가 '
                f'항상 정확히 1이 되도록 설계된 경계값이라, VRC4(at_least CHECK)의 b1 통과 여부가 '
                f'q,p와 무관하게 w_g2+w_g4>=λ로 정확히 환원된다. 표본 {len(samples)}개 전부에서 '
                f'실제 판정과 분석식이 일치({verified}).'),
    }]
    for block in base_doc['scenarios']:
        w_g2, w_g4, lam_s = block['weights']['g2'], block['weights']['g4'], block['lambda']
        rows.append({'constraint_form': 'w_g2 + w_g4 >= lambda', 'verified_analytically': verified,
                    'scenario_id': block['scenario_id'], 'w_g2': w_g2, 'w_g4': w_g4,
                    'sum': w_g2 + w_g4, 'lambda': lam_s, 'satisfies_vrc4': bool(w_g2 + w_g4 >= lam_s - 1e-9),
                    'note': f"사전등록 시나리오({block['scenario_id']})"})
    w_inferred = {'g1': 0.30, 'g2': 0.30, 'g3': 0.20, 'g4': 0.20}
    lam_w_inferred = 0.50
    rows.append({'constraint_form': 'w_g2 + w_g4 >= lambda', 'verified_analytically': verified,
                'scenario_id': 'W_inferred', 'w_g2': w_inferred['g2'], 'w_g4': w_inferred['g4'],
                'sum': w_inferred['g2'] + w_inferred['g4'], 'lambda': lam_w_inferred,
                'satisfies_vrc4': bool(w_inferred['g2'] + w_inferred['g4'] >= lam_w_inferred - 1e-9),
                'note': 'Phase 4 Step 2(b) 최대잉여법 이산화 결과(λ=0.50 고정)'})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Step 2-1: I2-I3 상충 곡선
STAGE_CODE = robust.STAGE_CODE


def _perturbation_replicate_cache(root, prereg_doc, panel, scenarios, candidates, n=None, seed=None):
    """6조합(모형2×시나리오3)의 교란 점 단계를 int8 코드로 미리 계산해 캐시한다.

    I2-I3 상충 곡선은 부분공간(가능 단계 집합)만 25가지로 바꿔가며 같은 교란
    복제본에 대한 포함 여부를 다시 세는 것이므로, 교란 자체(가장 비싼 부분)는
    한 번만 계산해 재사용한다.
    """
    root = Path(root)
    values = p5._values(panel)  # noqa: SLF001
    unc = prereg_doc['perturbation']
    n = unc['n_replicates'] if n is None else n
    seed = unc['seed'] if seed is None else seed
    pool = perturb.revision_pool(root / 'outputs/tables/vintage_수정폭_실측.csv')
    n_rows = len(panel)
    cache = {}
    for model_id in MODEL_IDS:
        cand = candidates[model_id]
        for scenario_id in SCENARIO_IDS:
            s = scenarios[scenario_id]
            base_stage = np.asarray(p5._pessimistic(values, s.weights, s.lam, cand['q'], cand['p']))  # noqa: SLF001
            base_code = np.array([STAGE_CODE[c] for c in base_stage], dtype=np.int8)
            rng = np.random.default_rng(seed)
            reps = np.empty((n, n_rows), dtype=np.int8)
            for k in range(n):
                perturbed = perturb.perturb_once(panel, pool, rng)
                p_values = qp_calibration.values_from_panel(perturbed)
                p_stage = p5._pessimistic(p_values, s.weights, s.lam, cand['q'], cand['p'])  # noqa: SLF001
                reps[k, :] = np.array([STAGE_CODE[c] for c in p_stage], dtype=np.int8)
            cache[(model_id, scenario_id)] = {'base_code': base_code, 'reps': reps}
    return cache


def _c3b_from_cache(cache, possible_code_sets_per_row):
    means = []
    for (_, _), data in cache.items():
        base_code, reps = data['base_code'], data['reps']
        valid = (reps != -1) & (base_code[None, :] != -1)
        contain = np.zeros(reps.shape[1], dtype=np.int64)
        n_valid = valid.sum(axis=0)
        for i in range(reps.shape[1]):
            if n_valid[i] == 0:
                continue
            col_valid = reps[valid[:, i], i]
            allowed = possible_code_sets_per_row[i]
            contain[i] = sum(1 for code in col_valid if code in allowed)
        with np.errstate(invalid='ignore'):
            rate = np.where(n_valid > 0, contain / np.maximum(n_valid, 1), np.nan)
        means.append(float(np.nanmean(rate)))
    return float(np.mean(means))


def _possible_code_sets(matrix_subset, row_keys):
    """행별 CAI>0인 단계 코드 집합(0/1/2)을 int8 행렬에서 직접 뽑는다."""
    sets = []
    for i in range(matrix_subset.shape[1]):
        codes = set(matrix_subset[:, i].tolist())
        codes.discard(-1)
        sets.append(codes)
    return sets


def i2_i3_tradeoff_table(root, prereg_doc, panel, values, base_profiles, matrix, combined_mask, scenarios,
                         candidates, ratios=(1.0, 0.8, 0.6, 0.4, 0.2), n_replicates_each=5):
    root = Path(root)
    row_keys = panel[['industry', 'quarter']].reset_index(drop=True)
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced

    cache = _perturbation_replicate_cache(root, prereg_doc, panel, scenarios, candidates)

    pool_idx = np.nonzero(combined_mask)[0]
    master_rng = np.random.default_rng(prereg_doc['uncertainty_reporting']['seed'])

    rows = []
    for ratio in ratios:
        target_n = max(1, int(round(ratio * len(pool_idx))))
        for rep in range(n_replicates_each):
            chosen = master_rng.choice(pool_idx, size=target_n, replace=False)
            sub_matrix = matrix[chosen, :]
            possible_sets = _possible_code_sets(sub_matrix, row_keys)
            n_possible = np.array([len(s) for s in possible_sets])
            mean_np = float(n_possible[scorable].mean())
            i2 = float((n_possible[discriminating] <= 2).mean())
            i3 = _c3b_from_cache(cache, possible_sets)
            rows.append({'subsample_ratio': ratio, 'replicate': rep, 'n_samples': target_n,
                        'mean_n_possible_stages': mean_np, 'i2_value': i2, 'i3_value': i3})
    table = pd.DataFrame(rows)
    sp = resample.spearman(table['i2_value'], table['i3_value'])
    summary_row = pd.DataFrame([{'subsample_ratio': None, 'replicate': None, 'n_samples': None,
                                 'mean_n_possible_stages': None, 'i2_value': None, 'i3_value': None,
                                 'spearman_i2_i3': sp}])
    table['spearman_i2_i3'] = np.nan
    return pd.concat([table, summary_row], ignore_index=True)


# ---------------------------------------------------------------- Step 2-2: 지표 개념 구분
def robustness_metric_taxonomy_table(root):
    root = Path(root)
    rt = pd.read_csv(root / 'outputs/tables/electre_interval_robustness.csv')
    c3_mean = float(rt.loc[rt.metric_id == 'C3', 'value'].mean())
    c3b_mean = float(rt.loc[rt.metric_id == 'C3b', 'value'].mean())
    c3c_disc = float(rt.loc[rt.metric_id == 'C3c_discriminating', 'value'].iloc[0])
    return pd.DataFrame([
        {'metric_id': 'C3', 'uncertainty_source': '자료 불확실성',
        'definition': '교란 전후 점 배정(비관적 단일 단계)이 동일하게 유지되는 비율',
        'value': c3_mean, 'threshold': 0.95, 'pass': bool(c3_mean >= 0.95),
        'interpretation_limit': '점 배정 자체가 파라미터 선택 하나에 고정된 값이므로, '
                                '이 지표는 그 선택이 자료 개정에 얼마나 취약한지만 말하며 '
                                '파라미터 선택 자체의 타당성은 말하지 않는다.'},
        {'metric_id': 'C3b', 'uncertainty_source': '자료 불확실성 + 파라미터 불확실성(혼합)',
        'definition': '교란된 자료로 계산한 점 단계가 원자료 기준 가능 단계 집합(파라미터 '
                      '공간 전체에서 나온 구간)에 포함되는 비율',
        'value': c3b_mean, 'threshold': 0.95, 'pass': bool(c3b_mean >= 0.95),
        'interpretation_limit': '가능 단계 집합이 넓을수록(파라미터 불확실성이 클수록) 이 값은 '
                                '저절로 높아진다. 그래서 mean_n_possible_stages 없이 이 값만으로는 '
                                '자료 안정성과 집합 자체의 느슨함을 구분할 수 없다.'},
        {'metric_id': 'C3c', 'uncertainty_source': '자료 불확실성(파라미터 공간은 고정 표집)',
        'definition': '자료를 교란한 뒤 가능 단계 집합을 다시 계산해 원 집합과 구하는 '
                      'Jaccard 유사도 평균',
        'value': c3c_disc, 'threshold': 0.90, 'pass': bool(c3c_disc >= 0.90),
        'interpretation_limit': '가능 단계 집합이 자료 교란에 얼마나 안정적인지만 말하며, 그 '
                                '집합이 얼마나 좁은지(정보량)는 말하지 않는다 — 아주 넓은 집합도 '
                                '자료 교란에 안정적일 수 있다.'},
    ])


# ---------------------------------------------------------------- Step 2-3: LIM2 추가
LIM2_STATEMENT = (
    '구간 배정 산출물은 사전등록한 I3(교란 후 점 단계가 가능 단계 집합에 포함되는 비율, '
    '임계 0.95)를 충족하지 못했다(실측 {i3_value:.3f}). I3는 자료 불확실성과 파라미터 불확실성을 '
    '결합한 지표이며, 가능 단계 집합이 좁을수록 값이 낮아지는 구조를 갖는다'
    '(평균 가능 단계 수 {mean_np:.3f}). 두 불확실성을 분리해 자료 교란 하의 가능 집합 안정성만 '
    '측정한 C3c는 판별표본 {c3c_disc:.3f}, 전체 {c3c_all:.3f}로 임계 0.90을 충족했다. '
    '합격선을 낮추지 않았으며 최종 판정은 INTERVAL_BLOCKED_BY_I3로 유지한다.')
LIM2_ACTION_TAKEN = '판정 유지, 지표의 개념 구분을 별도 기록'
LIM2_WHAT_WOULD_RESOLVE = (
    '자료 불확실성과 파라미터 불확실성을 분리해 정의한 지표로 사전등록을 다시 하거나, '
    '개정폭이 작은 자료원을 확보하는 것. 현재 자료와 현재 사전등록으로는 해결할 수 없다.')


def append_lim2(root):
    """electre_limitation_record.csv에 LIM2를 추가한다. LIM1 행은 절대 수정하지 않는다."""
    root = Path(root)
    path = root / 'outputs/tables/electre_limitation_record.csv'
    existing = pd.read_csv(path)
    if 'LIM2' in set(existing.get('limitation_id', [])):
        return existing  # 이미 있으면 다시 붙이지 않는다(멱등)
    lim1_columns = set(existing.columns)

    rt = pd.read_csv(root / 'outputs/tables/electre_interval_robustness.csv')
    fd = pd.read_csv(root / 'outputs/tables/electre_final_decision.csv')
    interval_row = fd[fd.block_type == 'interval_assignment'].iloc[0]
    i3_value = float(interval_row['i3_value'])
    mean_np = float(interval_row['mean_n_possible_stages'])
    c3c_disc = float(rt.loc[rt.metric_id == 'C3c_discriminating', 'value'].iloc[0])
    c3c_all = float(rt.loc[rt.metric_id == 'C3c_scorable', 'value'].iloc[0])

    statement = LIM2_STATEMENT.format(i3_value=i3_value, mean_np=mean_np, c3c_disc=c3c_disc, c3c_all=c3c_all)
    lim2_row = {'limitation_id': 'LIM2', 'statement': statement,
               'action_taken': LIM2_ACTION_TAKEN, 'what_would_resolve': LIM2_WHAT_WOULD_RESOLVE}
    for col in lim1_columns:
        if col not in lim2_row:
            lim2_row[col] = None
    combined = pd.concat([existing, pd.DataFrame([lim2_row])[list(existing.columns)]], ignore_index=True)
    return combined


# ---------------------------------------------------------------- Step 3: 전체 이력 문서
PHASE_HISTORY = (
    {'phase': 0, 'purpose': '기준선 고정 — 재현 앵커 대조, 동결 대상 해시 기록',
    'key_finding': 'v1.0/후보 D 분포·강제 관찰 71행·crisp 불일치 고유조합 1개, 전부 재현 확인',
    'next_decision': 'Phase 1 진행'},
    {'phase': 1, 'purpose': 'electre.py 함수 추가(낙관적 배정·veto) + prereg.py 사전등록 게이트',
    'key_finding': '비관·낙관 배정 v1.0/D 모두 160/160 일치, veto 부등호 오류 발견·수정',
    'next_decision': 'Phase 2 진행'},
    {'phase': 2, 'purpose': '진단 산출물 3종 — 낙관/비관 일치율, 입력교란 유지율, 파라미터공간 필연/가능배정',
    'key_finding': '필연배정 비율 0.0112(전체공간), AM1로 p_upper<=b1 제약 발견',
    'next_decision': 'AM1 개정 후 Phase 2 재실행, Phase 3 진행'},
    {'phase': 3, 'purpose': '검증 설계 교체 — C1~C4·S1 재판정, 기존 next_negative_state 게이트 폐기',
    'key_finding': '6개 model×scenario 조합 모두 BLOCKED_MULTIPLE, C3·S1이 공통 병목',
    'next_decision': 'AM4로 Phase 4 종료규칙 사전확정 후 REGISTERED 전환'},
    {'phase': 4, 'purpose': '모형 변경 시도 — veto 확정(Step1), 가중치·λ 재추론(Step2), C3 원인진단(Step3)',
    'key_finding': '18개 조합 전부 C3 미달(최대 0.935), g2 b1 경계=개정폭 90분위(비율 1.029)',
    'next_decision': 'EX2·EX3 발동 — AM6로 선호정보 확충 후 Phase 5(구간 배정 전환)'},
    {'phase': 5, 'purpose': '공식 산출물을 점 배정에서 구간 배정으로 전환 — I1~I4 재판정',
    'key_finding': '필연배정 0.011→0.517(가상 프로파일 포함), I3(0.893<0.95) 미달로 INTERVAL_BLOCKED_BY_I3',
    'next_decision': 'Phase 6(VRC4 의존성 검증·최종 기록)'},
    {'phase': 6, 'purpose': '최종 검증·기록·제출물 — VRC4 근거 수집, I3 구조 기록, 이력 문서',
    'key_finding': '(이 문서 자체가 결과)', 'next_decision': '사람의 결정 대기'},
)


def write_revalidation_history_md(root, prereg_doc, limitation_record):
    """limitation_record는 호출자가 이미 LIM2까지 붙인 DataFrame을 그대로 넘긴다
    (아직 디스크에 쓰지 않았을 수 있으므로 파일을 다시 읽지 않는다)."""
    root = Path(root)
    ig = {g['id']: g for g in prereg_doc['invalidated_gates']}
    fd = pd.read_csv(root / 'outputs/tables/electre_final_decision.csv')
    interval_row = fd[fd.block_type == 'interval_assignment'].iloc[0]
    lim = limitation_record
    lim1 = lim[lim.limitation_id == 'LIM1'].iloc[0]
    lim2 = lim[lim.limitation_id == 'LIM2'].iloc[0]
    n_outputs = {2: 6, 3: 9, 4: 6, 5: 5, 6: 9}

    lines = ['# 창원국가산단 ELECTRE TRI-B 재검증 전체 이력', '']

    lines += ['## 1. 왜 재검증했는가', '']
    for gid in ('IG1', 'IG2', 'IG3'):
        g = ig[gid]
        lines += [f"**{gid}** — {g['retired']}", '', g['reason'], '']

    lines += ['## 2. Phase 0~6 이력', '', '| Phase | 목적 | 산출물 수 | 주요 발견 | 다음 결정 |',
             '|---|---|---|---|---|']
    for p in PHASE_HISTORY:
        n = n_outputs.get(p['phase'], '-')
        lines.append(f"| {p['phase']} | {p['purpose']} | {n} | {p['key_finding']} | {p['next_decision']} |")
    lines.append('')

    lines += ['## 3. 사전등록 개정 이력', '']
    for a in prereg_doc['amendments']:
        lines += [f"**{a['id']}** (Phase {a['phase_at_amendment']}, "
                 f"등록상태={a['prereg_status_at_amendment']}, "
                 f"결과 인지 전 개정={not a['result_known_before_amendment']})",
                 '', f"- 변경: {a['change']}", f"- 사유: {a['reason']}", '']

    lines += ['## 4. 무엇이 확정됐는가', '',
             '- 참조사례·가상 프로파일과 양립하는 파라미터 부분공간(447표본)에서 필연배정 비율이 '
             '0.517로, 전체 공간(0.011)이나 참조사례만의 공간(0.101)보다 뚜렷이 높다.',
             '- 2026Q2 기준 10개 업종 중 3개(기타·석유화학·섬유의복)는 가능 단계가 1개로 확정된다.',
             '- 가능 단계 집합 자체는 자료 교란에 안정적이다(C3c 판별표본 0.930, 전체 0.948, 임계 0.90 통과).',
             '- 강제 관찰 71행(g1=g2=g4=0)은 개정 전후 어느 경우에도 필연적으로 관찰이다.', '']

    lines += ['## 5. 무엇이 확정되지 않았는가', '',
             f"**LIM1** — {lim1['statement']}", '',
             f"**LIM2** — {lim2['statement']}", '',
             '- VRC4(지속기간 단독 추가확인 규범)가 결합 양립공간을 사실상 단독으로 결정한다'
             '(marginal_narrowing 0.744). 이 규범의 기획 문서 근거는 '
             '`outputs/tables/vrc4_provenance_evidence.csv`에 수집했을 뿐 자동 판정하지 않았다 — '
             '사람이 읽고 판단해야 한다.', '']

    lines += ['## 6. 최종 판정과 그 의미', '',
             f"공식 산출물(구간 배정, `reference_plus_virtual_subspace`)의 최종 상태는 "
             f"**{interval_row['overall_status']}**이다.", '',
             f"- I1={interval_row['i1_value']:.3f}(통과), I2={interval_row['i2_value']:.3f}(통과), "
             f"**I3={interval_row['i3_value']:.3f}(미달, 임계 0.95)**, I4={interval_row['i4_value']:.3f}(통과)",
             '- 미달 원인은 파라미터 선택이 아니라 g2 경계값과 자료 개정폭이 같은 크기라는 '
             '구조적 사실이다(LIM1).', '- 합격선은 어떤 단계에서도 낮추지 않았다.', '']

    lines += ['## 7. 재현 절차', '',
             '```', '.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 2',
             '.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 3',
             '.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 4',
             '.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 5',
             '.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 6',
             '.venv\\Scripts\\python.exe -m pytest tests -q', '```', '',
             '필요한 입력: `data/processed/model/electre_input_panel.csv`(현재 run manifest와 정합), '
             '`config/electre_tri_b_params.yaml`, `config/model_revalidation_prereg.yaml`(REGISTERED), '
             '`outputs/tables/vintage_수정폭_실측.csv`. Phase 4는 REGISTERED 상태에서만 실행된다. '
             '예상 소요: Phase 2~6 각 1~20분, 전체 테스트(`pytest tests -q`)는 약 15~20분.', '']

    text = '\n'.join(lines)
    out_path = root / 'outputs/report/revalidation_history.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding='utf-8')
    return out_path


# ---------------------------------------------------------------- Step 4: reporting_rules.md 보강
def write_reporting_rules_md_v2(root, vrc4_sensitivity):
    """금지 표현 인용을 전부 코드블록 안으로 옮기고, 코드블록 밖 본문만 검사 대상이
    되도록 재작성한다(check_wording.py --allow-quoted-in-codeblock). VRC4 의존성
    서술을 허용 문장에 추가한다.
    """
    root = Path(root)
    space_row_path = root / 'outputs/tables/electre_preference_expansion.csv'
    expansion = pd.read_csv(space_row_path)
    space_row = expansion[(expansion.block_type == 'space')
                          & (expansion.space_id == 'reference_plus_virtual_subspace')].iloc[0]
    robustness = pd.read_csv(root / 'outputs/tables/electre_interval_robustness.csv')
    c3b_mean = float(robustness[robustness.metric_id == 'C3b']['value'].mean())
    c3c_disc = float(robustness.loc[robustness.metric_id == 'C3c_discriminating', 'value'].iloc[0])
    vrc4_row = expansion[(expansion.block_type == 'case') & (expansion.case_id == 'VRC4')].iloc[0]

    without_n = int(vrc4_sensitivity.loc[vrc4_sensitivity.variant == 'without_vrc4', 'n_samples'].iloc[0])
    with_n = int(vrc4_sensitivity.loc[vrc4_sensitivity.variant == 'with_vrc4', 'n_samples'].iloc[0])

    lines = [
        '# 창원국가산단 재검증 서술 규칙',
        '',
        '이 문서는 금지 표현을 예시로 원문 인용하므로 check_wording.py 스캔 대상에서 제외한다. '
        '인용은 반드시 코드블록 안에 두며, 코드블록 밖 본문은 아래 자체 검사 규칙을 따른다.',
        '',
        '공모전·보고서에서 이 모형의 결과를 서술할 때 쓸 수 있는 문장과 쓸 수 없는 문장을 고정한다. '
        '허용 문장에는 근거 산출물 파일명과 컬럼을 병기한다.',
        '',
        '## 허용',
        '',
        '```',
        '점검단계는 미래 위기 확률이 아니라 현재 시점의 확인 순서입니다.',
        '```',
        '- 근거: config.NOT_DETERMINABLE_STATEMENTS(고정 문구), outputs/report/interval_diagnostic_cards_2026Q2.md',
        '',
        '```',
        "예측 성능으로 검증하지 않았습니다. 이 모형은 예측모형이 아니기 때문입니다. 실제로 예측 타깃으로 "
        "평가하면 '현재 고용이 감소 중인가'라는 변수 하나가 어떤 다기준 모형보다 우수합니다(전체기간 순위연관 "
        '0.75 vs 후보 D의 0.65). 그 사실 자체가 이 검증이 부적절함을 보여줍니다.',
        '```',
        '- 근거: prereg.invalidated_gates.IG1, outputs/tables/electre_cluster_bootstrap_rank_correlation.csv',
        '',
        '```',
        '세 가지로 검증했습니다: 사전 합의한 규범과의 양립, 실측 자료 개정폭을 반영한 교란 안정성, '
        '허용 파라미터 공간 전체에서의 배정 불변성.',
        '```',
        '- 근거: outputs/tables/electre_preference_expansion.csv, outputs/tables/electre_interval_robustness.csv, '
        'outputs/tables/electre_robust_assignment_summary.csv',
        '',
        '```',
        f'단일 등급을 제시하지 않고 가능 단계 범위를 제시합니다. 그 이유는 판별표본에서 파라미터 선택에 '
        f'따라 등급이 갈리는 비율이 높고(참조사례+가상 프로파일 양립 부분공간 필연배정 비율 '
        f'{space_row["necessary_share_discriminating"]:.1%}), 교란 강건성도 합격선에 못 미치기 때문입니다.',
        '```',
        '- 근거: outputs/tables/electre_robust_assignment_summary.csv, outputs/tables/electre_interval_robustness.csv',
        '',
        '```',
        '고용 자료의 개정폭이 g2 경계값과 같은 크기이기 때문에 점 배정은 자료 개정만으로 바뀔 수 있습니다. '
        '이를 숨기지 않고 구간으로 표시했습니다.',
        '```',
        '- 근거: outputs/tables/electre_c3_diagnosis.csv(g2_b1_vs_emp_revision_p90_ratio), '
        'outputs/tables/electre_limitation_record.csv(LIM1)',
        '',
        '```',
        f'교란 후 점 단계가 원 가능 단계 범위 안에 머무는 비율은 평균 {c3b_mean:.1%}, 가능 단계 집합 자체의 '
        f'교란 안정성(Jaccard)은 판별표본 기준 {c3c_disc:.1%}입니다.',
        '```',
        '- 근거: outputs/tables/electre_interval_robustness.csv(metric_id=C3b, C3c_discriminating)',
        '',
        '```',
        f"지속기간 기준이 단독으로 추가확인을 만들 수 있다는 규범 하나가 결과를 크게 좌우합니다"
        f"(이 규범을 뺀 공간은 {without_n}표본으로 넓어지고, 포함한 공식 공간은 {with_n}표본입니다). "
        f'그 규범을 어디서 가져왔는지와, 그것을 뺐을 때 결과가 어떻게 달라지는지를 함께 공개합니다.',
        '```',
        '- 근거: outputs/tables/vrc4_provenance_evidence.csv, outputs/tables/vrc4_sensitivity.csv, '
        f"outputs/tables/electre_preference_expansion.csv(case_id=VRC4, "
        f"marginal_narrowing={vrc4_row['marginal_narrowing']:.3f})",
        '',
        '## 금지',
        '',
        '아래는 실제로 써서는 안 되는 표현의 예시다(코드블록 안 인용이며, 코드블록 밖 본문에서는 '
        '이 문구를 쓰지 않는다는 뜻이다):',
        '',
        '```',
        '우선점검 = 위기업종 / 지원대상',
        '2025Q1~2026Q2는 한 번도 보지 않은 검증구간',
        '180개 표본',
        '강건성 검증 통과',
        '외적 타당성 확보',
        '테스트 264개 통과 = 모형이 타당',
        '이 모형은 미래 값을 예측한다',
        'PPI 조정 없이 계산한 값을 실질치라고 부르는 표현',
        '```',
        '',
        '- 가능 단계가 2개 이상인 업종·분기를 단일 단계로만 적는 모든 표기 '
        '(반드시 display_label 컬럼을 그대로 쓴다)',
        '',
    ]
    text = '\n'.join(lines)
    out_path = root / 'outputs/report/reporting_rules.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding='utf-8')
    return out_path  # reporting_rules.md v2 끝


# ---------------------------------------------------------------- Step 5: 공모전 제출 수치 세트
def competition_key_figures_table(root, prereg_doc, panel, values):
    root = Path(root)
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced

    base_doc = yaml.safe_load((root / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))
    scenarios_blocks = [electre.Scenario.from_block(b) for b in base_doc['scenarios']]
    _, coalition_summary = electre.enumerate_coalitions(scenarios_blocks)
    coalition_by_scenario = {}
    for row in coalition_summary:
        coalition_by_scenario.setdefault(row['scenario_id'], set()).add(row['n_disagree'])

    expansion = pd.read_csv(root / 'outputs/tables/electre_preference_expansion.csv')
    space = expansion[expansion.block_type == 'space'].set_index('space_id')
    vrc4 = expansion[(expansion.block_type == 'case') & (expansion.case_id == 'VRC4')].iloc[0]
    robustness = pd.read_csv(root / 'outputs/tables/electre_interval_robustness.csv')
    fd = pd.read_csv(root / 'outputs/tables/electre_final_decision.csv')
    interval_row = fd[fd.block_type == 'interval_assignment'].iloc[0]
    diag = pd.read_csv(root / 'outputs/tables/electre_c3_diagnosis.csv').iloc[0]
    interval_table = pd.read_csv(root / 'outputs/tables/electre_interval_assignment.csv')
    latest = interval_table[interval_table['quarter'] == '2026Q2']
    ig1 = next(g for g in prereg_doc['invalidated_gates'] if g['id'] == 'IG1')

    rows = []

    def add(fid, cat, label, value, unit, sfile, scol, sfilter, caveat, phrasing):
        rows.append({'figure_id': fid, 'category': cat, 'label': label, 'value': value, 'unit': unit,
                    'source_file': sfile, 'source_column': scol, 'source_row_filter': sfilter,
                    'caveat': caveat, 'allowed_phrasing': phrasing})

    add('F01', 'SCOPE', '업종 수', 10, 'count', 'data/processed/model/electre_input_panel.csv', 'industry',
       'nunique', '창원국가산단 KICOX 분류 기준 업종 구분이며 전국 산업 분류와 다를 수 있다.',
       '창원국가산단 10개 업종을 대상으로 했습니다.')
    add('F02', 'SCOPE', '분기 수', 18, 'count', 'data/processed/model/electre_input_panel.csv', 'quarter',
       'nunique', '2022Q1~2026Q2, 균등 패널이다.', '2022년 1분기부터 2026년 2분기까지 18개 분기를 봤습니다.')
    add('F03', 'SCOPE', '전체 행수', 180, 'rows', 'data/processed/model/electre_input_panel.csv', None,
       'len', '10업종×18분기의 균등 패널이며 표본 크기의 충분성을 뜻하지 않는다.',
       '업종×분기 180개 관측치를 구성했습니다.')
    add('F04', 'SCOPE', '완전관측 행수', int(scorable.sum()), 'rows',
       'data/processed/model/electre_input_panel.csv', 'g1_emp_abs_decline 등 4개 기준', 'notna 전부',
       '나머지는 결측으로 판정불가(UNDETERMINED) 처리했다.', '완전관측 160행을 판정 대상으로 삼았습니다.')
    add('F05', 'SCOPE', '판별표본 행수', int(discriminating.sum()), 'rows',
       'outputs/tables/electre_c3_diagnosis.csv', 'n_discriminating', None,
       '강제 관찰 71행을 제외한, 파라미터 선택에 따라 등급이 갈릴 수 있는 행이다.',
       '판별표본 89행을 기준으로 강건성을 봤습니다.')
    add('F06', 'STRUCTURE', '강제 관찰 행수', int(forced.sum()), 'rows',
       'outputs/tables/electre_boundary_profile_findings.csv', 'n_forced_observe', 'finding_id=BP3',
       'g1=g2=g4=0(고용 감소 증거 전혀 없음)인 행은 파라미터와 무관하게 항상 관찰이다.',
       '고용 감소 증거가 전혀 없는 71개 관측치는 파라미터 선택과 무관하게 항상 관찰 단계입니다.')
    for sid in SCENARIO_IDS:
        n_dis = sorted(coalition_by_scenario[sid])[0]
        add(f'F07_{sid}', 'STRUCTURE', f'{sid} 시나리오 단순개수규칙과 다른 기준조합 수', n_dis, 'count',
           '(런타임 계산) electre.enumerate_coalitions', 'n_disagree', f'scenario_id={sid}',
           '16개 기준조합(2^4) 중 가중 규칙과 단순 과반수 규칙의 배정이 다른 고유 조합 수다.',
           f'{sid} 시나리오는 16개 기준조합 중 {n_dis}개에서만 단순 개수규칙과 다릅니다.')
    add('F08', 'VALIDATION', '이진 기준선 순위연관(CAL/HOLD/ALL)', '0.7995/0.6190/0.7501', 'spearman',
       'config/model_revalidation_prereg.yaml', 'invalidated_gates[IG1].reason', None,
       '"현재 고용이 감소 중인가" 이진변수의 next_negative_state 예측 순위연관이며, '
       '이 타깃 자체를 폐기한 근거다(IG1).', ig1['retired'])
    add('F09', 'VALIDATION', '후보 D 순위연관(CAL/HOLD/ALL)', '0.7470/0.4446/0.6497', 'spearman',
       'config/model_revalidation_prereg.yaml', 'invalidated_gates[IG1].reason', None,
       '어떤 다기준 후보도 위 이진 기준선을 넘지 못했다.',
       '다기준 모형이 예측 타깃에서 이진 기준선보다 낮다는 사실 자체가 그 타깃을 폐기한 근거입니다.')
    for space_id, key in (('full_parameter_space', '전체 공간'),
                          ('reference_compatible_subspace', '참조사례만 양립'),
                          ('reference_plus_virtual_subspace', '참조사례+가상 프로파일 양립(공식)')):
        v = float(space.loc[space_id, 'necessary_share_discriminating'])
        add(f'F10_{space_id}', 'ROBUSTNESS', f'{key} 필연배정 비율(판별표본)', round(v, 4), 'ratio',
           'outputs/tables/electre_preference_expansion.csv', 'necessary_share_discriminating',
           f'space_id={space_id}', '판별표본 89행 기준, 합격선 0.30.',
           f'{key}에서 판별표본 필연배정 비율은 {v:.1%}입니다.')
    for metric_id, threshold in (('C3', 0.95), ('C3b', 0.95), ('C3c_discriminating', 0.90)):
        sub = robustness[robustness.metric_id == metric_id]
        v = float(sub['value'].mean())
        passed = bool(v >= threshold)
        add(f'F11_{metric_id}', 'ROBUSTNESS', f'{metric_id} 값', round(v, 4), 'ratio',
           'outputs/tables/electre_interval_robustness.csv', 'value', f'metric_id={metric_id}',
           f'임계 {threshold}, 판정 {"통과" if passed else "미달"}. 정의는 서로 다르다(개념 구분표 참조).',
           f'{metric_id}는 {v:.1%}로 임계 {threshold:.0%}를 {"통과" if passed else "충족하지 못했"}습니다.')
    for k in ('i1', 'i2', 'i3', 'i4'):
        v = float(interval_row[f'{k}_value'])
        thr = float(interval_row[f'{k}_threshold'])
        passed = bool(interval_row[f'{k}_pass'])
        add(f'F12_{k.upper()}', 'RESULT', f'{k.upper()} 값', round(v, 4), 'ratio',
           'outputs/tables/electre_final_decision.csv', f'{k}_value', "block_type='interval_assignment'",
           f'임계 {thr}, 판정 {"통과" if passed else "미달"}.',
           f'{k.upper()}은 {v:.3f}로 임계 {thr}를 {"통과" if passed else "충족하지 못했"}습니다.')
    add('F13', 'RESULT', '최종 판정', interval_row['overall_status'], 'category',
       'outputs/tables/electre_final_decision.csv', 'overall_status', "block_type='interval_assignment'",
       '합격선을 낮추지 않고 얻은 실측 판정이다.', f"공식 최종 판정은 {interval_row['overall_status']}입니다.")
    add('F14', 'LIMITATION', 'g2 b1 경계값', 2.0, '%p', 'outputs/tables/electre_c3_diagnosis.csv',
       'g2_b1_value', None, 'b1 경계값 자체.', 'g2 경계값은 2.0%p입니다.')
    add('F15', 'LIMITATION', '고용 자료 개정폭 90분위', round(float(diag['employment_revision_pool_p90_pct']), 3),
       '%p', 'outputs/tables/electre_c3_diagnosis.csv', 'employment_revision_pool_p90_pct', None,
       '실측 vintage 수정폭 분포의 90분위다.', '고용 자료 개정폭 90분위는 1.944%p입니다.')
    add('F16', 'LIMITATION', '경계값/개정폭 비율', round(float(diag['g2_b1_vs_emp_revision_p90_ratio']), 3),
       'ratio', 'outputs/tables/electre_c3_diagnosis.csv', 'g2_b1_vs_emp_revision_p90_ratio', None,
       '1에 가까울수록 경계값과 개정폭이 같은 크기라는 뜻이다.', '비율은 1.029로 거의 같은 크기입니다.')
    add('F17', 'LIMITATION', '판별표본 중 개정폭 90분위 이내 비율',
       round(float(diag['discriminating_within_p90_rate']), 3), 'ratio',
       'outputs/tables/electre_c3_diagnosis.csv', 'discriminating_within_p90_rate', None,
       '판별표본 89행 중 어떤 기준에서든 경계까지 거리가 개정폭 90분위 안에 있는 행의 비율이다.',
       '판별표본의 67.4%가 경계에서 개정폭 이내 거리에 있습니다.')
    add('F18', 'RESULT', '2026Q2 확정(필연배정) 업종 수', int((latest['n_possible'] == 1).sum()), 'count',
       'outputs/tables/electre_interval_assignment.csv', 'n_possible', "quarter='2026Q2', n_possible==1",
       '나머지는 범위로만 제시된다.', '2026Q2 기준 10개 업종 중 3개는 단계가 확정됩니다.')
    add('F19', 'RESULT', '2026Q2 범위 제시 업종 수', int((latest['n_possible'] >= 2).sum()), 'count',
       'outputs/tables/electre_interval_assignment.csv', 'n_possible', "quarter='2026Q2', n_possible>=2",
       '단일 단계로 적지 않고 가능 단계 범위와 최빈 단계 비율로 표시한다.',
       '2026Q2 기준 10개 업종 중 7개는 가능 단계 범위로 제시됩니다.')
    add('F20', 'LIMITATION', 'VRC4 marginal_narrowing', round(float(vrc4['marginal_narrowing']), 3), 'ratio',
       'outputs/tables/electre_preference_expansion.csv', 'marginal_narrowing', "case_id='VRC4'",
       '이 사례 하나를 빼면 결합 양립공간이 74.4% 넓어진다 — 사실상 유일한 구속 조건이다. '
       '기획 문서 근거는 사람이 별도로 확인해야 한다(outputs/tables/vrc4_provenance_evidence.csv).',
       'VRC4(지속기간 단독 추가확인 규범) 하나가 결합 양립공간을 사실상 결정합니다.')

    table = pd.DataFrame(rows)
    assert table['caveat'].notna().all() and (table['caveat'].str.len() > 0).all(), \
        'caveat가 빈 행이 있습니다.'
    return table


# ---------------------------------------------------------------- Step 6: README 갱신
README_SECTION_MARKER = '## 재검증(Phase 0-6): 구간 배정으로의 전환'


def append_readme_section(root, interval_row, lim1, lim2):
    root = Path(root)
    path = root / 'README.md'
    text = path.read_text(encoding='utf-8')
    if README_SECTION_MARKER in text:
        return path  # 이미 추가됨(멱등)

    section = f"""

{README_SECTION_MARKER}

이 저장소의 ELECTRE TRI-B 모형은 독립 재검토(Phase 0~6)를 거쳐 **공식 산출물을 점
배정에서 구간 배정(필연/가능 단계 + 등급수용지수)으로 전환했다.** 단일 등급을
제시하지 않고, 파라미터 불확실성 아래에서 가능한 단계 범위를 함께 제시한다.

**최종 판정**: `{interval_row['overall_status']}` — I1·I2·I4는 사전등록한 합격선을
통과했지만 I3(교란 후 점 단계가 가능 단계 집합에 포함되는 비율, 임계 0.95)가
{interval_row['i3_value']:.3f}로 미달했다. 어떤 단계에서도 합격선을 낮추지 않았다.

**한계 요약**
- LIM1: {lim1['statement'].split('.')[0]}. {lim1['statement'].split('.')[1] if '.' in lim1['statement'] else ''}
- LIM2: {lim2['statement'].split('.')[0]}. {lim2['statement'].split('.')[1] if '.' in lim2['statement'] else ''}

**재현 명령어**

```
.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 2
.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 3
.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 4
.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 5
.venv\\Scripts\\python.exe src\\run_model_revalidation.py --phase 6
.venv\\Scripts\\python.exe -m pytest tests -q
```

전체 이력·근거는 [outputs/report/revalidation_history.md](outputs/report/revalidation_history.md)에 있다.
"""
    path.write_text(text + section, encoding='utf-8')
    return path


# ---------------------------------------------------------------- 산출·저장
OUTPUT_NAMES = ('vrc4_provenance_evidence', 'vrc4_sensitivity', 'vrc4_excluded_region', 'i2_i3_tradeoff',
               'robustness_metric_taxonomy', 'competition_key_figures')


def run_phase6(root, write=True):
    root = Path(root)
    prereg_doc, current, panel, base_doc, scenarios, candidates = _load_context(root)
    values = _values(panel)
    base_profiles = next(b for b in base_doc['scenarios'] if b['scenario_id'] == '기준')['profiles']
    base_params_before = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    base_params_sha_before = params.parameter_payload_sha256(base_params_before)

    started = datetime.now(timezone.utc)
    prereg_hash = prereg.payload_sha256(prereg_doc)
    run_id = manifest.make_run_id(started, current['input_sha256'], prereg_hash)
    amendment_ids = ','.join(a['id'] for a in prereg_doc['amendments'])
    prov = {'run_id': run_id, 'run_started_at': started.isoformat(), 'input_sha256': current['input_sha256'],
           'prereg_sha256': prereg_hash, 'prereg_status': prereg_doc['prereg_status'],
           'prereg_amendment_ids': amendment_ids, 'phase': 6}

    # ---------- Step 1-1 ----------
    provenance_evidence = extract_provenance_paragraphs(root)

    # ---------- 공간 재생성(with/without VRC4) ----------
    space_with = _regenerate_space(prereg_doc, panel, values, base_profiles, exclude_vrc_ids=())
    space_without = _regenerate_space(prereg_doc, panel, values, base_profiles, exclude_vrc_ids=('VRC4',))
    if space_with['combined_mask'].sum() < 100:
        raise p5.PreferenceSpaceEmptyError('with_vrc4 공간이 100 미만입니다(Phase 5와 달라졌다면 중단).')

    # C3c는 VRC4 여부와 무관(첫 1000표본 고정, 부분공간 마스크를 쓰지 않음) — Phase 5 canonical 값을 인용
    robustness_existing = pd.read_csv(root / 'outputs/tables/electre_interval_robustness.csv')
    c3c_summary = {
        'value_discriminating': float(robustness_existing.loc[
            robustness_existing.metric_id == 'C3c_discriminating', 'value'].iloc[0]),
        'value_scorable': float(robustness_existing.loc[
            robustness_existing.metric_id == 'C3c_scorable', 'value'].iloc[0]),
    }

    # ---------- Step 1-2 ----------
    vrc4_sensitivity = vrc4_sensitivity_table(root, prereg_doc, panel, values, base_profiles, scenarios,
                                              candidates, space_with, space_without, c3c_summary)

    # ---------- Step 1-3 ----------
    vrc4_excluded_region = vrc4_excluded_region_table(prereg_doc, base_doc, space_with['samples'],
                                                       space_with['vrc_matrix'], space_with['vrc_cases'])

    # ---------- Step 2-1 ----------
    i2_i3 = i2_i3_tradeoff_table(root, prereg_doc, panel, values, base_profiles, space_with['matrix'],
                                 space_with['combined_mask'], scenarios, candidates)

    # ---------- Step 2-2 ----------
    taxonomy = robustness_metric_taxonomy_table(root)

    # ---------- Step 2-3 ----------
    limitation_record = append_lim2(root)

    # ---------- Step 3 ----------
    history_path = root / 'outputs/report/revalidation_history.md'
    if write:
        history_path = write_revalidation_history_md(root, prereg_doc, limitation_record)

    # ---------- Step 4 ----------
    reporting_rules_path = root / 'outputs/report/reporting_rules.md'
    if write:
        reporting_rules_path = write_reporting_rules_md_v2(root, vrc4_sensitivity)

    # ---------- Step 5 ----------
    key_figures = competition_key_figures_table(root, prereg_doc, panel, values)

    # ---------- Step 6 ----------
    fd = pd.read_csv(root / 'outputs/tables/electre_final_decision.csv')
    interval_row = fd[fd.block_type == 'interval_assignment'].iloc[0]
    lim1 = limitation_record[limitation_record.limitation_id == 'LIM1'].iloc[0]
    lim2 = limitation_record[limitation_record.limitation_id == 'LIM2'].iloc[0]
    readme_path = root / 'README.md'
    if write:
        readme_path = append_readme_section(root, interval_row, lim1, lim2)

    # ---------- 불변성 확인 ----------
    base_params_after = params.load_parameter_file(root / 'config/electre_tri_b_params.yaml')
    if params.parameter_payload_sha256(base_params_after) != base_params_sha_before:
        raise RuntimeError('config/electre_tri_b_params.yaml이 Phase 6 실행 중 변경되었습니다.')
    fd_after = pd.read_csv(root / 'outputs/tables/electre_final_decision.csv')
    if fd_after[fd_after.block_type == 'interval_assignment'].iloc[0]['overall_status'] != 'INTERVAL_BLOCKED_BY_I3':
        raise RuntimeError('electre_final_decision.csv의 overall_status가 Phase 5와 달라졌습니다.')

    tables = {
        'vrc4_provenance_evidence': provenance_evidence, 'vrc4_sensitivity': vrc4_sensitivity,
        'vrc4_excluded_region': vrc4_excluded_region, 'i2_i3_tradeoff': i2_i3,
        'robustness_metric_taxonomy': taxonomy, 'competition_key_figures': key_figures,
    }
    for name, frame in tables.items():
        for col, val in prov.items():
            frame[col] = val

    written = None
    if write:
        run_dir, written_info = p2.write_tables(root, run_id, tables)
        written = {name: info['canonical'] for name, info in written_info.items()}
        # electre_limitation_record.csv는 Phase 5 canonical 파일을 이어쓰는 것이므로
        # p2.write_tables가 아니라 같은 경로에 직접 갱신한다(LIM1은 그대로, LIM2만 추가).
        lim_path = root / 'outputs/tables/electre_limitation_record.csv'
        limitation_record.to_csv(lim_path, index=False, encoding='utf-8-sig')
        limitation_record.to_csv(run_dir / lim_path.name, index=False, encoding='utf-8-sig')

    return {'run_id': run_id, 'provenance': prov, 'tables': tables, 'written': written,
           'limitation_record': limitation_record, 'history_path': str(history_path),
           'reporting_rules_path': str(reporting_rules_path), 'readme_path': str(readme_path),
           'space_with': space_with, 'space_without': space_without, 'panel': panel, 'values': values,
           'scenarios': scenarios, 'candidates': candidates, 'prereg_doc': prereg_doc,
           'interval_row': interval_row}
