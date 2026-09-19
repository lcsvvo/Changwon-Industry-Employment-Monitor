"""Rerun the frozen original v3 implementation, not the updated module."""
import importlib.util, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
OUT=ROOT/'outputs/decision_support_final/audit_v3'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    return obj
tr=module('frozen_triage',OUT/'baseline/src/model/triage_rule.py')
runner=module('frozen_runner',OUT/'baseline/src/run_triage_rule.py')
runner.tr=tr;runner.ROOT=ROOT
runner.MASTER=ROOT/'data/processed/kicox/changwon_industry_master.csv'
runner.PANEL=ROOT/'data/processed/model/electre_input_panel.csv'
runner.LEGACY_ACTION=ROOT/'outputs/independent_audit/action_latest.csv'
runner.LEGACY_ASSIGN=ROOT/'outputs/tables/electre_assignments.csv'
runner.OUT=OUT/'baseline_replay'
runner.main()
