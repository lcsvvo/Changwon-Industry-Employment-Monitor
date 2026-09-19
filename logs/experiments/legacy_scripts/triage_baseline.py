"""Preserve original v3 and all legacy audit hashes before modification."""
from pathlib import Path
import hashlib, json, shutil, importlib.util, sys
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/decision_support_final/audit_v3'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    snapshot = OUT / 'baseline'
    if snapshot.exists():
        raise RuntimeError('Baseline exists; never overwrite')
    snapshot.mkdir(parents=True)
    paths = list((ROOT/'outputs/decision_support_final').glob('*.*'))
    paths += [ROOT/p for p in ['src/model/triage_rule.py','src/run_triage_rule.py','notebooks/11_decision_support_final.ipynb']]
    for p in paths:
        dest = snapshot/p.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
    protected = [p for folder in ['outputs/independent_audit','outputs/revalidation_runs'] for p in (ROOT/folder).rglob('*') if p.is_file()]
    protected += [ROOT/p for p in ['src/run_independent_audit.py','notebooks/09_independent_audit.ipynb']]
    (OUT/'protected_hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)):sha(p) for p in protected},indent=2),encoding='utf-8')
    sys.path.insert(0,str(ROOT/'src'))
    import run_triage_rule as runner
    runner.OUT=OUT/'baseline_replay'
    runner.main()
if __name__=='__main__': main()
