"""Phase 4 검증(Phase 4.5 구조 반영): 분기 재점검 · 분석본 보정 비교 · 분기 운영 사후검토 · 실제 업무시각 · 변경 기록 표시."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import hashlib
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from export.diff import AUX_ONLY, CORE_CHANGED, REVIEW_THRESHOLD_LABEL, snapshot_diff  # noqa: E402
from export.documents import registered_document  # noqa: E402
from export.snapshot import SNAPSHOT_ROOT, list_snapshots, load_snapshot  # noqa: E402
from workflow import catalog as C  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow.service import REFERRAL_OCCURRED, WorkflowError, WorkflowService  # noqa: E402

A = "재담당"


@pytest.fixture(scope="module")
def snap():
    metas = [m for m in list_snapshots(SNAPSHOT_ROOT) if m["quarter"] == "2026Q2"]
    return load_snapshot("2026Q2", metas[-1]["snapshot_version"], SNAPSHOT_ROOT)


@pytest.fixture(scope="module")
def v1():
    return load_snapshot("2026Q2", "v1", SNAPSHOT_ROOT)


@pytest.fixture
def svc(tmp_path):
    return WorkflowService(M.make_session_factory(f"sqlite:///{(tmp_path / 'wf.db').as_posix()}"))


def _now():
    return datetime.now(timezone.utc)


def _adv(svc, rid, to, text=None):
    contact = ("공문", "테스트 연락 경로") if to == "발송 기록" else (None, None)
    return svc.advance_referral(A, rid, to, text, _now() if to in REFERRAL_OCCURRED else None,
                                contact_method=contact[0], contact_route=contact[1])


def _open(svc, snap, industry, quarter):
    if snap.get(industry, quarter)["triage"]["stage"] != "관찰":
        svc.start_candidate_review(A, snap, industry, quarter)
    return svc.open_case(A, snap, industry, quarter, "현장확인", A)


def _field(svc, cid, result="확인"):
    item = svc.get_case(cid)["current_scope"]["checks"][0]["id"]
    svc.record_check_result(A, cid, item, "방문", result, "메모", performed_unknown=True)


def _resolver(snapshot):
    return lambda q: snapshot


def _file_hashes(version):
    d = SNAPSHOT_ROOT / "2026Q2" / version
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir()}


def _reviews(case):
    return [sc for sc in case["scopes"] if sc["review_kind"] == "재점검"]


# ================================================================ 재점검
def test_not_due_before_next_review_quarter_data(snap, svc):
    """1. 다음 검토 분기 자료가 분석본에 없으면 재점검 목록에 나오지 않는다."""
    cid = _open(svc, snap, "기계", "2026Q2")
    svc.record_decision(A, cid, "추가확인", "다음 분기 재확인", "2026Q3")
    assert svc.due_reviews(_resolver(snap)) == []
    with pytest.raises(WorkflowError, match="분석본 자료"):
        svc.start_quarterly_review(A, cid, snap)
    assert _reviews(svc.get_case(cid)) == []


def test_review_requires_snapshot_with_that_quarter(snap, svc):
    """2. 해당 분기 분석본 자료가 있어야 재점검할 수 있다."""
    cid = _open(svc, snap, "전기전자", "2025Q4")
    svc.record_decision(A, cid, "추가확인", "다음 분기 재확인", "2026Q1")
    assert [d["case_id"] for d in svc.due_reviews(_resolver(snap))] == [cid]
    records = {k: v for k, v in snap.records.items() if k != ("전기전자", "2026Q1")}
    without = replace(snap, records=records)
    assert svc.due_reviews(_resolver(without)) == []
    assert svc.due_reviews(lambda q: None) == []
    with pytest.raises(WorkflowError, match="분석본 자료"):
        svc.start_quarterly_review(A, cid, without)


def test_reviews_accumulate_on_same_case(snap, svc):
    """3·4. 재점검은 점검 건을 복제하지 않고 같은 건에 점검 시점으로 누적된다."""
    cid = _open(svc, snap, "전기전자", "2025Q4")
    svc.record_decision(A, cid, "추가확인", "재확인", "2026Q1")
    svc.start_quarterly_review(A, cid, snap)
    svc.record_decision(A, cid, "계속 점검", "계속 확인", "2026Q2")
    assert [d["review_quarter"] for d in svc.due_reviews(_resolver(snap))] == ["2026Q2"]
    svc.start_quarterly_review(A, cid, snap)
    svc.record_decision(A, cid, "모니터링 전환", "정기 관찰", "2026Q3")
    assert svc.count_cases() == 1 and svc.due_reviews(_resolver(snap)) == []
    case = svc.get_case(cid)
    assert [(sc["review_kind"], sc["quarter"]) for sc in case["scopes"]] == [
        ("최초 점검", "2025Q4"), ("재점검", "2026Q1"), ("재점검", "2026Q2")]
    assert [(r["previous_quarter"], r["quarter"]) for r in _reviews(case)] == [("2025Q4", "2026Q1"), ("2026Q1", "2026Q2")]
    for sc in case["scopes"]:
        assert sc["current_stage"] == snap.get("전기전자", sc["quarter"])["triage"]["stage"]
    assert [sc["review_status"] for sc in case["scopes"]] == ["완료", "완료", "진행 중"]
    assert [[d["decision"] for d in sc["decisions"]] for sc in case["scopes"]] == [["추가확인"], ["계속 점검"], ["모니터링 전환"]]
    assert _reviews(case)[1]["previous_stage"] == _reviews(case)[0]["current_stage"]
    with pytest.raises(WorkflowError, match="이후"):  # 다음 검토 분기는 현재 점검 분기(2026Q2) 이후
        svc.record_decision(A, cid, "계속 점검", "x", "2026Q2")


def test_review_keeps_prior_snapshot_versions(snap, v1, svc):
    """5·6. 재점검에 최신 분석본을 써도 개설·과거 결정의 분석본 버전과 분석본 파일은 그대로다."""
    before = {v: _file_hashes(v) for v in ("v1", "v2", "v3")}
    cid = _open(svc, v1, "전기전자", "2025Q4")
    svc.record_decision(A, cid, "추가확인", "재확인", "2026Q1")
    svc.start_quarterly_review(A, cid, snap)
    svc.record_decision(A, cid, "모니터링 전환", "관찰", "2026Q2")
    case = svc.get_case(cid)
    assert (case["snapshot_quarter"], case["snapshot_version"]) == ("2026Q2", "v1")
    rv = _reviews(case)[0]
    assert (rv["previous_snapshot_version"], rv["snapshot_version"]) == ("v1", snap.version)
    assert case["scopes"][0]["snapshot_version"] == "v1"
    decided = list(reversed([a for a in svc.audit_log() if a["action"] == "case.decision_recorded"]))
    assert [a["snapshot_version"] for a in decided] == ["v1", snap.version]
    assert {v: _file_hashes(v) for v in ("v1", "v2", "v3")} == before


def test_stage_movement_is_fact_only(snap, svc):
    """7. 단계 이동은 분석본 값만 옮기고 개선·악화 등으로 해석하지 않는다."""
    cid = _open(svc, snap, "전기전자", "2025Q4")
    svc.record_decision(A, cid, "추가확인", "재확인", "2026Q1")
    r = svc.start_quarterly_review(A, cid, snap)
    assert set(r) >= {"previous_stage", "current_stage"}
    assert not {k for k in r if any(w in k for w in ("improve", "worse", "trend", "flag", "score"))}
    words = ("개선", "악화", "호전", "나빠", "좋아", "improv", "worsen")
    for path in [ROOT / "src/app/main.py", ROOT / "src/workflow/service.py", ROOT / "src/export/diff.py"]:
        text = path.read_text(encoding="utf-8")
        assert not [w for w in words if w in text], path.name


# ================================================================ 분석본 보정 비교
def test_snapshot_diff_classifies_and_is_read_only(snap, v1):
    """8. diff 는 CORE/부가정보를 나누고 분석본 파일을 바꾸지 않는다."""
    before = {v: _file_hashes(v) for v in ("v1", "v2", "v3")}
    v2 = load_snapshot("2026Q2", "v2", SNAPSHOT_ROOT)
    d = snapshot_diff(v2, snap)
    assert d["verdict"] == AUX_ONLY and d["core_changes"] == [] and "external_sources" in d["aux_sections_added"]
    assert snapshot_diff(v1, v2)["verdict"] == AUX_ONLY
    records = copy.deepcopy(snap.records)
    records[("기계", "2026Q2")]["q2"]["emp_delta"] += 1
    changed = snapshot_diff(snap, replace(snap, records=records))
    assert changed["verdict"] == CORE_CHANGED
    assert [(c["industry"], c["quarter"], c["field"]) for c in changed["core_changes"]] == [("기계", "2026Q2", "q2.emp_delta")]
    records = copy.deepcopy(snap.records)
    records[("기계", "2026Q2")]["external_sources"][0]["source_period"] = "x"
    aux = snapshot_diff(snap, replace(snap, records=records))
    assert aux["verdict"] == AUX_ONLY and aux["aux_changed_records"] == [("기계", "2026Q2")]
    assert {v: _file_hashes(v) for v in ("v1", "v2", "v3")} == before


def test_no_automatic_review_flag(snap, v1, svc):
    """9. 재검토 기준이 없으므로 review_flag 를 만들지 않는다(의도된 비활성)."""
    d = snapshot_diff(v1, snap)
    assert d["review_flag_enabled"] is False and d["threshold_status"] == "not_configured"
    assert d["review_flag"] is None and d["review_threshold"] is None
    assert d["review_threshold_label"] == REVIEW_THRESHOLD_LABEL == "자동 재검토 기준 미설정"
    cols = {c.name for t in M.Base.metadata.sorted_tables for c in t.columns}
    assert not [c for c in cols if "flag" in c]
    assert svc.audit_log() == []


def test_external_evidence_never_changes_triage(snap, svc):
    """13. 재점검 단계는 분석본 Triage 값 그대로이며 외부자료는 CORE 비교에 들어가지 않는다."""
    cid = _open(svc, snap, "전기전자", "2025Q4")
    svc.record_decision(A, cid, "추가확인", "재확인", "2026Q1")
    r = svc.start_quarterly_review(A, cid, snap)
    assert r["current_stage"] == snap.get("전기전자", "2026Q1")["triage"]["stage"]
    records = copy.deepcopy(snap.records)
    for rec in records.values():
        for s in rec.get("external_sources") or []:
            s["available"] = not s["available"]
    d = snapshot_diff(snap, replace(snap, records=records))
    assert d["core_changes"] == [] and d["verdict"] == AUX_ONLY


# ================================================================ 분기 사후검토
def _full_case(svc, snap, industry, quarter):
    cid = _open(svc, snap, industry, quarter)
    _field(svc, cid, "부분 확인")
    svc.record_support_needs(A, cid, ["crisis_response", "technology_transition"], "메모")
    rid = svc.record_decision(A, cid, "인계", "인계", None, [("crisis_response", "경남TP 위기지원센터")],
                              snap)["referral_ids"][0]
    return cid, rid


def test_operations_exclude_examples(snap, tmp_path):
    """10. 시연 실행의 기록은 모든 운영지표에서 빠진다(같은 DB 에서 운영 실행으로 조회해도)."""
    sf = M.make_session_factory(f"sqlite:///{(tmp_path / 'ops.db').as_posix()}")
    demo, ops = WorkflowService(sf, demo=True), WorkflowService(sf, demo=False)
    _, rid = _full_case(demo, snap, "기계", "2026Q2")
    _adv(demo, rid, "발송 기록", "x")
    o = ops.operations_summary(snap, "2026Q2")
    assert o["excluded_example_cases"] == 1 and o["cases_opened"] == 0 and o["scopes"] == 0
    assert o["priority_opened"]["numerator"] == 0 and o["priority_candidates"] == 2
    assert sum(o["field_results"].values()) == 0 and sum(o["support_functions"].values()) == 0
    assert o["referrals_created"] == 0 and o["referral_reply"]["ratio"] is None
    assert o["stage_moves"] == {} and sum(o["decisions"].values()) == 0 and o["cases_closed"] == 0
    assert sum(o["occurred_in_quarter"].values()) == 0 and sum(o["occurred_unknown_all_quarters"].values()) == 0
    assert demo.operations_summary(snap, "2026Q2") == o  # 시연 실행에서 봐도 운영지표는 운영 기록만

    _full_case(ops, snap, "목재종이", "2026Q2")
    o = ops.operations_summary(snap, "2026Q2")
    assert o["cases_opened"] == 1 and o["priority_opened"] == {"numerator": 1, "denominator": 2, "ratio": 0.5}
    assert o["field_results"]["부분 확인"] == 1 and o["support_functions"]["crisis_response"] == 1
    assert o["referrals_created"] == 1 and o["decisions"]["인계"] == 1


def test_operations_compute_no_accuracy(snap, svc):
    """11. 관찰·미개설 사례에 대한 정확도류 지표를 계산하지 않는다."""
    _open(svc, snap, "운송장비", "2026Q2")
    o = svc.operations_summary(snap, "2026Q2")
    banned = ("accuracy", "precision", "recall", "hit", "miss", "observation", "정확", "적중")
    assert not [w for w in banned if w in " ".join(o.keys())]
    assert o["priority_opened"]["numerator"] == 0 and o["check_opened"]["denominator"] == 0
    for path in [ROOT / "src/app/main.py", ROOT / "src/workflow/service.py"]:
        text = path.read_text(encoding="utf-8").lower()
        assert not [w for w in ("accuracy", "precision", "recall", "정확도", "적중률") if w in text], path.name


def test_reply_rate_denominator_is_sent_referrals(snap, svc):
    """12. 회신율 분모 = 이 분기 시점에서 작성되고 발송이 기록된 인계. 작성만 된 인계는 분모에서 빠진다."""
    cid, r1 = _full_case(svc, snap, "목재종이", "2026Q2")
    svc.record_support_needs(A, cid, ["crisis_response", "vocational_training"], "메모")
    r2 = svc.create_referral(A, snap, cid, "vocational_training", "경남지역인적자원개발위원회")
    _adv(svc, r1, "발송 기록", "공문")
    _adv(svc, r1, "접수 확인")
    _adv(svc, r1, "처리·회신 기록", "회신")
    o = svc.operations_summary(snap, "2026Q2")
    assert o["referrals_created"] == 2 and o["referrals_sent"] == 1
    assert o["referral_reply"] == {"numerator": 1, "denominator": 1, "ratio": 1.0}
    _adv(svc, r2, "발송 기록", "공문")
    o = svc.operations_summary(snap, "2026Q2")
    assert o["referral_reply"] == {"numerator": 1, "denominator": 2, "ratio": 0.5}


def test_stage_moves_counted_at_review_quarter(snap, svc):
    cid = _open(svc, snap, "전기전자", "2025Q4")
    svc.record_decision(A, cid, "추가확인", "재확인", "2026Q1")
    r = svc.start_quarterly_review(A, cid, snap)
    assert svc.operations_summary(snap, "2026Q1")["stage_moves"] == {f"추가확인 → {r['current_stage']}": 1}
    assert svc.operations_summary(snap, "2025Q4")["stage_moves"] == {}


# ================================================================ 실제 업무시각 / 기록시각
def test_referral_occurred_time_is_explicit(snap, svc):
    """발송·접수·회신 시각은 담당자 입력값이며, 입력하지 않으면 현재 시각으로 채우지 않는다."""
    cid, rid = _full_case(svc, snap, "목재종이", "2026Q2")
    with pytest.raises(WorkflowError, match="실제 발생 일시"):
        svc.advance_referral(A, rid, "발송 기록", "공문", contact_method="공문", contact_route="경로")
    sent = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)
    svc.advance_referral(A, rid, "발송 기록", "공문", sent, contact_method="공문", contact_route="경로")
    with pytest.raises(WorkflowError, match="앞섭니다"):
        svc.advance_referral(A, rid, "접수 확인", None, sent - timedelta(days=1))
    with pytest.raises(WorkflowError, match="미래"):
        svc.advance_referral(A, rid, "접수 확인", None, _now() + timedelta(days=2))
    with pytest.raises(WorkflowError, match="시간대"):
        svc.advance_referral(A, rid, "접수 확인", None, datetime(2026, 9, 2))
    svc.advance_referral(A, rid, "접수 확인", None, occurred_unknown=True)
    r = svc.get_case(cid)["referrals"][0]
    assert r["sent_at"].startswith("2026-09-01T01:00") and r["received_at"] is None
    events = svc.referral_events(rid)
    sent_ev = next(e for e in events if e["action"] == "referral.sent")
    assert sent_ev["occurred_at"].startswith("2026-09-01T01:00") and sent_ev["recorded_at"] > sent_ev["occurred_at"]
    recv = next(e for e in events if e["action"] == "referral.received")
    assert recv["occurred_at"] is None and recv["occurred_unknown"] is True


# ================================================================ 화면(AppTest)
def _app(tmp_path, monkeypatch, page, demo=False):
    from streamlit.testing.v1 import AppTest
    url = f"sqlite:///{(tmp_path / 'ui.db').as_posix()}"
    monkeypatch.setenv("DSS_DATABASE_URL", url)
    if demo:
        monkeypatch.setenv("DSS_DEMO_MODE", "1")
    else:
        monkeypatch.delenv("DSS_DEMO_MODE", raising=False)
    s = WorkflowService(M.make_session_factory(url), demo=demo)
    return s, AppTest.from_file(str(ROOT / "src/app/main.py"), default_timeout=120), page


def _text(at):
    parts = [m.value for m in list(at.markdown) + list(at.caption) + list(at.warning) + list(at.info)]
    parts += [e.label for e in at.expander]
    return " || ".join(parts)


def test_screen_operations_empty_db_shows_zero_and_bias_note(tmp_path, monkeypatch, snap):
    s, at, page = _app(tmp_path, monkeypatch, "분기 사후검토")
    demo = WorkflowService(s.Session, demo=True)
    _full_case(demo, snap, "기계", "2026Q2")  # 시연 기록만 존재
    at.run()
    at.sidebar.radio(key="page").set_value(page).run()
    at.selectbox(key="ops_quarter").set_value("2026Q2").run()
    assert not at.exception
    text = _text(at)
    assert "관찰 업종과 개설되지 않은 후보에서 놓친 신호는 이 지표로 확인할 수 없습니다" in text
    assert "시연 기록 1건(점검 건 단위, 그 하위 기록 전부)은 모든 지표에서 제외" in text and "아직 기록 없음" in text
    assert [m.value for m in at.metric][:2] == ["2", "0 / 2 (0%)"]
    for basis in ("점검 시점 분기", "실제 업무 발생일의 달력 분기", "실제로 종결한 날의 달력 분기"):
        assert basis in text


def test_screen_methodology_sections(tmp_path, monkeypatch, snap):
    _, at, page = _app(tmp_path, monkeypatch, "투명성·방법론")
    at.run()
    at.sidebar.radio(key="page").set_value(page).run()
    assert not at.exception
    text = _text(at)
    for h in ("시스템 목적", "분석 — Q1 상태 · Q2 규모 · Q3 시간 · Triage", "선택적 재검토 — ELECTRE/SMAA",
              "외부자료 — 판정 정답 자료가 아님", "사람이 결정하는 지점", "현재 한계", "분석본 버전 비교"):
        assert h in text, h
    assert "등록 해시 일치" in text
    assert "Triage 단계 변경: **금지**" in text and "`VALIDATION`" in text and "`CONTEXT`" in text
    assert "시나리오 미등록(DRAFT)" in text and "지원사업 요건 카드: 공식 원장 11건" in text
    assert "분석 판정값 변경 없음 · 부가정보 갱신" in text and "자동 재검토 기준 미설정" in text
    assert "비활성(기준 상태 not_configured)" in text and "후향 재구성 분석" in text
    assert "프로토타입 · 인증 미연결" in text
    doc = registered_document(snap, "final_methodology")
    assert doc["hash_match"] and "ELECTRE 선택적 채택" in doc["sections"]
    assert f"원문 인용 — {doc['path']} · ELECTRE 선택적 채택" in text


def test_screen_audit_uses_business_labels(tmp_path, monkeypatch, snap):
    s, at, page = _app(tmp_path, monkeypatch, "변경 기록")
    cid = _open(s, snap, "기계", "2026Q2")
    s.record_support_needs(A, cid, ["vocational_training"], "메모")
    at.run()
    at.sidebar.radio(key="page").set_value(page).run()
    assert not at.exception
    detail = at.dataframe[1].value
    items = " ".join(detail["항목"])
    assert "지원 필요 기능" in items and "점검 건 번호" in items and "점검 시점 번호" in items
    assert "직업훈련" in " ".join(detail["변경 후"])
    raw = ("function_tags", "case_id", "snapshot_version", "recorded_at", "catalog_version", "field_checked",
           "quarterly_review_id")
    assert not [w for w in raw if w in items]
    header = at.dataframe[0].value
    assert "사용 분석본" in header.columns and "지원 필요 기능 #" in " ".join(header["대상"])
    assert "판정 당시 분석본" not in (ROOT / "src/app/main.py").read_text(encoding="utf-8")
