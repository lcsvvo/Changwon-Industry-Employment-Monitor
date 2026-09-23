"""등록된 분석본(Snapshot) 두 버전의 차이 계산 — 읽기 전용.

- 분석 판정값(CORE: 생산·고용·Q1~Q3·E/R/A/P·Triage·자료품질)과 부가정보(외부자료·확인질문·선택적 재검토 등)를
  나눠 비교한다. 어느 쪽도 Snapshot 파일을 수정하지 않는다.
- 변화량으로 재검토 플래그를 붙이는 기준은 승인되지 않았다. 따라서 review_flag 는 만들지 않고(None),
  차이를 계산해 보여주기만 한다.
"""
from __future__ import annotations

from export.snapshot import Snapshot

CORE_SECTIONS = ("activity", "q1", "q2", "q3", "signals", "triage", "data_quality")
KEY_FIELDS = ("industry", "quarter", "quarter_end")
META_CORE = ("rule_version", "parameter_spec", "scenario_status", "window", "record_scope")
META_AUX = ("export_contract_version", "evidence_layer_version")
# 재검토 플래그 정책: 기준값이 승인되지 않았으므로 의도적으로 비활성(버그가 아님).
# 기준이 승인되면 이 값과 threshold 를 함께 바꾸고, 그 전까지 자동 플래그는 0건이어야 한다.
REVIEW_FLAG_ENABLED = False
THRESHOLD_STATUS = "not_configured"
REVIEW_THRESHOLD_LABEL = "자동 재검토 기준 미설정"

CORE_CHANGED = "분석 판정값 변경 있음"
AUX_ONLY = "분석 판정값 변경 없음 · 부가정보 갱신"
NO_CHANGE = "변경 없음"

# 화면용 핵심 필드 라벨(없는 필드는 경로 그대로)
FIELD_LABEL = {
    "activity.production": "생산액", "activity.production_yoy": "생산 YoY",
    "q1.state": "Q1 상태", "q2.employment": "고용", "q2.emp_delta": "고용 증감",
    "q2.employment_yoy": "고용 YoY", "q2.contribution_pct": "순감소 기여율",
    "q3.state_run_length": "Q3 상태 지속", "q3.repeated_signal": "Q3 반복 신호",
    "signals.E": "E", "signals.R": "R", "signals.A": "A", "signals.P": "P",
    "triage.stage": "Triage 단계", "triage.stage_reason": "판정 사유",
}
MISSING = object()


def _flatten(value, prefix: str, out: dict) -> dict:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{prefix}.{k}" if prefix else k, out)
    else:
        out[prefix] = value
    return out


def _compare(old: dict, new: dict, sections) -> tuple[list[dict], set[str], set[str]]:
    a, b = {}, {}
    for sec in sections:
        if sec in old:
            _flatten(old[sec], sec, a)
        if sec in new:
            _flatten(new[sec], sec, b)
    changes = [{"field": k, "label": FIELD_LABEL.get(k, k), "old": a[k], "new": b[k]}
               for k in a.keys() & b.keys() if a[k] != b[k]]
    return sorted(changes, key=lambda c: c["field"]), set(b) - set(a), set(a) - set(b)


def record_diff(old: dict | None, new: dict | None) -> dict:
    """업종×분기 레코드 하나의 CORE / 부가정보 차이."""
    if old is None or new is None:
        return {"missing": "old" if old is None else "new", "core_changes": [], "aux_changes": []}
    aux_sections = sorted((set(old) | set(new)) - set(CORE_SECTIONS) - set(KEY_FIELDS))
    core, core_add, core_rm = _compare(old, new, CORE_SECTIONS)
    aux, aux_add, aux_rm = _compare(old, new, aux_sections)
    return {"missing": None, "core_changes": core, "core_fields_added": sorted(core_add),
            "core_fields_removed": sorted(core_rm), "aux_changes": aux,
            "aux_fields_added": sorted(aux_add), "aux_fields_removed": sorted(aux_rm),
            "aux_sections_added": sorted(set(new) - set(old) - set(CORE_SECTIONS)),
            "aux_sections_removed": sorted(set(old) - set(new) - set(CORE_SECTIONS))}


def snapshot_diff(old: Snapshot, new: Snapshot) -> dict:
    """두 분석본의 차이. 같은 분석대상 분기의 다른 버전 비교를 기본으로 한다."""
    keys_old, keys_new = set(old.records), set(new.records)
    core_records, aux_records, core_changes = [], [], []
    aux_added, aux_sections_added = set(), set()
    for key in sorted(keys_old & keys_new):
        d = record_diff(old.records[key], new.records[key])
        if d["core_changes"] or d["core_fields_added"] or d["core_fields_removed"]:
            core_records.append(key)
            core_changes += [{"industry": key[0], "quarter": key[1], **c} for c in d["core_changes"]]
        if d["aux_changes"] or d["aux_fields_added"] or d["aux_fields_removed"]:
            aux_records.append(key)
        aux_added |= set(d["aux_fields_added"])
        aux_sections_added |= set(d["aux_sections_added"])
    meta_core = [k for k in META_CORE if old.meta.get(k) != new.meta.get(k)]
    meta_aux = [k for k in META_AUX if old.meta.get(k) != new.meta.get(k)]
    src_old = {r["key"] for r in old.meta.get("provenance_refs", [])}
    src_new = {r["key"] for r in new.meta.get("provenance_refs", [])}
    only_old, only_new = sorted(keys_old - keys_new), sorted(keys_new - keys_old)

    if core_records or meta_core or only_old or only_new:
        verdict = CORE_CHANGED
    elif aux_records or meta_aux or src_old != src_new or old.meta["data_hash"] != new.meta["data_hash"]:
        verdict = AUX_ONLY
    else:
        verdict = NO_CHANGE
    return {
        "old": f"{old.quarter} {old.version}", "new": f"{new.quarter} {new.version}",
        "verdict": verdict,
        "core_changed_records": core_records, "core_changes": core_changes,
        "core_meta_changed": meta_core,
        "records_only_in_old": only_old, "records_only_in_new": only_new,
        "aux_changed_records": aux_records, "aux_sections_added": sorted(aux_sections_added),
        "aux_fields_added": sorted(aux_added), "aux_meta_changed": {k: (old.meta.get(k), new.meta.get(k)) for k in meta_aux},
        "sources_added": sorted(src_new - src_old), "sources_removed": sorted(src_old - src_new),
        "data_hash_changed": old.meta["data_hash"] != new.meta["data_hash"],
        "review_flag_enabled": REVIEW_FLAG_ENABLED, "threshold_status": THRESHOLD_STATUS,
        "review_flag": None, "review_threshold": None, "review_threshold_label": REVIEW_THRESHOLD_LABEL,
    }
