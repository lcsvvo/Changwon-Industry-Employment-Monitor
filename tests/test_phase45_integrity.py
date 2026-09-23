"""Phase 4.5 운영 정합성 검증: 분석본 성격 · 점검 시점(review scope) 이력 · 결정↔상태 · 사후검토 시간축 ·
시연 범위 · 기관 제안/검증 · 접수경로 · Alembic · 신원 경계 · 재검토 표시 비활성."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import inspect
import json
import sys

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from export.diff import REVIEW_FLAG_ENABLED, THRESHOLD_STATUS, snapshot_diff  # noqa: E402
from export.snapshot import (  # noqa: E402
    DIAGNOSIS_FILE, META_FILE, REFERENCE_FILE, SNAPSHOT_ROOT, list_snapshots, load_snapshot, nature_note,
    register_snapshot, resolve_for_quarter, snapshot_nature,
)
from workflow import identity as I  # noqa: E402
from workflow import migrate as MG  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow.service import REFERRAL_OCCURRED, WorkflowError, WorkflowService, quarter_of  # noqa: E402

A = "정합담당"


@pytest.fixture(scope="module")
def snap():
    metas = [m for m in list_snapshots(SNAPSHOT_ROOT) if m["quarter"] == "2026Q2"]
    return load_snapshot("2026Q2", metas[-1]["snapshot_version"], SNAPSHOT_ROOT)


@pytest.fixture
def sf(tmp_path):
    return M.make_session_factory(f"sqlite:///{(tmp_path / 'wf.db').as_posix()}")


@pytest.fixture
def svc(sf):
    return WorkflowService(sf)


def _now():
    return datetime.now(timezone.utc)


def _open(svc, snap, industry="전기전자", quarter="2025Q4"):
    if snap.get(industry, quarter)["triage"]["stage"] != "관찰":
        svc.start_candidate_review(A, snap, industry, quarter)
    return svc.open_case(A, snap, industry, quarter, "현장확인", A)


def _items(svc, cid):
    return [i["id"] for i in svc.get_case(cid)["current_scope"]["checks"]]


def _result(svc, cid, code="확인", at=None):
    item = _items(svc, cid)[0]
    return svc.record_check_result(A, cid, item, "방문", code, f"{code} 메모", at, performed_unknown=at is None)


def _adv(svc, rid, to, text=None, at=None):
    contact = ("공문", "테스트 연락 경로") if to == "발송 기록" else (None, None)
    return svc.advance_referral(A, rid, to, text, at or (_now() if to in REFERRAL_OCCURRED else None),
                                contact_method=contact[0], contact_route=contact[1])


def _three_scope_case(svc, snap):
    """2025Q4 최초 점검 → 2026Q1 재점검 → 2026Q2 재점검 (각 시점에 결과·메모·기능·결정)."""
    cid = _open(svc, snap)
    _result(svc, cid, "확인")
    svc.record_note(A, cid, "2025Q4 메모")
    svc.record_support_needs(A, cid, ["vocational_training"], "훈련 필요")
    svc.record_decision(A, cid, "계속 점검", "계속 확인", "2026Q1")
    svc.start_quarterly_review(A, cid, snap)
    _result(svc, cid, "부분 확인", _now() - timedelta(days=3))
    svc.record_note(A, cid, "2026Q1 메모")
    svc.record_support_needs(A, cid, ["crisis_response", "employment_retention"], "위기 대응 필요")
    rid = svc.record_decision(A, cid, "인계", "위기대응 인계", "2026Q2", [("crisis_response", "경남TP 위기지원센터")],
                              snap)["referral_ids"][0]
    return cid, rid


# ================================================================ 1·2. 분석본 성격
def test_past_quarters_are_reconstructed(snap, svc):
    assert snapshot_nature("2026Q2", "2025Q4") == "reconstructed"
    assert snapshot_nature("2026Q2", "2026Q2") == "contemporaneous"
    note = nature_note("2026Q2", "2025Q4")
    for part in ("후향 재구성 분석 · 2026Q2 실행 기준", "2025Q4 당시 저장 분석본 없음", "후속 보정자료가 반영되었을 수 있음"):
        assert part in note
    assert nature_note("2026Q2", "2026Q2") == "당시 분석본 · 2026Q2 실행"
    cid = _open(svc, snap)
    case = svc.get_case(cid)
    assert case["snapshot_nature"] == "reconstructed" and case["scopes"][0]["snapshot_nature"] == "reconstructed"
    cid2 = _open(svc, snap, "기계", "2026Q2")
    assert svc.get_case(cid2)["snapshot_nature"] == "contemporaneous"
    # 현재 등록본은 2026Q2 실행뿐 — 가짜 과거 분석본이 없다
    assert {m["quarter"] for m in list_snapshots(SNAPSHOT_ROOT)} == {"2026Q2"}


def test_screen_marks_reconstructed_quarter(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DSS_DATABASE_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    monkeypatch.delenv("DSS_DEMO_MODE", raising=False)
    at = AppTest.from_file(str(ROOT / "src/app/main.py"), default_timeout=120).run()
    at.sidebar.radio(key="page").set_value("업종 진단").run()
    at.selectbox(key="dx_quarter").set_value("2025Q4").run()
    body = " || ".join(m.value for m in list(at.markdown) + list(at.caption))
    assert "후향 재구성 분석 · 2026Q2 실행 기준" in body and "당시 저장 분석본 없음" in body
    at.selectbox(key="dx_quarter").set_value("2026Q2").run()
    body = " || ".join(m.value for m in list(at.markdown) + list(at.caption))
    assert "당시 분석본 · 2026Q2 실행" in body and "후향 재구성 분석 · 2026Q2" not in body
    side = " || ".join(x.value for x in list(at.sidebar.info) + list(at.sidebar.warning))
    assert "프로토타입 · 인증 미연결" in side


def _write_snapshot(root: Path, meta: dict, records: list, reference: dict):
    """테스트용: 임시 폴더에 형식이 맞는 분석본을 쓴다(저장소의 snapshots/ 에는 쓰지 않음)."""
    d = root / meta["quarter"] / meta["snapshot_version"]
    d.mkdir(parents=True)
    diag = json.dumps({"records": records}, ensure_ascii=False).encode()
    ref = json.dumps(reference, ensure_ascii=False).encode()
    meta = {**meta, "payload_sha256": {DIAGNOSIS_FILE: hashlib.sha256(diag).hexdigest(),
                                       REFERENCE_FILE: hashlib.sha256(ref).hexdigest()}}
    (d / DIAGNOSIS_FILE).write_bytes(diag)
    (d / REFERENCE_FILE).write_bytes(ref)
    (d / META_FILE).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_future_contemporaneous_snapshots_accumulate(tmp_path, snap, sf):
    """실행 분기별 분석본이 누적되고, 대상 분기 실행본이 있으면 그것을 '당시 분석본'으로 쓴다."""
    root = tmp_path / "snapshots"
    m, created = register_snapshot(ROOT, root)  # 실제 등록 경로: 실행 분기 = 분석 window 끝
    assert created and (root / "2026Q2" / "v1").exists() and m["quarter"] == "2026Q2"
    # 2026Q3 실행이 등록된 상황(임시 폴더에서만 구성)
    base = load_snapshot("2026Q2", "v1", root)
    new = json.loads(json.dumps(base.records[("기계", "2026Q2")]))
    new["quarter"] = "2026Q3"
    meta = {**base.meta, "quarter": "2026Q3", "window": ["2022Q1", "2026Q3"], "snapshot_version": "v1"}
    _write_snapshot(root, meta, list(base.records.values()) + [new], base.reference)
    assert [(x["quarter"], x["snapshot_version"]) for x in list_snapshots(root)] == [("2026Q2", "v1"), ("2026Q3", "v1")]
    assert load_snapshot("2026Q2", "v1", root).meta["data_hash"] == m["data_hash"]  # 이전 실행본 보존
    q3 = resolve_for_quarter("2026Q3", root)
    assert q3.quarter == "2026Q3" and snapshot_nature(q3.quarter, "2026Q3") == "contemporaneous"
    q2 = resolve_for_quarter("2026Q2", root)
    assert q2.quarter == "2026Q2"  # 2026Q2 는 그 분기 실행본(당시 분석본)을 우선
    assert resolve_for_quarter("2025Q4", root).quarter == "2026Q3"  # 당시본 없는 분기 → 최신 실행(후향 재구성)
    assert resolve_for_quarter("2021Q4", root) is None
    # 재점검이 2026Q3 당시 분석본을 쓰면 시점 성격도 contemporaneous
    svc = WorkflowService(sf)
    svc.start_candidate_review(A, q2, "기계", "2026Q2")
    cid = svc.open_case(A, q2, "기계", "2026Q2", "확인", A)
    svc.record_decision(A, cid, "추가확인", "다음 분기", "2026Q3")
    assert [d["snapshot_nature"] for d in svc.due_reviews(lambda q: resolve_for_quarter(q, root))] == ["contemporaneous"]
    r = svc.start_quarterly_review(A, cid, q3)
    assert (r["snapshot_quarter"], r["snapshot_nature"]) == ("2026Q3", "contemporaneous")
    _result(svc, cid)
    svc.record_support_needs(A, cid, ["crisis_response"], "재점검 인계")
    with pytest.raises(WorkflowError, match="현재 점검 시점"):
        svc.record_decision(A, cid, "인계", "오래된 분석본", None,
                            [("crisis_response", "경남TP 위기지원센터")], q2)
    out = svc.record_decision(A, cid, "인계", "현재 분석본", None,
                              [("crisis_response", "경남TP 위기지원센터")], q3)
    assert len(out["referral_ids"]) == 1


# ================================================================ 3~6. 점검 시점별 보존
def test_scope_records_are_preserved_per_review(snap, svc):
    cid, _ = _three_scope_case(svc, snap)
    svc.start_quarterly_review(A, cid, snap)  # 2026Q2
    case = svc.get_case(cid)
    s0, s1, s2 = case["scopes"]
    assert [(s["quarter"], s["review_kind"]) for s in case["scopes"]] == [
        ("2025Q4", "최초 점검"), ("2026Q1", "재점검"), ("2026Q2", "재점검")]
    # 현장확인 결과: 시점마다 따로, 이전 시점 결과 유지
    assert s0["checks"][0]["latest"]["result_code"] == "확인" and s0["checks"][0]["latest"]["performed_at"] is None
    assert s1["checks"][0]["latest"]["result_code"] == "부분 확인" and s1["checks"][0]["latest"]["performed_at"]
    assert all(i["latest"] is None for i in s2["checks"])
    assert {i["id"] for i in s0["checks"]}.isdisjoint({i["id"] for i in s1["checks"]})
    # 메모·지원 필요 기능·결정
    assert [n["note"] for n in s0["notes"]] == ["2025Q4 메모"] and [n["note"] for n in s1["notes"]] == ["2026Q1 메모"]
    assert s0["support_needs"]["function_tags"] == ["vocational_training"]
    assert s1["support_needs"]["function_tags"] == ["employment_retention", "crisis_response"]
    assert s2["support_needs"] is None
    assert [d["decision"] for d in s0["decisions"]] == ["계속 점검"] and [d["decision"] for d in s1["decisions"]] == ["인계"]
    assert len(s1["referrals"]) == 1 and s0["referrals"] == []
    # 업무 테이블만으로 조회 가능(audit 없이)
    with svc.Session() as s:
        n = s.execute(text("SELECT COUNT(*) FROM check_results WHERE case_id = :c"), {"c": cid}).scalar()
        by_scope = dict(s.execute(text("SELECT quarterly_review_id, COUNT(*) FROM case_notes WHERE case_id = :c "
                                       "GROUP BY quarterly_review_id"), {"c": cid}).all())
    assert n == 2 and by_scope == {s0["id"]: 1, s1["id"]: 1}


def test_previous_scope_cannot_be_overwritten(snap, svc):
    cid, _ = _three_scope_case(svc, snap)
    case = svc.get_case(cid)
    old_item = case["scopes"][0]["checks"][0]["id"]
    with pytest.raises(WorkflowError, match="이전 점검 시점"):
        svc.record_check_result(A, cid, old_item, "전화", "반대증거", "x", performed_unknown=True)
    # 같은 시점에서 다시 기록하면 덮어쓰지 않고 추가
    item = case["current_scope"]["checks"][0]["id"]
    svc.record_check_result(A, cid, item, "문서", "반대증거", "재확인", performed_unknown=True)
    cur = svc.get_case(cid)["current_scope"]["checks"][0]
    assert [h["result_code"] for h in cur["history"]] == ["부분 확인", "반대증거"] and cur["latest"]["result_code"] == "반대증거"
    assert svc.get_case(cid)["scopes"][0]["checks"][0]["latest"]["result_code"] == "확인"
    hist = svc.get_case(cid)["current_scope"]["support_need_history"]
    svc.record_support_needs(A, cid, ["further_observation"], "추가관찰로 변경")
    after = svc.get_case(cid)["current_scope"]["support_need_history"]
    assert after[:len(hist)] == hist and after[-1]["function_tags"] == ["further_observation"]


def test_check_result_performed_and_recorded_time_are_separate(snap, svc):
    cid = _open(svc, snap)
    item = _items(svc, cid)[0]
    with pytest.raises(WorkflowError, match="실제 확인 일시"):
        svc.record_check_result(A, cid, item, "방문", "확인", "x")
    when = datetime(2026, 8, 3, 1, 30, tzinfo=timezone.utc)
    r = svc.record_check_result(A, cid, item, "방문", "확인", "x", when)
    assert r["performed_at"].startswith("2026-08-03T01:30") and r["recorded_at"] > r["performed_at"]
    r2 = svc.record_check_result(A, cid, item, "방문", "확인", "y", performed_unknown=True)
    assert r2["performed_at"] is None and r2["performed_at_unknown"] is True
    with pytest.raises(WorkflowError, match="미래"):
        svc.record_check_result(A, cid, item, "방문", "확인", "z", _now() + timedelta(days=1))


# ================================================================ 7·8. 결정 ↔ 점검 건 상태
def test_decision_rules_table():
    assert M.DECISION_RULES == {
        "계속 점검": {"case_status": "진행 중", "next_review": "required"},
        "추가확인": {"case_status": "진행 중", "next_review": "required"},
        "모니터링 전환": {"case_status": "모니터링", "next_review": "required"},
        "인계": {"case_status": "진행 중", "next_review": "optional"},
        "종결": {"case_status": "종결", "next_review": "none"},
    }


def test_decisions_set_case_status(snap, svc):
    cid = _open(svc, snap)
    for d in ("계속 점검", "추가확인", "모니터링 전환"):
        with pytest.raises(WorkflowError, match="다음 검토 분기"):
            svc.record_decision(A, cid, d, "근거")
    svc.record_decision(A, cid, "모니터링 전환", "정기 관찰", "2026Q1")
    case = svc.get_case(cid)
    assert (case["status"], case["next_review_quarter"]) == ("모니터링", "2026Q1")
    svc.record_note(A, cid, "모니터링 중에도 기록은 가능")  # 모니터링은 종결이 아님
    svc.start_quarterly_review(A, cid, snap)  # 담당자가 재점검을 시작하면 다시 진행 중
    assert svc.get_case(cid)["status"] == "진행 중"
    assert any(a["action"] == "case.status_changed" and a["after"]["status"] == "진행 중" for a in svc.audit_log())
    svc.record_decision(A, cid, "계속 점검", "계속", "2026Q2")
    assert svc.get_case(cid)["status"] == "진행 중"


def test_close_decision_closes_case_in_one_transaction(snap, svc):
    cid, rid = _three_scope_case(svc, snap)
    with pytest.raises(WorkflowError, match="종결 확인"):
        svc.record_decision(A, cid, "종결", "사유")
    n = len(svc.get_case(cid)["decisions"])
    with pytest.raises(WorkflowError, match="인계 기록"):  # 진행 중 인계가 있으면 거부, 결정도 남지 않음
        svc.record_decision(A, cid, "종결", "사유", confirm_close=True)
    case = svc.get_case(cid)
    assert len(case["decisions"]) == n and case["status"] == "진행 중" and case["closed_at"] is None
    _adv(svc, rid, "종결", "철회")
    svc.record_decision(A, cid, "종결", "현장 변화 없음 확인", "2026Q4", confirm_close=True)
    case = svc.get_case(cid)
    assert case["status"] == "종결" and case["decision"] == "종결" and case["closed_at"]
    assert case["closing_note"] == "현장 변화 없음 확인" and case["next_review_quarter"] is None
    assert case["current_scope"]["review_status"] == "완료"
    actions = [a["action"] for a in svc.audit_log()[:3]]
    assert set(actions) == {"case.decision_recorded", "case.closed", "review.completed"}
    for call in (lambda: svc.record_note(A, cid, "x"),
                 lambda: _result(svc, cid),
                 lambda: svc.record_decision(A, cid, "계속 점검", "x", "2027Q1"),
                 lambda: svc.start_quarterly_review(A, cid, snap)):
        with pytest.raises(WorkflowError, match="종결"):
            call()


# ================================================================ 9. 사후검토 시간축
def test_operations_time_axis(snap, svc):
    cid, rid = _three_scope_case(svc, snap)
    sent_at = datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)  # 2026Q3(KST)
    _adv(svc, rid, "발송 기록", "공문", sent_at)
    svc.advance_referral(A, rid, "접수 확인", None, occurred_unknown=True)
    _adv(svc, rid, "처리·회신 기록", "회신")
    _adv(svc, rid, "종결", "완료")
    svc.start_quarterly_review(A, cid, snap)  # 2026Q2
    svc.record_decision(A, cid, "종결", "종결", confirm_close=True)
    q4, q1, q2 = (svc.operations_summary(snap, q) for q in ("2025Q4", "2026Q1", "2026Q2"))
    # 개설: 개설 분기에만
    assert (q4["cases_opened"], q1["cases_opened"], q2["cases_opened"]) == (1, 0, 0)
    # 현장확인·지원 기능·결정: 각 점검 시점 분기
    assert q4["field_results"]["확인"] == 1 and q4["field_results"]["부분 확인"] == 0
    assert q1["field_results"]["부분 확인"] == 1 and q1["field_results"]["확인"] == 0
    assert q4["support_functions"]["vocational_training"] == 1 and q1["support_functions"]["crisis_response"] == 1
    assert q4["decisions"]["계속 점검"] == 1 and q1["decisions"]["인계"] == 1 and q2["decisions"]["종결"] == 1
    # 단계 이동: 재점검 시점 분기
    assert q4["stage_moves"] == {} and len(q1["stage_moves"]) == 1 and len(q2["stage_moves"]) == 1
    # 인계 생성: 인계를 결정한 시점 분기
    assert (q4["referrals_created"], q1["referrals_created"], q2["referrals_created"]) == (0, 1, 0)
    assert q1["referral_reply"] == {"numerator": 1, "denominator": 1, "ratio": 1.0}
    # 발송·접수·회신: 실제 발생일의 달력 분기 / 미입력은 별도
    q3 = svc.operations_summary(snap, "2026Q3")
    assert q3["occurred_in_quarter"]["발송"] == 1 and q1["occurred_in_quarter"]["발송"] == 0
    assert q3["occurred_unknown_all_quarters"]["접수"] == 1
    # 종결: 실제 종결일의 달력 분기
    now_q = quarter_of(_now())
    assert svc.operations_summary(snap, now_q)["cases_closed"] == 1 and q2["cases_closed"] == (1 if now_q == "2026Q2" else 0)
    assert "2026Q3" in svc.operations_quarters(snap)


# ================================================================ 10. 시연 범위
def test_demo_scope_propagates_and_is_excluded(snap, sf):
    demo, ops = WorkflowService(sf, demo=True), WorkflowService(sf, demo=False)
    cid, rid = _three_scope_case(demo, snap)
    _adv(demo, rid, "발송 기록", "공문")
    demo.propose_institution(A, "시연 기관", "시연 기능", "https://example.org", ["technology_transition"])
    with demo.Session() as s:
        assert s.execute(text("SELECT is_example FROM inspection_cases WHERE id = :c"), {"c": cid}).scalar() == 1
        assert s.execute(text("SELECT MIN(is_example) FROM candidate_reviews")).scalar() == 1
        assert s.execute(text("SELECT MIN(is_example) FROM institution_registry")).scalar() == 1
        for table in ("quarterly_reviews", "case_check_items", "check_results", "case_notes", "case_support_needs",
                      "case_decisions", "referrals"):  # 모든 하위 기록은 시연 점검 건에 묶인다
            orphan = s.execute(text(f"SELECT COUNT(*) FROM {table} t JOIN inspection_cases c ON c.id = t.case_id "
                                    "WHERE c.is_example = 0")).scalar()
            total = s.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert orphan == 0 and total > 0, table
    # 운영 실행은 시연 기록을 보지도 고치지도 못한다(반대도 같다)
    assert ops.list_cases() == [] and ops.due_reviews(lambda q: snap) == [] and ops.institution_registry() == []
    with pytest.raises(WorkflowError, match="시연 기록"):
        ops.record_note(A, cid, "운영 실행에서 시연 건 수정 시도")
    op_cid = _open(ops, snap, "기계", "2026Q2")
    with pytest.raises(WorkflowError, match="운영 기록"):
        demo.record_note(A, op_cid, "시연 실행에서 운영 건 수정 시도")
    o = ops.operations_summary(snap, "2026Q1")
    assert o["excluded_example_cases"] == 1 and o["scopes"] == 0 and o["referrals_created"] == 0
    assert demo.audit_log() and all(a["is_example"] for a in demo.audit_log())
    assert ops.audit_log() and all(not a["is_example"] for a in ops.audit_log())
    assert len(ops.audit_log(include_all=True)) == len(ops.audit_log()) + len(demo.audit_log())


def test_runtime_database_urls_are_physically_separated():
    normal = M.database_url_for_runtime(False, {})
    demo = M.database_url_for_runtime(True, {})
    assert normal != demo and normal.endswith("workflow.db") and demo.endswith("workflow-demo.db")
    with pytest.raises(M.DatabaseScopeError, match="DSS_DEMO_DATABASE_URL"):
        M.database_url_for_runtime(True, {"DSS_DATABASE_URL": "postgresql://example/operations"})
    with pytest.raises(M.DatabaseScopeError, match="다른 DB"):
        M.database_url_for_runtime(True, {
            "DSS_DATABASE_URL": "postgresql://example/shared",
            "DSS_DEMO_DATABASE_URL": "postgresql://example/shared",
        })
    with pytest.raises(M.DatabaseScopeError, match="다른 DB"):
        M.database_url_for_runtime(False, {
            "DSS_DATABASE_URL": "postgresql://example/shared",
            "DSS_DEMO_DATABASE_URL": "postgresql://example/shared",
        })
    with pytest.raises(M.DatabaseScopeError, match="다른 DB"):
        M.database_url_for_runtime(True, {"DSS_DEMO_DATABASE_URL": M.DEFAULT_DATABASE_URL})
    assert M.database_url_for_runtime(True, {
        "DSS_DATABASE_URL": "postgresql://example/operations",
        "DSS_DEMO_DATABASE_URL": "postgresql://example/demo",
    }).endswith("/demo")


def test_user_cannot_set_example_flag():
    assert "is_example" not in inspect.signature(WorkflowService.open_case).parameters
    for name, fn in inspect.getmembers(WorkflowService, inspect.isfunction):
        if not name.startswith("_"):  # 공개 업무 API 에는 시연 여부를 넘길 곳이 없다
            assert "is_example" not in inspect.signature(fn).parameters, name
    app = (ROOT / "src/app/main.py").read_text(encoding="utf-8")
    assert "시연·테스트용 기록" not in app and "is_example=" not in app
    assert I.runtime_context({"DSS_DEMO_MODE": "1"}).demo is True
    assert I.runtime_context({}).demo is False


# ================================================================ 11~13. 기관 제안·검증 · 접수경로
def test_only_verified_institutions_are_referable(snap, svc, sf):
    cid = _open(svc, snap)
    _result(svc, cid)
    svc.record_support_needs(A, cid, ["employment_retention", "technology_transition"], "현장 확인")
    # 카탈로그 proposed(창원고용복지+센터)·rejected 는 인계 불가
    assert svc.institution_candidates(snap, "employment_retention") == []
    with pytest.raises(WorkflowError, match="담당기관 미확정"):
        svc.record_decision(A, cid, "인계", "x", None, [("employment_retention", "창원고용복지+센터")], snap)
    # 새 기관 후보 제안은 proposed 로만 저장되고 인계 불가
    p = svc.propose_institution(A, "제안 기관", "설비 전환 컨설팅", "https://example.org/dept",
                                ["technology_transition"], "기술지원팀", "담당자 확인")
    assert p["status"] == "proposed" and svc.institution_candidates(snap, "technology_transition") == []
    with pytest.raises(WorkflowError, match="담당기관 미확정"):
        svc.record_decision(A, cid, "인계", "x", None, [("technology_transition", "제안 기관")], snap)
    with pytest.raises(WorkflowError):
        svc.propose_institution(A, "출처 없음", "기능", "not-a-url", ["technology_transition"])
    assert not [n for n in dir(WorkflowService) if "verify" in n or "approve" in n]  # 승인 경로 없음(로그인 이후)
    # (관리자 검증을 흉내 내어) verified 가 되면 그때만 인계 가능
    with sf.begin() as s:
        s.execute(text("UPDATE institution_registry SET status='verified', reviewed_by='관리자', "
                       "reviewed_at=:t, review_note='공식 문서 확인' WHERE id=:i"), {"t": _now(), "i": p["id"]})
    cands = svc.institution_candidates(snap, "technology_transition")
    assert [c["institution"] for c in cands] == ["제안 기관"] and cands[0]["intake_route_verified"] is False
    out = svc.record_decision(A, cid, "인계", "x", None, [("technology_transition", "제안 기관")], snap)
    r = svc.get_case(cid)["referrals"][0]
    assert out["referral_ids"] == [r["id"]] and r["institution_source"] == f"registry:{p['id']}"


def test_intake_route_is_distinct_and_recorded_on_send(snap, svc):
    cands = svc.institution_candidates(snap, "crisis_response")
    assert cands[0]["function_verified"] is True and cands[0]["intake_route_verified"] is False
    cid = _open(svc, snap)
    _result(svc, cid)
    svc.record_support_needs(A, cid, ["crisis_response"], "위기")
    rid = svc.record_decision(A, cid, "인계", "인계", None, [("crisis_response", "경남TP 위기지원센터")],
                              snap)["referral_ids"][0]
    with pytest.raises(WorkflowError, match="연락·접수 방식"):
        svc.advance_referral(A, rid, "발송 기록", "x", _now())
    with pytest.raises(WorkflowError, match="접수·연락 경로"):
        svc.advance_referral(A, rid, "발송 기록", "x", _now(), contact_method="전화", contact_route=" ")
    svc.advance_referral(A, rid, "발송 기록", "x", _now(), contact_method="전화",
                         contact_route="센터 대표전화(담당자 확인 필요)", external_reference="통화메모-01")
    r = svc.get_case(cid)["referrals"][0]
    assert (r["contact_method"], r["contact_route"], r["external_reference"]) == (
        "전화", "센터 대표전화(담당자 확인 필요)", "통화메모-01")
    ev = next(e for e in svc.referral_events(rid) if e["action"] == "referral.sent")
    assert ev["contact"] == ("전화", "센터 대표전화(담당자 확인 필요)", "통화메모-01")


# ================================================================ 14. Alembic
def test_new_db_is_built_by_migrations(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    eng = create_engine(f"sqlite:///{(tmp_path / 'new.db').as_posix()}")
    MG.upgrade(eng)
    assert MG.current_revision(eng) == MG.head_revision() == "0005_backend_services"
    with eng.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), M.Base.metadata) == []
        ddl = " ".join(r[0] for r in c.execute(text("SELECT sql FROM sqlite_master WHERE type='table'")))
    for ck in ("ck_case_status", "ck_review_kind", "ck_result_code", "ck_institution_status", "ck_referral_contact_method"):
        assert ck in ddl, ck
    assert "모니터링" in ddl


def test_models_module_does_not_use_create_all():
    assert "create_all(" not in (ROOT / "src/workflow/models.py").read_text(encoding="utf-8")


def _legacy_phase4_db(path: Path):
    """Alembic 도입 전(create_all) Phase 4 구조 DB 에 Phase 4 방식의 기록을 넣는다."""
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    MG.upgrade(eng, MG.BASELINE)
    t = ["2026-09-01 00:00:00.000000", "2026-09-02 00:00:00.000000", "2026-09-03 00:00:00.000000",
         "2026-09-04 00:00:00.000000"]
    with eng.begin() as c:
        c.execute(text("DROP TABLE alembic_version"))
        c.execute(text(
            "INSERT INTO inspection_cases (id, industry, quarter, snapshot_quarter, snapshot_version, snapshot_data_hash, "
            "triage_stage_at_open, origin, opening_reason, assignee, status, decision, next_review_quarter, opened_by, "
            "opened_at, is_example) VALUES (1,'전기전자','2025Q4','2026Q2','v3','h','추가확인','수동 개설(관찰)','사유',"
            "'김','진행 중','모니터링 전환','2026Q2','김',:t0,0)"), {"t0": t[0]})
        c.execute(text("INSERT INTO case_check_items (id, case_id, position, question_text, question_source, method, "
                       "result, memo, recorded_by, recorded_at) VALUES (1,1,0,'질문1','check_question','방문','확인',"
                       "'현장 메모',"
                       "'김',:t1), (2,1,1,'질문2','check_questions_context',NULL,NULL,NULL,NULL,NULL)"), {"t1": t[1]})
        c.execute(text("INSERT INTO case_decisions (id, case_id, decision, rationale, next_review_quarter, decided_by, "
                       "decided_at) VALUES (1,1,'인계','인계','2026Q1','김',:t1), "
                       "(2,1,'모니터링 전환','관찰','2026Q2','김',:t3)"), {"t1": t[1], "t3": t[3]})
        c.execute(text("INSERT INTO quarterly_reviews (id, case_id, quarter, snapshot_quarter, snapshot_version, "
                       "snapshot_data_hash, previous_quarter, previous_snapshot_quarter, previous_snapshot_version, "
                       "previous_stage, current_stage, review_status, reviewer, review_note, decision_id, started_at, "
                       "reviewed_at) VALUES (1,1,'2026Q1','2026Q2','v3','h','2025Q4','2026Q2','v3','추가확인','관찰',"
                       "'완료','김','관찰',2,:t2,:t3)"), {"t2": t[2], "t3": t[3]})
        c.execute(text("INSERT INTO case_support_needs (id, case_id, function_tags, note, field_checked, "
                       "catalog_version, recorded_by, recorded_at) VALUES "
                       "(1,1,'[\"crisis_response\"]','초기',1,'function-catalog/1.0.0','김',:t1), "
                       "(2,1,'[\"further_observation\"]','재점검',0,'function-catalog/1.0.0','김',:t3)"),
                  {"t1": t[1], "t3": t[3]})
        c.execute(text("INSERT INTO referrals (id, case_id, decision_id, function_tag, institution, catalog_version, "
                       "status, created_by, created_at) VALUES (1,1,1,'crisis_response','경남TP 위기지원센터',"
                       "'function-catalog/1.0.0','종결','김',:t1)"), {"t1": t[1]})
        c.execute(text("INSERT INTO audit_log (actor, action, target_type, target_id, created_at) "
                       "VALUES ('김','case.opened','inspection_case','1',:t0)"), {"t0": t[0]})
    return eng


def test_legacy_db_is_upgraded_with_data_preserved(tmp_path):
    path = tmp_path / "legacy.db"
    eng = _legacy_phase4_db(path)
    assert "alembic_version" not in sa_inspect(eng).get_table_names()
    svc = WorkflowService(M.make_session_factory(f"sqlite:///{path.as_posix()}"))  # stamp baseline → head
    assert MG.current_revision(eng) == MG.head_revision()
    case = svc.get_case(1)
    assert case["status"] == "모니터링" and case["snapshot_nature"] == "reconstructed"
    s0, s1 = case["scopes"]
    assert (s0["review_kind"], s0["quarter"], s0["review_status"]) == ("최초 점검", "2025Q4", "완료")
    assert (s1["review_kind"], s1["quarter"], s1["review_status"]) == ("재점검", "2026Q1", "진행 중")
    # 문항 결과 → check_results (실제 확인 시각은 기록된 적 없으므로 NULL)
    assert [i["question_text"] for i in s0["checks"]] == ["질문1", "질문2"]
    r = s0["checks"][0]["latest"]
    assert (r["result_code"], r["method"], r["note"], r["performed_at"]) == ("확인", "방문", "현장 메모", None)
    assert s0["checks"][1]["latest"] is None
    # 결정·지원 기능·인계는 기록 시점의 점검 시점으로
    assert [d["id"] for d in s0["decisions"]] == [1] and [d["id"] for d in s1["decisions"]] == [2]
    assert s0["support_needs"]["function_tags"] == ["crisis_response"]
    assert s1["support_needs"]["function_tags"] == ["further_observation"]
    assert [x["id"] for x in s0["referrals"]] == [1] and case["referrals"][0]["institution_source"] == "catalog"
    assert len(svc.audit_log()) == 1
    cols = {c["name"] for c in sa_inspect(eng).get_columns("case_check_items")}
    assert not cols & {"method", "result", "memo", "recorded_by", "recorded_at"}


def test_outdated_db_without_migration_is_reported(tmp_path):
    path = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    MG.upgrade(eng, MG.BASELINE)
    with pytest.raises(M.SchemaOutdatedError, match="0001_baseline"):
        M.make_session_factory(f"sqlite:///{path.as_posix()}", migrate=False)


def test_unknown_legacy_structure_is_not_stamped(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'odd.db').as_posix()}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE inspection_cases (id INTEGER PRIMARY KEY)"))
    with pytest.raises(MG.MigrationError):
        MG.upgrade(eng)


# ================================================================ 15. 신원 경계
def test_auth_boundary(snap, svc):
    with pytest.raises(I.AuthNotConfigured):
        I.runtime_context({"DSS_AUTH_MODE": "external"})
    rt = I.runtime_context({})
    assert rt.auth_mode == I.LOCAL_PROTOTYPE and not rt.authenticated and "인증 미연결" in rt.banner
    actor = I.local_actor(" 김담당 ")
    assert actor == I.Actor("local:김담당", "김담당", I.LOCAL_PROTOTYPE) and I.local_actor("  ") is None
    cid = _open(svc, snap)
    svc.record_note(actor, cid, "신원 경계 확인")
    a = svc.audit_log()[0]
    assert (a["actor"], a["actor_id"]) == ("김담당", "local:김담당")


# ================================================================ 16·17. 재검토 표시 · 요건 카드
def test_review_flag_disabled_and_requirement_cards_are_seeded(snap, svc):
    assert REVIEW_FLAG_ENABLED is False and THRESHOLD_STATUS == "not_configured"
    v1 = load_snapshot("2026Q2", "v1", SNAPSHOT_ROOT)
    d = snapshot_diff(v1, snap)
    assert d["review_flag_enabled"] is False and d["review_flag"] is None
    with svc.Session() as s:
        ids = {r.requirement_id for r in s.query(M.RequirementCard).all()}
        assert ids == {"R01", "R02", "R03", "R04", "R06", "R07", "R08", "R09", "R10", "R11-A", "R11-B"}


def test_snapshot_files_untouched_by_phase45():
    """기존 분석본 v1~v3 는 무결성 해시가 그대로다(로드 시 검증)."""
    for v in ("v1", "v2", "v3"):
        load_snapshot("2026Q2", v, SNAPSHOT_ROOT)
    assert not (SNAPSHOT_ROOT / "2026Q3").exists()  # 가짜 분석본을 저장소에 만들지 않음


def test_reconstructed_snapshot_exposes_honest_provenance():
    snap = load_snapshot("2026Q2", "v3", SNAPSHOT_ROOT)
    old = snap.provenance("2024Q4")
    current = snap.provenance("2026Q2")
    assert old["snapshot_type"] == "reconstructed" and old["data_cutoff"] == "2024-12-31"
    assert old["as_of_enforcement"] == "NOT_VERIFIABLE_FROM_CURRENT_ARTIFACTS"
    assert old["reconstruction_note"] and current["snapshot_type"] == "contemporaneous"
    assert current["as_of_enforcement"] == "VERIFIED" and current["reconstruction_note"] is None
