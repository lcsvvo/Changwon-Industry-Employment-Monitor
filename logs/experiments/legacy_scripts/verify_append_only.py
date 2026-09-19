# -*- coding: utf-8 -*-
"""electre.py가 이번 세션에서 추가-전용으로만 바뀌었는지 git HEAD와 대조해 증명한다.

주의: 이 스크립트는 src/model/electre.py가 git HEAD에 이미 커밋돼 있다는 전제로
설계됐다. 이 전제가 거짓이면(파일이 untracked이면) git show가 실패하며, 그 경우
이 스크립트로는 "추가-전용"을 증명할 수 없다 — 그 사실을 그대로 보고하고 멈춘다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'src/model/electre.py'


def norm(s):
    return s.replace('\r\n', '\n').rstrip('\n')


def main():
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    if head.returncode != 0:
        print('git rev-parse HEAD 실패:', file=sys.stderr)
        print(head.stderr, file=sys.stderr)
        return 1
    print(f'작업 디렉터리: {ROOT}')
    print(f'HEAD: {head.stdout.strip()}')

    old = subprocess.run(['git', 'show', f'HEAD:{TARGET}'], cwd=ROOT, capture_output=True, text=True,
                         encoding='utf-8')
    if old.returncode != 0:
        print(f'git show HEAD:{TARGET} 실패 — {TARGET}가 HEAD에 존재하지 않습니다(추적 파일이 아님).',
              file=sys.stderr)
        print(old.stderr, file=sys.stderr)
        tracked = subprocess.run(['git', 'ls-files', TARGET], cwd=ROOT, capture_output=True, text=True)
        print(f'git ls-files {TARGET} 결과: {tracked.stdout!r} (빈 문자열이면 미추적)', file=sys.stderr)
        return 1

    new_text = (ROOT / TARGET).read_text(encoding='utf-8')
    old_norm, new_norm = norm(old.stdout), norm(new_text)
    if not new_norm.startswith(old_norm):
        print(f'{TARGET}가 추가-전용이 아닙니다: HEAD 내용이 현재 파일의 접두사가 아닙니다.',
              file=sys.stderr)
        return 1

    added_lines = len(new_norm.split('\n')) - len(old_norm.split('\n'))
    print(f'append-only 확인. HEAD 대비 추가된 줄 수 = {added_lines}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
