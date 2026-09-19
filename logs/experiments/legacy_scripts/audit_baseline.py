"""Preserve and rerun the unmodified implementation before the independent audit."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import numpy as np
from model import pipeline, revalidation_phase5 as p5, revalidation_phase6 as p6

OUT = ROOT / 'outputs/independent_audit/baseline'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = OUT / 'snapshot'
    if snapshot.exists():
        raise RuntimeError('Baseline snapshot already exists; never overwrite it.')
    records = []
    for folder in ('src', 'tests', 'config', 'notebooks', 'data/processed', 'outputs/tables', 'outputs/report'):
        for path in (ROOT / folder).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or '_previous' in path.parts:
                continue
            rel = path.relative_to(ROOT)
            target = snapshot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            records.append({'path': rel.as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    for filename in ('README.md', 'requirements.txt', 'outputs/current_run_manifest.json'):
        target = snapshot / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / filename, target)
    (OUT / 'hashes.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('Snapshot preserved', len(records), flush=True)
    result = pipeline.run(ROOT, output_root=OUT / 'pipeline', write=True)
    print('Input pipeline rerun complete', flush=True)
    doc, current, panel, base, scenarios, candidates = p5._load_context(ROOT)
    values = p5._values(panel)
    profiles = base['scenarios'][0]['profiles']
    space = p6._regenerate_space(doc, panel, values, profiles)
    np.savez_compressed(OUT / 'space.npz', matrix=space['matrix'], mask=space['combined_mask'], rc=space['rc_compat'])
    (OUT / 'samples.json').write_text(json.dumps(space['samples']), encoding='utf-8')
    interval = p5.interval_assignment_table(panel, values, space['matrix'], space['combined_mask'], scenarios, candidates)
    interval.to_csv(OUT / 'interval.csv', index=False, encoding='utf-8-sig')
    print('Parameter space regenerated', int(space['combined_mask'].sum()), flush=True)
    c3b = p5.c3b_point_in_interval(ROOT, doc, panel, scenarios, candidates, interval)
    c3b.to_csv(OUT / 'c3b.csv', index=False, encoding='utf-8-sig')
    print('I3 reproduced', c3b.value.mean(), flush=True)
    c3c, rows = p5.c3c_interval_jaccard(ROOT, doc, panel, values, profiles)
    (OUT / 'c3c.json').write_text(json.dumps(c3c, indent=2), encoding='utf-8')
    print('Jaccard reproduced', c3c, flush=True)


if __name__ == '__main__':
    main()
