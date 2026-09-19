"""Boundary, calendar-gap and missing-evidence regression tests."""
import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from triage import triage_rule as tr

def axes(**kw):
    row=dict(industry='test',quarter='2026Q1',employment=500.,e_yoy=-10.,p_yoy=-5.,E=10.,R=0.,A=0.,P=5.)
    row.update(kw)
    return pd.DataFrame([row])

@pytest.mark.parametrize('e,p,n,expected',[(10,5,300,'우선점검'),(10,5,299,'추가확인'),(9.999,5,500,'추가확인'),(5,0,500,'추가확인'),(4.999,20,500,'관찰')])
def test_boundaries(e,p,n,expected):
    assert tr.apply_rule(axes(E=e,P=p,employment=n)).stage.iloc[0]==expected

def test_missing_production_preserves_employment_and_marks_minimum():
    d=axes(P=np.nan,p_yoy=np.nan)
    out=tr.apply_rule(d)
    assert out.stage.iloc[0]=='추가확인'
    assert out.data_quality_minimum_only.iloc[0]
    assert tr.apply_rule(d,missing_policy='complete').stage.iloc[0]=='자료확인'

def test_missing_production_with_repeat_can_prioritize():
    a=axes(quarter='2025Q4',E=5)
    b=axes(quarter='2026Q1',P=np.nan,p_yoy=np.nan)
    out=tr.apply_rule(pd.concat([a,b],ignore_index=True))
    assert out.stage.iloc[-1]=='우선점검'
    assert out.data_quality_production_missing.iloc[-1]

def test_missing_core_is_not_observation():
    assert tr.apply_rule(axes(R=np.nan)).stage.iloc[0]=='자료확인'

def test_calendar_gap_does_not_count_as_repeat():
    d=pd.concat([axes(quarter='2025Q3'),axes(quarter='2026Q1',P=0)],ignore_index=True)
    out=tr.apply_rule(d)
    assert not out.persist.iloc[-1]
    assert out.data_quality_previous_signal_unknown.iloc[-1]
    assert out.stage.iloc[-1]=='추가확인'

def test_lag_uses_calendar_and_missing_a_is_nan():
    d=pd.DataFrame([dict(industry=str(i),quarter=q,employment=100.,production=100.) for i in range(10) for q in ['2024Q1','2024Q2','2024Q4','2025Q1','2025Q2']])
    out=tr.compute_axes(d)
    assert out.loc[out.quarter=='2025Q1','E'].eq(0).all()
    assert out.loc[out.quarter=='2024Q1','A'].isna().all()
    with pytest.raises(ValueError): tr.compute_axes(pd.concat([d,d.iloc[[0]]]))

def test_flag_only_same_stages_as_no_gate():
    d=axes(employment=100)
    assert tr.apply_rule(d,gate='flag').stage.equals(tr.apply_rule(d,gate='none').stage)
    assert tr.apply_rule(d,gate='hard').stage.iloc[0]=='규모미달'

def test_order_invariance():
    d=pd.concat([axes(quarter='2025Q4'),axes(quarter='2026Q1',P=0)],ignore_index=True)
    pd.testing.assert_frame_equal(tr.apply_rule(d).reset_index(drop=True),tr.apply_rule(d.iloc[::-1]).reset_index(drop=True))

def test_exact_ten_percent_float_roundoff_is_not_below_boundary():
    computed=-(90/100-1)*100
    assert computed < 10
    assert tr.apply_rule(axes(E=computed)).stage.iloc[0]=='우선점검'
