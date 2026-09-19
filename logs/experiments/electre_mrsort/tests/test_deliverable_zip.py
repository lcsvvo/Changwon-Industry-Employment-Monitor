# -*- coding: utf-8 -*-
"""전달물 정리: __pycache__·*.pyc가 저장소 추적 대상과 배포 ZIP에서 제외되는지 확인한다."""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import build_deliverable_zip as bdz  # noqa: E402


@pytest.mark.parametrize('name, excluded', [
    ('src/model/__pycache__/config.cpython-314.pyc', True),
    ('src/x.pyc', True), ('src/x.pyo', True),
    ('notebooks/.ipynb_checkpoints/a.ipynb', True),
    ('src/model/config.py', False), ('tests/fixtures/model_regression_fixture.json', False),
])
def test_is_excluded(name, excluded):
    assert bdz.is_excluded(name) is excluded


def test_gitignore_covers_bytecode_caches():
    text = (ROOT / '.gitignore').read_text(encoding='utf-8')
    assert '__pycache__/' in text and '*.py[cod]' in text


def test_no_bytecode_tracked_or_listed_for_zip():
    try:
        tracked = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('git을 사용할 수 없습니다.')
    assert not [n for n in tracked.splitlines() if bdz.is_excluded(n)]
    files = bdz.deliverable_files(ROOT)
    assert files and not [n for n in files if bdz.is_excluded(n)]
    assert 'src/model/pipeline.py' in files


def test_deliverable_contains_reproduction_contract():
    files = set(bdz.deliverable_files(ROOT))
    required = {
        'src/model/pipeline.py', 'src/run_decision_support_model.py', 'src/build_deliverable_zip.py',
        'config/electre_tri_b_params.template.yaml', 'config/parameter_briefing.md',
        'config/stage_actions.template.yaml', 'notebooks/04_decision_support_model.ipynb',
        'tests/fixtures/model_regression_fixture.json', 'requirements.txt', 'README.md',
        'data/processed/model/electre_input_panel.csv',
    }
    assert required <= files, sorted(required - files)


def test_build_excludes_caches(tmp_path):
    (tmp_path / '__pycache__').mkdir()
    for name in ['a.py', '__pycache__/a.cpython-314.pyc', 'b.pyc']:
        (tmp_path / name).write_text('x', encoding='utf-8')
    out, n = bdz.build(tmp_path / 'deliverable.zip', root=tmp_path,
                       files=['a.py', '__pycache__/a.cpython-314.pyc', 'b.pyc'])
    assert n == 1
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ['a.py']
