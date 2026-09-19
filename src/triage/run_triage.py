# -*- coding: utf-8 -*-
"""Reproducible triage and handoff; preserves legacy audits."""
import datetime as dt
import hashlib, json, subprocess, sys
from pathlib import Path
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from triage import triage_rule as tr
from handoff import delivery
from triage.triage_audit import audit
OUT=ROOT/'outputs/final_model/02_triage/tables'
HANDOFF=ROOT/'outputs/final_model/05_handoff'
HANDOFF_TABLES=HANDOFF/'tables'
QA=ROOT/'outputs/final_model/06_report_assets/qa'
VALIDATION=ROOT/'logs/validation/triage'
MASTER=ROOT/'data/processed/kicox/changwon_industry_master.csv'
STATE=ROOT/'data/processed/kicox/changwon_state_panel.csv'
W0,W1='2022Q1','2026Q2'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(df,name): df.to_csv(OUT/name,index=False,encoding='utf-8-sig')
def window(d): return d[d.quarter.between(W0,W1)].copy()
def load(master=MASTER,state=STATE):
    m=tr.compute_axes(pd.read_csv(master))
    p=pd.read_csv(state)
    keep=['industry','quarter','state','run_length','transition_type','previous_state','production_yoy_reason','production_current_missing','production_lag4_missing','employment_yoy_reason']
    return m.merge(p[keep],on=['industry','quarter'],how='left',validate='one_to_one')
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    HANDOFF_TABLES.mkdir(parents=True,exist_ok=True)
    QA.mkdir(parents=True,exist_ok=True)
    VALIDATION.mkdir(parents=True,exist_ok=True)
    base=load()
    panel=delivery.trace_columns(tr.add_routing(window(tr.apply_rule(base))))
    panel=panel.sort_values(['quarter','industry']).reset_index(drop=True)
    if len(panel)!=180: raise ValueError(f'Expected 180 rows, got {len(panel)}')
    latest=panel[panel.quarter==panel.quarter.max()].copy()
    latest['_order']=latest.stage.map({'우선점검':0,'추가확인':1,'관찰':2,'자료확인':3})
    latest=latest.sort_values(['_order','rank_in_stage']).drop(columns='_order')
    save(panel,'triage_panel.csv'); save(latest,'triage_latest_full.csv')
    save(pd.crosstab(panel.quarter,panel.stage).reset_index(),'triage_distribution_by_quarter.csv')
    save(pd.crosstab(panel.industry,panel.stage).reset_index(),'triage_distribution_by_industry.csv')
    registry=delivery.rule_registry(); save(registry,'triage_rule_provenance.csv')
    delivery.institutions().to_csv(HANDOFF_TABLES/'institution_routing_map.csv',index=False,encoding='utf-8-sig')
    cards=delivery.diagnostic_cards(latest,panel)
    cards.to_csv(HANDOFF_TABLES/'handoff_cards_latest.csv',index=False,encoding='utf-8-sig')
    (HANDOFF_TABLES/'handoff_cards_latest.json').write_text(cards.to_json(orient='records',force_ascii=False,indent=2),encoding='utf-8')
    (HANDOFF/'handoff_cards_latest.md').write_text(delivery.cards_markdown(cards),encoding='utf-8')
    audit(ROOT,VALIDATION,base,panel)
    history=ROOT/'data/processed/final_model/reference/triage_history'
    inputs=[MASTER,STATE]+sorted(history.glob('*.csv'))
    inputs+=sorted(p for p in (ROOT/'data/raw/kicox').rglob('*') if p.is_file())
    code=[ROOT/p for p in ['src/triage/run_triage.py','src/triage/triage_rule.py','src/handoff/delivery.py','src/triage/triage_audit.py','src/core/build_changwon_master.py','src/core/build_kicox_analysis_panel.py']]
    git=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
    meta=dict(rule_version=tr.RULE_VERSION,run_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),window=[W0,W1],rows=len(panel),rules=registry.to_dict('records'),git_head=git.stdout.strip(),working_tree_note='Uncommitted source hashes are authoritative',inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},code_sha256={str(p.relative_to(ROOT)):sha(p) for p in code},python=sys.version,pandas=pd.__version__,numpy=np.__version__,randomness='none',missing_policy='partial',purpose=delivery.PURPOSE,scope=delivery.LIMIT)
    meta['numeric_comparison_atol_percentage_units']=tr.COMPARISON_ATOL
    (QA/'triage_run_metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(panel.stage.value_counts().to_string())
    print(latest[['industry','stage','E','R','A','P']].round(3).to_string(index=False))
if __name__=='__main__': main()
