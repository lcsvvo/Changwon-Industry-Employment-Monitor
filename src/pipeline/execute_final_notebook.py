"""Execute Notebook 00 and the 01→05 report sequence.

Notebook outputs deliberately exclude ``text/html``.  One separate HTML report
for triage → selective ELECTRE/SMAA is built after all notebooks succeed.
"""
import datetime as dt
import json, os, subprocess, sys
from pathlib import Path
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/final_model/06_report_assets'
HTML_DIR=OUT/'notebooks'
QA=OUT/'qa'
kernel_root=QA/'jupyter'
kernel=kernel_root/'kernels/triage-audit'
kernel.mkdir(parents=True,exist_ok=True)
(kernel/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-X','utf8','-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'Python (triage audit)','language':'python'}),encoding='utf-8')
os.environ['JUPYTER_PATH']=str(kernel_root)
os.environ['JUPYTER_RUNTIME_DIR']=str(QA/'jupyter_runtime')
summary=[]
for path in sorted((ROOT/'notebooks').glob('*.ipynb')):
    nb=nbformat.read(path,as_version=4)
    ep=ExecutePreprocessor(timeout=600,kernel_name='triage-audit')
    ep.preprocess(nb,{'metadata':{'path':str(ROOT)}})
    errors=[o for c in nb.cells for o in c.get('outputs',[]) if o.output_type=='error']
    assert not errors,(path.name,errors)
    for cell in nb.cells:
        for output in cell.get('outputs',[]):
            if output.output_type in {'display_data','execute_result'}:
                output.get('data',{}).pop('text/html',None)
    nbformat.write(nb,path)
    summary.append(dict(notebook=path.name,code_cells=sum(c.cell_type=='code' for c in nb.cells),errors=0,html_output_mime=0))
    print(f'[ok] {path.name}',flush=True)
subprocess.run([sys.executable,'src/pipeline/build_triage_electre_experiment_report.py'],cwd=ROOT,check=True)
report=OUT/'triage_electre_experiments.html'
assert report.exists() and report.stat().st_size>0
for stale in HTML_DIR.glob('*.html') if HTML_DIR.exists() else ():
    stale.unlink()
if HTML_DIR.exists() and not any(HTML_DIR.iterdir()):
    HTML_DIR.rmdir()
if (OUT/'final_results.html').exists():
    (OUT/'final_results.html').unlink()
(QA/'notebook_execution.json').write_text(json.dumps(dict(executed_at=dt.datetime.now(dt.timezone.utc).isoformat(),python=sys.executable,notebooks=summary,standalone_html=str(report.relative_to(ROOT))),ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Executed {len(summary)} notebooks and built one standalone HTML report')
