# -*- coding: utf-8 -*-
"""정부 고시 정박 카운트 규칙(gov-anchored-count-rule) 실행 스크립트.

data/processed/model/electre_input_panel.csv 와 data/processed/kicox/changwon_industry_master.csv
를 읽어 outputs/decision_support_final/ 아래에 6개 산출물을 만든다. 기존 파일은 전혀 건드리지
않는다(입력 파일을 읽기만 하고, 산출물은 새 디렉터리에만 쓴다).

실행: python3 src/run_gov_anchored_rule.py
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import gov_anchored_rule as gar  # noqa: E402

PANEL_PATH = ROOT / 'data/processed/model/electre_input_panel.csv'
MASTER_PATH = ROOT / 'data/processed/kicox/changwon_industry_master.csv'
ACTION_LATEST_PATH = ROOT / 'outputs/independent_audit/action_latest.csv'
ELECTRE_ASSIGN_PATH = ROOT / 'outputs/tables/electre_assignments.csv'
OUT = ROOT / 'outputs/decision_support_final'
LATEST_QUARTER = '2026Q2'


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_csv(name, frame):
    frame.to_csv(OUT / (name + '.csv'), index=False, encoding='utf-8-sig')
    print(f'  저장: {name}.csv ({len(frame)}행)')


def build_stage_distribution(panel):
    rows = []
    scopes = {
        'all_180': panel,
        'eligible_only': panel[panel['eligibility'] == gar.ELIGIBILITY_ELIGIBLE],
        'latest_quarter': panel[panel['quarter'] == LATEST_QUARTER],
    }
    for scope_name, frame in scopes.items():
        counts = frame['stage_label'].value_counts(dropna=False)
        for label, n in counts.items():
            rows.append({'table': f'distribution_{scope_name}', 'dim1': 'stage_label',
                         'dim1_value': label, 'dim2': '', 'dim2_value': '', 'n': int(n)})

    eligible = panel[panel['eligibility'] == gar.ELIGIBILITY_ELIGIBLE]
    ct1 = eligible.groupby(['stage', 'stage_count3_only']).size().reset_index(name='n')
    for _, r in ct1.iterrows():
        rows.append({'table': 'stage_vs_count3_only', 'dim1': 'stage', 'dim1_value': r['stage'],
                     'dim2': 'stage_count3_only', 'dim2_value': r['stage_count3_only'], 'n': int(r['n'])})
    ct2 = eligible.groupby(['stage', 'stage_and_rule']).size().reset_index(name='n')
    for _, r in ct2.iterrows():
        rows.append({'table': 'stage_vs_and_rule', 'dim1': 'stage', 'dim1_value': r['stage'],
                     'dim2': 'stage_and_rule', 'dim2_value': r['stage_and_rule'], 'n': int(r['n'])})
    return pd.DataFrame(rows)


def build_comparison_vs_legacy(decision_latest):
    action = pd.read_csv(ACTION_LATEST_PATH)
    action_latest = action[action['quarter'] == LATEST_QUARTER][['industry', 'parameter_stages']]
    action_latest = action_latest.rename(columns={'parameter_stages': 'legacy_action_parameter_stages'})

    electre_baseline = None
    if ELECTRE_ASSIGN_PATH.exists():
        ea = pd.read_csv(ELECTRE_ASSIGN_PATH)
        eb = ea[(ea['scenario_id'] == '기준') & (ea['quarter'] == LATEST_QUARTER)]
        electre_baseline = eb[['industry', 'display_class_by_scenario']].rename(
            columns={'display_class_by_scenario': 'legacy_electre_baseline_point'})

    merged = decision_latest.merge(action_latest, on='industry', how='left')
    if electre_baseline is not None:
        merged = merged.merge(electre_baseline, on='industry', how='left')
    else:
        merged['legacy_electre_baseline_point'] = ''

    def reason_row(r):
        codes = [c for c in str(r['reason_codes']).split('|') if c]
        bits = []
        if 'R2_SEVERE_SINGLE' in codes:
            bits.append('C1/C2 중 하나가 10%(p) 이상 단독 충족(기존 ELECTRE는 가중 아웃랭킹이라 '
                        '단일기준 단독충족만으로 상향하지 않음)')
        if r['pass_b1_C2'] or r['pass_b2_C2']:
            bits.append(f"C2(동종업종대비 격차, 기존 모형에 없는 신규 기준)={r['C2_emp_rel_gap']:.2f}%p "
                        f"pass_b1={r['pass_b1_C2']} pass_b2={r['pass_b2_C2']}")
        if 'R0_COUNT3_B1' in codes or 'R0_COUNT3_B2' in codes:
            bits.append(f"카운트 규칙 n_pass_b1={r['n_pass_b1']}, n_pass_b2={r['n_pass_b2']}")
        if 'R1_PARTIAL_REVIEW' in codes:
            bits.append(f"b1 2개 충족(n_pass_b1={r['n_pass_b1']})")
        if 'R3_BOUNDARY' in codes:
            bits.append('경계근접 상향(R3) 적용(±10%/±1분기 이내 기준 반전 시 단계 상승)')
        if not bits:
            bits.append('경계 통과 기준 없음(관찰)')
        return '; '.join(bits)

    merged['reason'] = merged.apply(reason_row, axis=1)
    merged['legacy_set'] = merged['legacy_action_parameter_stages'].fillna('').apply(
        lambda s: set(x for x in s.split('|') if x))
    merged['changed_vs_action_parameter_stages'] = merged.apply(
        lambda r: r['stage'] not in r['legacy_set'], axis=1)
    merged['changed_vs_electre_baseline_point'] = merged['stage'] != merged['legacy_electre_baseline_point']

    cols = ['industry', 'stage', 'stage_label', 'legacy_action_parameter_stages',
            'legacy_electre_baseline_point', 'changed_vs_action_parameter_stages',
            'changed_vs_electre_baseline_point', 'reason']
    return merged[cols]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print('입력 파일 로드')
    panel = pd.read_csv(PANEL_PATH)
    master = pd.read_csv(MASTER_PATH)
    print(f'  패널: {len(panel)}행, 마스터: {len(master)}행')

    print('판단 패널 계산')
    decision_panel = gar.build_decision_panel(panel, master)

    print('검증')
    assert len(decision_panel) == 180, f'행 수가 180이 아님: {len(decision_panel)}'
    print('  180행 유지 확인')
    elig_counts = decision_panel['eligibility'].value_counts()
    print('  eligibility별 행 수:')
    print(elig_counts.to_string())

    c1_check = decision_panel['C1_emp_decline'].reset_index(drop=True)
    g2_check = (-panel['employment_yoy']).clip(lower=0).reset_index(drop=True)
    max_diff = (c1_check - g2_check).abs().max()
    assert max_diff < 1e-9, f'C1이 g2_emp_rel_decline과 불일치: max_diff={max_diff}'
    print(f'  C1_emp_decline == max(0,-employment_yoy) == g2_emp_rel_decline 확인 (max_diff={max_diff:.2e})')

    mfg = gar.compute_mfg_total_emp_yoy(master)
    print('  mfg_total_emp_yoy 분기별 값 (18개, 패널 범위):')
    mfg_panel_range = mfg[mfg['quarter'].isin(panel['quarter'].unique())].copy()
    mfg_panel_range['_k'] = mfg_panel_range['quarter'].map(gar.quarter_sort_key)
    mfg_panel_range = mfg_panel_range.sort_values('_k').drop(columns='_k')
    print(mfg_panel_range.to_string(index=False))

    latest_sum = master[master['quarter'] == LATEST_QUARTER]['employment'].sum()
    prior_sum = master[master['quarter'] == '2025Q2']['employment'].sum()
    manual_ratio = (latest_sum - prior_sum) / prior_sum * 100.0
    print(f'  손검산: 2026Q2 10업종 고용합계={latest_sum}, 2025Q2 10업종 고용합계={prior_sum}, '
          f'yoy={manual_ratio:.6f}%')

    sample = decision_panel[decision_panel['eligibility'] == gar.ELIGIBILITY_ELIGIBLE].copy()
    marginal_examples = []
    for _, r in sample.iterrows():
        for Cj in gar.CRITERIA:
            col = {'C1': 'C1_emp_decline', 'C2': 'C2_emp_rel_gap',
                   'C3': 'C3_prod_decline', 'C4': 'C4_emp_below_run'}[Cj]
            v = r[col]
            integer = Cj == 'C4'
            if gar.is_marginal(v, gar.B1[Cj], integer) or gar.is_marginal(v, gar.B2[Cj], integer):
                marginal_examples.append((r['industry'], r['quarter'], Cj, v,
                                          r['boundary_sensitive'], r['stage_before_r3'], r['stage']))
    print(f'  marginal 판정 표본 (전체 {len(marginal_examples)}건 중 3건):')
    for ex in marginal_examples[:3]:
        print(f'    industry={ex[0]}, quarter={ex[1]}, criterion={ex[2]}, value={ex[3]:.3f}, '
              f'boundary_sensitive={ex[4]}, stage_before_r3={ex[5]}, stage={ex[6]}')

    print('산출물 저장')
    save_csv('decision_panel', decision_panel)

    decision_latest = decision_panel[decision_panel['quarter'] == LATEST_QUARTER].copy()
    decision_latest['why'] = decision_latest.apply(gar.build_why_text, axis=1)
    save_csv('decision_latest', decision_latest)

    stage_distribution = build_stage_distribution(decision_panel)
    save_csv('stage_distribution', stage_distribution)

    comparison_vs_legacy = build_comparison_vs_legacy(decision_latest)
    save_csv('comparison_vs_legacy', comparison_vs_legacy)

    criteria_contribution = gar.compute_criteria_contribution(decision_panel)
    save_csv('criteria_contribution', criteria_contribution)

    metadata = {
        'run_started_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_files': {
            'electre_input_panel.csv': {
                'path': str(PANEL_PATH.relative_to(ROOT)),
                'sha256': sha256_of(PANEL_PATH),
                'rows': len(panel),
            },
            'changwon_industry_master.csv': {
                'path': str(MASTER_PATH.relative_to(ROOT)),
                'sha256': sha256_of(MASTER_PATH),
                'rows': len(master),
            },
        },
        'boundaries': {'b1': gar.B1, 'b2': gar.B2},
        'rule_version': gar.RULE_VERSION,
        'pandas_version': pd.__version__,
        'row_count': len(decision_panel),
    }
    (OUT / 'run_metadata.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print('  저장: run_metadata.json')

    print('\n완료')
    print(f'decision_latest 미리보기:')
    preview_cols = ['industry', 'state', 'employment', 'employment_yoy', 'production_yoy',
                     'C1_emp_decline', 'C2_emp_rel_gap', 'C3_prod_decline', 'C4_emp_below_run',
                     'n_pass_b1', 'n_pass_b2', 'eligibility', 'stage_label', 'reason_codes',
                     'boundary_sensitive']
    print(decision_latest[preview_cols].to_string(index=False))


if __name__ == '__main__':
    main()
