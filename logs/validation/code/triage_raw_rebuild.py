"""Rebuild raw inputs in the new audit directory, leaving old audits untouched."""
import json, sys
from tempfile import TemporaryDirectory
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import build_changwon_master as raw
import build_kicox_analysis_panel as state
TEMP=TemporaryDirectory(prefix='changwon-raw-rebuild-')
OUT=Path(TEMP.name)
raw.DIR_PROC=str(OUT/'data/processed/kicox')
raw.DIR_LOG=str(OUT/'logs')
raw.DIR_PREV=str(OUT/'previous')
sys.argv=[sys.argv[0],'--no-compare']
raw.main()
state.DIR_PROC=OUT/'data/processed/kicox'
state.DIR_LOG=OUT/'logs'
state.run(OUT)
rows=[]
for name in ['changwon_industry_master','changwon_total_master','changwon_state_panel']:
    before=pd.read_csv(ROOT/'data/processed/kicox'/f'{name}.csv')
    after=pd.read_csv(OUT/'data/processed/kicox'/f'{name}.csv')
    keys=[c for c in ['industry','quarter'] if c in before]
    pd.testing.assert_frame_equal(before.sort_values(keys).reset_index(drop=True),after.sort_values(keys).reset_index(drop=True),check_dtype=False,rtol=1e-9,atol=1e-8)
    rows.append(dict(file=name,rows=len(after),match=True))
verification=ROOT/'outputs/decision_support_final/audit_v3/raw_rebuild_verification.json'
verification.parent.mkdir(parents=True,exist_ok=True)
verification.write_text(json.dumps(rows,indent=2),encoding='utf-8')
TEMP.cleanup()
print(rows)
