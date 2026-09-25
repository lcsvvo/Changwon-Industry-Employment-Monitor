"""기존 분석 산출물 → 불변 Snapshot 변환·등록·조회.

구조: 기존 Python 분석 pipeline → 검증된 산출물(outputs/final_model) → Export(이 모듈) → Snapshot → Application.

- 분석값을 다시 계산하지 않는다. 원천 행을 key(industry, quarter)로 읽어 필드만 옮긴다.
- 원천이 없는 항목은 null 과 사유로 남기며, 다른 분기 값을 빌려오지 않는다.
- 같은 기준분기의 새 run 은 v2, v3… 로 추가되고 기존 버전은 덮어쓰지 않는다.
- (기준분기, 버전)은 한번 발급되면 그 내용과 영구히 묶인다. 발급 이력은 snapshots/registry.json 에
  추가만 하므로, 버전 폴더가 지워져도 그 번호는 다시 발급되지 않는다(점검 건·회차·변경 기록·후보 검토가 참조).
- 보관(archived)·무효(invalidated)는 폴더를 지우지 않고 registry 의 상태 이벤트로만 남긴다.

실행: python -m export.snapshot   (src 를 PYTHONPATH 에 둔 상태)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from export import schema as S

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT = ROOT / "snapshots"
META_FILE = "snapshot_meta.json"
DIAGNOSIS_FILE = "industry_diagnosis.json"
REFERENCE_FILE = "reference.json"
REGISTRY_FILE = "registry.json"  # 버전 폴더 밖: 발급 이력·상태 이벤트(추가만 한다)
REGISTRY_SCHEMA = "snapshot-registry/1"
SNAPSHOT_STATUSES = ("active", "archived", "invalidated")


class ExportContractError(RuntimeError):
    """원천 산출물이 Export 계약(키·단계 보존)을 어겼을 때."""


class SnapshotIntegrityError(RuntimeError):
    """등록된 Snapshot 파일이 등록 당시와 달라졌을 때."""


class SnapshotMissingError(FileNotFoundError):
    """요청한 (기준분기, 버전)의 Snapshot 폴더가 없을 때. 최신 분석본으로 대신하지 않는다."""


# ---------------------------------------------------------------- 값 변환
def _native(value, field: str | None = None):
    """pandas/numpy 값을 JSON 값으로. NaN → None. 정수 필드만 int 로."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if field in S.INT_FIELDS and isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.replace("\r\n", "\n")
    return value


def _split_questions(text):
    if text is None:
        return []
    return [line.strip() for line in re.split(r"\r?\n", str(text)) if line.strip()]


