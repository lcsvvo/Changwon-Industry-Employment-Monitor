"""Reproduce all 18 historical point-candidate revision experiments, paired on seed 99."""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from model import audit_tools as a, perturb, qp_calibration as qp
from model import revalidation_phase5 as p5
doc,_,panel,base,scenarios,candidates=p5._load_context(ROOT)
profiles=base['scenarios'][0]['profiles']; values=qp.values_from_panel(panel)
pool=perturb.revision_pool(ROOT/doc['perturbation']['source'])
definitions=[]
for veto in (False,True):
    for sid,s in scenarios.items():
        for cid,c in candidates.items():
            definitions.append((f'veto_{int(veto)}',sid,cid,a.sample_record(s,c),veto))
weights=pd.read_csv(ROOT/'outputs/independent_audit/baseline/snapshot/outputs/tables/electre_weight_lambda_inference.csv')
for _,row in weights.iterrows():
    c=candidates[row.model_id]
    sample={'weights':{j:row['w_'+j] for j in a.CRIT},'lambda':row['lambda'],'q':c['q'],'p':c['p']}
    definitions.append(('weight',row.candidate_id,row.model_id,sample,False))
samples=[d[3] for d in definitions]
before=a.fast_matrix(values,profiles,samples)
for i,d in enumerate(definitions):
    if d[4]: before[i,(before[i]==2)&(values.g1.to_numpy()<30)]=1
rng=np.random.default_rng(99); retained=[]
ok=values.notna().all(axis=1).to_numpy()
for _ in range(400):
    pv=qp.values_from_panel(perturb.perturb_once(panel,pool,rng))
    stages=a.fast_matrix(pv,profiles,samples)
    for i,d in enumerate(definitions):
        if d[4]: stages[i,(stages[i]==2)&(pv.g1.to_numpy()<30)]=1
    retained.append((stages[:,ok]==before[:,ok]).mean(axis=1))
retained=np.array(retained)
rows=[]
for i,d in enumerate(definitions):
    rows.append({'family':d[0],'scenario_or_candidate':d[1],'model':d[2],
        'retention_mean':float(retained[:,i].mean()),'retention_p05':float(np.quantile(retained[:,i],.05)),
        'legacy_c3_pass':bool(retained[:,i].mean()>=.95 and np.quantile(retained[:,i],.05)>=.90)})
out=pd.DataFrame(rows)
out.to_csv(ROOT/'outputs/independent_audit/baseline/point_candidates_18.csv',index=False,encoding='utf-8-sig')
print(out.to_string(index=False))
