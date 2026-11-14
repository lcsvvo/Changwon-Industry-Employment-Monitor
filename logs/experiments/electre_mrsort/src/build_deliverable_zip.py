# -*- coding: utf-8 -*-
"""전달용 ZIP 생성.

Git이 추적하는 파일과 .gitignore에 걸리지 않는 새 파일만 담는다. .gitignore와 무관하게
__pycache__, *.pyc, *.pyo, .ipynb_checkpoints는 항상 제외한다.

실행
    python src/build_deliverable_zip.py
    python src/build_deliverable_zip.py --output outputs/custom_deliverable.zip
"""
import argparse
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {'__pycache__', '.ipynb_checkpoints', '.pytest_cache'}
EXCLUDED_SUFFIXES = ('.pyc', '.pyo')


def is_excluded(name):
    path = PurePosixPath(name)
    return bool(EXCLUDED_DIRS & set(path.parts)) or path.name.endswith(EXCLUDED_SUFFIXES)


def deliverable_files(root=ROOT):
    out = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                         cwd=root, capture_output=True, check=True).stdout.decode('utf-8')
    names = {n for n in out.split('\0') if n}
    return sorted(n for n in names if not is_excluded(n) and (Path(root) / n).is_file())


def build(output, root=ROOT, files=None):
    output = Path(output).resolve()
    files = deliverable_files(root) if files is None else [f for f in files if not is_excluded(f)]
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            if Path(root, name).resolve() == output:
                continue
            zf.write(Path(root) / name, arcname=name)
    return output, len(files)


def main(argv=None):
    parser = argparse.ArgumentParser(description='전달용 ZIP 생성(__pycache__·*.pyc 제외)')
    parser.add_argument('--output', default=str(ROOT / 'outputs' / 'changwon_deliverable.zip'),
                        help='생성할 ZIP 경로(기본: outputs/changwon_deliverable.zip)')
    args = parser.parse_args(argv)
    path, n = build(args.output)
    print(f'{path} ({n} files)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
