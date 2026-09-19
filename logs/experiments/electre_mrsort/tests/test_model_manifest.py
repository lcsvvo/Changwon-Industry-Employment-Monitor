# -*- coding: utf-8 -*-
"""provenance·실행별 산출물·stale ELECTRE 산출물 안전장치 테스트.

stale 파일은 임시 디렉터리에만 만든다. 합성 파라미터는 BLOCKED_NOT_REGISTERED 경로 확인용이며
등록 조건을 채우지 않으므로 ELECTRE 점검단계를 만들지 않는다.
"""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import config, manifest, pipeline  # noqa: E402

pytestmark = pytest.mark.skipif(not (ROOT / config.PATHS['state_panel']).is_file(), reason='기준 패널 없음')


@pytest.fixture(scope='module')
def bundle():
    return pipeline.run(ROOT, write=False)


def write_stale(output_root, key, run_id='OLD-REGISTERED-RUN'):
    path = output_root / config.PARAMETER_OUTPUTS[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'run_id,industry,display_class_by_scenario\n{run_id},X,PRIORITY\n', encoding='utf-8')
    return path, path.read_bytes()


# ---------------------------------------------------------------- provenance
def test_every_table_carries_provenance(bundle):
    prov = bundle['provenance']
    raw = next(r['sha256_raw_bytes'] for r in bundle['report']['inputs']
               if r['path'] == config.PATHS['state_panel'].as_posix())
    assert prov['input_sha256_raw_bytes'] == raw
    for key, frame in bundle['tables'].items():
        missing = [c for c in config.PROVENANCE_COLUMNS if c not in frame.columns]
        assert not missing, (key, missing)
        assert set(frame['run_id']) == {bundle['run_id']}, key
        assert set(frame['input_sha256']) == {prov['input_sha256']}, key
        assert set(frame['input_sha256_raw_bytes']) == {raw}, key
        assert set(frame['model_spec_version']) == {config.MODEL_SPEC_VERSION}, key
        assert set(frame['effective_parameter_status']) == {prov['effective_parameter_status']}, key
        assert set(frame['parameter_status']) == {prov['parameter_status']}, key
        assert set(frame['parameter_set_id'].astype(str)) == {str(prov['parameter_set_id'])}, key
        assert set(frame['parameter_file_sha256']) == {prov['parameter_file_sha256']}, key


def test_report_uses_same_run_id(bundle):
    assert bundle['report']['run_id'] == bundle['run_id'] == bundle['provenance']['run_id']
    assert re.fullmatch(r'\d{8}T\d{12}Z-[0-9a-f]{8}', bundle['run_id'])


def test_no_write_creates_nothing(tmp_path):
    pipeline.run(ROOT, write=False, output_root=tmp_path)
    assert not any(tmp_path.iterdir())


# ---------------------------------------------------------------- stale 안전장치
def test_blocked_missing_parameters_marks_old_electre_files_stale(tmp_path):
    stale_path, before = write_stale(tmp_path, 'assignments')
    b = pipeline.run(ROOT, write=True, output_root=tmp_path,
                     params_path=tmp_path / 'intentionally_missing_params.yaml')
    assert b['report']['run_mode'] == 'BLOCKED_MISSING_PARAMETERS'
    assert stale_path.read_bytes() == before, '기존 파일을 삭제·수정하지 않는다'

    current = manifest.load_manifest(tmp_path)
    assert current['run_id'] == b['run_id']
    entry = current['files']['assignments']
    assert entry['status'] == 'STALE_NOT_CURRENT' and entry['file_run_id'] == 'OLD-REGISTERED-RUN'
    marker = json.loads(stale_path.with_name(stale_path.name + '.stale.json').read_text(encoding='utf-8'))
    assert marker['current_run_id'] == b['run_id'] and marker['status'] == 'STALE_NOT_CURRENT'
    assert marker['canonical_path'] == config.PARAMETER_OUTPUTS['assignments'].as_posix()
    assert marker['file_run_id'] == 'OLD-REGISTERED-RUN'
    assert marker['sha256_raw_bytes'] == entry['sha256_raw_bytes']
    assert manifest.load_current_table(tmp_path, 'assignments') is None
    assert current['files']['recent4_stage_history']['status'] == 'NOT_GENERATED_BLOCKED'

    cards_current = manifest.load_current_table(tmp_path, 'cards_csv')
    assert set(cards_current['run_id']) == {b['run_id']}
    report = json.loads((tmp_path / config.OUTPUTS['validation_report']).read_text(encoding='utf-8'))
    assert report['run_id'] == b['run_id']
    assert report['stale_parameter_outputs_present'][0]['canonical_path'] == \
        config.PARAMETER_OUTPUTS['assignments'].as_posix()
    run_dir = tmp_path / config.RUN_DIR_ROOT / b['run_id']
    assert (run_dir / 'run_manifest.json').is_file()
    assert (run_dir / config.OUTPUTS['cards_csv'].name).is_file()
    assert not (run_dir / config.PARAMETER_OUTPUTS['assignments'].name).exists()


