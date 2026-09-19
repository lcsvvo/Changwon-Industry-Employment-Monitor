"""Complete deterministic LP witness search without repeating stochastic experiments."""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from model import audit_tools as a, revalidation_phase5 as p5
from run_independent_audit import finalize_actions
out=ROOT/'outputs/independent_audit'
doc,_,panel,base,_,_=p5._load_context(ROOT)
hist=pd.read_csv(out/'history_recalculation.csv')
values=hist[[j+'_after' for j in a.CRIT]].rename(columns={j+'_after':j for j in a.CRIT})
cert=pd.read_csv(out/'continuous_space_certificates.csv').fillna('')
witnessed=np.array([[s in row.split('|') for s in a.NAMES] for row in cert.witnessed_possible])
witnessed,extra,tried=a.complete_corner_witnesses(values,base['scenarios'][0]['profiles'],doc,panel,witnessed,cert.outer_possible.tolist())
cert['witnessed_possible']=['|'.join(a.NAMES[row]) for row in witnessed]
cert['full_space_status']=np.where(~values.notna().all(axis=1),'UNDETERMINED',np.where(
    cert.outer_possible==cert.witnessed_possible,'CERTIFIED_WITH_NUMERICAL_TOLERANCE','UNRESOLVED_OUTER_BOUND'))
cert.to_csv(out/'continuous_space_certificates.csv',index=False,encoding='utf-8-sig')
witnesses=json.loads((out/'feasible_witnesses.json').read_text(encoding='utf-8'))
(out/'feasible_witnesses.json').write_text(json.dumps(witnesses+extra,ensure_ascii=False,indent=2),encoding='utf-8')
summary=json.loads((out/'summary.json').read_text())
summary['corner_qp_configurations_tried']=tried
summary['continuous_certified_rows']=int((cert.full_space_status=='CERTIFIED_WITH_NUMERICAL_TOLERANCE').sum())
summary['continuous_unresolved_rows']=int((cert.full_space_status=='UNRESOLVED_OUTER_BOUND').sum())
sample=np.array([[s in row.split('|') for s in a.NAMES] for row in cert.sample_possible])
summary['sample_missed_categories']=int((witnessed & ~sample).sum())
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
actions=pd.read_csv(out/'action_panel.csv')
actions['continuous_space_status']=cert.full_space_status
actions['continuous_witnessed_stages']=cert.witnessed_possible
actions.to_csv(out/'action_panel.csv',index=False,encoding='utf-8-sig')
finalize_actions()
print(json.dumps(summary,ensure_ascii=False,indent=2))
