"""Phase 0~3 검증(Phase 4.5 구조 반영): Export 계약·Snapshot·점검 업무 흐름·지원 기능·인계 기록·감사 기록."""
from dataclasses import replace
from pathlib import Path
import copy
import json
import math
import shutil
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from export import schema as S
from export.snapshot import (
    SNAPSHOT_ROOT, SnapshotIntegrityError, build_snapshot, list_snapshots, load_snapshot,
    register_snapshot,
)
from workflow import models as M
from workflow.service import WorkflowError, WorkflowService

TOL = 1e-9


def _src(key):
    return pd.read_csv(ROOT / S.SOURCES[key]["path"], encoding="utf-8-sig", float_precision="round_trip")


def _same(a, b):
    if b is None or (isinstance(b, float) and math.isnan(b)):
        return a is None
    if isinstance(b, float):
        return a == b
    return a == (b.item() if hasattr(b, "item") else b)


@pytest.fixture(scope="module")
def snap():
    """저장소에 등록된 최신 분석 버전(2026Q2)."""
    metas = [m for m in list_snapshots(SNAPSHOT_ROOT) if m["quarter"] == "2026Q2"]
    assert metas, "snapshots/2026Q2 가 등록돼 있어야 한다"
    return load_snapshot("2026Q2", metas[-1]["snapshot_version"], SNAPSHOT_ROOT)


@pytest.fixture(scope="module")
def triage():
    return _src("triage_panel")


@pytest.fixture
def svc(tmp_path):
    return WorkflowService(M.make_session_factory(f"sqlite:///{(tmp_path / 'wf.db').as_posix()}"))