def test_blocked_not_registered_marks_old_electre_files_stale(tmp_path):
    doc = yaml.safe_load((ROOT / config.PATHS['params_template']).read_text(encoding='utf-8'))
    doc['parameter_set_id'] = 'UNIT-TEST-UNREGISTERED'
    for s in doc['scenarios']:
        s.update(weights={'g1': 0.25, 'g2': 0.25, 'g3': 0.25, 'g4': 0.25},
                 profiles={'b1': {'g1': 10, 'g2': 1, 'g3': 1, 'g4': 2}, 'b2': {'g1': 20, 'g2': 2, 'g3': 2, 'g4': 3}},
                 delta_emp=0.0, require_employment_evidence=True)
        s['lambda'] = 0.5
    params_path = tmp_path / 'unregistered_params.yaml'
    params_path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    stale_path, before = write_stale(tmp_path, 'scenario_summary')

    b = pipeline.run(ROOT, write=True, output_root=tmp_path, params_path=params_path)
    assert b['report']['run_mode'] == 'BLOCKED_NOT_REGISTERED'
    assert b['assignments'] is None and not b['param_tables']
    assert stale_path.read_bytes() == before
    assert manifest.current_table_status(tmp_path, 'scenario_summary') == 'STALE_NOT_CURRENT'
    assert manifest.load_current_table(tmp_path, 'scenario_summary') is None
    assert set(b['tables']['cards_csv']['parameter_set_id']) == {'UNIT-TEST-UNREGISTERED'}


def test_modified_canonical_file_is_not_read_as_current(tmp_path):
    pipeline.run(ROOT, write=True, output_root=tmp_path)
    path = tmp_path / config.OUTPUTS['cards_csv']
    path.write_text(path.read_text(encoding='utf-8-sig').replace(manifest.load_manifest(tmp_path)['run_id'],
                                                                  'OTHER-RUN'), encoding='utf-8-sig')
    with pytest.raises(manifest.StaleOutputError):
        manifest.load_current_table(tmp_path, 'cards_csv')


def test_new_run_replaces_stale_marker_when_file_is_regenerated(tmp_path):
    pipeline.run(ROOT, write=True, output_root=tmp_path)
    first = manifest.load_manifest(tmp_path)['run_id']
    pipeline.run(ROOT, write=True, output_root=tmp_path)
    second = manifest.load_manifest(tmp_path)['run_id']
    assert first != second
    assert set(manifest.load_current_table(tmp_path, 'input_panel')['run_id']) == {second}


# ---------------------------------------------------------------- notebook
def test_notebook_reads_electre_outputs_only_through_manifest():
    nb = json.loads((ROOT / 'notebooks' / '04_decision_support_model.ipynb').read_text(encoding='utf-8'))
    code = '\n'.join(''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code')
    assert 'read_csv' not in code
    for path in config.PARAMETER_OUTPUTS.values():
        assert path.name not in code, path.name
    assert "manifest.load_current_table(ROOT, 'assignments')" in code
