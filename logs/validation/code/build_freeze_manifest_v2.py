# -*- coding: utf-8 -*-
"""V2 동결 매니페스트와 static/runtime 분리 metadata 생성.

기존 매니페스트·잠금은 읽기만 한다. 지우지도, 덮어쓰지도 않는다.
`outputs/decision_support_final/run_metadata.json` 원본도 고치지 않는다 —
static 부분만 따로 뽑아 파생 파일로 저장한다.

실행:  python scripts/build_freeze_manifest_v2.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reproducibility import policy as P                # noqa: E402

OUT = ROOT / "outputs" / "reproducibility"
SOURCE_RUN_METADATA = ROOT / "outputs" / "decision_support_final" / "run_metadata.json"


def split_metadata_files() -> dict:
    """run_metadata.json 을 static / runtime 파생 파일로 나눠 쓴다."""
    meta = json.loads(SOURCE_RUN_METADATA.read_text(encoding="utf-8"))
    static, runtime = P.split_run_metadata(meta)
    OUT.mkdir(parents=True, exist_ok=True)
    header = {
        "_derived_from": SOURCE_RUN_METADATA.relative_to(ROOT).as_posix(),
        "_source_file_sha256": P.sha256_file(SOURCE_RUN_METADATA),
        "_policy_version": P.POLICY_VERSION,
        "_note": ("원본 run_metadata.json 은 수정하지 않는다. 이 파일은 파생물이며, "
                  "재현성 판정에 쓰는 canonical 해시는 static 영역에서만 계산한다."),
    }
    (OUT / "run_metadata_static.json").write_text(
        json.dumps({**header, "static": static}, ensure_ascii=False, indent=2,
                   sort_keys=True), encoding="utf-8")
    (OUT / "run_metadata_runtime.json").write_text(
        json.dumps({**header,
                    "_note": "실행시각·환경 필드. 재현성 판정에 쓰지 않는다.",
                    "runtime": runtime}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return {
        "source": SOURCE_RUN_METADATA.relative_to(ROOT).as_posix(),
        "source_file_sha256": P.sha256_file(SOURCE_RUN_METADATA),
        "static_file": "outputs/reproducibility/run_metadata_static.json",
        "runtime_file": "outputs/reproducibility/run_metadata_runtime.json",
        **P.describe_split(meta),
    }


def parent_manifest_state() -> list[dict]:
    """기존 잠금들의 현재 상태를 '읽어서' 기록한다. 고치지 않는다."""
    out = []
    for rel in P.PARENT_MANIFESTS:
        p = ROOT / rel
        out.append(dict(path=rel, exists=p.exists(),
                        sha256=P.sha256_file(p) if p.exists() else None,
                        treatment="역사적 감사기록 — 수정·삭제하지 않는다"))
    return out


def v1_mismatch_record() -> dict:
    """V1 보호목록의 현재 불일치를 사실 그대로 옮긴다(성공으로 덮지 않는다)."""
    lock_path = ROOT / "outputs/hybrid_validation/EXECUTION_LOCK.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    protected = lock["protected_hashes"]
    match, mismatch, missing = [], [], []
    for rel, want in protected.items():
        p = ROOT / rel
        if not p.exists():
            missing.append(rel)
        elif P.sha256_file(p) == want:
            match.append(rel)
        else:
            mismatch.append(dict(path=rel, locked_sha256=want,
                                 current_sha256=P.sha256_file(p)))
    cats = {r["path"]: r["category"] for r in P.classification()}
    for m in mismatch:
        m["v2_category"] = cats.get(m["path"], "UNCLASSIFIED")
    return {
        "v1_lock": lock_path.relative_to(ROOT).as_posix(),
        "v1_protected_file_count": len(protected),
        "matched": len(match),
        "mismatched": len(mismatch),
        "missing": missing,
        "mismatched_files": mismatch,
        "status": ("V1 정책 기준으로 여전히 실패 상태다. 이 기록을 성공으로 바꾸지 않는다. "
                   "경위는 outputs/robustness_extension/PROTECTED_HASH_AMENDMENT.md 참조."),
    }


def main() -> int:
    # static/runtime 파생 파일을 먼저 써야 아래 해시 수집에 포함된다.
    split = split_metadata_files()
    rows = P.classification()
    entries, missing = [], []
    for r in rows:
        p = ROOT / r["path"]
        e = dict(r)
        if not p.exists():
            e["exists"] = False
            e["sha256"] = None
            missing.append(r["path"])
        else:
            e["exists"] = True
            digest = P.sha256_file(p)
            e["sha256"] = digest if r["hash_protected"] else None
            if not r["hash_protected"]:
                # C·D 는 참고용으로만 남긴다. 불일치가 모형 결과 불일치가 아니다.
                e["sha256_informational"] = digest
        entries.append(e)

    by_cat: dict[str, list[dict]] = {}
    for e in entries:
        by_cat.setdefault(e["category"], []).append(e)

    manifest = {
        "policy_version": P.POLICY_VERSION,
        "policy_document": "docs/reproducibility/PROTECTION_POLICY_V2.md",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "parent_manifest": parent_manifest_state(),
        "reason_for_policy_revision": P.REASON_FOR_POLICY_REVISION,
        "hash_protected_categories": list(P.HASH_PROTECTED_CATEGORIES),
        "hash_method": "sha256 over raw file bytes",
        "runtime_keys_excluded_from_canonical_hash": sorted(P.RUNTIME_KEYS),
        "immutable_protocol_files": by_cat.get(P.IMMUTABLE_PROTOCOL, []),
        "deterministic_protected_files": by_cat.get(P.DETERMINISTIC_PROTECTED, []),
        "runtime_metadata_files": by_cat.get(P.RUNTIME_METADATA, []),
        "mutable_documentation_files": by_cat.get(P.MUTABLE_DOCUMENTATION, []),
        "run_metadata_split": split,
        "v1_lock_state_at_v2_creation": v1_mismatch_record(),
        "missing_files": missing,
        "notes": [
            "A(IMMUTABLE_PROTOCOL)·B(DETERMINISTIC_PROTECTED) 만 바이트 해시 보호 대상이다.",
            "C(RUNTIME_METADATA)·D(MUTABLE_DOCUMENTATION) 의 해시 불일치는 "
            "모형 결과 불일치로 처리하지 않는다. sha256_informational 은 참고값이다.",
            "C 파일 중 일부는 내부에 결정적 필드를 갖는다. 그 필드만 "
            "deterministic_fields 로 지정해 따로 검사한다.",
            "기존 V1 잠금은 그대로 두었고, 당시 불일치 2건도 지우지 않았다.",
            "이 매니페스트는 성능·판정 결과를 바꾸지 않는다. 보호 범위만 정의한다.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "FREEZE_MANIFEST_V2.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] {path.relative_to(ROOT)}")
    for cat in (P.IMMUTABLE_PROTOCOL, P.DETERMINISTIC_PROTECTED,
                P.RUNTIME_METADATA, P.MUTABLE_DOCUMENTATION):
        n = len(by_cat.get(cat, []))
        prot = "해시 보호" if cat in P.HASH_PROTECTED_CATEGORIES else "보호 대상 아님"
        print(f"     {cat:24s} {n:3d}건  ({prot})")
    if missing:
        print(f"     [주의] 매니페스트에 있으나 없는 파일 {len(missing)}건: {missing}")
    v1 = manifest["v1_lock_state_at_v2_creation"]
    print(f"     V1 잠금 상태 보존: {v1['matched']}/{v1['v1_protected_file_count']} 일치, "
          f"{v1['mismatched']}건 불일치(그대로 기록)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
