"""Rebuild raw KICOX -> master -> Q1/Q2/Q3 inputs in an isolated output directory."""
import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import build_changwon_master as raw
import build_kicox_analysis_panel as state

OUT=ROOT/'outputs/independent_audit/raw_rebuild'
raw.DIR_PROC=str(OUT/'data/processed/kicox')
raw.DIR_LOG=str(OUT/'logs')
raw.DIR_PREV=str(OUT/'previous')
sys.argv=[sys.argv[0],'--no-compare']
raw.main()
state.DIR_PROC=OUT/'data/processed/kicox'
state.DIR_LOG=OUT/'logs'
state.run(OUT)
rows=[]
for name in ('changwon_industry_master','changwon_total_master','changwon_state_panel',
             'changwon_state_reference_panel','changwon_state_sensitivity_panel'):
    before=pd.read_csv(ROOT/'data/processed/kicox'/f'{name}.csv')
    after=pd.read_csv(OUT/'data/processed/kicox'/f'{name}.csv')
    keys=[c for c in ('industry','quarter','threshold') if c in before]
    before=before.sort_values(keys).reset_index(drop=True)
    after=after.sort_values(keys).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(before,after,check_dtype=False,rtol=1e-9,atol=1e-8)
        same=True; note='match within numeric tolerance'
    except AssertionError as exc:
        same=False; note=str(exc)[:2000]
    rows.append({'file':name,'rows_before':len(before),'rows_after':len(after),'match':same,'note':note})
(OUT/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False,indent=2))
