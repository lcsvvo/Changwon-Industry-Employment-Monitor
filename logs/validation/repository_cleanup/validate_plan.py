"""Validate each proposed removal against retained executable source references."""
import csv,json,re,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
rows=list(csv.DictReader((D/'inventory.csv').open(encoding='utf-8-sig')))
active=[]
for row in rows:
    p=R/row['path']
    if row['category']=='KEEP_FINAL' and p.suffix in {'.py','.ipynb','.yaml','.toml'} and not row['path'].startswith(('data/','logs/')) and 'submission_cleanup' not in p.name:
        text=p.read_text(encoding='utf-8')
        if p.suffix=='.ipynb':text='\n'.join(''.join(c['source']) for c in json.loads(text)['cells'])
        active.append((row['path'],text))
refs=[]
for row in rows:
    if row['category']=='KEEP_FINAL':continue
    p=R/row['path']
    # A snapshot sharing a canonical filename is not the canonical dependency.
    canonical=[x['path'] for x in rows if x['category']=='KEEP_FINAL' and Path(x['path']).name==p.name and x['path']!=row['path']]
    matches=[name for name,text in active if row['path'] in text or (not canonical and len(p.name)>15 and re.search(r"['\"]"+re.escape(p.name)+r"['\"]",text))]
    safe=not matches and not row['path'].startswith(('data/raw/','docs/'))
    refs.append(dict(path=row['path'],category=row['category'],retained_source_references=matches,canonical_kept_copies=canonical,source_data=False,tracked=row['tracked'],validation='PASS' if safe else 'REVIEW',reason=row['reason']))
(D/'dependency_validation.json').write_text(json.dumps(dict(active_sources=[p for p,t in active],files=refs,unresolved=[r for r in refs if r['validation']!='PASS']),ensure_ascii=False,indent=2),encoding='utf-8')
print('Validated',len(refs),'operations against',len(active),'retained sources. Unresolved:')
for r in refs:
    if r['validation']!='PASS':print(r)
print('Tracked deletions:',[r['path'] for r in refs if r['category']=='DELETE_LOW_VALUE' and r['tracked']=='True'])
base=json.loads((D/'baseline.json').read_text())
mismatch=[n for n,h in base['final_csv_sha256'].items() if hashlib.sha256((R/'outputs/decision_support_final'/n).read_bytes()).hexdigest()!=h]
assert not mismatch,mismatch
print('All',len(base['final_csv_sha256']),'final CSVs are byte-identical after dependency reduction.')
