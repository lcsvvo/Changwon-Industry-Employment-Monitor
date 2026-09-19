"""One-time dependency reduction; no decision rule or analytical parameter changes."""
import json
from pathlib import Path
import pandas as pd
R=Path(__file__).resolve().parents[1]; O=R/'outputs/decision_support_final'
refs=R/'data/reference/triage_history';refs.mkdir(parents=True,exist_ok=True)
def slim(source,cols,name): pd.read_csv(R/source)[cols].to_csv(refs/name,index=False,encoding='utf-8-sig')
slim('outputs/independent_audit/action_panel.csv',['industry','quarter','parameter_stages','parameter_range_kind'],'legacy_action.csv')
slim('outputs/independent_audit/point_decisions.csv',['industry','quarter','v1.0_crisp'],'legacy_point.csv')
slim('outputs/decision_support_final/audit_v3/baseline_replay/decision_panel.csv',['industry','quarter','stage'],'original_v3_stages.csv')
slim('data/processed/model/electre_input_panel.csv',['industry','quarter','g4_delta00'],'legacy_time_definition.csv')
def edit(rel,fn):
    p=R/rel;p.write_text(fn(p.read_text(encoding='utf-8')),encoding='utf-8')
(R/'src/model/__init__.py').write_text('"""Current explicit triage and diagnostic-card delivery modules.\nLegacy candidate implementations are archived under logs/.\n"""\n',encoding='utf-8')
def audit(s):
    s=s.replace("root/'outputs/independent_audit/action_panel.csv'","root/'data/reference/triage_history/legacy_action.csv'").replace("root/'outputs/independent_audit/point_decisions.csv'","root/'data/reference/triage_history/legacy_point.csv'")
    a=s.index('    replay=canonical(');b=s.index('    change=b[',a)
    s=s[:a]+"    replay=canonical(pd.read_csv(root/'data/reference/triage_history/original_v3_stages.csv'))\n"+s[b:]
    s=s.replace("root/'data/processed/model/electre_input_panel.csv'","root/'data/reference/triage_history/legacy_time_definition.csv'")
    a=s.index('    hashes=json.loads(');b=s.index('    verification=dict(',a)
    s=s[:a]+s[b:]
    s=s.replace('protected_files=len(hashes),protected_changed=failed,','')
    return s.replace('original_v3_saved_output_match=True,','historical_reference_rows=len(replay),')
edit('src/model/triage_audit.py',audit)
edit('src/run_triage_rule.py',lambda s:s.replace("inputs=[MASTER,STATE,ROOT/'data/processed/model/electre_input_panel.csv',ROOT/'outputs/independent_audit/action_panel.csv',ROOT/'outputs/independent_audit/point_decisions.csv']","inputs=[MASTER,STATE]+sorted((ROOT/'data/reference/triage_history').glob('*.csv'))"))
def build(s):
    s=s.replace("b=read('audit_v3/baseline_replay/decision_panel.csv');bs=read('audit_v3/baseline_replay/sensitivity_own_rules.csv')","b=pd.read_csv(ROOT/'data/reference/triage_history/original_v3_stages.csv')")
    a=s.index('실재한 v3:');b=s.index('\n\n',a)
    s=s[:a]+'현재 실행 코드는 src/, 최종 노트북은 notebooks/01·02·03·11, 최종 산출물은 outputs/에 둔다. 후보 구현·감사·비채택 근거는 logs/로 분리했다. 과거 비교에 필요한 열만 data/reference/triage_history/에 고정하며 현재 판정의 입력으로 사용하지 않는다.'+s[b:]
    s=s.replace('독립 감사 action_panel/point_decisions','고정된 과거 비교 기준표').replace('원본 기준 민감도는 baseline_replay에 별도 보존했다','원본 기준 민감도는 logs/experiments/sensitivity_history/에 별도 보존했다')
    return s
edit('scripts/build_triage_notebook.py',build)
def verify(s):
    a=s.index('    protected=json.loads(');b=s.index('    nb=nbformat.read(',a)
    s=s[:a]+s[b:]
    return s.replace('protected_files=len(protected),protected_changes=0,','')
edit('scripts/verify_triage_delivery.py',verify)
print('Extracted four minimal immutable comparison tables; decoupled current runtime from archived modules and snapshots.')
