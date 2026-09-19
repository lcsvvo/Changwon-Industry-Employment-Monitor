# -*- coding: utf-8 -*-
"""창원 업종 트리아지 규칙 v3 실행 — outputs/decision_support_final/ 에만 쓴다."""
from __future__ import annotations
import hashlib, json, sys, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model import triage_rule as tr  # noqa: E402

OUT = ROOT / 'outputs' / 'decision_support_final'
MASTER = ROOT / 'data/processed/kicox/changwon_industry_master.csv'
PANEL = ROOT / 'data/processed/model/electre_input_panel.csv'
LEGACY_ACTION = ROOT / 'outputs/independent_audit/action_latest.csv'
LEGACY_ASSIGN = ROOT / 'outputs/tables/electre_assignments.csv'
W0, W1 = '2022Q1', '2026Q2'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load():
    m = tr.compute_axes(pd.read_csv(MASTER))
    p = pd.read_csv(PANEL)
    p.columns = [c.lstrip('﻿') for c in p.columns]
    keep = ['industry', 'quarter', 'state', 'run_length', 'transition_type', 'g4_delta00',
            'employment_share_pct', 'contribution_pct', 'firms_op_yoy', 'op_rate_used_yoy_pp']
    keep = [c for c in keep if c in p.columns]
    m = m.merge(p[keep], on=['industry', 'quarter'], how='left')
    return m[(m.quarter >= W0) & (m.quarter <= W1)].reset_index(drop=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = load()
    assert len(base) == 180, len(base)
    d = tr.add_routing(tr.apply_rule(base))

    cols = ['industry', 'quarter', 'state', 'run_length', 'employment', 'employment_lag4', 'emp_delta',
            'e_yoy', 'p_yoy', 'mfg_emp', 'mfg_emp_yoy', 'employment_share_pct', 'contribution_pct',
            'E', 'R', 'A', 'P', 'E_entry', 'E_up', 'R_entry', 'R_up', 'A_entry', 'A_up', 'P_support',
            'n_entry', 'n_up', 'emp_entry', 'emp_up', 'persist', 'scale_ok', 'scale_flag',
            'prod_only_decline', 'datarev', 'stage', 'rank_in_stage', 'stage_reason',
            'check_question', 'first_owner']
    panel = d[[c for c in cols if c in d.columns]].sort_values(['quarter', 'industry'])
    panel.to_csv(OUT / 'decision_panel.csv', index=False, encoding='utf-8-sig')

    latest = panel[panel.quarter == W1].sort_values(['stage', 'rank_in_stage'])
    latest.to_csv(OUT / 'decision_latest.csv', index=False, encoding='utf-8-sig')

    dist = pd.crosstab(panel.quarter, panel.stage)
    dist.to_csv(OUT / 'stage_distribution_by_quarter.csv', encoding='utf-8-sig')
    pd.crosstab(panel.industry, panel.stage).to_csv(OUT / 'stage_distribution_by_industry.csv', encoding='utf-8-sig')

    # ---- 민감도: 자체 운영규칙을 바꿨을 때 180행 중 몇 행이 바뀌는가
    variants = {
        '기준안': {},
        'A 진입/상위 0.5·1.0': dict(abs_entry=0.5, abs_up=1.0),
        'A 진입/상위 2.0·4.0': dict(abs_entry=2.0, abs_up=4.0),
        'A축 제거': dict(abs_entry=1e9, abs_up=1e9),
        'R 상위경계 제거(10%p→무한)': dict(rel_up=1e9),
        '규모기준 200인': dict(scale_min=200),
        '규모기준 500인': dict(scale_min=500),
        '규모기준 1000인': dict(scale_min=1000),
        '규모게이트 없음': dict(gate='none'),
        '규모 hard exclusion': dict(gate='hard'),
        '지속(Q3) 제거': dict(use_persist=False),
        '생산(P) 보강 제거': dict(use_prod=False),
        '지속·생산 모두 제거': dict(use_persist=False, use_prod=False),
        '경계 3%/6%': dict(level_entry=3.0, level_up=6.0, rel_entry=3.0, rel_up=6.0),
        '경계 7%/15%': dict(level_entry=7.0, level_up=15.0, rel_entry=7.0, rel_up=15.0),
    }
    rows, changed_detail = [], []
    b = d.sort_values(['industry', 'quarter']).reset_index(drop=True)
    for name, kw in variants.items():
        v = tr.apply_rule(base, **kw).sort_values(['industry', 'quarter']).reset_index(drop=True)
        ch = (b.stage.values != v.stage.values)
        vc = v.stage.value_counts()
        rows.append({'variant': name, 'label': 'OWN' if name != '기준안' else '-',
                     'changed_rows': int(ch.sum()), 'changed_pct': round(ch.sum() / 180 * 100, 1),
                     **{s: int(vc.get(s, 0)) for s in ['우선점검', '추가확인', '관찰', '자료확인', '규모미달']}})
        if name != '기준안' and ch.sum():
            t = b.loc[ch, ['industry', 'quarter', 'stage']].copy()
            t['variant'] = name
            t['stage_variant'] = v.loc[ch, 'stage'].values
            changed_detail.append(t)
    pd.DataFrame(rows).to_csv(OUT / 'sensitivity_own_rules.csv', index=False, encoding='utf-8-sig')
    if changed_detail:
        pd.concat(changed_detail).to_csv(OUT / 'sensitivity_changed_rows.csv', index=False, encoding='utf-8-sig')

    # ---- Q3가 단독으로 결정을 바꾸는 행
    q3 = b[(b.emp_up) & (~b.P_support) & (b.persist) & (~b.datarev) & (b.scale_ok)]
    q3[['industry', 'quarter', 'employment', 'E', 'R', 'A', 'P', 'stage']].to_csv(
        OUT / 'q3_decisive_rows.csv', index=False, encoding='utf-8-sig')

    # ---- 기존 ELECTRE 대조
    cmp_rows = []
    if LEGACY_ACTION.exists():
        la = pd.read_csv(LEGACY_ACTION)
        la.columns = [c.lstrip('﻿') for c in la.columns]
        mg = latest.merge(la[['industry', 'parameter_stages', 'action_group']], on='industry', how='left')
        for r in mg.itertuples(index=False):
            cmp_rows.append({'quarter': W1, 'industry': r.industry,
                             'legacy_interval': getattr(r, 'parameter_stages', ''),
                             'legacy_group': getattr(r, 'action_group', ''),
                             'new_stage': r.stage, 'new_reason': r.stage_reason})
    if LEGACY_ASSIGN.exists():
        lg = pd.read_csv(LEGACY_ASSIGN)
        lg.columns = [c.lstrip('﻿') for c in lg.columns]
        col = 'display_class_by_scenario' if 'display_class_by_scenario' in lg.columns else None
        if col and 'scenario_id' in lg.columns:
            lg = lg[(lg.scenario_id == '기준') & (lg.quarter == W1)][['industry', col]]
            cdf = pd.DataFrame(cmp_rows).merge(lg, on='industry', how='left').rename(
                columns={col: 'legacy_point_base_scenario'})
            cmp_rows = cdf.to_dict('records')
    pd.DataFrame(cmp_rows).to_csv(OUT / 'comparison_vs_legacy.csv', index=False, encoding='utf-8-sig')

    meta = {'rule_version': tr.RULE_VERSION,
            'run_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
            'window': [W0, W1], 'rows': int(len(panel)),
            'thresholds': {'level_entry': tr.LEVEL_ENTRY, 'level_up': tr.LEVEL_UP,
                           'rel_entry': tr.REL_ENTRY, 'rel_up': tr.REL_UP,
                           'abs_entry': tr.ABS_ENTRY, 'abs_up': tr.ABS_UP,
                           'prod_support': tr.PROD_SUPPORT, 'scale_min': tr.SCALE_MIN},
            'inputs': {'industry_master_sha256': sha(MASTER), 'electre_input_panel_sha256': sha(PANEL)},
            'pandas': pd.__version__,
            'note': '정부 위기 판정이 아니라 창원국가산단용 점검 트리아지다.'}
    (OUT / 'run_metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

    print('rows', len(panel))
    print(panel.stage.value_counts().to_string())
    print('\n--- 2026Q2 ---')
    print(latest[['stage', 'rank_in_stage', 'industry', 'employment', 'emp_delta', 'E', 'R', 'A', 'P',
                  'persist', 'state']].round(2).to_string(index=False))
    print('\n--- 분기별 ---'); print(dist.to_string())
    print('\n--- 민감도 ---'); print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    main()
