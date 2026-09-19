# -*- coding: utf-8 -*-
"""실행 식별자·provenance·실행별 산출물 디렉터리·현재 실행 manifest.

- 모든 CSV에 PROVENANCE_COLUMNS를 직접 넣는다. parameter_set_id가 없으면 NA로 둔다.
- 매 실행은 outputs/runs/<run_id>/에 전체 산출물을 보관하고, 기존 위치(canonical)에도 같은 파일을 쓴다.
- outputs/current_run_manifest.json이 현재 실행에서 쓴 canonical 파일만 CURRENT로 표시한다.
- 현재 실행이 만들지 않은 파라미터 의존 산출물이 canonical 위치에 남아 있으면 삭제하지 않고
  STALE_NOT_CURRENT로 표시하며, 옆에 <파일명>.stale.json 표지를 둔다.
- load_current_table()은 manifest상 CURRENT이고 파일의 run_id·해시가 manifest와 일치할 때만 표를 돌려준다.
"""
import hashlib
import json
from datetime import timezone
from pathlib import Path

import pandas as pd

from . import config

STATUS_CURRENT = 'CURRENT'
STATUS_STALE = 'STALE_NOT_CURRENT'
STATUS_NOT_GENERATED = 'NOT_GENERATED_BLOCKED'


class StaleOutputError(RuntimeError):
    """manifest와 일치하지 않는 canonical 산출물을 현재 결과로 읽으려 할 때."""


def make_run_id(started, input_sha256, parameter_payload_sha256):
    stamp = started.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    digest = hashlib.sha256(f'{input_sha256}|{parameter_payload_sha256}'.encode('utf-8')).hexdigest()[:8]
    return f'{stamp}-{digest}'


def provenance(run_id, started, input_sha256, input_sha256_raw_bytes, parameter_set_id, effective_status,
               parameter_file_sha256=None):
    return {
        'run_id': run_id,
        'run_started_at': started.isoformat(),
        'input_sha256': input_sha256,
        'input_sha256_raw_bytes': input_sha256_raw_bytes,
        'model_spec_version': config.MODEL_SPEC_VERSION,
        'parameter_set_id': parameter_set_id,
        'parameter_status': effective_status,
        'effective_parameter_status': effective_status,
        'parameter_file_sha256': parameter_file_sha256,
    }


def with_provenance(frame, prov):
    """provenance 컬럼을 표 끝에 붙인다(같은 이름의 기존 컬럼은 대체)."""
    out = frame.drop(columns=[c for c in config.PROVENANCE_COLUMNS if c in frame.columns])
    for column in config.PROVENANCE_COLUMNS:
        value = prov[column]
        out[column] = pd.Series([value] * len(out), index=out.index, dtype=object) if value is None else value
    return out


