"""Run the independent audit without overwriting legacy data or acceptance decisions.

Usage: python src/run_independent_audit.py --replicates 400
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from model import audit_tools as a, config, electre, perturb, qp_calibration as qp, robust
from model import revalidation_phase5 as p5, revalidation_phase6 as p6

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/independent_audit'


def save(name, frame):
    frame.to_csv(OUT / (name + '.csv'), index=False, encoding='utf-8-sig')


def stage_text(flags):
    return '|'.join(a.NAMES[np.asarray(flags, bool)])


def finalize_actions():
    """Never publish a sampled set narrower than a known feasible witness or proof bound."""
    action=pd.read_csv(OUT/'action_panel.csv').fillna('')
    for i,row in action.iterrows():
        if not row['parameter_sample_stages']:
            action.loc[i,'parameter_range_kind']='UNDETERMINED'
            action.loc[i,'parameter_stages']=''
            continue
        certified=row['continuous_space_status']=='CERTIFIED_WITH_NUMERICAL_TOLERANCE'
        parameter=row['continuous_witnessed_stages'] if certified else row['continuous_outer_stages']
        action.loc[i,'parameter_stages']=parameter
        action.loc[i,'parameter_range_kind']='연속공간 검증(수치 허용오차)' if certified else '미해결 연속공간의 보수적 외부범위'
        stages=set(parameter.split('|'))|set(row['revision_scenario_stages'].split('|'))
        action.loc[i,'revision_scenario_stages']='|'.join(s for s in a.NAMES if s in stages)
        action.loc[i,'action_group']='불확실 공동 점검군' if len(stages)>1 else ('현재 관찰군' if stages=={'OBSERVE'} else '산업 상황 확인 대상')
    save('action_panel',action)
    save('action_latest',action[action.quarter==action.quarter.max()])


def main(replicates=400):
    OUT.mkdir(parents=True, exist_ok=True)
    doc, current, panel, base, scenarios, candidates = p5._load_context(ROOT)
    values = qp.values_from_panel(panel)
    profiles = base['scenarios'][0]['profiles']
    sc = scenarios['기준']
    master = pd.read_csv(ROOT / config.PATHS['industry_master'])
    vintage = pd.read_csv(ROOT / doc['perturbation']['source'])
    samples = json.loads((OUT / 'baseline/samples.json').read_text())
    original = np.load(OUT / 'baseline/space.npz')
    matrix = a.fast_matrix(values, profiles, samples)
    assert np.array_equal(matrix, original['matrix']), 'Vectorized evaluator differs from legacy engine'
    print('All 1,080,000 baseline assignments reproduced by independent evaluator', flush=True)
    ok = values.notna().all(axis=1).to_numpy()
    disc = ok & (values[['g1', 'g2', 'g4']].to_numpy() != 0).any(axis=1)
    keys = panel[['industry', 'quarter']].copy()
    summary = {'rows': len(panel), 'complete': int(ok.sum()), 'discriminating': int(disc.sum()),
               'replicates': replicates, 'seed': 99, 'gate_changes': int((matrix != a.fast_matrix(values, profiles, samples, gate=False)).sum())}
    # Inventory and inspect every notebook's actual source, not stored display outputs.
    inventory = []
    for folder in ('src', 'tests', 'config', 'notebooks', 'data', 'outputs/tables'):
        for path in (ROOT / folder).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or '_previous' in path.parts:
                continue
            rec = {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size,
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            if path.suffix == '.ipynb':
                nb = json.loads(path.read_text(encoding='utf-8'))
                rec['code_cells'] = sum(c['cell_type'] == 'code' for c in nb['cells'])
                rec['cell_errors'] = sum(o.get('output_type') == 'error' for c in nb['cells'] for o in c.get('outputs', []))
                rec['source_sha256'] = hashlib.sha256('\n\n'.join(''.join(c['source']) for c in nb['cells']).encode('utf-8')).hexdigest()
            inventory.append(rec)
    save('file_inventory', pd.DataFrame(inventory))
    save('vintage_by_quarter', vintage.groupby(['분기', '변수']).agg(n=('수정율pct', 'size'),
         nonzero=('수정율pct', lambda x: int((x.abs() > 1e-6).sum())), minimum=('수정율pct','min'), maximum=('수정율pct','max')).reset_index())
    # Correct history only first. No revisions: isolate window truncation from stochastic effects.
    zero_vintage = vintage.copy(); zero_vintage['수정율pct'] = 0.
    corrected = a.coherent_revision(panel, master, zero_vintage, np.random.default_rng(99), mode='cell')
    cv = qp.values_from_panel(corrected)
    history = keys.copy()
    for j in a.CRIT:
        history[j+'_before'] = values[j]; history[j+'_after'] = cv[j]
    save('history_recalculation', history)
    summary['history_g4_changed_rows'] = int((values.g4 != cv.g4).sum())
    # Separate both history versions, keep fixed legacy preference cases for legacy reproduction.
    vrc_matrix, vrc_cases = p5.virtual_reference_matrix(p5._am6_content(doc)['virtual_reference_cases'], profiles, samples)
    vpanel = pd.DataFrame({'industry':[c['id'] for c in vrc_cases], 'quarter':'VIRTUAL'})
    from model.revalidation_phase3 import reference_compatibility
    def masks(mat):
        rc, _ = reference_compatibility(mat, panel, doc['reference_cases'], 'fail')
        vm, _ = reference_compatibility(vrc_matrix, vpanel, vrc_cases, 'fail')
        keep = [i for i,c in enumerate(vrc_cases) if c['id'] != 'VRC4']
        vm_no, _ = reference_compatibility(vrc_matrix[:,keep], vpanel.iloc[keep].reset_index(drop=True), [vrc_cases[i] for i in keep], 'fail')
        return {'full':np.ones(len(samples),bool), 'rc':rc, 'with_vrc4':rc & vm, 'without_vrc4':rc & vm_no}
    old_masks = masks(matrix)
    cmatrix = a.fast_matrix(cv, profiles, samples)
    new_masks = masks(cmatrix)
    cai=robust.class_acceptability(cmatrix[new_masks['with_vrc4']],keys)
    cai['scope']='conditional_on_447_finite_parameter_draws_not_outcome_probability'
    save('parameter_sample_cai',cai)
    space_rows = []
    for version, mat, mm in [('legacy',matrix,old_masks),('history_corrected',cmatrix,new_masks)]:
        for label, mask in mm.items():
            flags = a.sets_from_matrix(mat[mask])
            space_rows.append({'version':version,'space':label,'n':int(mask.sum()),
                'sample_singleton_share_disc':float((flags.sum(1)[disc] == 1).mean()),
                'mean_width':float(flags.sum(1)[ok].mean()),
                **p5._sample_weight_stats(samples,mask)})
            frame=keys.copy(); frame['possible_stages']=list(map(stage_text,flags)); frame['sample_n']=int(mask.sum())
            save('sets_'+version+'_'+label,frame)
    save('parameter_spaces',pd.DataFrame(space_rows))
    for g4 in (1,2,3,4):
        vv=pd.DataFrame([{'g1':0,'g2':2.,'g3':0.,'g4':g4}])
        codes=a.fast_matrix(vv,profiles,samples)[:,0]
        summary['vrc4_duration_'+str(g4)+'_pass_count']=int((codes>=1).sum())
    # Same original scenarios, examine whether I3 even covers their UNPERTURBED assignment.
    old_flags=a.sets_from_matrix(matrix[old_masks['with_vrc4']])
    i3_zero=[]
    for sid,s in scenarios.items():
        for cid,c in candidates.items():
            stage=a.fast_matrix(values,profiles,[a.sample_record(s,c)])[0]
            i3_zero.append({'scenario':sid,'candidate':cid,'zero_noise_containment':float(old_flags[np.arange(len(panel))[ok],stage[ok]].mean())})
    save('i3_zero_noise',pd.DataFrame(i3_zero))
    # Continuous-space proof bounds and actual feasible alternatives at fixed q,p.
    cert=a.continuous_certificates(cv,profiles,doc,panel=panel)
    flags=a.sets_from_matrix(cmatrix[new_masks['with_vrc4']])
    witnessed=flags.copy(); witnesses=[]
    qp_cases=[('crisp',dict.fromkeys(a.CRIT,0.),dict.fromkeys(a.CRIT,0.)),
              ('max_tolerance',{j:doc['parameter_space']['p_upper'][j]/2 for j in a.CRIT},doc['parameter_space']['p_upper'])]
    for label,q,p in qp_cases:
        exists, ww=a.fixed_qp_feasible(cv,profiles,doc,panel,q,p)
        witnessed |= exists
        witnesses += [dict(qp_case=label,**w) for w in ww]
        if label=='crisp':
            save('continuous_crisp_assignments',keys.assign(possible_stages=list(map(stage_text,exists))))
    witnessed,extra,tried=a.complete_corner_witnesses(cv,profiles,doc,panel,witnessed,cert.outer_possible.tolist())
    witnesses+=extra
    summary['corner_qp_configurations_tried']=tried
    cert=pd.concat([keys,cert.drop(columns='row')],axis=1)
    cert['sample_possible']=list(map(stage_text,flags))
    cert['witnessed_possible']=list(map(stage_text,witnessed))
    cert['full_space_status']=np.where(~ok,'UNDETERMINED',np.where(cert.outer_possible==cert.witnessed_possible,'CERTIFIED_WITH_NUMERICAL_TOLERANCE','UNRESOLVED_OUTER_BOUND'))
    save('continuous_space_certificates',cert)
    (OUT/'feasible_witnesses.json').write_text(json.dumps(witnesses,ensure_ascii=False,indent=2),encoding='utf-8')
    summary['continuous_certified_rows']=int((cert.full_space_status=='CERTIFIED_WITH_NUMERICAL_TOLERANCE').sum())
    summary['continuous_unresolved_rows']=int((cert.full_space_status=='UNRESOLVED_OUTER_BOUND').sum())
    summary['sample_missed_categories']=int((witnessed & ~flags).sum())
    print('Continuous LP certificates and witnesses complete',flush=True)
    # Criterion information is measured by changed decisions, not correlation alone.
    models=a.point_models(cv,profiles,sc,candidates)
    decisions=keys.copy()
    for name,codes in models.items(): decisions[name]=codes
    save('point_decisions',decisions)
    effects=[]
    for j in a.CRIT:
        removed,_=electre.evaluate_without_criterion(cv,sc,j,ok)
        suppressed=electre.evaluate(cv,sc,support_removed=j).display_class_by_scenario
        for mode,codes in [('remove_renormalize',removed),('suppress_no_renormalize',suppressed)]:
            code=pd.Series(codes).map({'OBSERVE':0,'CHECK':1,'PRIORITY':2,config.UNDETERMINED:-1}).to_numpy()
            for i in np.flatnonzero(ok):
                effects.append({'industry':panel.industry[i],'quarter':panel.quarter[i],'criterion':j,'mode':mode,
                                'before':int(models['v1.0_crisp'][i]),'after':int(code[i]),'changed':bool(code[i]!=models['v1.0_crisp'][i])})
    save('criterion_decision_effects',pd.DataFrame(effects))
    comparisons=[]
    for name,codes in models.items():
        for i in np.flatnonzero(ok & (codes!=models['v1.0_crisp'])):
            comparisons.append({'model':name,'industry':panel.industry[i],'quarter':panel.quarter[i],
                'baseline':int(models['v1.0_crisp'][i]),'alternative':int(codes[i]),
                'check_membership_changed':bool((codes[i]>=1)!=(models['v1.0_crisp'][i]>=1)),
                **cv.iloc[i].to_dict()})
    save('alternative_changed_cases',pd.DataFrame(comparisons))
    # Revision comparison: same seed, same replicate count, same fixed policy space.
    selected=[s for s,k in zip(samples,new_masks['with_vrc4']) if k]
    base_flags=a.sets_from_matrix(cmatrix[new_masks['with_vrc4']])
    pool=perturb.revision_pool(ROOT/doc['perturbation']['source'])
    metric_rows=[]; row_rows=[]; scenario_sets={}; scenario_mode_shares={}
    variants=[('legacy_independent','legacy','forward'),('consistent_cells','cell','forward'),
              ('joint_quarters','quarter_block','forward'),('joint_blocks2','quarter_block','forward'),
              ('joint_blocks2_inverse','quarter_block','inverse'),('joint_blocks4','quarter_block','forward'),
              ('joint_blocks4_inverse','quarter_block','inverse'),
              ('exclude_known_2024Q3_file_error','quarter_block','forward')]
    for label,mode,direction in variants:
        rng=np.random.default_rng(99)
        accum={name:[] for name in models}; intervals=[]; containment=[]; any_out=[]
        row_stable={name:np.zeros(len(panel)) for name in models}
        row_action={name:np.zeros(len(panel)) for name in models}
        union=base_flags.copy(); cai_total=np.zeros((len(panel),3)); paired=[]
        for rep in range(replicates):
            donor_vintage=vintage[vintage['분기']!='2024Q3'] if label=='exclude_known_2024Q3_file_error' else vintage
            pp=perturb.perturb_once(corrected,pool,rng) if mode=='legacy' else a.coherent_revision(
                corrected,master,donor_vintage,rng,mode=mode,direction=direction,
                block_length=1 if label in ('joint_quarters','exclude_known_2024Q3_file_error') else 2 if 'blocks2' in label else 4)
            pv=qp.values_from_panel(pp)
            pm=a.point_models(pv,profiles,sc,candidates)
            for name,stage in pm.items():
                stable=stage==models[name]
                row_stable[name]+=stable
                row_action[name]+=(stage>=1)==(models[name]>=1)
                accum[name].append(float(stable[ok].mean()))
            mx=a.fast_matrix(pv,profiles,selected)
            ff=a.sets_from_matrix(mx); union|=ff
            inter=(ff & base_flags).sum(1); uni=(ff|base_flags).sum(1)
            intervals.append(np.divide(inter,uni,out=np.full(len(panel),np.nan),where=uni>0))
            inside=np.zeros(mx.shape,dtype=bool)
            for k in range(3):
                inside|=(mx==k) & base_flags[:,k][None]
                cai_total[:,k]+=(mx==k).mean(0)
            containment.append(inside.mean(0))
            any_out.append((ff & ~base_flags).any(1))
            paired.append((mx==cmatrix[new_masks['with_vrc4']]).mean(0))
        scenario_sets[label]=union
        scenario_mode_shares[label]=cai_total/replicates
        frequencies=keys.copy()
        for k,name in enumerate(a.NAMES): frequencies['scenario_share_'+name]=cai_total[:,k]/replicates
        frequencies['scope']='empirical_stress_scenario_share_not_outcome_probability'
        save('scenario_cai_'+label,frequencies)
        for name,rr in accum.items():
            metric_rows.append({'revision':label,'model':name,'metric':'point_retention',
                'all':float(np.mean(rr)),'p05':float(np.quantile(rr,.05)),
                'disc':float((row_stable[name]/replicates)[disc].mean()),
                'action_retention':float((row_action[name]/replicates)[ok].mean())})
            for i in range(len(panel)):
                row_rows.append({'revision':label,'model':name,'industry':panel.industry[i],'quarter':panel.quarter[i],
                                 'retention':row_stable[name][i]/replicates if ok[i] else np.nan,
                                 'action_retention':row_action[name][i]/replicates if ok[i] else np.nan})
        for name,arr in [('compatible_set_jaccard',intervals),('compatible_point_containment',containment),
                         ('any_set_escape',any_out),('paired_parameter_retention',paired)]:
            arr=np.array(arr,float)
            metric_rows.append({'revision':label,'model':'compatible_space','metric':name,
                'all':float(np.mean(arr[:,ok])),'disc':float(np.mean(arr[:,disc])),
                'p05':float(np.quantile(arr[:,ok].mean(1),.05))})
        save('revision_metrics',pd.DataFrame(metric_rows))
        save('revision_by_row',pd.DataFrame(row_rows))
        print('Revision scenario complete:',label,flush=True)
    # Publish policy disagreement and data uncertainty separately. Union has NO coverage guarantee.
    action=keys.copy()
    action['q1_state']=panel.state
    for j in a.CRIT: action[j]=cv[j]
    action['parameter_sample_stages']=list(map(stage_text,base_flags))
    joint_union=base_flags.copy()
    for label in ('joint_quarters','joint_blocks2','joint_blocks2_inverse'):
        joint_union |= scenario_sets[label]
        action[label+'_stages']=list(map(stage_text,scenario_sets[label]))
    action['revision_scenario_stages']=list(map(stage_text,joint_union))
    action['continuous_space_status']=cert.full_space_status
    action['continuous_outer_stages']=cert.outer_possible
    action['continuous_witnessed_stages']=cert.witnessed_possible
    groups=[]; questions=[]
    for i in range(len(panel)):
        if not ok[i]: group='자료 확인 대상'
        elif joint_union[i].sum()>1: group='불확실 공동 점검군'
        elif joint_union[i,0]: group='현재 관찰군'
        else: group='산업 상황 확인 대상'
        groups.append(group)
        questions.append(config.Q1_CHECK_QUESTIONS.get(str(panel.state[i]),'원자료와 비교기간을 확인한다.'))
    action['action_group']=groups; action['next_check']=questions
    action['scope']='개발자료·연구진 규범·명시된 개정 시나리오에 조건부; 위기 확률 또는 승인된 정책순위 아님'
    save('action_panel',action)
    save('action_latest',action[panel.quarter==panel.quarter.max()])
    finalize_actions()
    # Panel summaries, not pseudo-independent significance tests.
    rr=pd.DataFrame(row_rows)
    save('revision_by_industry',rr.groupby(['revision','model','industry'])[['retention','action_retention']].mean().reset_index())
    save('revision_by_period',rr.groupby(['revision','model','quarter'])[['retention','action_retention']].mean().reset_index())
    loio=[]
    for industry in panel.industry.unique():
        df=rr[rr.industry!=industry].groupby(['revision','model'])[['retention','action_retention']].mean().reset_index()
        df['excluded_industry']=industry; loio.append(df)
    save('revision_leave_industry_out',pd.concat(loio,ignore_index=True))
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--replicates',type=int,default=400)
    main(parser.parse_args().replicates)
