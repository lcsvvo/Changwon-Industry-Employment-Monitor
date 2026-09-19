# -*- coding: utf-8 -*-
"""보호정책 V2 회귀검사.

기존 `tests/test_hybrid_validation.py` 는 손대지 않았다. 그 파일의
`test_lock_and_original_outputs_unchanged` 는 V1 정책 기준의 검사이고,
`run_metadata.json`(runtime)과 `README.md`(documentation) 때문에 여전히 실패한다.
그 실패를 느슨하게 만들거나 숨기지 않는다 — 여기서는 **다른 질문**을 검사한다.

    V1 질문 : 잠금 당시의 125개 파일 바이트가 전부 그대로인가?
    V2 질문 : 모형 결과와 프로토콜이 그대로인가? (runtime·문서 변경은 별개로 취급)

검사 묶음
    test_deterministic_outputs_unchanged      B 범주 바이트 고정
    test_protocol_files_unchanged             A 범주 바이트 고정
    test_runtime_metadata_schema              C 범주 — 바이트가 아니라 스키마·결정적 필드
    test_documentation_not_in_output_freeze   D 범주가 모형 결과 검사에 섞이지 않는지
    회귀검사 8절                               Triage/rolling/hybrid 결과 불변
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reproducibility import policy as P                # noqa: E402

MANIFEST_PATH = ROOT / "outputs/reproducibility/FREEZE_MANIFEST_V2.json"
EXPECTED_STAGES = {"관찰": 128, "추가확인": 35, "우선점검": 17}


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST_PATH.exists():
        pytest.skip("V2 매니페스트 없음 — python scripts/build_freeze_manifest_v2.py 먼저 실행")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _check_bytes(entries: list[dict]) -> list[str]:
    bad = []
    for e in entries:
        p = ROOT / e["path"]
        if not e.get("exists"):
            bad.append(f"{e['path']}: 매니페스트에 있으나 파일이 없다")
            continue
        if P.sha256_file(p) != e["sha256"]:
            bad.append(f"{e['path']}: sha256 불일치")
    return bad


# ---------------------------------------------------------------- A 범주
def test_protocol_files_unchanged(manifest):
    """프로토콜·실행잠금·승인 당시 사양의 바이트가 그대로인가."""
    entries = manifest["immutable_protocol_files"]
    assert len(entries) >= 15
    assert not _check_bytes(entries)


def test_existing_locks_are_not_rewritten(manifest):
    """V2 작업이 기존 잠금 파일을 건드리지 않았는지."""
    for parent in manifest["parent_manifest"]:
        p = ROOT / parent["path"]
        assert p.exists(), f"기존 잠금이 사라졌다: {parent['path']}"
        assert P.sha256_file(p) == parent["sha256"], (
            f"기존 잠금이 수정됐다: {parent['path']}")


def test_v1_failure_record_is_preserved_not_overwritten(manifest):
    """V1 실패를 성공으로 덮어쓰지 않았는지. 기록이 사실과 일치하는지."""
    rec = manifest["v1_lock_state_at_v2_creation"]
    assert rec["v1_protected_file_count"] == 125
    assert rec["mismatched"] == 2, "V1 불일치 건수 기록이 사실과 다르다"
    assert rec["matched"] == 123
    paths = {m["path"] for m in rec["mismatched_files"]}
    assert paths == {"outputs/decision_support_final/run_metadata.json", "README.md"}
    # 각 불일치가 V2 에서 어느 범주로 재분류됐는지 명시되어 있어야 한다
    cats = {m["path"]: m["v2_category"] for m in rec["mismatched_files"]}
    assert cats["outputs/decision_support_final/run_metadata.json"] == P.RUNTIME_METADATA
    assert cats["README.md"] == P.MUTABLE_DOCUMENTATION
    # 경위 문서가 남아 있어야 한다
    amendment = ROOT / "outputs/robustness_extension/PROTECTED_HASH_AMENDMENT.md"
    assert amendment.exists()


# ---------------------------------------------------------------- B 범주
def test_deterministic_outputs_unchanged(manifest):
    """입력·판정코드·설정·결정적 산출물의 바이트가 그대로인가."""
    entries = manifest["deterministic_protected_files"]
    assert len(entries) >= 80
    assert not _check_bytes(entries)


def test_deterministic_set_covers_the_decisive_artifacts(manifest):
    """보호 대상에서 핵심 산출물이 빠지지 않았는지 (범위 축소 방지)."""
    paths = {e["path"] for e in manifest["deterministic_protected_files"]}
    must = {
        "outputs/decision_support_final/decision_panel.csv",
        "outputs/decision_support_final/decision_latest.csv",
        "outputs/decision_support_final/stage_distribution_by_quarter.csv",
        "outputs/decision_support_final/diagnostic_cards_latest.csv",
        "outputs/rolling_backtest/predictions_long.csv",
        "outputs/rolling_backtest/outcomes_long.csv",
        "outputs/hybrid_validation/hybrid_predictions.csv",
        "outputs/hybrid_validation/hybrid_overlap.csv",
        "src/model/triage_rule.py",
        "src/run_triage_rule.py",
        "data/processed/kicox/changwon_industry_master.csv",
    }
    assert must <= paths, f"보호 대상에서 빠진 핵심 파일: {sorted(must - paths)}"


# ---------------------------------------------------------------- C 범주
def test_runtime_metadata_schema(manifest):
    """runtime metadata 는 바이트가 아니라 스키마로 검사한다."""
    entries = manifest["runtime_metadata_files"]
    assert len(entries) >= 10
    for e in entries:
        assert e["sha256"] is None, (
            f"{e['path']}: runtime 파일에 구속력 있는 해시가 걸렸다")
        assert "sha256_informational" in e or not e.get("exists")
        for field in e.get("deterministic_fields", []):
            p = ROOT / e["path"]
            if not p.exists():
                continue
            meta = json.loads(p.read_text(encoding="utf-8"))
            assert field in meta, f"{e['path']}: 결정적 필드 {field} 가 없다"


def test_runtime_metadata_static_split_is_canonical():
    """static 부분만으로 계산한 canonical 해시가 재계산과 일치하는가."""
    src = ROOT / "outputs/decision_support_final/run_metadata.json"
    derived = ROOT / "outputs/reproducibility/run_metadata_static.json"
    if not derived.exists():
        pytest.skip("파생 static metadata 없음")
    meta = json.loads(src.read_text(encoding="utf-8"))
    static, runtime = P.split_run_metadata(meta)
    stored = json.loads(derived.read_text(encoding="utf-8"))
    assert stored["static"] == static
    assert P.canonical_hash(static) == P.canonical_hash(stored["static"])
    # runtime 필드는 static 에 남아 있으면 안 된다
    assert not (set(static) & P.RUNTIME_KEYS)
    # 실제로 갈라놓은 runtime 필드가 존재해야 한다 (분리가 형식만인지 확인)
    assert {"run_at_utc", "git_head"} <= set(runtime)


def test_original_run_metadata_is_not_rewritten(manifest):
    """원본 run_metadata.json 을 사후 수정해 옛 해시를 맞추려 하지 않았는지."""
    split = manifest["run_metadata_split"]
    src = ROOT / split["source"]
    assert P.sha256_file(src) == split["source_file_sha256"]
    v1_locked = {m["path"]: m["locked_sha256"]
                 for m in manifest["v1_lock_state_at_v2_creation"]["mismatched_files"]}
    assert P.sha256_file(src) != v1_locked["outputs/decision_support_final/run_metadata.json"], (
        "원본을 되돌려 V1 해시를 맞춘 흔적이 있다 — 이번 정책은 그렇게 하지 않는다")


# ---------------------------------------------------------------- D 범주
def test_documentation_not_in_output_freeze(manifest):
    """문서가 모형 결과 동결 대상에 섞여 있지 않은가."""
    doc_paths = {e["path"] for e in manifest["mutable_documentation_files"]}
    protected = ({e["path"] for e in manifest["deterministic_protected_files"]}
                 | {e["path"] for e in manifest["immutable_protocol_files"]})
    assert not (doc_paths & protected)
    assert "README.md" in doc_paths
    assert "PROJECT_STRUCTURE.md" in doc_paths
    for e in manifest["mutable_documentation_files"]:
        assert e["sha256"] is None, f"{e['path']}: 문서에 구속력 있는 해시가 걸렸다"


def test_readme_change_is_not_a_model_output_failure(manifest):
    """README 가 바뀌어도 B·A 범주 검사에는 영향이 없어야 한다."""
    readme = ROOT / "README.md"
    assert readme.exists()
    doc_entry = next(e for e in manifest["mutable_documentation_files"]
                     if e["path"] == "README.md")
    current = P.sha256_file(readme)
    # 현재 바이트가 참고값과 달라도 A·B 검사는 그대로 통과해야 한다
    assert doc_entry["sha256"] is None
    assert not _check_bytes(manifest["deterministic_protected_files"])
    assert not _check_bytes(manifest["immutable_protocol_files"])
    assert isinstance(current, str) and len(current) == 64


# ---------------------------------------------------------------- 8절 회귀검사
def test_triage_180_rows_and_stage_distribution_unchanged():
    d = pd.read_csv(ROOT / "outputs/decision_support_final/decision_panel.csv")
    d.columns = [c.lstrip("﻿") for c in d.columns]
    assert len(d) == 180
    assert d["stage"].value_counts().to_dict() == EXPECTED_STAGES


def test_decision_artifacts_match_manifest_hashes(manifest):
    wanted = {
        "outputs/decision_support_final/decision_panel.csv",
        "outputs/decision_support_final/decision_latest.csv",
        "outputs/decision_support_final/stage_distribution_by_quarter.csv",
        "outputs/decision_support_final/diagnostic_cards_latest.csv",
        "outputs/decision_support_final/diagnostic_cards_latest.json",
        "outputs/decision_support_final/diagnostic_cards_latest.md",
    }
    entries = [e for e in manifest["deterministic_protected_files"] if e["path"] in wanted]
    assert len(entries) == len(wanted)
    assert not _check_bytes(entries)


def test_rolling_and_hybrid_deterministic_outputs_unchanged(manifest):
    entries = [e for e in manifest["deterministic_protected_files"]
               if e["path"].startswith(("outputs/rolling_backtest/",
                                        "outputs/hybrid_validation/"))]
    assert len(entries) >= 12
    assert not _check_bytes(entries)
    # 기존 잠금이 기록한 해시와도 여전히 일치하는지 (역사적 결과 불변)
    roll = json.loads((ROOT / "outputs/rolling_backtest/PREDICTION_LOCK.json")
                      .read_text(encoding="utf-8"))
    assert P.sha256_file(ROOT / "outputs/rolling_backtest/predictions_long.csv") == \
        roll["prediction_sha256"]
    hyb = json.loads((ROOT / "outputs/hybrid_validation/PREDICTION_LOCK.json")
                     .read_text(encoding="utf-8"))
    assert P.sha256_file(ROOT / "outputs/hybrid_validation/hybrid_predictions.csv") == \
        hyb["prediction_sha256"]
    assert P.sha256_file(ROOT / "outputs/hybrid_validation/hybrid_overlap.csv") == \
        hyb["overlap_sha256"]


def test_context_layer_does_not_overwrite_triage_fields():
    ctx_path = ROOT / "data/processed/context/industry_context_signals.csv"
    if not ctx_path.exists():
        pytest.skip("해석층 산출물 없음")
    tri = pd.read_csv(ROOT / "outputs/decision_support_final/decision_panel.csv")
    tri.columns = [c.lstrip("﻿") for c in tri.columns]
    ctx = pd.read_csv(ctx_path)
    ctx.columns = [c.lstrip("﻿") for c in ctx.columns]
    m = tri[["industry", "quarter", "stage", "employment"]].merge(
        ctx[["industry", "quarter", "stage", "employment"]],
        on=["industry", "quarter"], suffixes=("_tri", "_ctx"))
    assert len(m) == 180
    assert m["stage_tri"].equals(m["stage_ctx"])
    assert m["employment_tri"].equals(m["employment_ctx"])