def _copy_sources(dst: Path):
    for spec in S.SOURCES.values():
        target = dst / spec["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / spec["path"], target)


# ================================================================ Phase 0
def test_registered_snapshot_matches_fresh_export(snap):
    fresh = build_snapshot(ROOT)
    assert fresh["meta"]["data_hash"] == snap.meta["data_hash"]
    assert {(r["industry"], r["quarter"]): r for r in fresh["records"]} == snap.records


def test_snapshot_meta_contract(snap):
    for key in ("run_id", "quarter", "snapshot_version", "data_hash", "rule_version",
                "scenario_status", "parameter_spec", "created_at", "provenance_refs"):
        assert snap.meta.get(key), key
    assert snap.meta["rule_version"] == "changwon-triage-rule/3.1.0-audited"
    refs = {r["key"] for r in snap.meta["provenance_refs"]}
    assert refs == set(S.SOURCES)


def test_scenario_status_is_separate_from_parameter_spec(snap):
    """시나리오 상태(draft)와 실제 적용 설정(parameter_spec)을 섞지 않는다."""
    assert "parameter_scenario" not in snap.meta
    assert snap.meta["scenario_status"] == "draft" and snap.meta["scenario_status"] in S.SCENARIO_STATUSES
    assert snap.meta["scenario_status_basis"]["approved_scenario_registry"] is None
    assert snap.meta["scenario_status_basis"]["electre_prereg_status_counts"] == {"DRAFT": 35}
    rules = json.loads((ROOT / S.SOURCES["triage_run_metadata"]["path"]).read_text(encoding="utf-8"))["rules"]
    spec = snap.meta["parameter_spec"]
    assert [(r["rule_name"], r["threshold"]) for r in spec["triage_rules"]] == [(r["rule_name"], r["threshold"]) for r in rules]
    assert spec["electre_specification"] == "D_small_indifference"
    assert spec["electre_triage_stage_mutation"] == "forbidden"


def test_snapshot_covers_all_18_quarters(snap):
    """과거 분기도 같은 분석본에서 조회한다(전기전자 2025Q4 포함)."""
    assert len(snap.quarters) == 18 and snap.quarters[0] == "2022Q1" and snap.quarters[-1] == "2026Q2"
    assert all(len(snap.by_quarter(q)) == 10 for q in snap.quarters)
    assert snap.get("전기전자", "2025Q4")["triage"]["stage"] == "추가확인"
    assert [h["quarter"] for h in snap.history("전기전자", "2025Q4")] == [
        "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4"]


def test_application_never_reads_analysis_outputs_directly():
    """앱·업무 계층은 원천 CSV·중간산출물을 직접 읽지 않고 Snapshot 만 쓴다."""
    forbidden = ("read_csv", "outputs/final_model", "data/processed", "data/raw", ".csv", "triage_panel",
                 "industry_context_signals")
    for path in list((ROOT / "src/app").glob("*.py")) + list((ROOT / "src/workflow").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} 에 {token}"


def test_snapshot_values_equal_source(snap, triage):
    """1. Snapshot 값 = 원천 산출물 값 (모든 매핑 필드, 180행)."""
    assert len(snap.records) == len(triage) == 180
    for _, row in triage.iterrows():
        rec = snap.get(row["industry"], row["quarter"])
        for section, fields in S.TRIAGE_SECTIONS.items():
            for name, col in fields:
                assert _same(rec[section][name], row[col]), (row["industry"], row["quarter"], section, name)
        for f in S.QUALITY_FIELDS:
            for a in S.QUALITY_ATTRS:
                assert _same(rec["data_quality"]["fields"][f][a], row[f"{f}_{a}"])
        assert rec["questions"]["check_question"] == row["check_question"]

    electre = _src("electre_smaa_review_cases")
    for _, row in electre.iterrows():
        e = snap.get(row["industry"], row["quarter"])["electre_smaa"]
        for name, col in S.ELECTRE_FIELDS:
            assert _same(e[name], row[col]), (row["industry"], row["quarter"], name)

    evidence = _src("external_evidence_summary")
    for _, row in evidence.iterrows():
        summ = snap.get(row["industry"], row["quarter"])["external_evidence"]["summary"]
        for col in evidence.columns:
            if col not in S.EVIDENCE_EXCLUDE:
                assert _same(summ[col], row[col]), col


def test_triage_distribution_128_35_17(snap):
    """2. 전체 분포."""
    stages = pd.Series([r["triage"]["stage"] for r in snap.records.values()]).value_counts().to_dict()
    assert stages == {"관찰": 128, "추가확인": 35, "우선점검": 17}
    dist = pd.DataFrame(snap.reference["triage_distribution_by_quarter"])
    assert int(dist["관찰"].sum()) == 128 and int(dist["추가확인"].sum()) == 35 and int(dist["우선점검"].sum()) == 17


def test_golden_machine_2026q2(snap):
    """3. 기계 2026Q2 골든 값, 목재종이 2026Q2."""
    r = snap.get("기계", "2026Q2")
    assert abs(r["activity"]["production_yoy"] - (-19.5473508775)) < TOL
    assert abs(r["q1"]["production_yoy"] - (-19.5473508775)) < TOL
    assert r["q2"]["emp_delta"] == -3979
    assert abs(r["q2"]["contribution_pct"] - 91.8513388735) < TOL
    assert abs(r["q2"]["employment_share_pct"] - 51.192197161) < TOL
    assert r["triage"]["stage"] == "우선점검"
    assert snap.get("목재종이", "2026Q2")["triage"]["stage"] == "우선점검"


def test_electre_never_overwrites_triage(snap, triage):
    """4. 전기전자 2025Q4: Triage 추가확인 유지, ELECTRE PRIORITY 는 보조정보."""
    r = snap.get("전기전자", "2025Q4")
    assert r["triage"]["stage"] == "추가확인"
    assert r["electre_smaa"]["electre_stage"] == "PRIORITY"
    assert r["electre_smaa"]["possible_stages"] == "CHECK|PRIORITY"
    assert r["electre_smaa"]["possible_stages_list"] == ["CHECK", "PRIORITY"]
    # 모든 레코드에서 Triage 단계는 원천과 같고, ELECTRE 는 추가확인에만 붙는다.
    src_stage = {(x.industry, x.quarter): x.stage for x in triage.itertuples()}
    for key, rec in snap.records.items():
        assert rec["triage"]["stage"] == src_stage[key]
        assert rec["triage"]["stage"] in S.TRIAGE_STAGES
        if rec["electre_smaa"]["available"]:
            assert rec["triage"]["stage"] == rec["electre_smaa"]["triage_stage_preserved"] == "추가확인"
        else:
            assert rec["triage"]["stage"] != "추가확인"
    assert sum(r["electre_smaa"]["available"] for r in snap.records.values()) == 35


def test_external_evidence_not_reused_across_quarters(snap):
    """8. 외부근거는 원천 분기(2026Q2)에만 있고 다른 분기에 재사용되지 않는다."""
    with_ev = [r for r in snap.records.values() if r["external_evidence"]["available"]]
    assert len(with_ev) == 10
    assert all(r["quarter"] == r["external_evidence"]["source_quarter"] == "2026Q2" for r in with_ev)
    for r in snap.records.values():
        if r["quarter"] != "2026Q2":
            ev = r["external_evidence"]
            assert ev == {"available": False, "narrative_available": False, "source_quarter": None,
                          "summary": None, "card": None, "reason": S.NO_EVIDENCE_REASON}
            assert r["explanation_trace"] is None


def test_context_questions_cover_all_quarters_from_final_panel(snap):
    """9(a). 맥락 기반 추가 확인질문은 180행 전부 최종 산출물(context 패널)에서만 온다."""
    panel = _src("check_questions_context_panel").set_index(["industry", "quarter"])
    for key, r in snap.records.items():
        q = r["questions"]
        assert q["context_available"] and q["context_source"] == "check_questions_context_panel"
        assert q["context_questions"] == [x.strip() for x in str(panel.loc[key, "check_questions_context"]).splitlines() if x.strip()]
        assert q["check_question"] == panel.loc[key, "check_question"]
        comps = q["context_provenance"]["components"]
        assert sum(len(v) for v in comps.values()) == len(q["context_questions"])
    # 기존 최종 산출물(trace 10 · ELECTRE 35)과 동일
    for name in ("explanation_trace", "electre_smaa_review_cases"):
        for _, row in _src(name).iterrows():
            rec = snap.get(row["industry"], row["quarter"])
            assert rec["questions"]["context_questions"] == [
                x.strip() for x in str(row["check_questions_context"]).splitlines() if x.strip()]


def test_context_questions_are_not_external_evidence(snap):
    """맥락 질문이 과거 분기에 생겨도 외부근거 카드는 원천 분기(2026Q2)에만 있다."""
    past = [r for r in snap.records.values() if r["quarter"] != "2026Q2"]
    assert past and all(r["questions"]["context_available"] for r in past)
    assert all(not r["external_evidence"]["available"] for r in past)
    assert all(r["external_evidence"]["available"] for r in snap.by_quarter("2026Q2"))


def test_previous_snapshot_version_is_kept(snap):
    """새 최종 산출물 추가로 새 버전이 생기고, 이전 v1 은 덮어쓰지 않는다."""
    assert snap.version != "v1"
    v1 = load_snapshot("2026Q2", "v1", SNAPSHOT_ROOT)  # payload 해시 검증 포함
    assert v1.meta["data_hash"] != snap.meta["data_hash"]
    assert "check_questions_context_panel" not in {r["key"] for r in v1.meta["provenance_refs"]}
    assert "check_questions_context_panel" in {r["key"] for r in snap.meta["provenance_refs"]}
    for key, r in v1.records.items():  # 판정·지표는 두 버전이 같다
        assert r["triage"] == snap.records[key]["triage"] and r["signals"] == snap.records[key]["signals"]

def test_register_is_append_only(tmp_path):
    """5(a)·Snapshot 등록: 같은 원천은 재등록하지 않고, 새 run 은 v2 로 추가되며 v1 은 불변."""
    src_root, snap_root = tmp_path / "src", tmp_path / "snapshots"
    _copy_sources(src_root)
    m1, created1 = register_snapshot(src_root, snap_root)
    m1b, created1b = register_snapshot(src_root, snap_root)
    assert (created1, created1b) == (True, False) and m1b["snapshot_version"] == "v1"
    v1_bytes = {p.name: p.read_bytes() for p in (snap_root / "2026Q2" / "v1").iterdir()}

    meta_path = src_root / S.SOURCES["triage_run_metadata"]["path"]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["run_at_utc"] = "2026-09-30T00:00:00+00:00"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    m2, created2 = register_snapshot(src_root, snap_root)
    assert created2 and m2["snapshot_version"] == "v2" and m2["data_hash"] != m1["data_hash"]
    assert {p.name: p.read_bytes() for p in (snap_root / "2026Q2" / "v1").iterdir()} == v1_bytes


def test_tampered_snapshot_is_rejected(tmp_path):
    snap_root = tmp_path / "snapshots"
    register_snapshot(ROOT, snap_root)
    f = snap_root / "2026Q2" / "v1" / "industry_diagnosis.json"
    f.write_bytes(f.read_bytes().replace("우선점검".encode(), "관찰".encode(), 1))
    with pytest.raises(SnapshotIntegrityError):
        load_snapshot("2026Q2", "v1", snap_root)


# ================================================================ Phase 2
def test_snapshot_registration_creates_no_case(tmp_path, svc):
    """5. Snapshot 등록·후보 조회만으로는 점검 건·검토·감사 기록이 생기지 않는다."""
    register_snapshot(ROOT, tmp_path / "snapshots")
    s = load_snapshot("2026Q2", "v1", tmp_path / "snapshots")
    cands = svc.candidates(s, "2026Q2")
    assert [c["industry"] for c in cands if c["candidate_type"] == "우선점검 후보"] == ["기계", "목재종이"]
    assert svc.count_cases() == 0 and svc.list_cases() == [] and svc.audit_log() == []
    assert all(c["review"] is None and c["open_case_id"] is None for c in cands)


def test_priority_candidate_case_only_after_user_action(snap, svc):
    """6. 우선점검 후보는 담당자 검토 시작 → 개설 행동 이후에만 점검 건이 된다."""
    with pytest.raises(WorkflowError):
        svc.open_case("김담당", snap, "기계", "2026Q2", "현장확인 필요", "김담당")
    assert svc.count_cases() == 0
    review = svc.start_candidate_review("김담당", snap, "기계", "2026Q2")
    assert review["status"] == "검토 중" and svc.count_cases() == 0
    cid = svc.open_case("김담당", snap, "기계", "2026Q2", "우선점검 후보 검토 결과 현장확인 필요", "김담당")
    case = svc.get_case(cid)
    assert case["origin"] == "우선점검 후보" and case["status"] == "진행 중"
    assert case["triage_stage_at_open"] == "우선점검"
    assert svc.candidates(snap, "2026Q2")[0]["review"]["status"] == "점검 건 개설"
    with pytest.raises(WorkflowError):  # 같은 업종×분기 중복 개설 금지
        svc.open_case("김담당", snap, "기계", "2026Q2", "중복", "김담당")


def test_observation_manual_case_requires_reason(snap, svc):
    """7. 관찰 단계도 사유를 입력하면 수동 개설 가능, 사유 없으면 불가."""
    assert snap.get("운송장비", "2026Q2")["triage"]["stage"] == "관찰"
    with pytest.raises(WorkflowError):
        svc.start_candidate_review("이담당", snap, "운송장비", "2026Q2")
    with pytest.raises(WorkflowError):
        svc.open_case("이담당", snap, "운송장비", "2026Q2", "   ", "이담당")
    cid = svc.open_case("이담당", snap, "운송장비", "2026Q2", "협력사 감원 제보 확인", "이담당")
    assert svc.get_case(cid)["origin"] == "수동 개설(관찰)"


def test_checklist_uses_registered_questions_only(snap, svc):
    """9(b). 체크리스트는 등록된 질문만 복사. 질문 원천이 없으면 생성하지 않는다."""
    rec = snap.get("음식료", "2024Q1")
    cid = svc.open_case("박담당", snap, "음식료", "2024Q1", "수동 확인", "박담당")
    checks = svc.get_case(cid)["current_scope"]["checks"]
    expected = [rec["questions"]["check_question"]] + rec["questions"]["context_questions"]
    assert [c["question_text"] for c in checks] == list(dict.fromkeys(expected))

    rec_e = snap.get("전기전자", "2025Q4")
    svc.start_candidate_review("박담당", snap, "전기전자", "2025Q4")
    cid_e = svc.open_case("박담당", snap, "전기전자", "2025Q4", "추가확인 검토", "박담당")
    texts = [c["question_text"] for c in svc.get_case(cid_e)["current_scope"]["checks"]]
    assert texts == list(dict.fromkeys([rec_e["questions"]["check_question"]] + rec_e["questions"]["context_questions"]))

    blank = copy.deepcopy(snap.get("철강", "2026Q2"))
    blank["questions"].update(check_question=None, context_questions=[], context_available=False)
    records = dict(snap.records)
    records[("철강", "2026Q2")] = blank
    no_q = replace(snap, records=records)
    cid_n = svc.open_case("박담당", no_q, "철강", "2026Q2", "질문 원천 없음 확인", "박담당")
    assert svc.get_case(cid_n)["current_scope"]["checks"] == []


def test_case_snapshot_version_is_fixed(tmp_path, svc):
    """10. 점검 건은 개설 당시 분석 버전을 고정한다(새 버전 등록 후에도)."""
    src_root, snap_root = tmp_path / "src", tmp_path / "snapshots"
    _copy_sources(src_root)
    register_snapshot(src_root, snap_root)
    v1 = load_snapshot("2026Q2", "v1", snap_root)
    svc.start_candidate_review("최담당", v1, "목재종이", "2026Q2")
    cid = svc.open_case("최담당", v1, "목재종이", "2026Q2", "우선점검 후보 확인", "최담당")

    meta_path = src_root / S.SOURCES["triage_run_metadata"]["path"]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["run_at_utc"] = "2026-10-01T00:00:00+00:00"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    m2, created = register_snapshot(src_root, snap_root)
    assert created and m2["snapshot_version"] == "v2"

    case = svc.get_case(cid)
    assert (case["snapshot_quarter"], case["snapshot_version"]) == ("2026Q2", "v1")
    assert case["snapshot_data_hash"] == v1.meta["data_hash"] != m2["data_hash"]
    assert all(a["snapshot_version"] == "v1" for a in svc.audit_log())


def test_every_state_change_is_audited(snap, svc):
    """11. 검토 시작·개설·현장결과·결정·종결이 모두 audit 에 남는다."""
    svc.start_candidate_review("정담당", snap, "기계", "2026Q2")
    cid = svc.open_case("정담당", snap, "기계", "2026Q2", "현장확인", "정담당")
    item = svc.get_case(cid)["current_scope"]["checks"][0]
    with pytest.raises(WorkflowError):  # 종결 확인 없이 종결 결정 불가
        svc.record_decision("정담당", cid, "종결", "확인 없는 종결 시도")
    with pytest.raises(WorkflowError):
        svc.record_check_result("정담당", cid, item["id"], "이메일", "확인")
    svc.record_check_result("정담당", cid, item["id"], "방문", "부분 확인", "수주 감소 확인, 감원 계획 미확인", performed_unknown=True)
    with pytest.raises(WorkflowError):
        svc.record_decision("정담당", cid, "추가확인", "다음 분기 재확인")  # 다음 검토 분기 누락
    svc.record_decision("정담당", cid, "추가확인", "다음 분기 재확인", "2026Q3")
    svc.record_decision("정담당", cid, "종결", "현장확인 결과 추가 조치 불필요", confirm_close=True)
    with pytest.raises(WorkflowError):
        svc.record_check_result("정담당", cid, item["id"], "전화", "확인", performed_unknown=True)

    logs = list(reversed(svc.audit_log()))
    assert [a["action"] for a in logs] == [
        "candidate.review_started", "case.opened", "candidate.case_opened",
        "case.field_result_recorded", "case.decision_recorded", "case.decision_recorded", "case.closed",
        "review.completed",
    ]
    for a in logs:
        assert a["actor"] == "정담당" and a["created_at"] and a["after"]
        assert (a["snapshot_quarter"], a["snapshot_version"]) == (snap.quarter, snap.version)
    assert logs[0]["before"] is None and logs[1]["before"] is None
    assert logs[3]["before"] is None and logs[3]["after"]["result_code"] == "부분 확인"
    assert logs[3]["after"]["performed_at"] is None and logs[3]["after"]["performed_at_unknown"] is True
    closed = next(a for a in logs if a["action"] == "case.closed")
    assert closed["before"]["status"] == "진행 중" and closed["after"]["status"] == "종결"
    case = svc.get_case(cid)
    assert case["status"] == "종결" and len(case["decisions"]) == 2


# ================================================================ 화면(AppTest)
def _diag_screen(tmp_path, monkeypatch, industry, quarter):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DSS_DATABASE_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    at = AppTest.from_file(str(ROOT / "src/app/main.py"), default_timeout=120).run()
    at.sidebar.radio(key="page").set_value("업종 진단").run()
    at.selectbox(key="dx_industry").set_value(industry)
    at.selectbox(key="dx_quarter").set_value(quarter).run()
    assert not at.exception
    return " || ".join([m.value for m in list(at.markdown) + list(at.caption)] + [e.label for e in at.expander])


def test_screen_past_quarter_shows_same_quarter_sources_and_questions(snap, tmp_path, monkeypatch):
    text = _diag_screen(tmp_path, monkeypatch, "전기전자", "2025Q4")
    rec = snap.get("전기전자", "2025Q4")
    assert "기본 확인질문" in text and rec["questions"]["check_question"] in text
    assert "맥락 기반 추가 확인질문" in text
    assert all(x in text for x in rec["questions"]["context_questions"])
    # 외부자료: 교차확인/보조 맥락 구분, 해당 분기 자료만, 최신분기 카드 없음
    assert "**교차확인 자료** · `VALIDATION`" in text and "**보조 맥락 자료** · `CONTEXT`" in text
    assert "2025Q4 (분기)" in text and "2025 하반기(7~12월) 자료 · 분기값 아님" in text
    assert "고용24 공개 채용공고** — 해당 시점 자료 없음" in text
    assert "모집단 차이" in text
    assert "원천 분기 2026Q2" not in text and "2026Q2 (분기)" not in text
    assert "ELECTRE: **PRIORITY**" in text and "Triage: **추가확인** (변경되지 않음)" in text
    app_text = (ROOT / "src/app/main.py").read_text(encoding="utf-8")  # 원천 질문 원문은 제외, 앱 문구만
    assert "입증" not in app_text and "검증 완료" not in app_text and "정답 검증" not in app_text


def test_screen_latest_quarter_keeps_external_evidence_separate(snap, tmp_path, monkeypatch):
    text = _diag_screen(tmp_path, monkeypatch, "기계", "2026Q2")
    rec = snap.get("기계", "2026Q2")
    assert "기본 확인질문" in text and "맥락 기반 추가 확인질문" in text
    assert "외부자료 (2026Q2 기준)" in text and "2026Q2 (분기)" in text
    assert "최신분기 외부근거 요약 카드 · 원천 분기 2026Q2" in text
    assert all(x in text for x in rec["questions"]["context_questions"])


# ================================================================ 분기별 외부자료
def _sources(rec):
    return {s["key"]: s for s in rec["external_sources"]}


def test_external_sources_keep_registered_roles(snap):
    roles = _src("data_role_table").set_index("dataset_id")["role"].to_dict()
    for rec in snap.records.values():
        keys = [s["key"] for s in rec["external_sources"]]
        assert keys == [x["key"] for x in S.EVIDENCE_SOURCES] + ["changwon_jobs", "kepco_legal_dong_ksic"]
        for s in rec["external_sources"]:
            assert s["role"] == roles[s["dataset_id"]]
    assert {s["key"]: s["role"] for s in snap.records[("기계", "2026Q2")]["external_sources"]} == {
        "ppi": "VALIDATION", "eis_cci": "VALIDATION", "customs_trade": "CONTEXT",
        "kepco_business_type": "CONTEXT", "ecos_bsi": "CONTEXT", "kosis_labor_flow": "CONTEXT",
        "changwon_jobs": "CONTEXT", "kepco_legal_dong_ksic": "CONTEXT"}


def test_external_sources_outside_coverage_are_unavailable(snap):
    """source 실제 가용기간 밖에서는 자료 없음(값 비움)."""
    for rec in snap.records.values():
        for s in rec["external_sources"]:
            if not s["available"]:
                assert s["values"] == {} and s["source_period"] is None and s["unavailable_label"]
        src = _sources(rec)
        assert not src["changwon_jobs"]["available"]          # 고용24 = 2026Q3 단면, 분석기간과 겹치지 않음
        assert not src["kepco_legal_dong_ksic"]["available"]  # 품질정보만
        if rec["quarter"].startswith("2022"):
            assert not src["eis_cci"]["available"]            # 전년동월 비교값 없음
        if rec["quarter"] in ("2023Q4", "2024Q4"):
            assert not src["ppi"]["available"]                # KICOX 명목생산 YoY 없음
        if rec["industry"] not in ("기계", "운송장비", "전기전자", "철강"):
            assert not src["customs_trade"]["available"]


def test_external_sources_use_same_quarter_values_only(snap):
    """각 분기는 같은 분기 패널 행 값만 쓴다(최신값 소급 없음)."""
    panel = _src("external_evidence_panel").set_index(["industry", "quarter"])
    for key, rec in snap.records.items():
        for s in rec["external_sources"]:
            for col, v in s["values"].items():
                raw = panel.loc[key, col]
                raw = raw.replace("\r\n", "\n") if isinstance(raw, str) else raw
                assert _same(v, raw), (key, s["key"], col)
    # 시간에 따라 변하는 값은 분기마다 달라야 한다(한 분기 값이 전 분기에 복제되지 않음)
    power = {r["quarter"]: _sources(r)["kepco_business_type"]["values"]["power_usage_kwh"]
             for r in snap.records.values()}
    assert len(set(power.values())) == 18
    bsi = {r["quarter"]: _sources(r)["ecos_bsi"]["values"]["bsi_region_business"] for r in snap.records.values()}
    latest = bsi["2026Q2"]
    assert sum(v == latest for q, v in bsi.items() if q != "2026Q2") < 17


def test_half_year_flow_is_labelled_not_quarterly(snap):
    for rec in snap.records.values():
        s = _sources(rec)["kosis_labor_flow"]
        year, qn = rec["quarter"][:4], int(rec["quarter"][-1])
        assert s["available"]
        assert str(int(float(s["values"]["mfg_flow_period"]))) == f"{year}0{1 if qn <= 2 else 2}"
        span = "상반기(1~6월)" if qn <= 2 else "하반기(7~12월)"
        assert s["source_period"] == f"{year} {span} 자료 · 분기값 아님"


def test_latest_quarter_sources_match_existing_summary(snap):
    summary = _src("external_evidence_summary").set_index("industry")
    for rec in snap.by_quarter("2026Q2"):
        row = summary.loc[rec["industry"]]
        for s in rec["external_sources"]:
            for col, v in s["values"].items():
                if col in row.index:
                    assert _same(v, row[col]) or (isinstance(v, str) and v == str(row[col]).replace("\r\n", "\n"))


def test_context_questions_align_with_same_quarter_sources(snap):
    """맥락 질문이 외부자료를 근거로 만들어졌다면 같은 분기(반기)에 그 자료가 있다."""
    sys.path.insert(0, str(ROOT / "src"))
    from evidence.modules.questions import EXTERNAL_QUESTIONS
    source_of = {"trade": "customs_trade", "mfg_flow": "kosis_labor_flow", "oprate_power": "kepco_business_type",
                 "bsi": "ecos_bsi"}
    checked = 0
    for rec in snap.records.values():
        ext_q = rec["questions"]["context_provenance"]["components"]["external_questions"]
        src = _sources(rec)
        for flag, text in EXTERNAL_QUESTIONS.items():
            if " ".join(text.split()) in [" ".join(x.split()) for x in ext_q]:
                key = next(v for k, v in source_of.items() if flag.startswith(k))
                assert src[key]["available"], (rec["industry"], rec["quarter"], flag)
                checked += 1
    assert checked > 100


# ================================================================ Phase 3: 지원 필요 기능 · 담당 기관 · 인계 기록
from workflow import catalog as C  # noqa: E402


def _adv(svc, actor, rid, to, text=None):
    """인계 단계 기록. 발송·접수·회신은 실제 발생 일시를 명시한다(여기서는 '지금 막 발생'을 선택한 경우)."""
    from datetime import datetime, timezone
    from workflow.service import REFERRAL_OCCURRED
    contact = ("공문", "테스트 연락 경로") if to == "발송 기록" else (None, None)
    return svc.advance_referral(actor, rid, to, text,
                                datetime.now(timezone.utc) if to in REFERRAL_OCCURRED else None,
                                contact_method=contact[0], contact_route=contact[1])


def _case_with_field_result(svc, snap, actor="한담당", industry="기계", quarter="2026Q2"):
    svc.start_candidate_review(actor, snap, industry, quarter)
    cid = svc.open_case(actor, snap, industry, quarter, "우선점검 후보 현장확인", actor)
    return cid, svc.get_case(cid)["current_scope"]["checks"][0]["id"]


def test_catalog_is_single_source_of_function_tags():
    tags = [f["tag"] for f in C.functions()]
    labels = [f["label"] for f in C.functions()]
    assert labels == ["고용유지", "직업훈련", "전직·재취업", "채용매칭", "기업 경영·기술 애로", "기술전환", "위기대응", "추가관찰"]
    assert len(set(tags)) == 8
    # 기능 이름은 카탈로그에만 있다(앱·서비스·모델에 문자열로 중복 정의하지 않음)
    for path in [ROOT / "src/app/main.py", ROOT / "src/workflow/service.py", ROOT / "src/workflow/models.py"]:
        text = path.read_text(encoding="utf-8")
        assert not [x for x in labels + tags if x in text], path.name


def test_routing_audit_uses_only_existing_routing_map_rows(snap):
    """카탈로그의 기관은 기존 institution_routing_map 행과 1:1. 새 기관 없음."""
    routing = [(r["institution"], r["source_url"]) for r in snap.reference["institution_routing_map"]]
    audit = [(e["institution"], e["source_url"]) for e in C.routing_audit()]
    assert sorted(audit) == sorted(routing) == sorted(set(routing))
    for e in C.routing_audit():
        assert e["audit_class"] in ("A", "B", "C")
        assert e["verified"] == (e["audit_class"] == "A") and bool(e["function_tags"]) == (e["audit_class"] == "A")
        assert (e["verified_at"] is not None) == e["verified"]
        assert set(e["function_tags"]) | set(e["candidate_tags_for_review"]) <= set(C.function_tags())


def test_no_industry_to_institution_mapping(snap):
    """3. 업종→기관 직접 매핑이 없다: 매핑 키는 기능뿐이고 Snapshot 기록에 기관명이 없다."""
    import inspect
    for e in C.routing_audit():
        assert not {"industry", "quarter", "stage", "triage_stage"} & set(e)
    names = {e["institution"] for e in C.routing_audit()}
    blob = json.dumps(list(snap.records.values()), ensure_ascii=False)
    assert not [n for n in names if n in blob]
    assert list(inspect.signature(WorkflowService.institution_candidates).parameters) == [
        "self", "snapshot", "function_tag"]


def test_unverified_mapping_shows_unmapped(snap):
    """4. 검증되지 않은 기능은 담당기관 후보가 없다(= 담당기관 미확정)."""
    routing = snap.reference["institution_routing_map"]
    mapped = {t: [c["institution"] for c in C.institution_candidates(t, routing)] for t in C.function_tags()}
    assert mapped["crisis_response"] == ["경남TP 위기지원센터"]
    assert mapped["vocational_training"] == ["경남지역인적자원개발위원회"]
    for t in ("employment_retention", "reemployment", "recruitment_matching", "business_difficulty",
              "technology_transition", "further_observation"):
        assert mapped[t] == [], t
    # 기관 기능표에 해당 행이 없는 분석 버전이면 검증 매핑도 쓰지 않는다
    assert C.institution_candidates("crisis_response", []) == []


def test_function_tags_are_never_auto_filled(snap, svc):
    """2. 점검 건 개설 시 지원 필요 기능은 비어 있다(Triage 단계와 무관)."""
    for ind, q in [("기계", "2026Q2"), ("전기전자", "2025Q4"), ("운송장비", "2026Q2")]:
        if snap.get(ind, q)["triage"]["stage"] != "관찰":
            svc.start_candidate_review("자담당", snap, ind, q)
        cid = svc.open_case("자담당", snap, ind, q, "확인", "자담당")
        case = svc.get_case(cid)
        sc = case["current_scope"]
        assert sc["support_needs"] is None and sc["support_need_history"] == [] and case["referrals"] == []
    assert not [a for a in svc.audit_log() if a["action"] == "case.support_needs_recorded"]
    with pytest.raises(WorkflowError):  # 선택 이유 없이 기록 불가
        svc.record_support_needs("자담당", cid, ["vocational_training"], "  ")
    with pytest.raises(WorkflowError):  # 카탈로그 밖 기능 불가
        svc.record_support_needs("자담당", cid, ["정책추천"], "메모")


def test_support_need_before_field_check_is_reference_only(snap, svc):
    """1. 현장확인 전에도 기능 선택은 가능하나 '참고용'으로 기록되고 인계는 막힌다."""
    cid, item = _case_with_field_result(svc, snap)
    rec = svc.record_support_needs("한담당", cid, ["vocational_training"], "사전 메모")
    assert rec["field_checked"] is False
    with pytest.raises(WorkflowError, match="현장확인 결과"):
        svc.record_decision("한담당", cid, "인계", "훈련 연계", None,
                            [("vocational_training", "경남지역인적자원개발위원회")], snap)
    assert svc.get_case(cid)["decisions"] == [] and svc.get_case(cid)["referrals"] == []
    svc.record_check_result("한담당", cid, item, "방문", "확인", "숙련인력 부족 확인", performed_unknown=True)
    assert svc.record_support_needs("한담당", cid, ["vocational_training"], "현장 확인 후")["field_checked"] is True


def _case_screen_text(at):
    return " || ".join(m.value for m in list(at.markdown) + list(at.caption) + list(at.warning))


def test_screen_warns_before_field_check(snap, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    url = f"sqlite:///{(tmp_path / 'ui.db').as_posix()}"
    monkeypatch.setenv("DSS_DATABASE_URL", url)
    s = WorkflowService(M.make_session_factory(url))
    cid, _ = _case_with_field_result(s, snap)
    at = AppTest.from_file(str(ROOT / "src/app/main.py"), default_timeout=120).run()
    at.sidebar.radio(key="page").set_value("점검 건").run()
    assert not at.exception
    text = _case_screen_text(at)
    assert "현장확인 전·참고용" in text and "선택된 지원 필요 기능 없음" in text
    fn = [cb for cb in at.checkbox if str(cb.key).startswith("fn_")]
    assert sorted(cb.label for cb in fn) == sorted(f["label"] for f in C.functions())
    assert all(not cb.value for cb in fn)  # 자동 체크 없음
    s.record_support_needs("한담당", cid, ["technology_transition", "crisis_response"], "현장확인 전 메모")
    at.run()
    text = _case_screen_text(at)
    assert C.UNMAPPED_LABEL in text and C.NO_VERIFIED_MAPPING in text
    assert "경남TP 위기지원센터" in text
    assert "R09 · 상반기 Stand-up 맞춤지원" in text and "과거 회차" in text
    assert "_현장확인 전·참고용 선택_" in text
    for word in ("referral", "function_tag", "candidate", "추천합니다"):
        assert word not in text


def test_no_referral_without_handoff_decision(snap, svc):
    """5·6. '인계'를 고르지 않으면 인계 기록이 생기지 않고, 사용자 행동 이후에만 생긴다."""
    cid, item = _case_with_field_result(svc, snap)
    svc.record_check_result("한담당", cid, item, "방문", "확인", "메모", performed_unknown=True)
    svc.record_support_needs("한담당", cid, ["crisis_response"], "위기대응 필요")
    assert svc.get_case(cid)["referrals"] == []
    with pytest.raises(WorkflowError):  # 인계 아닌 결정에 인계 대상 전달 불가
        svc.record_decision("한담당", cid, "추가확인", "재확인", "2026Q3",
                            [("crisis_response", "경남TP 위기지원센터")], snap)
    svc.record_decision("한담당", cid, "추가확인", "재확인", "2026Q3")
    with pytest.raises(WorkflowError):  # 현재 결정이 인계가 아니면 인계 기록 추가 불가
        svc.create_referral("한담당", snap, cid, "crisis_response", "경남TP 위기지원센터")
    with pytest.raises(WorkflowError):  # 인계에는 대상이 필요
        svc.record_decision("한담당", cid, "인계", "인계", None, [], snap)
    with pytest.raises(WorkflowError):  # 선택하지 않은 기능은 인계 불가
        svc.record_decision("한담당", cid, "인계", "인계", None,
                            [("vocational_training", "경남지역인적자원개발위원회")], snap)
    with pytest.raises(WorkflowError):  # 검증되지 않은 기관 불가
        svc.record_decision("한담당", cid, "인계", "인계", None, [("crisis_response", "창원고용복지+센터")], snap)
    case = svc.get_case(cid)
    assert case["referrals"] == [] and [d["decision"] for d in case["decisions"]] == ["추가확인"]
    out = svc.record_decision("한담당", cid, "인계", "위기대응 인계", None,
                              [("crisis_response", "경남TP 위기지원센터")], snap)
    case = svc.get_case(cid)
    assert len(case["referrals"]) == 1 and out["referral_ids"] == [case["referrals"][0]["id"]]
    r = case["referrals"][0]
    assert r["status"] == "작성" and r["decision_id"] == case["decisions"][-1]["id"]
    assert r["institution_source_url"] == "https://www.gntp.or.kr/introduce/staff" and r["catalog_version"]


def test_unmapped_function_keeps_case_and_selection(snap, svc):
    """B. 담당기관 미확정 기능: 인계 기록은 못 만들지만 점검 건·기능 선택 기록은 남는다."""
    cid, item = _case_with_field_result(svc, snap)
    svc.record_check_result("한담당", cid, item, "전화", "부분 확인", "메모", performed_unknown=True)
    svc.record_support_needs("한담당", cid, ["technology_transition", "employment_retention"], "설비전환 애로")
    assert svc.institution_candidates(snap, "technology_transition") == []
    with pytest.raises(WorkflowError, match=C.UNMAPPED_LABEL):
        svc.record_decision("한담당", cid, "인계", "인계 시도", None,
                            [("technology_transition", "경남TP 위기지원센터")], snap)
    svc.record_decision("한담당", cid, "모니터링 전환", "담당기관 미확정으로 재점검", "2026Q3")
    case = svc.get_case(cid)
    # 모니터링 전환: 적극 점검은 끝나고 재검토 계획은 보존
    assert case["status"] == "모니터링" and case["next_review_quarter"] == "2026Q3" and case["referrals"] == []
    assert case["current_scope"]["support_needs"]["function_tags"] == ["employment_retention", "technology_transition"]


def test_requirement_cards_do_not_auto_decide_or_block_workflow(snap, svc):
    """요건 카드는 일반 조건 안내일 뿐 인계·종결 흐름을 자동 결정하거나 막지 않는다."""
    with svc.Session() as s:
        assert s.query(M.RequirementCard).count() == 11
        assert all(card.auto_eligibility is False for card in s.query(M.RequirementCard).all())
    assert svc.requirement_cards("vocational_training")
    cid, item = _case_with_field_result(svc, snap)
    svc.record_check_result("한담당", cid, item, "방문", "확인", "메모", performed_unknown=True)
    svc.record_support_needs("한담당", cid, ["vocational_training"], "훈련 필요")
    rid = svc.record_decision("한담당", cid, "인계", "훈련 연계", None,
                              [("vocational_training", "경남지역인적자원개발위원회")], snap)["referral_ids"][0]
    for to, text in [("발송 기록", "공문 발송"), ("접수 확인", None), ("처리·회신 기록", "상담 일정 회신"), ("종결", "완료")]:
        _adv(svc, "한담당", rid, to, text)
    svc.record_decision("한담당", cid, "종결", "인계 완료", confirm_close=True)
    assert svc.get_case(cid)["status"] == "종결"


def test_referral_transitions_are_manual_and_audited(snap, svc):
    """7. 인계 기록 상태변경은 허용된 전이만, 모두 audit 에 남는다. 점검 건 종결과 모순 없음."""
    cid, item = _case_with_field_result(svc, snap)
    svc.record_check_result("한담당", cid, item, "방문", "확인", "메모", performed_unknown=True)
    svc.record_support_needs("한담당", cid, ["crisis_response", "vocational_training"], "현장 확인")
    rid = svc.record_decision("한담당", cid, "인계", "인계", None,
                              [("crisis_response", "경남TP 위기지원센터")], snap)["referral_ids"][0]
    rid2 = svc.create_referral("한담당", snap, cid, "vocational_training", "경남지역인적자원개발위원회")
    with pytest.raises(WorkflowError):  # 같은 기능·기관 진행 중 중복 불가
        svc.create_referral("한담당", snap, cid, "vocational_training", "경남지역인적자원개발위원회")
    with pytest.raises(WorkflowError):  # 발송 전 접수 불가
        _adv(svc, "한담당", rid, "접수 확인")
    _adv(svc, "한담당", rid, "발송 기록", "공문")
    _adv(svc, "한담당", rid, "접수 확인")
    with pytest.raises(WorkflowError):  # 회신 내용 필수
        _adv(svc, "한담당", rid, "처리·회신 기록", " ")
    _adv(svc, "한담당", rid, "처리·회신 기록", "현장 방문 예정")
    _adv(svc, "한담당", rid, "추가확인 필요", "대상 기업 명단 요청")
    _adv(svc, "한담당", rid, "발송 기록", "명단 추가 발송")
    _adv(svc, "한담당", rid, "접수 확인")
    _adv(svc, "한담당", rid, "처리·회신 기록", "지원 검토 회신")
    with pytest.raises(WorkflowError, match="인계 기록"):  # 진행 중 인계 기록이 있으면 종결 불가
        svc.record_decision("한담당", cid, "종결", "인계 처리 확인", confirm_close=True)
    assert svc.get_case(cid)["status"] == "진행 중"
    _adv(svc, "한담당", rid, "종결", "회신 확인")
    _adv(svc, "한담당", rid2, "종결", "발송 전 철회")
    with pytest.raises(WorkflowError):  # 종결된 인계 기록은 끝 상태
        _adv(svc, "한담당", rid, "발송 기록", "재발송")
    svc.record_decision("한담당", cid, "종결", "인계 처리 확인", confirm_close=True)

    logs = list(reversed(svc.audit_log(target_type="referral")))
    assert [a["action"] for a in logs] == [
        "referral.created", "referral.created", "referral.sent", "referral.received", "referral.replied",
        "referral.followup_required", "referral.sent", "referral.received", "referral.replied",
        "referral.closed", "referral.closed"]
    for a in logs:
        assert a["actor"] == "한담당" and a["created_at"] and a["after"]["case_id"] == cid
        assert (a["snapshot_quarter"], a["snapshot_version"]) == (snap.quarter, snap.version)
    assert [(a["before"] or {}).get("status") for a in logs[2:5]] == ["작성", "발송 기록", "접수 확인"]
    assert logs[4]["after"]["reply_content"] == "현장 방문 예정" and logs[4]["after"]["replied_at"]
    support = svc.audit_log(target_type="case_support_need")
    assert support and support[0]["after"]["function_tags"] == ["vocational_training", "crisis_response"]
    decided = [a for a in svc.audit_log() if a["action"] == "case.decision_recorded"]
    assert any(a["after"]["decision"] == "인계" for a in decided)
    assert all("referral_ids" not in a["after"] for a in decided)  # 결정 audit 에 반환용 값이 섞이지 않음


def test_closed_case_referrals_are_read_only(snap, svc):
    """8. 종결된 점검 건에서는 인계 기록·기능 선택을 바꿀 수 없다."""
    cid, item = _case_with_field_result(svc, snap)
    svc.record_check_result("한담당", cid, item, "방문", "확인", "메모", performed_unknown=True)
    svc.record_support_needs("한담당", cid, ["crisis_response"], "메모")
    rid = svc.record_decision("한담당", cid, "인계", "인계", None,
                              [("crisis_response", "경남TP 위기지원센터")], snap)["referral_ids"][0]
    _adv(svc, "한담당", rid, "종결", "발송 전 철회")
    svc.record_decision("한담당", cid, "종결", "종결", confirm_close=True)
    n = len(svc.audit_log())
    for call in (lambda: _adv(svc, "한담당", rid, "발송 기록", "x"),
                 lambda: svc.create_referral("한담당", snap, cid, "crisis_response", "경남TP 위기지원센터"),
                 lambda: svc.record_support_needs("한담당", cid, ["vocational_training"], "x")):
        with pytest.raises(WorkflowError, match="종결"):
            call()
    assert len(svc.audit_log()) == n


def test_handoff_is_one_transaction_on_the_case_snapshot(snap, svc):
    cid, item = _case_with_field_result(svc, snap)
    svc.record_check_result("한담당", cid, item, "방문", "확인", "메모", performed_unknown=True)
    svc.record_support_needs("한담당", cid, ["crisis_response"], "메모")
    other = replace(snap, meta={**snap.meta, "data_hash": "0" * 64})
    with pytest.raises(WorkflowError, match="분석본"):
        svc.record_decision("한담당", cid, "인계", "인계", None, [("crisis_response", "경남TP 위기지원센터")], other)
    assert svc.get_case(cid)["decisions"] == []  # 결정도 남지 않음(한 transaction)
    assert not svc.audit_log(target_type="referral")
