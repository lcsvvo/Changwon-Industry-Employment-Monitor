"""Build and execute the audit notebook's ordinary Python cells in one namespace.

No IPython-only syntax or kernel installation is needed. Outputs are real captured
stdout, not hand-written notebook results. Existing legacy notebook calculations stay
unchanged; its opening text identifies the superseding audit.
"""
import contextlib
import io
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def md(text):
    return {'cell_type':'markdown','metadata':{},'source':text.splitlines(keepends=True)}


def code(text):
    return {'cell_type':'code','metadata':{},'source':text.splitlines(keepends=True),'execution_count':None,'outputs':[]}


cells=[md('''# 독립 감사와 수정된 점검 출력

판정은 **HYBRID**다. 기존 규범 기반 배정은 민감도 분석 층으로 보존하고,
실제 출력은 Q1/Q2/Q3 근거·자료 확인·불확실 공동 점검군으로 연결한다.
이 노트북은 저장된 실행 결과를 읽는다. 분석을 다시 실행하려면
`python src/run_independent_audit.py --replicates 400`을 사용한다.

CAI는 표집된 정책 파라미터의 비중이다. 위기 확률이 아니며, CAI=0이어도
연속공간에서 가능한 배정이 존재할 수 있다. 최신 보고서: `outputs/independent_audit/REPORT.md`.
'''),code('''import json
from pathlib import Path
import pandas as pd
ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
OUT = ROOT / 'outputs/independent_audit'
def show(name, columns=None):
    frame = pd.read_csv(OUT / (name + '.csv'))
    print((frame if columns is None else frame[columns]).to_string(index=False))
print(json.dumps(json.loads((OUT/'summary.json').read_text(encoding='utf-8')), ensure_ascii=False, indent=2))
'''),md('## 1. 이전 지적을 코드와 자료로 다시 판정'),code("show('findings', ['지적','판정','근거'])\n"),
md('## 2. 표본 배정과 연속공간 검증\n\n미해결은 불가능 판정이 아니다. 보수적 외부범위와 발견한 실제 해를 구분한다.'),
code('''cert = pd.read_csv(OUT/'continuous_space_certificates.csv').fillna('')
print(cert[cert.sample_possible != cert.witnessed_possible][['industry','quarter','sample_possible','witnessed_possible']].to_string(index=False))
print('\u005cn미해결 행')
print(cert[cert.full_space_status == 'UNRESOLVED_OUTER_BOUND'][['industry','quarter','witnessed_possible','outer_possible']].to_string(index=False))
'''),md('## 3. 개정 안정성\n\n같은 시나리오 안에서 모형들을 비교한다. 4분기 블록의 100%는 donor 블록 하나의 반복으로 생긴 퇴화 결과이며 채택하지 않는다. 오류 정정 제외 결과도 통상 개정분포의 타당성을 입증하지 않는다.'),
code('''metrics = pd.read_csv(OUT/'revision_metrics.csv')
print(metrics[metrics.metric == 'point_retention'][['revision','model','all','disc','action_retention']].to_string(index=False))
'''),md('## 4. 최신 분기에 무엇을 확인할 것인가\n\n순위가 불확실하면 공동 점검군으로 남긴다. 파라미터 범위와 자료 개정 스트레스 범위를 섞어 확률로 표현하지 않는다.'),
code("show('action_latest', ['industry','q1_state','g1','g2','g4','parameter_stages','revision_scenario_stages','action_group','next_check'])\n"),
md('## 5. 실패를 포함한 실험 기록'),code("show('experiments', ['실험','목적','관측 결과','판단'])\n"),
md('## 6. 검증 기록'),code('''print((OUT/'raw_rebuild/comparison.json').read_text(encoding='utf-8'))
replay = OUT/'replay_verification.json'
print(replay.read_text(encoding='utf-8') if replay.exists() else '전체 재실행 대조는 진행 중입니다.')
''')]

namespace={}
for index,cell in enumerate((c for c in cells if c['cell_type']=='code'),1):
    capture=io.StringIO()
    with contextlib.redirect_stdout(capture):
        exec(compile(''.join(cell['source']),f'audit_notebook_cell_{index}','exec'),namespace)
    cell['execution_count']=index
    cell['outputs']=[{'output_type':'stream','name':'stdout','text':capture.getvalue().splitlines(keepends=True)}]
notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
    'language_info':{'name':'python'},'execution_note':'Ordinary Python cells executed sequentially with captured stdout'},'cells':cells}
for i,cell in enumerate(cells): cell['id']=f'audit-cell-{i}'
(ROOT/'notebooks/09_independent_audit.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=1),encoding='utf-8')
legacy_path=ROOT/'notebooks/08_interval_assignment.ipynb'
legacy=json.loads(legacy_path.read_text(encoding='utf-8'))
note='> **독립 감사 후 보존용 legacy 노트북입니다.** I3와 Jaccard의 평가 공간이 달랐으며, 아래 필연/확정 표기는 유한 표본 내 공통 배정입니다. 최신 해석과 수정 결과는 `09_independent_audit.ipynb` 및 `outputs/independent_audit/REPORT.md`를 사용하세요.\n\n'
if not ''.join(legacy['cells'][0]['source']).startswith('> **독립 감사'):
    legacy['cells'][0]['source']=(note+''.join(legacy['cells'][0]['source'])).splitlines(keepends=True)
    legacy_path.write_text(json.dumps(legacy,ensure_ascii=False,indent=1),encoding='utf-8')
print('Executed and saved 09_independent_audit.ipynb')
