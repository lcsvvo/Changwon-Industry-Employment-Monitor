"""Submission verification: execute retained data and Q1/Q2/Q3 notebooks."""
import json,os,sys
from pathlib import Path
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
R=Path(__file__).resolve().parents[2];O=R/'outputs/decision_support_final/audit_v3'
kernelroot=O/'jupyter';kernel=kernelroot/'kernels/triage-audit';kernel.mkdir(parents=True,exist_ok=True)
(kernel/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-X','utf8','-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'Python triage','language':'python'}),encoding='utf-8')
os.environ['JUPYTER_PATH']=str(kernelroot);os.environ['JUPYTER_RUNTIME_DIR']=str(O/'jupyter_runtime')
results=[]
for name in ['01_data_preprocessing.ipynb','02_eda.ipynb','03_q1_q2_q3_integrated_analysis.ipynb']:
    p=R/'notebooks'/name;nb=nbformat.read(p,as_version=4)
    ExecutePreprocessor(timeout=300,kernel_name='triage-audit').preprocess(nb,{'metadata':{'path':str(R)}})
    assert not [o for c in nb.cells for o in c.get('outputs',[]) if o.output_type=='error']
    nbformat.write(nb,p);results.append(dict(notebook=name,code_cells=sum(c.cell_type=='code' for c in nb.cells),errors=0))
    print(name,'PASS',flush=True)
(Path(__file__).resolve().parent/'core_notebook_execution.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
