# -*- coding: utf-8 -*-
"""입력 읽기·해시·출처 기록.

텍스트 입력의 해시는 줄바꿈(CRLF→LF)을 정규화한 SHA-256이다. Git autocrlf 설정에 따라
같은 내용이 다른 해시로 기록되어 fixture 갱신 필요로 오판하지 않도록 하기 위함이다.
"""
import hashlib
import subprocess
from pathlib import Path

import pandas as pd

from . import config


def sha256_text_file(path):
    data = Path(path).read_bytes().replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def sha256_files(root, rel_paths):
    """여러 파일을 경로명과 함께 순서대로 이어 해시한다."""
    h = hashlib.sha256()
    for rel in rel_paths:
        h.update(Path(rel).as_posix().encode('utf-8') + b'\0')
        h.update((Path(root) / rel).read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return h.hexdigest()


def read_csv(path, **kwargs):
    frame = pd.read_csv(path, **kwargs)
    frame.columns = [str(c).lstrip('﻿') for c in frame.columns]
    return frame


class InputRegistry:
    """실행에 사용한 입력의 경로·역할·해시를 기록한다."""

    def __init__(self, root):
        self.root = Path(root)
        self.records = []

    def record(self, rel_path, role, required=True):
        path = self.root / rel_path
        present = path.is_file()
        if required and not present:
            raise FileNotFoundError(f'필수 입력 파일이 없습니다: {Path(rel_path).as_posix()}')
        self.records.append({
            'path': Path(rel_path).as_posix(), 'role': role, 'required': required,
            'present': present, 'sha256': sha256_text_file(path) if present else None,
            'hash_method': config.HASH_METHOD,
            # 기존 outputs/tables/input_provenance.csv와 같은 방식(원본 바이트)의 해시
            'sha256_raw_bytes': hashlib.sha256(path.read_bytes()).hexdigest() if present else None,
        })
        return path if present else None

    def record_override(self, rel_path, role, present):
        """테스트·검증용 입력 대체 기록. 해시는 파일이 아니므로 남기지 않는다."""
        self.records.append({'path': Path(rel_path).as_posix(), 'role': role, 'required': False,
                             'present': present, 'override': True, 'sha256': None,
                             'hash_method': None, 'sha256_raw_bytes': None})

    def sha(self, rel_path):
        key = Path(rel_path).as_posix()
        return next((r['sha256'] for r in self.records if r['path'] == key), None)

    def sha_raw(self, rel_path):
        key = Path(rel_path).as_posix()
        return next((r['sha256_raw_bytes'] for r in self.records if r['path'] == key), None)


def git_state(root):
    """현재 커밋과 작업트리 변경 여부. git이 없으면 None."""
    try:
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True,
                               text=True, check=True).stdout.strip()
        return {'code_commit_sha': sha, 'code_worktree_dirty': bool(dirty)}
    except (OSError, subprocess.CalledProcessError):
        return {'code_commit_sha': None, 'code_worktree_dirty': None}
