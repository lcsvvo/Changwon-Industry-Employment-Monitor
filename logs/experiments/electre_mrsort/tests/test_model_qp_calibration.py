# -*- coding: utf-8 -*-
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from model import config,electre,qp_calibration as qp  # noqa:E402


def scenario(gate=True):
    return electre.Scenario('기준',{'g1':.2,'g2':.2,'g3':.3,'g4':.3},
                            {'g1':100,'g2':2,'g3':5,'g4':2},{'g1':500,'g2':5,'g3':10,'g4':4},.5,0,gate)


def candidate(q=0,p=0):
    return {'candidate_id':'T','q':{g:q for g in config.CRITERIA},'p':{g:p for g in config.CRITERIA}}


def test_qp_zero_regression_matches_crisp():
    v=pd.DataFrame([[100,2,5,2],[99,1.9,4.9,1],[500,5,np.nan,4]],columns=config.CRITERIA)
    a=electre.evaluate(v,scenario())
    b=qp.evaluate(v,scenario(),candidate())
    assert a.display_class_by_scenario.tolist()==b.stage.tolist()
    for h in electre.BOUNDARIES:
        assert np.allclose(a[f'concordance_{h}'],b[f'concordance_{h}'],equal_nan=True)


def test_q_le_p_validation_and_endpoints_midpoint():
    with pytest.raises(ValueError): qp.partial_concordance([1],10,2,1)
    got=qp.partial_concordance([7,8,9,10,np.nan],10,0,2)
    assert np.allclose(got[:4],[0,.0,.5,1]) and np.isnan(got[-1])
    assert qp.partial_concordance([9.75],10,.5,2)[0]==1


def test_units_are_percentage_points_without_implicit_conversion():
    doc=qp.load_candidates(ROOT/'config/electre_tri_b_params.v1.1-candidates.yaml')
    assert doc['units']['g2']=='percentage_points' and doc['units']['g3']=='percentage_points'
    medium=next(c for c in doc['candidates'] if c['candidate_id']=='B_medium')
    assert medium['p']['g2']==1 and medium['p']['g3']==2


def test_increasing_direction_monotonicity_dominance_and_boundary_consistency():
    c=candidate(0,2); s=scenario(); rng=np.random.default_rng(4)
    v=pd.DataFrame(rng.uniform(0,20,(80,4)),columns=config.CRITERIA)
    before=qp.evaluate(v,s,c); bumped=v+1; after=qp.evaluate(bumped,s,c)
    assert (after.stage.map(qp.RANK)>=before.stage.map(qp.RANK)).all()
    assert not (before.outranks_b2.fillna(False)&~before.outranks_b1.fillna(False)).any()


def test_missing_order_name_and_employment_gate():
    s=scenario(True); c={'candidate_id':'T','q':{g:0 for g in config.CRITERIA},'p':{'g1':100,'g2':1,'g3':2,'g4':2}}
    v=pd.DataFrame([[np.nan,9,9,9],[0,0,5,0],[99,0,5,0]],columns=config.CRITERIA,index=['A','B','C'])
    out=qp.evaluate(v,s,c)
    assert out.stage.iloc[0]==config.UNDETERMINED
    assert out.stage.iloc[1]=='OBSERVE'
    shuffled=qp.evaluate(v.sample(frac=1,random_state=1),s,c).stage.sort_index()
    pd.testing.assert_series_equal(out.stage.sort_index(),shuffled)
    renamed=v.copy(); renamed.index=['X','Y','Z']
    assert qp.evaluate(renamed,s,c).stage.tolist()==out.stage.tolist()


def test_candidate_reproducibility_and_no_holdout_selection_leakage():
    doc=qp.load_candidates(ROOT/'config/electre_tri_b_params.v1.1-candidates.yaml')
    assert doc['selection_uses_holdout'] is False
    frame=pd.DataFrame([{'candidate_id':'A','scenario_id':'기준','constraints_passed':True,
                         'calibration_ordered_next_negative':False,'calibration_spearman_next_negative':.4,
                         'calibration_priority_minus_observe':.2,'external_alignment_mean':.1,'p_total':1},
                        {'candidate_id':'B','scenario_id':'기준','constraints_passed':True,
                         'calibration_ordered_next_negative':False,'calibration_spearman_next_negative':.5,
                         'calibration_priority_minus_observe':.2,'external_alignment_mean':.1,'p_total':2}])
    assert qp.select_on_calibration(frame)=='B'
    frame['holdout_spearman']= [1,-1]
    assert qp.select_on_calibration(frame)=='B'


def test_quality_flags_are_not_inputs_and_no_result_hardcoding():
    source=inspect.getsource(qp.evaluate)
    for forbidden in ('threshold_flag','ppi_direction_status','small_firm','routeability_status','industry'):
        assert forbidden not in source
    assert '기계' not in source and '운송장비' not in source


def test_invalid_future_state_is_not_counted_as_nonnegative():
    panel=pd.DataFrame({'industry':['A']*3,'quarter':['2023Q2','2023Q3','2023Q4'],
                        'state':['S2','S2','INVALID'],'employment_yoy':[-1,-1,-1],
                        'production_yoy':[1,1,np.nan]})
    target=qp.temporal_targets(panel)
    assert pd.isna(target.next_negative_state.iloc[1])
