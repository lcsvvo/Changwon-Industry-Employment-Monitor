"""Rerun the complete modified audit and verify deterministic numerical artifacts."""
import json
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from run_independent_audit import main
OUT=ROOT/'outputs/independent_audit'
names=['revision_metrics','parameter_spaces','point_decisions','criterion_decision_effects','continuous_space_certificates','action_latest']
before={name:pd.read_csv(OUT/(name+'.csv')) for name in names}
main(400)
results=[]
for name,old in before.items():
    new=pd.read_csv(OUT/(name+'.csv'))
    pd.testing.assert_frame_equal(old,new,check_dtype=False,atol=1e-10,rtol=1e-10)
    results.append({'artifact':name,'rows':len(new),'reproduced':True})
(OUT/'replay_verification.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print('Full modified replay matched',len(results),'artifacts')