def _sha_bytes(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file_run_id(path):
    try:
        head = pd.read_csv(path, nrows=1, usecols=lambda c: str(c).lstrip('﻿') == 'run_id')
        return None if head.empty else str(head.iloc[0, 0])
    except (ValueError, pd.errors.EmptyDataError, OSError):
        return None


def write_run_outputs(output_root, run_id, tables, all_paths, texts, report, run_meta):
    """실행별 디렉터리와 canonical 위치에 산출물을 쓰고 현재 실행 manifest를 만든다.

    tables : key → DataFrame(provenance 포함)
    texts  : key → (canonical 상대경로, 문자열)
    report : 검증 보고서 dict(여기서 run_id·manifest 요약을 채운 뒤 JSON으로 저장)
    """
    output_root = Path(output_root)
    run_dir = output_root / config.RUN_DIR_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    entries = {}

    def put(key, rel, writer):
        canonical = output_root / rel
        canonical.parent.mkdir(parents=True, exist_ok=True)
        writer(canonical)
        writer(run_dir / Path(rel).name)
        marker = canonical.with_name(canonical.name + '.stale.json')
        if marker.exists():
            marker.unlink()  # 이 모듈이 만든 표지만 제거한다(현재 실행이 파일을 새로 씀)
        entries[key] = {'canonical_path': Path(rel).as_posix(),
                        'run_path': (config.RUN_DIR_ROOT / run_id / Path(rel).name).as_posix(),
                        'status': STATUS_CURRENT, 'sha256_raw_bytes': _sha_bytes(canonical)}

    for key, frame in tables.items():
        put(key, all_paths[key], lambda p, f=frame: f.to_csv(p, index=False, encoding='utf-8-sig'))
    for key, (rel, text) in texts.items():
        put(key, rel, lambda p, t=text: p.write_text(t, encoding='utf-8'))

    stale = []
    for key, rel in config.PARAMETER_OUTPUTS.items():
        if key in entries:
            continue
        canonical = output_root / rel
        if canonical.exists():
            file_run_id = _file_run_id(canonical)
            entry = {'canonical_path': rel.as_posix(), 'status': STATUS_STALE,
                     'file_run_id': file_run_id, 'sha256_raw_bytes': _sha_bytes(canonical),
                     'note': '현재 실행이 만들지 않은 과거 산출물이다. 삭제하지 않았으며 현재 결과로 사용할 수 없다.'}
            marker = canonical.with_name(canonical.name + '.stale.json')
            marker.write_text(json.dumps({'status': STATUS_STALE, 'current_run_id': run_id,
                                          'file_run_id': file_run_id, 'current_run_mode': run_meta['run_mode'],
                                          'canonical_path': rel.as_posix(),
                                          'sha256_raw_bytes': entry['sha256_raw_bytes'],
                                          'note': entry['note']}, ensure_ascii=False, indent=2),
                              encoding='utf-8')
            stale.append({'key': key, **entry})
        else:
            entry = {'canonical_path': rel.as_posix(), 'status': STATUS_NOT_GENERATED}
        entries[key] = entry

    report['run_id'] = run_id
    report['stale_parameter_outputs_present'] = stale
    report['current_run_manifest'] = config.CURRENT_MANIFEST.as_posix()
    report['run_dir'] = (config.RUN_DIR_ROOT / run_id).as_posix()
    report['outputs_written'] = sorted(e['canonical_path'] for e in entries.values() if e['status'] == STATUS_CURRENT)
    report_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    put('validation_report', config.OUTPUTS['validation_report'], lambda p: p.write_text(report_text, encoding='utf-8'))

    manifest = {'run_id': run_id, **run_meta, 'run_dir': report['run_dir'], 'files': entries}
    text = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)
    (run_dir / 'run_manifest.json').write_text(text, encoding='utf-8')
    current = output_root / config.CURRENT_MANIFEST
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(text, encoding='utf-8')
    return manifest


def load_manifest(output_root):
    path = Path(output_root) / config.CURRENT_MANIFEST
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def current_table_status(output_root, key):
    manifest = load_manifest(output_root)
    if manifest is None:
        return 'NO_CURRENT_MANIFEST'
    return manifest['files'].get(key, {}).get('status', 'UNKNOWN_KEY')


def load_current_table(output_root, key):
    """manifest상 CURRENT인 CSV만 읽는다. CURRENT가 아니면 None, 파일이 manifest와 다르면 StaleOutputError."""
    manifest = load_manifest(output_root)
    if manifest is None:
        return None
    entry = manifest['files'].get(key)
    if entry is None or entry.get('status') != STATUS_CURRENT:
        return None
    path = Path(output_root) / entry['canonical_path']
    if not path.is_file() or _sha_bytes(path) != entry['sha256_raw_bytes']:
        raise StaleOutputError(f'{entry["canonical_path"]}가 현재 실행 manifest의 해시와 다릅니다.')
    frame = pd.read_csv(path)
    frame.columns = [str(c).lstrip('﻿') for c in frame.columns]
    if 'run_id' not in frame or set(frame['run_id'].astype(str)) != {manifest['run_id']}:
        raise StaleOutputError(f'{entry["canonical_path"]}의 run_id가 현재 실행과 다릅니다.')
    return frame
