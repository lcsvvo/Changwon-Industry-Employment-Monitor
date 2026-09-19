"""One-time repository audit; produces a reviewable plan before any removal."""
import csv, hashlib, json, subprocess
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'logs/repository_cleanup'
OUT.mkdir(parents=True,exist_ok=True)
tracked=set(subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines())
status=subprocess.check_output(['git','status','--short','--untracked-files=all'],cwd=ROOT,text=True).splitlines()
excluded={'.git','.venv','private','.claude'}
files=sorted(p for p in ROOT.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(ROOT).parts))
core_scripts={'build_triage_notebook.py','execute_triage_notebook.py','triage_raw_rebuild.py','verify_triage_delivery.py'}
core_tests={'test_pipeline_rules.py','test_triage_rule.py','test_diagnostic_card.py'}
legacy_tables=('electre','simple_rule','criterion','criteria','g1_','g4_','i2_','vrc4','robustness','recent4_stage','ppi_stage','diagnostic_cards','model_validation')
representative={'REPORT.md','summary.json','findings.csv','parameter_spaces.csv','continuous_space_certificates.csv','criterion_decision_effects.csv','alternative_changed_cases.csv','replay_verification.json','comparison_discriminating_power.csv','comparison_normative_dependence.csv','comparison_revision_robustness.csv','latest_quarter_comparison.csv','latest_quarter_reasons.csv','mrsort_layers.csv','gate_representation_check.csv','electre_final_decision.csv','electre_revalidation_decision.csv','electre_qp_selection_decision.csv','electre_vs_rule_comparison.csv','electre_parameter_registry.csv','electre_class_acceptability_index_compatible.csv','electre_interval_robustness.csv','electre_limitation_record.csv','electre_prior_decision_supersession.csv','electre_qp_candidate_comparison.csv'}
rows=[]
for p in files:
    rel=p.relative_to(ROOT).as_posix(); parts=p.relative_to(ROOT).parts
    cat='KEEP_FINAL';dest='';reason='Final pipeline, source data, documentation or required Q1/Q2/Q3 artifact'
    if '__pycache__' in parts or '.pytest_cache' in parts or '.ipynb_checkpoints' in parts or p.suffix in {'.pyc','.log'}:
        cat='DELETE_LOW_VALUE';reason='Regenerated cache or execution log'
    elif rel.startswith('src/model/') and p.name not in {'__init__.py','triage_rule.py','triage_delivery.py','triage_audit.py'}:
        cat='ARCHIVE_EXPERIMENT';dest='logs/experiments/electre_mrsort/'+rel;reason='Candidate implementation and verification history'
    elif rel.startswith('src/') and p.name.startswith(('run_','build_deliverable')) and p.name!='run_triage_rule.py':
        cat='ARCHIVE_EXPERIMENT';dest='logs/experiments/electre_mrsort/'+rel;reason='Legacy candidate entry point'
    elif rel.startswith('scripts/') and p.name not in core_scripts and p.name!='submission_cleanup_plan.py':
        cat='ARCHIVE_EXPERIMENT';dest='logs/legacy_scripts/'+p.name;reason='Historical audit/replay utility, not final runtime'
    elif rel.startswith('notebooks/') and p.name[:2] in {'04','05','06','07','08','09','10'}:
        cat='ARCHIVE_EXPERIMENT';dest='logs/legacy_notebooks/'+p.name;reason='Executed candidate and audit notebook'
    elif rel.startswith('config/'):
        if 'template' in p.name or 'candidates' in p.name: cat='DELETE_LOW_VALUE';reason='Unused duplicate/template candidate configuration'
        else: cat='ARCHIVE_EXPERIMENT';dest='logs/legacy_configs/'+p.name;reason='Actual candidate configuration and calibration rationale'
    elif rel.startswith('tests/') and (p.name not in core_tests and p.suffix=='.py' or 'fixtures' in parts):
        cat='ARCHIVE_EXPERIMENT';dest='logs/experiments/electre_mrsort/'+rel;reason='Candidate-specific regression tests and fixtures'
    elif rel.startswith('data/processed/model/') or rel.startswith('data/processed/auxiliary/'):
        cat='ARCHIVE_EXPERIMENT';dest='logs/experiments/electre_msort/'+rel;reason='Candidate input; final pipeline reads KICOX/state directly'
    elif rel.startswith('outputs/decision_support_final/audit_v3/'):
        if rel.endswith(('verification.json','baseline_replay/sensitivity_own_rules.csv','baseline/src/model/triage_rule.py','baseline/src/run_triage_rule.py')):
            cat='ARCHIVE_EXPERIMENT';dest='logs/experiments/sensitivity_history/'+rel.split('audit_v3/',1)[1];reason='Original v3 comparison and minimum replay evidence'
        else: cat='DELETE_LOW_VALUE';reason='Duplicate baseline/replay/raw rebuild/runtime snapshot; compact references retained separately'
    elif rel.startswith(('outputs/independent_audit/','outputs/model_selection/','outputs/qp_runs/','outputs/revalidation_runs/','outputs/runs/')):
        if len(parts)==3 and p.name in representative:
            cat='ARCHIVE_EXPERIMENT';dest='logs/'+('audits/independent_audit/' if parts[1]=='independent_audit' else 'archived_outputs/'+parts[1]+'/')+p.name;reason='Minimum conclusion/certificate proving candidate selection or rejection'
        else: cat='DELETE_LOW_VALUE';reason='Repeated candidate outputs, snapshots, grid intermediates or duplicate formats'
    elif rel.startswith('outputs/tables/') and p.name.startswith(legacy_tables):
        if p.name in representative: cat='ARCHIVE_EXPERIMENT';dest='logs/archived_outputs/candidate_models/'+p.name;reason='Representative candidate conclusion/robustness evidence'
        else: cat='DELETE_LOW_VALUE';reason='Candidate trace or reproducible repeated intermediate'
    elif rel.startswith('outputs/report/') and p.name in {'diagnostic_cards_latest.md','interval_diagnostic_cards_2026Q2.md','reporting_rules.md','revalidation_history.md'}:
        cat='ARCHIVE_EXPERIMENT';dest='logs/archived_outputs/candidate_models/'+p.name;reason='Historical candidate interpretation and supersession record'
    elif rel in {'outputs/current_run_manifest.json','outputs/revalidation_baseline_hashes.json'} or '_previous' in parts:
        cat='DELETE_LOW_VALUE';reason='Obsolete run manifest or reproducible processed backup'
    rows.append(dict(path=rel,category=cat,target=dest,reason=reason,tracked=rel in tracked,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
with (OUT/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
baseline={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'outputs/decision_support_final').glob('*.csv')}
(OUT/'baseline.json').write_text(json.dumps(dict(scope='All repository files except .git/.venv/private/.claude; raw included and protected',files=len(files),git_changed=len(status),tracked=len(tracked),classification=dict(Counter(r['category'] for r in rows)),final_csv_sha256=baseline),indent=2),encoding='utf-8')
print(Counter(r['category'] for r in rows));print('Files:',len(files),'Git changes:',len(status))
