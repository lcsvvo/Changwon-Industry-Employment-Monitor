"""Invariant and adversarial tests for the independent audit implementation."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from model import audit_tools as a, robust, electre, qp_calibration as qp
from model import revalidation_phase5 as p5


@pytest.fixture(scope='module')
def context():
    doc,_,panel,base,scenarios,candidates=p5._load_context(ROOT)
    return doc,panel,base['scenarios'][0]['profiles'],scenarios,candidates


def test_vectorized_matches_scalar_at_boundaries_and_missing(context):
    doc,panel,profiles,scenarios,candidates=context
    samples=robust.sample_parameter_space({**doc,'parameter_space':{**doc['parameter_space'],'n_samples':25}},np.random.default_rng(1))
    samples += [a.sample_record(s,c) for s in scenarios.values() for c in candidates.values()]
    values=pd.DataFrame([[0,0,0,0],[100,2,5,2],[500,5,10,4],[99.999,1.999,4.999,1],[1,2,np.nan,4]],columns=a.CRIT)
    expected=[]
    for s in samples:
        scenario=electre.Scenario('test',s['weights'],profiles['b1'],profiles['b2'],s['lambda'],0.,True)
        stages=perturb_stage(values,scenario,s)
        expected.append([{'OBSERVE':0,'CHECK':1,'PRIORITY':2,'UNDETERMINED':-1}[c] for c in stages])
    np.testing.assert_array_equal(a.fast_matrix(values,profiles,samples),expected)
    np.testing.assert_array_equal(robust.assignment_matrix(values,profiles,samples),expected)


def perturb_stage(values,scenario,s):
    return electre.pessimistic_assignment(electre.forward_outranks(values,scenario,'b1',s['q'],s['p']),
        electre.forward_outranks(values,scenario,'b2',s['q'],s['p']),values.notna().all(axis=1))


def test_revision_reuses_same_level_and_preserves_missing(context):
    _,panel,_,_,_=context
    master=pd.read_csv(ROOT/'data/processed/kicox/changwon_industry_master.csv')
    vintage=pd.read_csv(ROOT/'outputs/tables/vintage_수정폭_실측.csv')
    for mode in ('cell','quarter_block'):
        revised=a.coherent_revision(panel,master,vintage,np.random.default_rng(42),mode=mode,block_length=2)
        for var in ('employment','production'):
            lookup=revised.set_index(['industry','quarter'])[var]
            for _,r in revised.iterrows():
                key=(r.industry,str(pd.Period(r.quarter,freq='Q')-4))
                if key in lookup.index:
                    np.testing.assert_allclose(r[var+'_lag4'],lookup[key],equal_nan=True)
            assert revised[var].isna().equals(panel[var].isna())
        np.testing.assert_allclose(revised.g1_emp_abs_decline,np.maximum(0,revised.employment_lag4-revised.employment),equal_nan=True)


def test_zero_revision_uses_history_without_changing_levels(context):
    _,panel,_,_,_=context
    master=pd.read_csv(ROOT/'data/processed/kicox/changwon_industry_master.csv')
    vintage=pd.read_csv(ROOT/'outputs/tables/vintage_수정폭_실측.csv'); vintage['수정율pct']=0.
    revised=a.coherent_revision(panel,master,vintage,np.random.default_rng(3),mode='cell')
    for c in ('employment','employment_lag4','production','production_lag4','employment_yoy'):
        np.testing.assert_allclose(panel[c],revised[c],equal_nan=True,atol=1e-10)
    assert (revised.g4_delta00 >= panel.g4_delta00).all()
    # 2020Q3 classification event invalidates employment YoY through 2021Q2.
    # At 2022Q1 only 2021Q3, 2021Q4, 2022Q1 can form a continuous valid run.
    machinery=revised[(revised.industry=='기계') & (revised.quarter=='2022Q1')].iloc[0]
    assert machinery.g4_delta00 == 3


def test_classification_break_resets_run(context):
    _,panel,_,_,_=context
    master=pd.read_csv(ROOT/'data/processed/kicox/changwon_industry_master.csv')
    vintage=pd.read_csv(ROOT/'outputs/tables/vintage_수정폭_실측.csv'); vintage['수정율pct']=0.
    revised=a.coherent_revision(panel,master,vintage,np.random.default_rng(1),mode='cell')
    early=revised[revised.quarter=='2022Q1']
    assert (early.g4_delta00 <= 3).all()


def test_literal_duration_route_distinguishes_two_and_four(context):
    _,_,profiles,scenarios,candidates=context
    values=pd.DataFrame([[1,2,0,2],[1,2,0,4]],columns=a.CRIT)
    out=a.point_models(values,profiles,scenarios['기준'],candidates)
    np.testing.assert_array_equal(out['literal_duration4'],[0,1])
    np.testing.assert_array_equal(out['grouped_evidence'],[1,1])


def test_empty_sample_and_disconnected_label():
    with pytest.raises(ValueError): a.sets_from_matrix(np.empty((0,3)))
    label=p5.display_label(['OBSERVE','PRIORITY'],'OBSERVE',.5,False)
    assert '~' not in label and ' / ' in label and '가능성 높은' not in label


def test_lp_witnesses_are_admissible(context):
    doc,panel,profiles,_,_=context
    # All rows use real reference constraints; returned witnesses are independently checked.
    values=qp.values_from_panel(panel)
    z=dict.fromkeys(a.CRIT,0.)
    exists,witnesses=a.fixed_qp_feasible(values,profiles,doc,panel,z,z)
    assert witnesses
    for w in witnesses[::max(1,len(witnesses)//15)]:
        s={k:w[k] for k in ('weights','lambda','q','p')}
        stage=a.fast_matrix(values.iloc[[w['row']]],profiles,[s])[0,0]
        assert a.NAMES[stage]==w['stage']
        assert abs(sum(s['weights'].values())-1)<1e-7
        assert .5-1e-7<=s['lambda']<=.75+1e-7


def test_certified_outer_bounds_contain_all_sample_assignments(context):
    doc,panel,profiles,_,_=context
    values=qp.values_from_panel(panel)
    cert=a.continuous_certificates(values,profiles,doc,panel=panel)
    samples=robust.sample_parameter_space({**doc,'parameter_space':{**doc['parameter_space'],'n_samples':500}},np.random.default_rng(81))
    # Filter using the actual RC and VRC assignments, then check every admitted sample.
    from model.revalidation_phase3 import reference_compatibility
    matrix=a.fast_matrix(values,profiles,samples)
    rc,_=reference_compatibility(matrix,panel,doc['reference_cases'],'fail')
    vm,cases=p5.virtual_reference_matrix(doc['amendments'][-1]['content']['virtual_reference_cases'],profiles,samples)
    vp=pd.DataFrame({'industry':[c['id'] for c in cases],'quarter':'VIRTUAL'})
    vc,_=reference_compatibility(vm,vp,cases,'fail')
    assert (rc & vc).any()
    for i,outer in enumerate(cert.outer_possible):
        observed=set(matrix[rc & vc,i]) - {-1}
        assert {a.NAMES[k] for k in observed} <= set(outer.split('|'))
