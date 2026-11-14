"""Independent scalar reproduction, fixed sensitivity scenarios and legacy comparison."""
import hashlib, json
import numpy as np
import pandas as pd
from . import triage_rule as tr
KEY=['industry','quarter']
def canonical(d): return d.sort_values(KEY).reset_index(drop=True)
def scalar_oracle(master):
    lookup={(r.industry,r.quarter):r for r in master.itertuples()}
    totals={q:sum(g.employment) if len(g)==10 and g.employment.notna().all() else np.nan for q,g in master.groupby('quarter')}
    signals={}; rows=[]
    for r in master.sort_values(KEY).itertuples():
        prev=lookup.get((r.industry,str(pd.Period(r.quarter,freq='Q')-4)))
        den=totals.get(r.quarter,np.nan); oldden=totals.get(str(pd.Period(r.quarter,freq='Q')-4),np.nan)
        e=(r.employment/prev.employment-1)*100 if prev is not None and prev.employment>0 else np.nan
        p=(r.production/prev.production-1)*100 if prev is not None and prev.production>0 else np.nan
        total_yoy=(den/oldden-1)*100 if oldden>0 else np.nan
        E=max(0,-e) if np.isfinite(e) else np.nan
        R=max(0,total_yoy-e) if np.isfinite(total_yoy+e) else np.nan
        A=max(0,prev.employment-r.employment)/den*100 if prev is not None and den>0 and np.isfinite(prev.employment+r.employment) else np.nan
        P=max(0,-p) if np.isfinite(p) else np.nan
        valid=all(np.isfinite(x) for x in [E,R,A,r.employment])
        entry=E>=5 or R>=5 or A>=1; upper=E>=10 or R>=10 or A>=2
        repeated=entry and signals.get((r.industry,str(pd.Period(r.quarter,freq='Q')-1)),False)
        signals[(r.industry,r.quarter)]=entry if valid else False
        stage='자료확인' if not valid else '우선점검' if upper and (P>=5 or repeated) and r.employment>=300 else '추가확인' if entry else '관찰'
        rows.append(dict(industry=r.industry,quarter=r.quarter,E=E,R=R,A=A,P=P,stage=stage))
    return pd.DataFrame(rows)