def _sha256(path: Path) -> str:
    """줄바꿈(CRLF/LF)을 정규화한 내용 해시. git autocrlf 로 OS 마다 바이트가 달라도 같은 원천은 같은 해시."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", float_precision="round_trip")


def _index(df: pd.DataFrame, name: str) -> dict:
    if df.duplicated(list(S.KEY)).any():
        raise ExportContractError(f"{name}: (industry, quarter) 중복")
    return {(r["industry"], r["quarter"]): r for _, r in df.iterrows()}


# ---------------------------------------------------------------- 빌드
def _load_sources(source_root: Path) -> dict:
    missing = [v["path"] for v in S.SOURCES.values() if not (source_root / v["path"]).exists()]
    if missing:
        raise FileNotFoundError(f"원천 산출물 없음: {missing}")
    p = {k: source_root / v["path"] for k, v in S.SOURCES.items()}
    return {
        "paths": p,
        "triage": _read_csv(p["triage_panel"]),
        "distribution": _read_csv(p["triage_distribution_by_quarter"]),
        "trace": _read_csv(p["explanation_trace"]),
        "context_q": _read_csv(p["check_questions_context_panel"]),
        "ext_panel": _read_csv(p["external_evidence_panel"]),
        "roles": _read_csv(p["data_role_table"]),
        "jobs_meta": json.loads(p["recruiting_snapshot_metadata"].read_text(encoding="utf-8")),
        "handoff": json.loads(p["handoff_cards_latest"].read_text(encoding="utf-8")),
        "routing": _read_csv(p["institution_routing_map"]),
        "electre": _read_csv(p["electre_smaa_review_cases"]),
        "protocol": json.loads(p["electre_smaa_protocol"].read_text(encoding="utf-8")),
        "evidence": _read_csv(p["external_evidence_summary"]),
        "cards": _read_csv(p["external_evidence_card_preview"]),
        "triage_meta": json.loads(p["triage_run_metadata"].read_text(encoding="utf-8")),
        "evidence_meta": json.loads(p["external_evidence_run_metadata"].read_text(encoding="utf-8")),
    }


def _check_contract(src: dict) -> None:
    """원천 간 key·stage 정합만 확인한다(재판정 아님)."""
    triage = src["triage"]
    stage = {(r.industry, r.quarter): r.stage for r in triage.itertuples()}
    if set(triage.stage.unique()) - set(S.TRIAGE_STAGES):
        raise ExportContractError(f"알 수 없는 Triage 단계: {set(triage.stage.unique())}")
    for name in ("trace", "electre", "evidence"):
        df = src[name]
        col = "triage_stage_preserved" if name == "electre" else "stage"
        for r in df.itertuples():
            key = (r.industry, r.quarter)
            if key not in stage:
                raise ExportContractError(f"{name}: triage_panel 에 없는 key {key}")
            if getattr(r, col) != stage[key]:
                raise ExportContractError(f"{name}: {key} 단계 불일치 {getattr(r, col)} ≠ {stage[key]}")
    # 맥락 확인질문 패널: 180행 전부, 기본 질문·단계는 triage_panel 과, context 는 기존 산출물과 같아야 한다.
    cq = src["context_q"]
    if len(cq) != len(triage) or set(zip(cq.industry, cq.quarter)) != set(stage):
        raise ExportContractError("check_questions_context_panel: triage_panel 과 key 집합 불일치")
    base_q = {(r.industry, r.quarter): r.check_question for r in triage.itertuples()}
    ctx = {}
    for r in cq.itertuples():
        key = (r.industry, r.quarter)
        if r.stage != stage[key] or r.check_question != base_q[key]:
            raise ExportContractError(f"check_questions_context_panel: {key} 단계·기본질문 불일치")
        ctx[key] = r.check_questions_context
    for name in ("trace", "electre"):
        for r in src[name].itertuples():
            if r.check_questions_context != ctx[(r.industry, r.quarter)]:
                raise ExportContractError(f"{name}: {(r.industry, r.quarter)} context 가 패널과 다름")
    # 분기별 외부자료 패널: 180행, 단계 보존, 최신분기 값 = 기존 최신분기 요약, source 정의 열 존재
    ep = src["ext_panel"]
    if len(ep) != len(triage) or set(zip(ep.industry, ep.quarter)) != set(stage):
        raise ExportContractError("external_evidence_panel: triage_panel 과 key 집합 불일치")
    for r in ep.itertuples():
        if r.stage != stage[(r.industry, r.quarter)]:
            raise ExportContractError(f"external_evidence_panel: {(r.industry, r.quarter)} 단계 불일치")
    needed = {c for spec in S.EVIDENCE_SOURCES for c in spec["columns"]}
    if needed - set(ep.columns):
        raise ExportContractError(f"external_evidence_panel: 열 없음 {needed - set(ep.columns)}")
    ev = src["evidence"].set_index(["industry", "quarter"])
    epi = ep.set_index(["industry", "quarter"])
    for col in [c for c in ev.columns if c in epi.columns]:
        a, b = ev[col], epi.loc[ev.index, col]
        if not (a.eq(b) | (a.isna() & b.isna())).all():
            raise ExportContractError(f"external_evidence_panel: 최신분기 {col} 가 요약과 다름")
    role_ids = set(src["roles"]["dataset_id"])
    for spec in S.EVIDENCE_SOURCES + [S.JOBS_SOURCE, S.KEPCO_LEGAL_SOURCE]:
        if spec["dataset_id"] not in role_ids:
            raise ExportContractError(f"data_role_table 에 dataset_id 없음: {spec['dataset_id']}")
    for card in src["handoff"]:
        key = (card["industry"], card["quarter"])
        if card["stage"] != stage.get(key):
            raise ExportContractError(f"handoff_cards_latest: {key} 단계 불일치")
    extra = set(zip(src["cards"].industry, src["cards"].quarter)) - set(zip(src["evidence"].industry, src["evidence"].quarter))
    if extra:
        raise ExportContractError(f"card_preview 에만 있는 외부근거 key: {extra}")
    dist = src["distribution"].set_index("quarter")
    counts = triage.groupby(["quarter", "stage"]).size().unstack(fill_value=0)
    for q, row in dist.iterrows():
        for st in S.TRIAGE_STAGES:
            if int(row.get(st, 0)) != int(counts.loc[q].get(st, 0)):
                raise ExportContractError(f"분포표와 panel 불일치: {q} {st}")


def _truthy(v) -> bool:
    if hasattr(v, "item"):
        v = v.item()
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def _source_period(kind: str, quarter: str, ext_row) -> str | None:
    if kind == "quarter":
        return f"{quarter} (분기)"
    if kind == "quarter_end_month":
        return f"{quarter} 분기말 월"
    if kind == "half_year":
        raw = _native(ext_row["mfg_flow_period"])
        if raw in (None, ""):
            return None
        code = str(int(float(raw)))
        year, half = code[:4], code[4:]
        span = "상반기(1~6월)" if half == "01" else "하반기(7~12월)"
        return f"{year} {span} 자료 · 분기값 아님"
    return None


def _external_sources(quarter: str, ext_row, roles: dict, jobs_meta: dict, legal_quality: dict | None) -> list[dict]:
    """해당 분기에 정렬된 외부자료를 source 별로 옮긴다. 값이 없으면 자료 없음으로 둔다(다른 분기 값 사용 금지)."""
    out = []
    for spec in S.EVIDENCE_SOURCES:
        values = {c: _native(ext_row[c]) for c in spec["columns"]}
        if "available_flag" in spec:
            available = _truthy(ext_row[spec["available_flag"]])
        else:
            available = any(values[c] is not None for c in spec["available_any"])
        reason = values.get(spec.get("reason_col")) if not available else None
        out.append({
            "key": spec["key"], "dataset_id": spec["dataset_id"], "label": spec["label"],
            "role": roles[spec["dataset_id"]]["role"], "available": available,
            "source_period": _source_period(spec["period"], quarter, ext_row) if available else None,
            "values": values if available else {},
            "scope_notes": [values[c] for c in spec.get("scope_cols", []) if values.get(c)],
            "limitations": roles[spec["dataset_id"]]["limitations"],
            "unavailable_label": None if available else (reason or S.NO_SOURCE_DATA),
            "provenance": "external_evidence_panel",
        })
    jobs_q = set(jobs_meta.get("registration_quarters", []))
    jobs_ok = quarter in jobs_q
    out.append({
        "key": S.JOBS_SOURCE["key"], "dataset_id": S.JOBS_SOURCE["dataset_id"], "label": S.JOBS_SOURCE["label"],
        "role": roles[S.JOBS_SOURCE["dataset_id"]]["role"], "available": jobs_ok,
        "source_period": None, "values": {}, "scope_notes": [],
        "limitations": roles[S.JOBS_SOURCE["dataset_id"]]["limitations"],
        "unavailable_label": None if jobs_ok else (
            f"{S.NO_SOURCE_DATA} (공고 등록일 {jobs_meta.get('registration_date_min')}~"
            f"{jobs_meta.get('registration_date_max')} · {', '.join(sorted(jobs_q))})"),
        "provenance": "recruiting_snapshot_metadata",
    })
    out.append({
        "key": S.KEPCO_LEGAL_SOURCE["key"], "dataset_id": S.KEPCO_LEGAL_SOURCE["dataset_id"],
        "label": S.KEPCO_LEGAL_SOURCE["label"], "role": roles[S.KEPCO_LEGAL_SOURCE["dataset_id"]]["role"],
        "available": False, "quality_only": True, "source_period": None, "values": {},
        "quality": legal_quality, "scope_notes": [],
        "limitations": roles[S.KEPCO_LEGAL_SOURCE["dataset_id"]]["limitations"],
        "unavailable_label": "수치 신호로 사용하지 않음 — 자료 품질·결합 한계 정보만",
        "provenance": "external_evidence_summary(업종별 품질 정보)",
    })
    return out


def _record(row, trace, electre, evidence, card, ctx_row, ext_row, roles, jobs_meta, legal_quality) -> dict:
    rec = {"industry": row["industry"], "quarter": row["quarter"], "quarter_end": _native(row["quarter_end"])}
    for section, fields in S.TRIAGE_SECTIONS.items():
        rec[section] = {name: _native(row[col], name) for name, col in fields}
    rec["data_quality"]["fields"] = {
        f: {a: _native(row[f"{f}_{a}"]) for a in S.QUALITY_ATTRS} for f in S.QUALITY_FIELDS
    }
    rec["triage"]["stage_label"] = S.QUEUE_LABEL[row["stage"]]
    rec["triage"]["candidate_label"] = S.CANDIDATE_LABEL[row["stage"]]

    # 확인질문: 기본 check_question(triage_panel) + 해당 분기 맥락 기반 추가 확인질문(context 패널).
    ctx_text = _native(ctx_row["check_questions_context"]) if ctx_row is not None else None
    rec["questions"] = {
        "check_question": _native(row["check_question"]),
        "q1_question_route": _native(row["q1_question_route"]),
        "context_questions": _split_questions(ctx_text),
        "context_available": bool(ctx_text),
        "context_source": "check_questions_context_panel" if ctx_text else None,
        "context_missing_label": None if ctx_text else S.NO_CONTEXT_QUESTION,
        "context_role": S.CONTEXT_QUESTION_ROLE,
        "context_provenance": (
            {
                "components": {
                    col: _split_questions(_native(ctx_row[col])) for col in S.CONTEXT_COMPONENTS
                },
                "signal_profile": _native(ctx_row["signal_profile"]),
                "quality_flag_list": _native(ctx_row["quality_flag_list"]),
            } if ctx_row is not None else None
        ),
        "handoff_review_functions": _native(ctx_row["handoff_review_functions"]) if ctx_row is not None else None,
    }

    rec["explanation_trace"] = (
        {f: _native(trace[f]) for f in S.TRACE_FIELDS} if trace is not None else None
    )

    if electre is not None:
        e = {name: _native(electre[col], name) for name, col in S.ELECTRE_FIELDS}
        e["electre_stage_label"] = S.ELECTRE_LABEL.get(e["electre_stage"])
        e["possible_stages_list"] = (e["possible_stages"] or "").split("|") if e["possible_stages"] else []
        e["triage_stage_preserved"] = _native(electre["triage_stage_preserved"])
        rec["electre_smaa"] = {"available": True, **e}
    else:
        rec["electre_smaa"] = {
            "available": False,
            "reason": "추가확인 사례에만 적용" if row["stage"] != "추가확인" else "원천 없음",
        }

    if evidence is not None:
        rec["external_evidence"] = {
            "available": True,
            "narrative_available": card is not None,
            "source_quarter": evidence["quarter"],
            "summary": {c: _native(evidence[c]) for c in evidence.index if c not in S.EVIDENCE_EXCLUDE},
            "card": (
                {c.removeprefix("card_"): _native(card[c]) for c in card.index if c not in ("industry", "quarter")}
                if card is not None else None
            ),
        }
    else:
        rec["external_evidence"] = {
            "available": False, "narrative_available": False,
            "source_quarter": None, "summary": None, "card": None,
            "reason": S.NO_EVIDENCE_REASON,
        }

    rec["external_sources"] = _external_sources(row["quarter"], ext_row, roles, jobs_meta, legal_quality)

    rec["provenance"] = {
        "triage": "triage_panel",
        "explanation_trace": "explanation_trace" if trace is not None else None,
        "electre_smaa": "electre_smaa_review_cases" if electre is not None else None,
        "external_evidence": (
            [k for k, v in (("external_evidence_summary", evidence), ("external_evidence_card_preview", card)) if v is not None]
            or None
        ),
        "context_questions": rec["questions"]["context_source"],
    }
    return rec


def build_snapshot(source_root: Path = ROOT) -> dict:
    """원천을 읽어 Snapshot 내용(meta 초안, records, reference)을 만든다. 파일은 쓰지 않는다."""
    source_root = Path(source_root)
    src = _load_sources(source_root)
    _check_contract(src)

    trace = _index(src["trace"], "explanation_trace")
    context_q = _index(src["context_q"], "check_questions_context_panel")
    ext_panel = _index(src["ext_panel"], "external_evidence_panel")
    roles = {r["dataset_id"]: {"role": r["role"], "limitations": _native(r["limitations"])}
             for r in src["roles"].to_dict("records")}
    legal_quality = {
        r["industry"]: {c: _native(r[c]) for c in S.KEPCO_LEGAL_QUALITY_COLS}
        for r in src["evidence"].to_dict("records")
    }
    electre = _index(src["electre"], "electre_smaa_review_cases")
    evidence = _index(src["evidence"], "external_evidence_summary")
    cards = _index(src["cards"], "external_evidence_card_preview")

    triage = src["triage"].sort_values(["quarter", "industry"])
    records = []
    for _, row in triage.iterrows():
        key = (row["industry"], row["quarter"])
        records.append(_record(row, trace.get(key), electre.get(key), evidence.get(key), cards.get(key),
                               context_q.get(key), ext_panel[key], roles, src["jobs_meta"],
                               legal_quality.get(row["industry"])))

    tmeta, emeta = src["triage_meta"], src["evidence_meta"]
    as_of = tmeta["window"][1]
    if as_of != triage.quarter.max():
        raise ExportContractError(f"메타 window 끝({as_of}) ≠ panel 최신분기({triage.quarter.max()})")

    refs = []
    for key, spec in S.SOURCES.items():
        path = src["paths"][key]
        ref = {"key": key, "path": spec["path"], "sha256": _sha256(path), "role": spec["role"]}
        if path.suffix == ".csv":
            ref["rows"] = int(len(_read_csv(path)))
        refs.append(ref)
    data_hash = hashlib.sha256(
        "\n".join(f"{r['key']}:{r['sha256']}" for r in sorted(refs, key=lambda r: r["key"])).encode()
    ).hexdigest()

    meta = {
        "run_id": f"{tmeta['git_head'][:10]}@{tmeta['run_at_utc']}",
        "quarter": as_of,
        "window": tmeta["window"],
        "data_hash": data_hash,
        "rule_version": tmeta["rule_version"],
        "evidence_layer_version": emeta.get("layer"),
        "export_contract_version": S.EXPORT_CONTRACT_VERSION,
        # 시나리오 상태와 실제 적용 설정을 분리한다.
        # 원천에 규칙 시나리오 등록·승인 기록이 없으므로 상태는 draft 로 고정한다.
        "scenario_status": "draft",
        "scenario_status_basis": {
            "approved_scenario_registry": None,
            "electre_prereg_status_counts": {
                str(k): int(v) for k, v in src["electre"]["prereg_status"].value_counts().items()
            },
        },
        "parameter_spec": {
            "triage_rule_version": tmeta["rule_version"],
            "triage_rules": [
                {k: r.get(k) for k in ("rule_name", "definition", "threshold", "role", "source_category")}
                for r in tmeta["rules"]
            ],
            "missing_policy": tmeta.get("missing_policy"),
            "electre_specification": src["protocol"].get("electre_specification"),
            "electre_scope": src["protocol"].get("scope"),
            "electre_triage_stage_mutation": src["protocol"].get("triage_stage_mutation"),
        },
        "record_scope": f"이 실행이 산출한 {tmeta['window'][0]}~{tmeta['window'][1]} 전체 업종×분기",
        "source_run": {
            "triage_run_at_utc": tmeta["run_at_utc"],
            "evidence_run_at_utc": emeta.get("run_at_utc"),
            "git_head": tmeta["git_head"],
            "triage_untouched_by_evidence": emeta.get("triage_untouched"),
        },
        "record_count": len(records),
        "provenance_refs": refs,
    }
    reference = {
        "triage_distribution_by_quarter": [
            {k: _native(v) for k, v in r.items()} for r in src["distribution"].to_dict("records")
        ],
        "institution_routing_map": [
            {k: _native(v) for k, v in r.items()} for r in src["routing"].to_dict("records")
        ],
        "electre_smaa_protocol": src["protocol"],
        "triage_rules": tmeta["rules"],
        "scope": tmeta.get("scope"),
    }
    return {"meta": meta, "records": records, "reference": reference}


# ---------------------------------------------------------------- 등록·조회
def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8")


def list_snapshots(snapshot_root: Path = SNAPSHOT_ROOT) -> list[dict]:
    """등록된 Snapshot meta 목록(기준분기, 버전 오름차순)."""
    snapshot_root = Path(snapshot_root)
    out = []
    if not snapshot_root.exists():
        return out
    for meta_path in snapshot_root.glob(f"*/v*/{META_FILE}"):
        out.append(json.loads(meta_path.read_text(encoding="utf-8")))
    return sorted(out, key=lambda m: (m["quarter"], int(m["snapshot_version"][1:])))


# ---------------------------------------------------------------- 발급 이력·상태(registry)
def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_registry(snapshot_root: Path = SNAPSHOT_ROOT) -> dict:
    """발급 이력(issued)과 상태 이벤트(status_events). 파일이 없으면 빈 registry."""
    path = Path(snapshot_root) / REGISTRY_FILE
    if not path.exists():
        return {"schema": REGISTRY_SCHEMA, "issued": [], "status_events": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != REGISTRY_SCHEMA:
        raise SnapshotIntegrityError(f"알 수 없는 분석본 registry 형식: {data.get('schema')}")
    data.setdefault("issued", [])
    data.setdefault("status_events", [])
    return data


def _write_registry(snapshot_root: Path, registry: dict) -> None:
    snapshot_root = Path(snapshot_root)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    tmp = snapshot_root / f".{REGISTRY_FILE}.tmp"
    tmp.write_bytes(_dump(registry))
    os.replace(tmp, snapshot_root / REGISTRY_FILE)


def _issued_record(meta: dict) -> dict:
    return {"quarter": meta["quarter"], "snapshot_version": meta["snapshot_version"],
            "data_hash": meta["data_hash"], "export_contract_version": meta.get("export_contract_version"),
            "payload_sha256": meta["payload_sha256"], "created_at": meta.get("created_at"),
            "recorded_at": _utcnow()}


def _issued_index(registry: dict) -> dict:
    return {(e["quarter"], e["snapshot_version"]): e for e in registry["issued"]}


def _same_content(entry: dict, meta: dict) -> bool:
    return (entry["data_hash"], entry["payload_sha256"]) == (meta["data_hash"], meta["payload_sha256"])


def _reconcile(snapshot_root: Path, registry: dict) -> bool:
    """registry 에 없는 기존 버전 폴더를 발급 이력에 올린다(폴더는 읽기만). 기록과 내용이 다르면 오류."""
    known, changed = _issued_index(registry), False
    for m in list_snapshots(snapshot_root):
        entry = known.get((m["quarter"], m["snapshot_version"]))
        if entry is None:
            registry["issued"].append(_issued_record(m))
            changed = True
        elif not _same_content(entry, m):
            raise SnapshotIntegrityError(
                f"{m['quarter']} {m['snapshot_version']} 폴더 내용이 발급 기록과 다릅니다(번호 재사용 또는 변조 의심).")
    return changed


def issued_record(quarter: str, version: str, snapshot_root: Path = SNAPSHOT_ROOT) -> dict | None:
    return _issued_index(read_registry(snapshot_root)).get((quarter, version))


def next_snapshot_version(quarter: str, snapshot_root: Path = SNAPSHOT_ROOT, registry: dict | None = None) -> str:
    """다음 버전 번호. 지금 남은 폴더가 아니라 한번이라도 발급된 번호(registry)·폴더 이름 중 최대값 + 1."""
    snapshot_root = Path(snapshot_root)
    registry = registry if registry is not None else read_registry(snapshot_root)
    used = {int(e["snapshot_version"][1:]) for e in registry["issued"] if e["quarter"] == quarter}
    qdir = snapshot_root / quarter
    if qdir.exists():  # meta 가 없는 폴더·임시 폴더 이름도 쓴 번호로 본다
        used |= {int(m.group(1)) for d in qdir.iterdir() if (m := re.fullmatch(r"\.?v(\d+)(?:\.tmp)?", d.name))}
    return f"v{max(used, default=0) + 1}"


def set_snapshot_status(quarter: str, version: str, status: str, reason: str, *, actor: str | None = None,
                        snapshot_root: Path = SNAPSHOT_ROOT) -> dict:
    """분석본 상태 변경(active/archived/invalidated). 폴더·meta 는 건드리지 않고 이벤트만 추가한다."""
    if status not in SNAPSHOT_STATUSES:
        raise ValueError(f"상태는 {SNAPSHOT_STATUSES} 중 하나여야 합니다: {status}")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("상태 변경 사유가 필요합니다.")
    snapshot_root = Path(snapshot_root)
    registry = read_registry(snapshot_root)
    _reconcile(snapshot_root, registry)
    if (quarter, version) not in _issued_index(registry):
        raise KeyError(f"발급된 적 없는 분석본: {quarter} {version}")
    event = {"quarter": quarter, "snapshot_version": version, "status": status, "reason": reason,
             "changed_at": _utcnow(), "actor": actor}
    registry["status_events"].append(event)
    _write_registry(snapshot_root, registry)
    return event


def snapshot_statuses(snapshot_root: Path = SNAPSHOT_ROOT) -> dict:
    """(기준분기, 버전) → 현재 상태(마지막 이벤트). 이벤트가 없으면 active."""
    out = {}
    for e in read_registry(snapshot_root)["status_events"]:
        out[(e["quarter"], e["snapshot_version"])] = {k: e.get(k) for k in ("status", "reason", "changed_at", "actor")}
    return out


def snapshot_status(quarter: str, version: str, snapshot_root: Path = SNAPSHOT_ROOT) -> dict:
    return snapshot_statuses(snapshot_root).get(
        (quarter, version), {"status": "active", "reason": None, "changed_at": None, "actor": None})


def active_snapshots(snapshot_root: Path = SNAPSHOT_ROOT) -> list[dict]:
    """신규 업무용 분석본(active). 보관·무효 분석본은 목록에서만 빠지고, 파일은 남아 기존 점검 건이 계속 불러온다."""
    statuses = snapshot_statuses(snapshot_root)
    return [m for m in list_snapshots(snapshot_root)
            if statuses.get((m["quarter"], m["snapshot_version"]), {}).get("status", "active") == "active"]


def register_snapshot(source_root: Path = ROOT, snapshot_root: Path = SNAPSHOT_ROOT) -> tuple[dict, bool]:
    """Snapshot 을 새 버전으로 등록한다. (meta, created) 반환.

    같은 기준분기에 data_hash·export 계약 버전이 같은 버전이 이미 있으면 새로 만들지 않는다.
    기존 버전 디렉터리는 절대 수정하지 않는다. 새 번호는 발급 이력 기준이라 지워진 번호를 다시 쓰지 않는다.
    """
    snapshot_root = Path(snapshot_root)
    built = build_snapshot(source_root)
    meta = built["meta"]
    registry = read_registry(snapshot_root)
    reconciled = _reconcile(snapshot_root, registry)
    existing = [m for m in list_snapshots(snapshot_root) if m["quarter"] == meta["quarter"]]
    for m in existing:
        if (m["data_hash"], m.get("export_contract_version")) == (meta["data_hash"], meta["export_contract_version"]):
            if reconciled:
                _write_registry(snapshot_root, registry)
            return m, False
    version = next_snapshot_version(meta["quarter"], snapshot_root, registry)
    final_dir = snapshot_root / meta["quarter"] / version
    if final_dir.exists():
        raise FileExistsError(f"이미 존재하는 Snapshot 디렉터리: {final_dir}")

    diag = _dump({"records": built["records"]})
    ref = _dump(built["reference"])
    meta = {
        **meta,
        "snapshot_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload_sha256": {
            DIAGNOSIS_FILE: hashlib.sha256(diag).hexdigest(),
            REFERENCE_FILE: hashlib.sha256(ref).hexdigest(),
        },
    }
    # 번호를 먼저 발급 이력에 남긴다 — 폴더 쓰기가 중간에 실패해도 이 번호는 다시 쓰이지 않는다
    registry["issued"].append(_issued_record(meta))
    _write_registry(snapshot_root, registry)
    tmp = final_dir.parent / f".{version}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    (tmp / DIAGNOSIS_FILE).write_bytes(diag)
    (tmp / REFERENCE_FILE).write_bytes(ref)
    (tmp / META_FILE).write_bytes(_dump(meta))
    os.replace(tmp, final_dir)
    return meta, True


@dataclass(frozen=True)
class Snapshot:
    meta: dict
    records: dict  # (industry, quarter) → record
    reference: dict

    @property
    def quarter(self) -> str:
        return self.meta["quarter"]

    @property
    def version(self) -> str:
        return self.meta["snapshot_version"]

    @property
    def quarters(self) -> list[str]:
        return sorted({q for _, q in self.records})

    @property
    def industries(self) -> list[str]:
        return sorted({i for i, _ in self.records})

    def get(self, industry: str, quarter: str) -> dict | None:
        return self.records.get((industry, quarter))

    def by_quarter(self, quarter: str) -> list[dict]:
        return [r for (i, q), r in sorted(self.records.items()) if q == quarter]

    def history(self, industry: str, upto: str, n: int = 6) -> list[dict]:
        qs = [q for q in self.quarters if q <= upto][-n:]
        return [self.records[(industry, q)] for q in qs if (industry, q) in self.records]

    def provenance(self, target_quarter: str) -> dict:
        """대상 분기 표시용 provenance. 기존 분석값·파일은 수정하지 않는다.

        과거 실행 산출물이 없는 분기는 reconstructed로 명시한다. 현재 등록 파일만으로는
        원천 데이터의 당시 as-of 컷오프를 완전 재현할 수 없으므로 강제 완료를 주장하지 않는다.
        """
        year, q = int(target_quarter[:4]), int(target_quarter[-1])
        end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[q]
        nature = snapshot_nature(self.quarter, target_quarter)
        return {
            "target_quarter": target_quarter,
            "generated_at": self.meta.get("created_at"),
            "data_cutoff": f"{year}-{end}",
            "snapshot_type": nature,
            "model_version": self.meta.get("rule_version"),
            "code_commit": self.meta.get("source_run", {}).get("git_head"),
            "provenance": f"{self.quarter}/{self.version}",
            "as_of_enforcement": "VERIFIED" if nature == CONTEMPORANEOUS else "NOT_VERIFIABLE_FROM_CURRENT_ARTIFACTS",
            "reconstruction_note": None if nature == CONTEMPORANEOUS else (
                f"{target_quarter} 당시 실행본이 없어 {self.quarter} 실행 분석본에서 후향 재구성. "
                "당시 원천의 완전한 as-of 컷오프를 현재 산출물만으로 검증할 수 없음."
            ),
        }


def load_snapshot(quarter: str, version: str, snapshot_root: Path = SNAPSHOT_ROOT) -> Snapshot:
    d = Path(snapshot_root) / quarter / version
    if not (d / META_FILE).exists():
        issued = issued_record(quarter, version, snapshot_root) is not None
        raise SnapshotMissingError(f"분석본 {quarter} {version} 파일이 없습니다"
                                   + (" (발급 기록은 있음)." if issued else "."))
    meta = json.loads((d / META_FILE).read_text(encoding="utf-8"))
    if (meta.get("quarter"), meta.get("snapshot_version")) != (quarter, version):
        raise SnapshotIntegrityError(f"{quarter}/{version} 폴더의 meta 가 다른 버전을 가리킴")
    entry = issued_record(quarter, version, snapshot_root)
    if entry is not None and not _same_content(entry, meta):  # 지워진 번호에 다른 내용이 들어온 경우
        raise SnapshotIntegrityError(f"분석본 {quarter} {version}의 내용이 발급 기록과 다릅니다.")
    payload = {}
    for name, expected in meta["payload_sha256"].items():
        raw = (d / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise SnapshotIntegrityError(f"{quarter}/{version}/{name} 가 등록 이후 변경됨")
        payload[name] = json.loads(raw.decode("utf-8"))
    records = {(r["industry"], r["quarter"]): r for r in payload[DIAGNOSIS_FILE]["records"]}
    return Snapshot(meta=meta, records=records, reference=payload[REFERENCE_FILE])


def verify_snapshot_binding(snapshot: Snapshot, quarter: str, version: str, data_hash: str | None) -> Snapshot:
    """점검 건·회차가 저장한 (기준분기, 버전, data_hash)와 불러온 분석본이 같은지. 다르면 SnapshotIntegrityError."""
    if (snapshot.quarter, snapshot.version) != (quarter, version) or (
            data_hash and snapshot.meta.get("data_hash") != data_hash):
        raise SnapshotIntegrityError(
            f"저장된 분석본({quarter} {version})과 현재 불러온 분석본의 내용(data_hash)이 다릅니다.")
    return snapshot


def load_bound_snapshot(quarter: str, version: str, data_hash: str | None,
                        snapshot_root: Path = SNAPSHOT_ROOT) -> Snapshot:
    """점검 기록에 묶인 분석본. 없으면 SnapshotMissingError, 내용이 다르면 SnapshotIntegrityError(대체하지 않음)."""
    return verify_snapshot_binding(load_snapshot(quarter, version, snapshot_root), quarter, version, data_hash)


# ---------------------------------------------------------------- 분석본 성격(당시 분석본 / 후향 재구성)
CONTEMPORANEOUS, RECONSTRUCTED = "contemporaneous", "reconstructed"
NATURE_LABEL = {
    CONTEMPORANEOUS: "당시 분석본",
    RECONSTRUCTED: "후향 재구성 분석",
}


def snapshot_nature(run_quarter: str, target_quarter: str) -> str:
    """분석 실행 분기 = 대상 분기이면 그 분기에 실행해 보존한 당시 분석본, 아니면 후속 실행으로 재구성한 과거분기."""
    return CONTEMPORANEOUS if run_quarter == target_quarter else RECONSTRUCTED


def nature_note(run_quarter: str, target_quarter: str) -> str:
    """화면 표기. 후향 재구성이면 '당시 분석본'이라는 표현을 쓰지 않는다."""
    if snapshot_nature(run_quarter, target_quarter) == CONTEMPORANEOUS:
        return f"당시 분석본 · {run_quarter} 실행"
    return (f"후향 재구성 분석 · {run_quarter} 실행 기준 · {target_quarter} 당시 저장 분석본 없음 · "
            "후속 보정자료가 반영되었을 수 있음")


def resolve_for_quarter(target_quarter: str, snapshot_root: Path = SNAPSHOT_ROOT) -> Snapshot | None:
    """대상 분기를 볼 분석본: 그 분기 실행본(당시 분석본)이 있으면 최신 버전, 없으면 그 분기를 포함한
    가장 최근 실행의 최신 버전(후향 재구성). 가짜 과거 분석본을 만들지 않는다."""
    metas = active_snapshots(snapshot_root)  # 신규 업무용(보관·무효 분석본은 고르지 않음)
    same = [m for m in metas if m["quarter"] == target_quarter]
    if same:
        m = same[-1]
    else:
        later = [m for m in metas if m["window"][0] <= target_quarter <= m["window"][1]]
        if not later:
            return None
        m = later[-1]
    return load_snapshot(m["quarter"], m["snapshot_version"], snapshot_root)


def latest_snapshot(snapshot_root: Path = SNAPSHOT_ROOT) -> Snapshot | None:
    metas = active_snapshots(snapshot_root)
    if not metas:
        return None
    m = metas[-1]
    return load_snapshot(m["quarter"], m["snapshot_version"], snapshot_root)


def main() -> None:
    ap = argparse.ArgumentParser(description="기존 분석 산출물을 Snapshot 으로 등록")
    ap.add_argument("--source-root", type=Path, default=ROOT)
    ap.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    ap.add_argument("--set-status", nargs=3, metavar=("QUARTER", "VERSION", "STATUS"),
                    help="등록 대신 분석본 상태를 바꾼다(active/archived/invalidated). 폴더는 지우지 않는다.")
    ap.add_argument("--reason", default="", help="--set-status 사유(필수)")
    args = ap.parse_args()
    if args.set_status:
        event = set_snapshot_status(*args.set_status, args.reason, snapshot_root=args.snapshot_root)
        print(f"[상태 변경] {event['quarter']}/{event['snapshot_version']} → {event['status']} ({event['reason']})")
        return
    meta, created = register_snapshot(args.source_root, args.snapshot_root)
    state = "새 버전 등록" if created else "동일 원천 — 기존 버전 유지"
    print(f"[{state}] {meta['quarter']}/{meta['snapshot_version']} records={meta['record_count']} data_hash={meta['data_hash'][:12]}")


if __name__ == "__main__":
    main()
