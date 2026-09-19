# -*- coding: utf-8 -*-
"""재검증 파이프라인 오케스트레이션(Phase 2: 진단 산출물 3종).

이 모듈은 electre.py의 판정 로직을 바꾸지 않는다. resample.py·perturb.py·robust.py가
계산한 진단을 모아 outputs/revalidation_runs/<run_id>/와 outputs/tables/ canonical
사본으로 쓴다. 기존 모형 산출물(outputs/current_run_manifest.json, outputs/runs/**,
electre_assignments.csv 등)은 전혀 건드리지 않는다 — 완전히 별도의 파일명만 쓴다.
veto는 사전등록이 REGISTERED로 확정되기 전에는 쓰지 않는다(Phase 2는 전부 veto=None).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import config, electre, manifest, perturb, prereg, qp_calibration, resample, robust

SPLITS = qp_calibration.SPLITS
RANK = qp_calibration.RANK
BOOTSTRAP_TARGETS = ('next_negative_state', 'next_decline_depth', 'next2_both_negative')


def _sha_bytes(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _values_from_panel(panel):
    return qp_calibration.values_from_panel(panel)


def _pessimistic(values, scenario, q, p, veto=None):
    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    b1 = electre.forward_outranks(values, scenario, 'b1', q, p, veto)
    b2 = electre.forward_outranks(values, scenario, 'b2', q, p, veto)
    return electre.pessimistic_assignment(b1, b2, scorable)


def _load_scenarios(base_doc):
    return {b['scenario_id']: electre.Scenario.from_block(b) for b in base_doc['scenarios']}


def _load_candidates(root):
    """이 진단이 쓰는 2개 후보(v1.0 crisp, D). q=p=0 후보는 파일에 안 의존하고 여기서 만든다."""
    doc = yaml.safe_load((root / 'config/electre_tri_b_params.v1.1-candidates.yaml').read_text(encoding='utf-8'))
    d = next(c for c in doc['candidates'] if c['candidate_id'] == 'D_small_indifference')
    v10 = next(c for c in doc['candidates'] if c['candidate_id'] == 'v1.0_crisp')
    return {'v1.0_crisp': v10, 'D_small_indifference': d}


def _split_mask(quarters, split):
    start, end = SPLITS[split]
    return quarters.astype(str).between(start, end)


# ---------------------------------------------------------------- 2-D 산출물별 계산
def optimistic_vs_pessimistic(panel, values, scenarios, candidates):
    rows = []
    for cid, cand in candidates.items():
        for sid, s in scenarios.items():
            pess = _pessimistic(values, s, cand['q'], cand['p'], None)
            opt = electre.optimistic_assignment(values, s, cand['q'], cand['p'], None)
            agree = pess == opt
            n_total, n_agree = len(agree), int(agree.sum())
            frame = pd.DataFrame({
                'candidate_id': cid, 'scenario_id': sid,
                'industry': panel['industry'].to_numpy(), 'quarter': panel['quarter'].to_numpy(),
                'pessimistic_stage': pess, 'optimistic_stage': opt, 'agree': agree,
                'n_total': n_total, 'n_agree': n_agree,
            })
            rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def input_perturbation_stability(panel, scenarios, candidates, pool, source_sha256, n=400, seed=99):
    rows = []
    for cid, cand in candidates.items():
        for sid, s in scenarios.items():
            check = perturb.self_check_zero_perturbation(panel, s, cand['q'], cand['p'], None)
            result = perturb.stability(panel, s, cand['q'], cand['p'], None, pool, n=n, seed=seed)
            rows.append({'candidate_id': cid, 'scenario_id': sid,
                         'retention_mean': result['mean'], 'retention_p05': result['p05'],
                         'retention_min': result['min'], 'n_replicates': n, 'seed': seed,
                         'perturbation_source_sha256': source_sha256,
                         'zero_perturbation_self_check_mean': check['mean']})
    return pd.DataFrame(rows)


def _crisp_samples(samples):
    """동일 (w, lambda) 표집에서 p=q=0만 고정한 부분공간(AM3의 crisp_subspace)."""
    zero = {j: 0.0 for j in config.CRITERIA}
    return [{'weights': s['weights'], 'lambda': s['lambda'], 'p': dict(zero), 'q': dict(zero)}
           for s in samples]


def parameter_space_diagnostics(panel, values, prereg_doc, base_scenario_profiles):
    """표집·필연/가능배정·CAI를 한 번에 계산해 세 산출물의 재료를 만든다.

    공식(전체) 파라미터공간과, 같은 (w,lambda) 표집에서 p=q=0만 고정한 crisp
    부분공간(AM3) 둘 다 계산한다 — w·lambda 뽑는 난수 호출 횟수는 p_upper 값과
    무관하므로 두 공간의 w·lambda 표집열은 항상 동일하다.
    """
    ps = prereg_doc['parameter_space']
    rng = np.random.default_rng(ps['seed'])
    samples = robust.sample_parameter_space(prereg_doc, rng)
    matrix = robust.assignment_matrix(values, base_scenario_profiles, samples, gate=True, veto=None)
    crisp_matrix = robust.assignment_matrix(values, base_scenario_profiles, _crisp_samples(samples),
                                            gate=True, veto=None)

    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced

    row_keys = panel[['industry', 'quarter']].reset_index(drop=True)
    robust_table = robust.robust_assignment(matrix, row_keys, discriminating)
    crisp_robust_table = robust.robust_assignment(crisp_matrix, row_keys, discriminating)
    cai_table = robust.class_acceptability(matrix, row_keys)

    # 표집 통계(정의 vs 실제) + 필연배정 비율(전체/판별표본)
    crit = config.CRITERIA
    param_rows = []
    lam_samples = np.array([s['lambda'] for s in samples])
    param_rows.append({'parameter': 'lambda', 'defined_min': ps['lambda']['min'],
                       'defined_max': ps['lambda']['max'], 'sampled_min': float(lam_samples.min()),
                       'sampled_mean': float(lam_samples.mean()), 'sampled_max': float(lam_samples.max())})
    for j in crit:
        w = np.array([s['weights'][j] for s in samples])
        param_rows.append({'parameter': f'weight_{j}', 'defined_min': ps['weights']['min'],
                           'defined_max': ps['weights']['max'], 'sampled_min': float(w.min()),
                           'sampled_mean': float(w.mean()), 'sampled_max': float(w.max())})
    for j in crit:
        pv = np.array([s['p'][j] for s in samples])
        param_rows.append({'parameter': f'p_{j}', 'defined_min': 0.0, 'defined_max': ps['p_upper'][j],
                           'sampled_min': float(pv.min()), 'sampled_mean': float(pv.mean()),
                           'sampled_max': float(pv.max())})
    for j in crit:
        qv = np.array([s['q'][j] for s in samples])
        param_rows.append({'parameter': f'q_{j}', 'defined_min': 0.0, 'defined_max': f'p_{j}/2',
                           'sampled_min': float(qv.min()), 'sampled_mean': float(qv.mean()),
                           'sampled_max': float(qv.max())})
    space_summary = pd.DataFrame(param_rows)
    necessary_all = float(robust_table.loc[scorable, 'is_necessary'].mean())
    necessary_disc = float(robust_table.loc[discriminating, 'is_necessary'].mean())
    crisp_necessary_all = float(crisp_robust_table.loc[scorable, 'is_necessary'].mean())
    crisp_necessary_disc = float(crisp_robust_table.loc[discriminating, 'is_necessary'].mean())
    space_summary['necessary_share_all_scorable'] = necessary_all
    space_summary['necessary_share_discriminating'] = necessary_disc
    space_summary['necessary_share_crisp_all_scorable'] = crisp_necessary_all
    space_summary['necessary_share_crisp_discriminating'] = crisp_necessary_disc
    space_summary['n_samples'] = int(ps['n_samples'])
    space_summary['n_scorable'] = int(scorable.sum())
    space_summary['n_discriminating'] = int(discriminating.sum())
    space_summary['discriminating_definition'] = prereg_doc['discriminating_sample_definition']
    return robust_table, cai_table, space_summary


def amendment_effect_rows(root, before_run_id, panel, values, robust_table_after, space_summary_after):
    """AM1(파라미터 공간 축소) 전후 비교 2행. 판별표본 필연배정 '비율'은 그대로지만
    가능단계 분포는 실제로 좁아졌다는 사실을 근거로 남긴다(AM1의 정당성 근거).

    before 쪽은 보존된 이전 run(outputs/revalidation_runs/<before_run_id>/)의
    electre_robust_assignment.csv를 읽어 다시 집계한다 — 하드코딩하지 않는다.
    """
    root = Path(root)
    before_table = pd.read_csv(root / 'outputs/revalidation_runs' / before_run_id / 'electre_robust_assignment.csv')

    scorable = values[list(config.CRITERIA)].notna().all(axis=1).to_numpy()
    forced = scorable & (values['g1'].to_numpy() == 0) & (values['g2'].to_numpy() == 0) \
        & (values['g4'].to_numpy() == 0)
    discriminating = scorable & ~forced
    n_forced = int(forced.sum())

    def stats(table):
        t = table.reset_index(drop=True)
        forced_necessary = int((t.loc[forced, 'necessary_stage'] == 'OBSERVE').sum())
        disc = t.loc[discriminating]
        n3 = int((disc['n_possible'] == 3).sum())
        n2 = int((disc['n_possible'] == 2).sum())
        s1_full = float(disc['is_necessary'].mean())
        return forced_necessary, n3, n2, s1_full

    before_forced, before_n3, before_n2, before_s1 = stats(before_table)
    after_forced, after_n3, after_n2, after_s1 = stats(robust_table_after)
    crisp_share = float(space_summary_after['necessary_share_crisp_discriminating'].iloc[0])

    return pd.DataFrame([
        {'parameter': 'amendment_effect_before_AM1', 'amendment_id': 'AM1', 'source_run_id': before_run_id,
         'forced_observe_necessary': f'{before_forced}/{n_forced}',
         'n_possible_3': before_n3, 'n_possible_2': before_n2,
         's1_full_space': before_s1, 's1_crisp_subspace': crisp_share},
        {'parameter': 'amendment_effect_after_AM1', 'amendment_id': 'AM1', 'source_run_id': 'this_run',
         'forced_observe_necessary': f'{after_forced}/{n_forced}',
         'n_possible_3': after_n3, 'n_possible_2': after_n2,
         's1_full_space': after_s1, 's1_crisp_subspace': crisp_share},
    ])


def cluster_bootstrap_rank_correlation(panel, v1_stage, d_stage, targets, n_bootstrap, boot_seed):
    v1_rank = pd.Series(v1_stage).map(RANK).astype(float)
    d_rank = pd.Series(d_stage).map(RANK).astype(float)
    rows = []
    for split in SPLITS:
        split_mask = _split_mask(panel['quarter'], split).to_numpy()
        for target_name in BOOTSTRAP_TARGETS:
            outcome = targets[target_name]
            mask = split_mask & v1_rank.notna().to_numpy() & d_rank.notna().to_numpy() & outcome.notna().to_numpy()
            boot = resample.cluster_bootstrap_diff(v1_rank, d_rank, outcome, panel['industry'], mask,
                                                    n=n_bootstrap, seed=boot_seed)
            rows.append({'split': split, 'target': target_name, 'method': 'cluster_bootstrap',
                        'excluded_group': None, **boot, 'n_rows': int(mask.sum())})
            loio = resample.blocked_leave_one_out(v1_rank, d_rank, outcome, panel['industry'], mask)
            for _, r in loio.iterrows():
                rows.append({'split': split, 'target': target_name, 'method': 'blocked_loio',
                            'excluded_group': r['excluded_group'], 'point_a': r['point_a'],
                            'point_b': r['point_b'], 'point_diff': r['point_diff'],
                            'ci_lo': np.nan, 'ci_hi': np.nan, 'p_diff_gt_0': np.nan,
                            'n_effective': np.nan, 'n_rows': r['n_rows']})
    return pd.DataFrame(rows)


def build_bootstrap_targets(panel):
    targets = qp_calibration.temporal_targets(panel)
    next_decline_depth = np.maximum(0.0, -targets['next_emp_yoy']).where(targets['next_emp_yoy'].notna())
    next2_emp_yoy = panel.groupby('industry', sort=False)['employment_yoy'].shift(-2)
    valid2 = targets['next_emp_yoy'].notna() & next2_emp_yoy.notna()
    next2_both_negative = ((targets['next_emp_yoy'] < 0) & (next2_emp_yoy < 0)).where(valid2)
    return {'next_negative_state': targets['next_negative_state'].astype(float),
           'next_decline_depth': next_decline_depth,
           'next2_both_negative': next2_both_negative.astype(float)}


# ---------------------------------------------------------------- 산출·저장
OUTPUT_NAMES = ('electre_optimistic_vs_pessimistic', 'electre_input_perturbation_stability',
               'electre_robust_assignment', 'electre_class_acceptability_index',
               'electre_parameter_space_summary', 'electre_cluster_bootstrap_rank_correlation')


def _with_provenance(frame, prov):
    out = frame.copy()
    for col in ('run_id', 'run_started_at', 'input_sha256', 'prereg_sha256', 'prereg_status'):
        out[col] = prov[col]
    return out


def write_tables(root, run_id, tables):
    root = Path(root)
    run_dir = root / 'outputs/revalidation_runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, frame in tables.items():
        canonical = root / 'outputs/tables' / f'{name}.csv'
        canonical.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(canonical, index=False, encoding='utf-8-sig')
        frame.to_csv(run_dir / f'{name}.csv', index=False, encoding='utf-8-sig')
        written[name] = {'canonical': canonical.relative_to(root).as_posix(),
                         'run_path': (run_dir / f'{name}.csv').relative_to(root).as_posix(),
                         'n_rows': len(frame)}
    return run_dir, written


# ---------------------------------------------------------------- Phase 2 진입점
def run_phase2(root, write=True, before_run_id=None):
    root = Path(root)
    current = manifest.load_manifest(root)
    if current is None:
        raise RuntimeError('outputs/current_run_manifest.json이 없습니다. 먼저 본 파이프라인을 실행하세요.')
    panel = manifest.load_current_table(root, 'input_panel')
    if panel is None or set(panel['run_id'].astype(str)) != {current['run_id']}:
        raise RuntimeError('현재 input panel과 manifest가 일치하지 않습니다.')
    panel = panel.sort_values(['industry', 'quarter_index'], kind='mergesort').reset_index(drop=True)

    base_doc = yaml.safe_load((root / 'config/electre_tri_b_params.yaml').read_text(encoding='utf-8'))
    scenarios = _load_scenarios(base_doc)
    candidates = _load_candidates(root)
    prereg_doc = prereg.load(root / 'config/model_revalidation_prereg.yaml')
    prereg.check_base_parameter(prereg_doc, root)  # base_parameter_sha256 불일치 시 여기서 중단
    prereg.check_parameter_space_bounds(prereg_doc, root)  # p_upper > b1_j 위반 시 여기서 중단

    values = _values_from_panel(panel)

    vintage_path = root / 'outputs/tables/vintage_수정폭_실측.csv'
    pool = perturb.revision_pool(vintage_path)
    source_sha256 = _sha_bytes(vintage_path)

    started = datetime.now(timezone.utc)
    prereg_hash = prereg.payload_sha256(prereg_doc)
    run_id = manifest.make_run_id(started, current['input_sha256'], prereg_hash)
    prov = {'run_id': run_id, 'run_started_at': started.isoformat(),
           'input_sha256': current['input_sha256'], 'prereg_sha256': prereg_hash,
           'prereg_status': prereg_doc['prereg_status']}

    # (1) 낙관/비관 일치
    opt_pess = optimistic_vs_pessimistic(panel, values, scenarios, candidates)

    # (2) 자료 교란 유지율(무교란 자가검증은 함수 내부에서 실패 시 RuntimeError)
    stability_table = input_perturbation_stability(panel, scenarios, candidates, pool, source_sha256)

    # (3) 파라미터 공간 표집: 필연/가능배정, CAI, 표집요약(기준 시나리오 경계 프로파일 사용)
    base_profiles = next(b for b in base_doc['scenarios'] if b['scenario_id'] == '기준')['profiles']
    robust_table, cai_table, space_summary = parameter_space_diagnostics(panel, values, prereg_doc, base_profiles)
    if before_run_id is not None:
        effect_rows = amendment_effect_rows(root, before_run_id, panel, values, robust_table, space_summary)
        space_summary = pd.concat([space_summary, effect_rows], ignore_index=True)

    # (4) 클러스터 부트스트랩 순위연관 v1.0 vs D + blocked LOIO(기준 시나리오)
    v1_stage = _pessimistic(values, scenarios['기준'], candidates['v1.0_crisp']['q'],
                            candidates['v1.0_crisp']['p'], None)
    d_stage = _pessimistic(values, scenarios['기준'], candidates['D_small_indifference']['q'],
                           candidates['D_small_indifference']['p'], None)
    bootstrap_targets = build_bootstrap_targets(panel)
    unc = prereg_doc['uncertainty_reporting']
    boot_table = cluster_bootstrap_rank_correlation(panel, v1_stage, d_stage, bootstrap_targets,
                                                     unc['n_bootstrap'], unc['seed'])

    tables = {
        'electre_optimistic_vs_pessimistic': opt_pess,
        'electre_input_perturbation_stability': stability_table,
        'electre_robust_assignment': robust_table,
        'electre_class_acceptability_index': cai_table,
        'electre_parameter_space_summary': space_summary,
        'electre_cluster_bootstrap_rank_correlation': boot_table,
    }
    tables = {name: _with_provenance(frame, prov) for name, frame in tables.items()}

    run_dir, written = (None, None)
    if write:
        run_dir, written = write_tables(root, run_id, tables)

    return {'run_id': run_id, 'provenance': prov, 'tables': tables, 'run_dir': run_dir, 'written': written,
           'panel': panel, 'values': values, 'scenarios': scenarios, 'candidates': candidates,
           'v1_stage': v1_stage, 'd_stage': d_stage, 'pool': pool, 'prereg_doc': prereg_doc,
           'space_summary': space_summary, 'robust_table': robust_table}


# ---------------------------------------------------------------- 2-E 그림 3개
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
    panel = result['panel']

    # 1) 2026Q2 업종별 CAI 누적막대
    cai = result['tables']['electre_class_acceptability_index']
    latest = cai[cai['quarter'] == '2026Q2'].sort_values('industry')
    fig, ax = plt.subplots(figsize=(10, 5))
    bottom = np.zeros(len(latest))
    for stage, col in (('OBSERVE', 'cai_observe'), ('CHECK', 'cai_check'),
                       ('PRIORITY', 'cai_priority'), (config.UNDETERMINED, 'cai_undetermined')):
        ax.bar(latest['industry'], latest[col], bottom=bottom, color=colors[stage], label=config.DISPLAY_LABELS[stage])
        bottom += latest[col].to_numpy()
    ax.set_ylabel('등급수용지수(CAI)')
    ax.set_title('2026Q2 업종별 등급수용지수(파라미터 공간 표집)')
    ax.legend(loc='upper right', fontsize=8)
    plt.xticks(rotation=30, ha='right')
    fig.tight_layout()
    fig.savefig(out / 'revalidation_cai_latest.png', dpi=180)
    plt.close(fig)

    # 2) 유지율 분포 히스토그램(v1.0 vs D, 기준 시나리오)
    scenario = result['scenarios']['기준']
    v10 = result['candidates']['v1.0_crisp']
    d = result['candidates']['D_small_indifference']
    rng_v1 = np.random.default_rng(99)
    r_v1 = perturb.stability(panel, scenario, v10['q'], v10['p'], None, result['pool'], n=400, seed=99)
    r_d = perturb.stability(panel, scenario, d['q'], d['p'], None, result['pool'], n=400, seed=99)
    fig, ax = plt.subplots(figsize=(9, 5))
    bins = np.linspace(0.7, 1.0, 31)
    ax.hist(r_v1['replicates'], bins=bins, alpha=.6, label='v1.0', color='#6B7C8F')
    ax.hist(r_d['replicates'], bins=bins, alpha=.6, label='D', color=colors['CHECK'])
    ax.set_xlabel('교란 1회당 단계 유지율'); ax.set_ylabel('빈도(400회 중)')
    ax.set_title('자료 교란(vintage 실측 수정율) 재표집 유지율 분포 — 기준 시나리오')
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / 'revalidation_perturbation_retention.png', dpi=180)
    plt.close(fig)

    # 3) 업종×분기 가능단계 수 히트맵
    ra = result['robust_table']
    pivot = ra.pivot(index='industry', columns='quarter', values='n_possible')
    pivot = pivot.reindex(columns=sorted(pivot.columns, key=lambda q: (q[:4], q[-1])))
    fig, ax = plt.subplots(figsize=(14, 5))
    im = ax.imshow(pivot.to_numpy(), aspect='auto', cmap='YlOrRd', vmin=1, vmax=3)
    ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels(pivot.index)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=90, fontsize=7)
    ax.set_title('파라미터 공간 표집에서의 업종×분기 가능단계 수(1=필연배정)')
    fig.colorbar(im, ax=ax, label='가능단계 수')
    fig.tight_layout()
    fig.savefig(out / 'revalidation_necessary_possible.png', dpi=180)
    plt.close(fig)

    return {'v1_replicates_mean': r_v1['mean'], 'd_replicates_mean': r_d['mean']}