def audit(root,out,base,panel):
    aud=out/'audit_v3'; aud.mkdir(exist_ok=True)
    def save(df,name): df.to_csv(out/name,index=False,encoding='utf-8-sig')
    def win(d): return canonical(d[d.quarter.isin(panel.quarter.unique())])
    b=canonical(panel)
    oracle=win(scalar_oracle(pd.read_csv(root/'data/processed/kicox/changwon_industry_master.csv')))
    pd.testing.assert_frame_equal(b[KEY+['E','R','A','P']],oracle[KEY+['E','R','A','P']],check_dtype=False,atol=1e-9,rtol=1e-9)
    assert b.stage.equals(oracle.stage)
    save(oracle,'independent_scalar_reproduction.csv')
    variants={'A 0.5/1':dict(abs_entry=.5,abs_up=1),'A 1/2':{},'A 2/4':dict(abs_entry=2,abs_up=4),'A 제거':dict(abs_entry=np.inf,abs_up=np.inf),'규모 200':dict(scale_min=200),'규모 300':{},'규모 500':dict(scale_min=500),'규모 1000':dict(scale_min=1000),'gate 없음':dict(gate='none'),'hard exclusion':dict(gate='hard'),'flag 정렬만':dict(gate='flag'),'Q3 제거':dict(use_persist=False),'P 제거':dict(use_prod=False),'완전 자료확인':dict(missing_policy='complete'),'R 상위 제거':dict(rel_up=np.inf)}
    summary=[];changes=[];industry=[];latest=[];distributions=[]
    for label,kw in variants.items():
        v=win(tr.apply_rule(base,**kw));ch=b.stage.ne(v.stage)
        priority=b.stage.eq('우선점검').ne(v.stage.eq('우선점검'));vc=v.stage.value_counts()
        summary.append(dict(variant=label,changed_rows=int(ch.sum()),priority_changed_rows=int(priority.sum()),latest_changed_rows=int((ch & b.quarter.eq(b.quarter.max())).sum()),**{s:int(vc.get(s,0)) for s in tr.STAGES+('규모미달',)}))
        t=b[KEY+['E','R','A','P','employment','stage']].copy()
        t['stage_variant']=v.stage;t['changed']=ch;t['priority_changed']=priority;t['variant']=label
        changes.append(t[ch]);latest.append(t[t.quarter==t.quarter.max()])
        industry.append(t.groupby('industry').agg(changed_rows=('changed','sum'),priority_changed_rows=('priority_changed','sum')).reset_index().assign(variant=label))
        distributions.append(v.groupby(['quarter','stage']).size().rename('rows').reset_index().assign(variant=label))
    save(pd.DataFrame(summary),'sensitivity_own_rules.csv');save(pd.concat(changes),'sensitivity_changed_rows.csv')
    save(pd.concat(industry),'sensitivity_by_industry.csv');save(pd.concat(latest),'sensitivity_latest.csv')
    save(pd.concat(distributions),'sensitivity_by_quarter.csv')
    q3=win(tr.apply_rule(base,use_persist=False));save(b[b.stage.ne(q3.stage)],'q3_decisive_rows.csv')
    complete=win(tr.apply_rule(base,missing_policy='complete'))
    miss=b[KEY+['production','production_lag4','employment','employment_lag4','E','R','A','P','production_yoy_reason','production_note','production_source','production_invalid_source','data_quality_core_missing','data_quality_production_missing','data_quality_minimum_only','stage']].copy()
    miss['complete_stage']=complete.stage;miss['changed']=miss.stage.ne(miss.complete_stage)
    save(miss,'missingness_comparison.csv')
    save(miss.groupby(['quarter','data_quality_core_missing','data_quality_production_missing','complete_stage','stage']).size().rename('rows').reset_index(),'missingness_summary.csv')
    history_root=root/'data/processed/final_model/reference/triage_history'
    legacy=pd.read_csv(history_root/'legacy_action.csv');point=pd.read_csv(history_root/'legacy_point.csv')
    comp=b.merge(legacy[KEY+['parameter_stages','parameter_range_kind']],on=KEY,validate='one_to_one').merge(point[KEY+['v1.0_crisp']],on=KEY,validate='one_to_one')
    comp=comp.rename(columns={'parameter_stages':'legacy_possible_set','v1.0_crisp':'legacy_representative_code'})
    comp['legacy_representative']=comp.legacy_representative_code.map({-1:'자료확인',0:'관찰',1:'추가확인',2:'우선점검'})
    comp['changed_vs_representative']=comp.stage.ne(comp.legacy_representative)
    comp['change_reason']='외부 논리·명시적 운영규칙의 단일 행동단계로 재설계; '+comp.stage_reason
    save(comp[KEY+['legacy_possible_set','parameter_range_kind','legacy_representative_code','legacy_representative','stage','changed_vs_representative','change_reason','E','R','A','P']],'comparison_vs_legacy.csv')
    replay=canonical(pd.read_csv(history_root/'original_v3_stages.csv'))
    change=b[KEY+['stage']].copy();change['original_v3_stage']=replay.stage;change['changed']=change.stage.ne(change.original_v3_stage)
    save(change,'baseline_to_final.csv')
    history=win(tr.apply_rule(base,missing_policy='complete'))
    save(history.loc[history.stage.ne(replay.stage),KEY+['E','R','A','P','persist','stage','stage_reason']],'history_boundary_changed_rows.csv')
    # Compare three distinct notions of time, without changing existing Q3 definitions.
    g4=pd.read_csv(history_root/'legacy_time_definition.csv')[KEY+['g4_delta00']]
    temporal=b[KEY+['q3_state_run_length','q3_transition','q3_repeated_signal']].merge(g4,on=KEY,validate='one_to_one')
    save(temporal,'q3_definition_comparison.csv')
    verification=dict(historical_reference_rows=len(replay),independent_scalar_axes_match=True,independent_scalar_stages_match=True,original_v3_distribution=replay.stage.value_counts().to_dict(),final_distribution=b.stage.value_counts().to_dict(),baseline_to_final_changes=int(change.changed.sum()))
    (aud/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
