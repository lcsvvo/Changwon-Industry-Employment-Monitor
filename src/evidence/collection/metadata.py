# -*- coding: utf-8 -*-
"""수집물 metadata 표준 (data/raw/<source>/_metadata/<name>.json)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

REQUIRED = (
    "dataset_name", "institution", "source_url", "api_endpoint", "retrieved_at",
    "observation_start", "observation_end", "geography", "industry_classification",
    "frequency", "unit", "original_filename", "file_hash_sha256", "api_parameters",
    "pagination", "mapping_notes", "role", "revision_vintage", "terms_limitations",
    "limitations", "notes",
)

SOURCE_DIRS = {
    "kicox_datagokr": Path("kicox/datagokr"),
    "changwon_factory_registry": Path("changwon_factory_registry"),
    "changwon_jobs": Path("employment_center"),
    "customs": Path("customs/legacy"),
    "customs_reference": Path("customs/reference"),
    "customs_trade": Path("customs/trade"),
    "ecos": Path("ecos/api"),
    "employment_insurance": Path("employment_insurance"),
    "kepco": Path("kepco/api"),
}


def raw_source_dir(root: Path, source: str) -> Path:
    """Return the source-based raw directory used by collectors."""
    return Path(root) / "data" / "raw" / SOURCE_DIRS.get(source, Path(source))


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def write_metadata(root: Path, source: str, name: str, **fields) -> Path:
    """필수 키를 모두 채워 metadata JSON 을 쓴다. 누락 키는 명시적으로 null 로 남긴다."""
    meta = {k: fields.get(k) for k in REQUIRED}
    extra = {k: v for k, v in fields.items() if k not in REQUIRED}
    meta.update(extra)
    meta["retrieved_at"] = meta.get("retrieved_at") or utcnow()
    meta["metadata_schema"] = "changwon-external-collection/1.0.0"
    d = raw_source_dir(root, source) / "_metadata"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def save_raw(root: Path, source: str, filename: str, body: bytes) -> Path:
    """원본 바이트를 수정 없이 저장한다."""
    d = raw_source_dir(root, source)
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(body)
    return p
