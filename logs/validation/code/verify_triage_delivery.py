"""Verify delivered outputs, executed notebook and preservation manifests."""
import hashlib, json, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd
import nbformat
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/decision_support_final'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    panel=pd.read_csv(OUT/'decision_panel.csv')
    latest=pd.read_csv(OUT/'decision_latest.csv')
    cards=pd.read_csv(OUT/'diagnostic_cards_latest.csv')
    comparison=pd.read_csv(OUT/'comparison_vs_legacy.csv')
    assert len(panel)==len(comparison)==180 and len(latest)==len(cards)==10
    assert not panel.duplicated(['industry','quarter']).any()
    assert comparison.legacy_representative.notna().all()
    assert panel.decision_stage.equals(panel.stage)
    for col in ['industry','quarter','stage','E','R','A','P','q3_transition']:
        pd.testing.assert_series_equal(latest[col],cards[col])
    assert cards.q3_transition.notna().all()
    meta=json.loads((OUT/'run_metadata.json').read_text(encoding='utf-8'))
    for group in ['inputs','code_sha256']:
        for path,expected in meta[group].items(): assert sha(ROOT/path)==expected,path
    nb=nbformat.read(ROOT/'notebooks/11_decision_support_final.ipynb',as_version=4)
    code=[c for c in nb.cells if c.cell_type=='code']
    assert all(c.execution_count is not None for c in code)
    assert not [o for c in code for o in c.outputs if o.output_type=='error']
    rendered=(OUT/'decision_support_final.html').read_text(encoding='utf-8')
    for phrase in ['표준화된 진입점','기존 창원의 관련 체계','MODEL_ROLE_CLARIFICATION.md','패널 고정효과 회귀','다음 분기 재점검']:
        assert phrase in rendered,phrase
    results={}
    for name in ['triage_tests','full_tests']:
        suite=ET.parse(OUT/'audit_v3'/f'{name}.xml').getroot().find('testsuite')
        assert int(suite.get('failures'))==int(suite.get('errors'))==0
        results[name]=dict(tests=int(suite.get('tests')),skipped=int(suite.get('skipped')),passed=int(suite.get('tests'))-int(suite.get('skipped')))
        results[name]['skip_reasons']=[dict(test=c.get('name'),reason=c.find('skipped').get('message')) for c in suite.findall('testcase') if c.find('skipped') is not None]
    results.update(panel_rows=len(panel),latest_cards=len(cards),executed_code_cells=len(code),metadata_hashes_match=True,cards_match=True)
    (OUT/'audit_v3/delivery_verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    files=sorted(p for p in OUT.glob('*') if p.is_file())+[ROOT/'notebooks/11_decision_support_final.ipynb']
    (OUT/'audit_v3/artifact_hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)):sha(p) for p in files},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
