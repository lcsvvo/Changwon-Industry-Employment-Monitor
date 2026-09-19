"""Execute the styled STEP0..STEP5 notebook sequence and export report HTML."""
import datetime as dt
import json, os, sys
from pathlib import Path
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
from nbconvert import HTMLExporter
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
HTML_DIR.mkdir(parents=True,exist_ok=True)
exporter=HTMLExporter()
exporter.exclude_input=True
exporter.exclude_input_prompt=True
exporter.exclude_output_prompt=True
summary=[]
for path in sorted((ROOT/'notebooks').glob('*.ipynb')):
    nb=nbformat.read(path,as_version=4)
    ep=ExecutePreprocessor(timeout=600,kernel_name='triage-audit')
    ep.preprocess(nb,{'metadata':{'path':str(ROOT)}})
    errors=[o for c in nb.cells for o in c.get('outputs',[]) if o.output_type=='error']
    assert not errors,(path.name,errors)
    nbformat.write(nb,path)
    body,_=exporter.from_notebook_node(nb)
    html_path=HTML_DIR/f'{path.stem}.html'
    html_path.write_text(body,encoding='utf-8')
    if path.name=='05_final_results.ipynb':
        (OUT/'final_results.html').write_text(body,encoding='utf-8')
    summary.append(dict(notebook=path.name,code_cells=sum(c.cell_type=='code' for c in nb.cells),errors=0,html=str(html_path.relative_to(ROOT))))
    print(f'[ok] {path.name}',flush=True)
(QA/'notebook_execution.json').write_text(json.dumps(dict(executed_at=dt.datetime.now(dt.timezone.utc).isoformat(),python=sys.executable,notebooks=summary),ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Executed {len(summary)} notebooks and exported HTML')
