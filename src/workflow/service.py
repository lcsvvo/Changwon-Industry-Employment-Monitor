"""점검 업무 흐름: Triage → 점검 후보 → 담당자 검토 → 점검 건(최초 점검) → 현장확인 → 지원 필요 기능 → 결정·인계
→ 분기 재점검(새 점검 시점) → … → 담당자 종결.

- Triage 결과(Snapshot)만으로는 아무 기록도 생기지 않는다. 점검 후보는 Snapshot 에서 읽기 전용으로 파생된다.
- 모든 업무 기록은 담당자 행동으로만 생기며 audit_log 에 남는다.
- 점검 건은 점검 시점(review scope: 최초 점검·재점검)으로 나뉜다. 현장확인 결과·메모·지원 필요 기능·결정·인계는
  그 시점에 묶여 추가만 되고, 이전 시점 기록은 수정할 수 없다(업무 테이블만으로 과거 조회 가능).
- 각 점검 시점은 사용한 분석본과 그 성격(당시 분석본 contemporaneous / 후향 재구성 reconstructed)을 고정한다.
- 결정별 점검 건 상태는 models.DECISION_RULES 를 따른다. 분석 결과로 상태를 바꾸지 않으며,
  '종결' 결정은 담당자가 종결을 명시적으로 확인했을 때 결정 기록과 점검 건 종료를 한 transaction 으로 처리한다.
- 시연 범위(is_example)는 서비스 생성 시 실행 맥락으로 정해지며 호출자가 바꿀 수 없다.
  시연 실행은 시연 기록만, 운영 실행은 운영 기록만 수정한다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from export.snapshot import Snapshot, SnapshotIntegrityError, snapshot_nature, verify_snapshot_binding
from workflow import catalog as C
from workflow import models as M
from workflow.identity import Actor

QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")
CANDIDATE_TYPE = {"우선점검": "우선점검 후보", "추가확인": "검토 후보"}
KST = timezone(timedelta(hours=9))

# audit action → 화면 표시명
ACTION_LABEL = {
    "candidate.review_started": "점검 후보 검토 시작",
    "candidate.review_concluded": "점검 후보 검토 종료(점검 불필요)",
    "candidate.case_opened": "점검 후보 → 점검 건 개설",
    "case.opened": "점검 건 개설(최초 점검)",
    "case.deleted": "점검 건 삭제",
    "audit.cleared": "변경 기록 초기화",
    "case.field_result_recorded": "현장확인 결과 입력",
    "case.context_questions_added": "현장확인 질문 후보 추가",
    "case.note_recorded": "현장 메모 기록",
    "case.decision_recorded": "결정 기록",
    "case.closed": "점검 건 종결",
    "case.status_changed": "점검 건 상태 변경",
    "case.support_needs_recorded": "지원 필요 기능 선택·변경",
    "referral.created": "인계 기록 작성(담당 기관 선택)",
    "referral.sent": "인계 발송 기록",
    "referral.received": "인계 접수 확인",
    "referral.replied": "처리·회신 기록",
    "referral.followup_required": "인계 추가확인 필요",
    "referral.closed": "인계 기록 종결",
    "review.started": "분기 재점검 시작",
    "review.completed": "점검 시점 완료",
    "institution.proposed": "새 기관 후보 제안",
}
TARGET_LABEL = {
    "candidate_review": "점검 후보", "inspection_case": "점검 건", "case_check_item": "현장확인 항목",
    "check_result": "현장확인 결과", "case_note": "현장 메모",
    "case_support_need": "지원 필요 기능", "referral": "인계 기록", "quarterly_review": "점검 시점",
    "institution_registry": "기관 후보", "audit_log": "변경 기록",
}
# 실제 업무 발생시각을 입력받는 인계 단계 → 컬럼 접두어(발송→접수→회신 순)
REFERRAL_OCCURRED = {"발송 기록": "sent", "접수 확인": "received", "처리·회신 기록": "replied"}
REFERRAL_ORDER = ("sent", "received", "replied")
# 인계 기록 상태전이 → (audit action, 사용자 입력 필드, 입력 필수 여부)
REFERRAL_ACTIONS = {
    "발송 기록": ("referral.sent", "sent_note", False),
    "접수 확인": ("referral.received", "received_note", False),
    "처리·회신 기록": ("referral.replied", "reply_content", True),
    "추가확인 필요": ("referral.followup_required", "followup_note", True),
    "종결": ("referral.closed", "closing_note", True),
}
REFERRAL_INPUT_LABEL = {"sent_note": "발송 메모", "received_note": "접수 확인 메모",
                        "reply_content": "회신 내용", "followup_note": "추가확인 필요 사유",
                        "closing_note": "종결 메모"}


class WorkflowError(ValueError):
    """업무 규칙 위반(필수값 누락, 종결된 건 수정 등)."""


def _require(value: str | None, label: str) -> str:
    if value is None or not str(value).strip():
        raise WorkflowError(f"{label}을(를) 입력해야 합니다.")
    return str(value).strip()


def _aware(dt: datetime) -> datetime:
    """SQLite 는 시간대를 저장하지 않으므로 읽은 값은 UTC 로 본다."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _plain(obj, fields) -> dict:
    out = {}
    for f in fields:
        v = getattr(obj, f)
        out[f] = _aware(v).isoformat() if isinstance(v, datetime) else v
    return out


def quarter_of(dt: datetime | str | None) -> str | None:
    """실제 시각 → 달력 분기(KST)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    d = _aware(dt).astimezone(KST)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _check_occurred(at: datetime | None, unknown: bool, label: str) -> None:
    if at is None and not unknown:
        raise WorkflowError(f"{label}를 입력하거나 '모름(미입력)'을 선택해야 합니다.")
    if at is not None:
        if at.tzinfo is None:
            raise WorkflowError(f"{label}에 시간대가 필요합니다.")
        if at > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise WorkflowError(f"{label}가 현재보다 미래입니다.")


CANDIDATE_FIELDS = ("id", "snapshot_quarter", "snapshot_version", "industry", "quarter",
                    "candidate_type", "status", "reviewer", "note", "is_example")
CASE_FIELDS = ("id", "industry", "quarter", "snapshot_quarter", "snapshot_version", "snapshot_data_hash",
               "snapshot_nature", "triage_stage_at_open", "origin", "candidate_review_id", "opening_reason",
               "assignee", "status", "decision", "next_review_quarter", "opened_by", "opened_at",
               "closed_by", "closed_at", "closing_note", "is_example")
SCOPE_FIELDS = ("id", "case_id", "review_kind", "quarter", "snapshot_quarter", "snapshot_version",
                "snapshot_data_hash", "snapshot_nature", "previous_quarter", "previous_snapshot_quarter",
                "previous_snapshot_version", "previous_stage", "current_stage", "review_status", "reviewer",
                "started_at", "reviewed_at")
ITEM_FIELDS = ("id", "case_id", "quarterly_review_id", "position", "question_text", "question_source")
RESULT_FIELDS = ("id", "case_id", "quarterly_review_id", "check_item_id", "method", "result_code", "note",
                 "performed_at", "recorded_by", "recorded_at")
NOTE_FIELDS = ("id", "case_id", "quarterly_review_id", "note", "recorded_by", "recorded_at")
DECISION_FIELDS = ("id", "case_id", "quarterly_review_id", "decision", "rationale", "next_review_quarter",
                   "decided_by", "decided_at")
SUPPORT_FIELDS = ("id", "case_id", "quarterly_review_id", "function_tags", "note", "field_checked",
                  "catalog_version", "recorded_by", "recorded_at")
REFERRAL_FIELDS = ("id", "case_id", "quarterly_review_id", "decision_id", "function_tag", "institution",
                   "institution_unit", "institution_source_url", "institution_source", "mapping_verified_at",
                   "catalog_version", "status", "note", "created_by", "created_at", "sent_by", "sent_at",
                   "sent_note", "contact_method", "contact_route", "external_reference", "received_by",
                   "received_at", "received_note", "replied_by", "replied_at", "reply_content", "followup_note",
                   "closed_by", "closed_at", "closing_note")
REGISTRY_FIELDS = ("id", "institution", "unit", "function_description", "function_tags", "source_url", "basis",
                   "status", "proposed_by", "proposed_at", "reviewed_by", "reviewed_at", "review_note",
                   "intake_route_verified", "intake_route", "is_example")
AUDIT_FIELDS = ("id", "actor", "actor_id", "action", "target_type", "target_id", "before", "after",
                "snapshot_quarter", "snapshot_version", "created_at", "is_example")


class WorkflowService:
    def __init__(self, session_factory, demo: bool = False):
        self.Session = session_factory
        self.demo = bool(demo)  # 실행 맥락이 정한 시연 범위. 이후 바꾸지 않는다.

    # ------------------------------------------------------------ 내부
    @staticmethod
    def _who(actor) -> tuple[str, str]:
        if isinstance(actor, Actor):
            return actor.display_name, actor.actor_id
        name = _require(actor, "담당자 이름")
        return name, f"local:{name}"

    def _audit(self, s, who, action, target_type, target_id, before, after, snap_q, snap_v):
        s.add(M.AuditLog(
            actor=who[0], actor_id=who[1], action=action, target_type=target_type, target_id=str(target_id),
            before=before, after=after, snapshot_quarter=snap_q, snapshot_version=snap_v,
            created_at=datetime.now(timezone.utc), is_example=self.demo,
        ))

    def _guard(self, is_example: bool) -> None:
        if bool(is_example) != self.demo:
            raise WorkflowError("운영 기록과 시연 기록은 서로 수정할 수 없습니다"
                                f"(현재 실행: {'시연' if self.demo else '운영'}).")

    def _case(self, s, case_id: int) -> M.InspectionCase:
        case = s.get(M.InspectionCase, case_id)
        if case is None:
            raise WorkflowError(f"점검 건 {case_id} 없음")
        self._guard(case.is_example)
        return case

    def _open_case_or_fail(self, s, case_id: int) -> M.InspectionCase:
        case = self._case(s, case_id)
        if case.status == "종결":
            raise WorkflowError("종결된 점검 건은 수정할 수 없습니다.")
        return case

    @staticmethod
    def _scopes(s, case_id: int) -> list[M.QuarterlyReview]:
        return list(s.scalars(select(M.QuarterlyReview).where(M.QuarterlyReview.case_id == case_id)
                              .order_by(M.QuarterlyReview.quarter)))

    def _current_scope(self, s, case: M.InspectionCase) -> M.QuarterlyReview:
        return self._scopes(s, case.id)[-1]

    @staticmethod
    def _copy_questions(s, case_id: int, scope_id: int, rec: dict) -> int:
        q = rec["questions"]
        texts: list[tuple[str, str]] = []
        if q["check_question"]:
            texts.append((q["check_question"], "check_question"))
        texts += [(t, "check_questions_context") for t in q["context_questions"]]
        unique: list[tuple[str, str]] = []
        for text, src in texts:
            if text not in {t for t, _ in unique}:
                unique.append((text, src))
        for pos, (text, src) in enumerate(unique):
            s.add(M.CaseCheckItem(case_id=case_id, quarterly_review_id=scope_id, position=pos,
                                  question_text=text, question_source=src))
        return len(unique)

    def _registry_verified(self, s) -> list[dict]:
        return [_plain(r, REGISTRY_FIELDS) for r in s.scalars(select(M.InstitutionRegistry).where(
            M.InstitutionRegistry.status == "verified", M.InstitutionRegistry.is_example.is_(False)))]

    # ------------------------------------------------------------ 점검 후보 (읽기 전용 파생)
    def candidates(self, snapshot: Snapshot, quarter: str) -> list[dict]:
        """Snapshot 의 Triage 단계를 점검 후보 라벨로 옮긴 목록 + 이 실행 범위(운영/시연)의 검토·점검 건 현황."""
        with self.Session() as s:
            reviews = {
                (r.industry, r.quarter): r for r in s.scalars(select(M.CandidateReview).where(
                    M.CandidateReview.snapshot_quarter == snapshot.quarter,
                    M.CandidateReview.snapshot_version == snapshot.version,
                    M.CandidateReview.quarter == quarter, M.CandidateReview.is_example.is_(self.demo)))
            }
            open_cases = {
                (c.industry, c.quarter): c for c in s.scalars(select(M.InspectionCase).where(
                    M.InspectionCase.quarter == quarter, M.InspectionCase.status.in_(M.OPEN_CASE_STATUSES),
                    M.InspectionCase.is_example.is_(self.demo)))
            }
        out = []
        for rec in snapshot.by_quarter(quarter):
            stage = rec["triage"]["stage"]
            key = (rec["industry"], rec["quarter"])
            review = reviews.get(key)
            case = open_cases.get(key)
            out.append({
                "industry": rec["industry"], "quarter": rec["quarter"], "stage": stage,
                "candidate_type": CANDIDATE_TYPE.get(stage),
                "rank_in_stage": rec["triage"]["rank_in_stage"],
                "review": _plain(review, CANDIDATE_FIELDS) if review else None,
                "open_case_id": case.id if case else None,
            })
        return out

    def start_candidate_review(self, actor, snapshot: Snapshot, industry: str, quarter: str,
                               note: str | None = None) -> dict:
        who = self._who(actor)
        rec = snapshot.get(industry, quarter)
        if rec is None:
            raise WorkflowError(f"분석본에 {industry} {quarter} 없음")
        stage = rec["triage"]["stage"]
        if stage not in CANDIDATE_TYPE:
            raise WorkflowError("관찰 단계는 점검 후보가 아닙니다. 필요하면 수동으로 점검 건을 개설하세요.")
        with self.Session.begin() as s:
            existing = s.scalar(select(M.CandidateReview).where(
                M.CandidateReview.snapshot_quarter == snapshot.quarter,
                M.CandidateReview.snapshot_version == snapshot.version,
                M.CandidateReview.industry == industry, M.CandidateReview.quarter == quarter))
            if existing:
                self._guard(existing.is_example)
                return _plain(existing, CANDIDATE_FIELDS)
            review = M.CandidateReview(
                snapshot_quarter=snapshot.quarter, snapshot_version=snapshot.version,
                industry=industry, quarter=quarter, candidate_type=CANDIDATE_TYPE[stage],
                status="검토 중", reviewer=who[0], note=(note or None), is_example=self.demo,
            )
            s.add(review)
            s.flush()
            after = _plain(review, CANDIDATE_FIELDS)
            self._audit(s, who, "candidate.review_started", "candidate_review", review.id,
                        None, after, snapshot.quarter, snapshot.version)
        return after

    def conclude_candidate_without_case(self, actor, review_id: int, note: str) -> dict:
        who = self._who(actor)
        note = _require(note, "점검 불필요 사유")
        with self.Session.begin() as s:
            review = s.get(M.CandidateReview, review_id)
            if review is None or review.status != "검토 중":
                raise WorkflowError("검토 중인 점검 후보만 종료할 수 있습니다.")
            self._guard(review.is_example)
            before = _plain(review, CANDIDATE_FIELDS)
            review.status, review.note = "점검 불필요", note
            s.flush()
            after = _plain(review, CANDIDATE_FIELDS)
            self._audit(s, who, "candidate.review_concluded", "candidate_review", review.id,
                        before, after, review.snapshot_quarter, review.snapshot_version)
        return after

    # ------------------------------------------------------------ 점검 건 · 최초 점검
    def open_case(self, actor, snapshot: Snapshot, industry: str, quarter: str,
                  reason: str, assignee: str) -> int:
        who = self._who(actor)
        reason = _require(reason, "개설 사유")
        assignee = _require(assignee, "담당자")
        rec = snapshot.get(industry, quarter)
        if rec is None:
            raise WorkflowError(f"분석본에 {industry} {quarter} 없음")
        stage = rec["triage"]["stage"]
        nature = snapshot_nature(snapshot.quarter, quarter)

        with self.Session.begin() as s:
            dup = s.scalar(select(M.InspectionCase).where(
                M.InspectionCase.industry == industry, M.InspectionCase.quarter == quarter,
                M.InspectionCase.status.in_(M.OPEN_CASE_STATUSES), M.InspectionCase.is_example.is_(self.demo)))
            if dup:
                raise WorkflowError(f"이미 진행 중인 점검 건이 있습니다(#{dup.id}).")

            review = None
            if stage in CANDIDATE_TYPE:
                review = s.scalar(select(M.CandidateReview).where(
                    M.CandidateReview.snapshot_quarter == snapshot.quarter,
                    M.CandidateReview.snapshot_version == snapshot.version,
                    M.CandidateReview.industry == industry, M.CandidateReview.quarter == quarter))
                if review is None or review.status != "검토 중":
                    raise WorkflowError("점검 후보는 담당자 검토를 시작한 뒤에 점검 건으로 개설할 수 있습니다.")
                self._guard(review.is_example)
                origin = CANDIDATE_TYPE[stage]
            else:
                origin = "수동 개설(관찰)"

            case = M.InspectionCase(
                industry=industry, quarter=quarter,
                snapshot_quarter=snapshot.quarter, snapshot_version=snapshot.version,
                snapshot_data_hash=snapshot.meta["data_hash"], snapshot_nature=nature,
                triage_stage_at_open=stage, origin=origin, candidate_review_id=review.id if review else None,
                opening_reason=reason, assignee=assignee, status="진행 중", opened_by=who[0],
                opened_at=datetime.now(timezone.utc), next_review_quarter=None, is_example=self.demo,
            )
            s.add(case)
            s.flush()
            scope = M.QuarterlyReview(
                case_id=case.id, review_kind="최초 점검", quarter=quarter, snapshot_quarter=snapshot.quarter,
                snapshot_version=snapshot.version, snapshot_data_hash=snapshot.meta["data_hash"],
                snapshot_nature=nature, current_stage=stage, review_status="진행 중", reviewer=who[0],
                started_at=case.opened_at)
            s.add(scope)
            s.flush()
            n = self._copy_questions(s, case.id, scope.id, rec)
            s.flush()

            after = _plain(case, CASE_FIELDS)
            after["checklist_size"] = n
            after["scope"] = _plain(scope, SCOPE_FIELDS)
            self._audit(s, who, "case.opened", "inspection_case", case.id, None, after,
                        snapshot.quarter, snapshot.version)
            if review is not None:
                before_r = _plain(review, CANDIDATE_FIELDS)
                review.status = "점검 건 개설"
                s.flush()
                self._audit(s, who, "candidate.case_opened", "candidate_review", review.id,
                            before_r, _plain(review, CANDIDATE_FIELDS), snapshot.quarter, snapshot.version)
            return case.id

    # ------------------------------------------------------------ 현재 점검 시점의 기록
    def record_check_result(self, actor, case_id: int, item_id: int, method: str, result: str,
                            note: str | None = None, performed_at: datetime | None = None,
                            performed_unknown: bool = False) -> dict:
        """현장확인 결과 추가. 실제 확인 시각은 담당자가 넣거나 '모름'을 명시한다(현재 시각으로 채우지 않음)."""
        who = self._who(actor)
        if method not in M.CHECK_METHODS:
            raise WorkflowError(f"확인 방법은 {M.CHECK_METHODS} 중 하나여야 합니다.")
        if result not in M.CHECK_RESULTS:
            raise WorkflowError(f"결과는 {M.CHECK_RESULTS} 중 하나여야 합니다.")
        _check_occurred(performed_at, performed_unknown, "실제 확인 일시")
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            scope = self._current_scope(s, case)
            item = s.get(M.CaseCheckItem, item_id)
            if item is None or item.case_id != case.id:
                raise WorkflowError("해당 점검 건의 현장확인 문항이 아닙니다.")
            if item.quarterly_review_id != scope.id:
                raise WorkflowError("이전 점검 시점의 현장확인 결과는 수정할 수 없습니다.")
            r = M.CheckResult(case_id=case.id, quarterly_review_id=scope.id, check_item_id=item.id,
                              method=method, result_code=result, note=(note or "").strip() or None,
                              performed_at=performed_at, recorded_by=who[0], recorded_at=datetime.now(timezone.utc))
            s.add(r)
            s.flush()
            after = _plain(r, RESULT_FIELDS)
            after["performed_at_unknown"] = performed_at is None
            self._audit(s, who, "case.field_result_recorded", "check_result", r.id, None, after,
                        scope.snapshot_quarter, scope.snapshot_version)
        return after

    def record_note(self, actor, case_id: int, note: str) -> dict:
        who = self._who(actor)
        note = _require(note, "메모")
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            scope = self._current_scope(s, case)
            n = M.CaseNote(case_id=case.id, quarterly_review_id=scope.id, note=note, recorded_by=who[0],
                           recorded_at=datetime.now(timezone.utc))
            s.add(n)
            s.flush()
            after = _plain(n, NOTE_FIELDS)
            self._audit(s, who, "case.note_recorded", "case_note", n.id, None, after,
                        scope.snapshot_quarter, scope.snapshot_version)
        return after

    def append_context_questions(self, actor, case_id: int, questions: list[str]) -> list[dict]:
        """backend가 만든 가설확인 질문을 현재 점검 시점에 추가한다.

        답을 만들지 않고, 기존 질문과 중복되는 문구는 건너뛴다. 저장 구조와 감사로그는
        기존 ``CaseCheckItem``/``AuditLog``를 재사용한다.
        """
        who = self._who(actor)
        cleaned = [str(q).strip() for q in questions or [] if str(q).strip()]
        cleaned = list(dict.fromkeys(cleaned))
        if not cleaned:
            return []
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            scope = self._current_scope(s, case)
            existing = list(s.scalars(select(M.CaseCheckItem).where(
                M.CaseCheckItem.quarterly_review_id == scope.id).order_by(M.CaseCheckItem.position)))
            seen = {item.question_text for item in existing}
            position = max((item.position for item in existing), default=-1) + 1
            added = []
            for text in cleaned:
                if text in seen:
                    continue
                item = M.CaseCheckItem(case_id=case.id, quarterly_review_id=scope.id,
                                       position=position, question_text=text,
                                       question_source="check_questions_context")
                s.add(item)
                s.flush()
                added.append(_plain(item, ITEM_FIELDS))
                seen.add(text)
                position += 1
            if added:
                self._audit(s, who, "case.context_questions_added", "quarterly_review", scope.id,
                            None, {"questions": added}, scope.snapshot_quarter, scope.snapshot_version)
        return added

    @staticmethod
    def _field_checked(s, scope_id: int) -> bool:
        return s.scalar(select(M.CheckResult.id).where(M.CheckResult.quarterly_review_id == scope_id).limit(1)) \
            is not None

    @staticmethod
    def _current_support(s, scope_id: int) -> M.CaseSupportNeed | None:
        return s.scalar(select(M.CaseSupportNeed).where(M.CaseSupportNeed.quarterly_review_id == scope_id)
                        .order_by(M.CaseSupportNeed.id.desc()).limit(1))

    def record_support_needs(self, actor, case_id: int, function_tags: list[str], note: str | None) -> dict:
        """담당자가 고른 지원 필요 기능을 현재 점검 시점에 기록한다(선택 전체를 새 행으로 추가). 시스템이 채우지 않는다."""
        who = self._who(actor)
        tags = list(dict.fromkeys(function_tags or []))
        unknown = [t for t in tags if C.function(t) is None]
        if unknown:
            raise WorkflowError(f"등록되지 않은 지원 기능입니다: {unknown}")
        note = (note or "").strip() or None
        if tags and note is None:
            raise WorkflowError("선택 이유 또는 메모를 입력해야 합니다.")
        order = C.function_tags()
        tags.sort(key=order.index)
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            scope = self._current_scope(s, case)
            prev = self._current_support(s, scope.id)
            if prev is None and not tags:
                raise WorkflowError("지원 필요 기능을 1개 이상 선택하세요.")
            rec = M.CaseSupportNeed(case_id=case.id, quarterly_review_id=scope.id, function_tags=tags, note=note,
                                    field_checked=self._field_checked(s, scope.id),
                                    catalog_version=C.catalog_version(), recorded_by=who[0],
                                    recorded_at=datetime.now(timezone.utc))
            s.add(rec)
            s.flush()
            after = _plain(rec, SUPPORT_FIELDS)
            self._audit(s, who, "case.support_needs_recorded", "case_support_need", rec.id,
                        _plain(prev, SUPPORT_FIELDS) if prev else None, after,
                        scope.snapshot_quarter, scope.snapshot_version)
        return after

    # ------------------------------------------------------------ 결정 (점검 건 상태의 유일한 변경 경로)
    def record_decision(self, actor, case_id: int, decision: str, rationale: str,
                        next_review_quarter: str | None = None,
                        handoff_targets: list[tuple[str, str]] | None = None,
                        snapshot: Snapshot | None = None, confirm_close: bool = False) -> dict:
        """현재 점검 시점에 결정을 기록하고, DECISION_RULES 에 따라 점검 건 상태를 같은 transaction 에서 맞춘다.

        - '인계'만 인계 대상(지원 필요 기능, 담당 기관)을 받아 인계 기록을 함께 만든다.
        - '종결'은 confirm_close=True(담당자의 명시적 종결 확인)일 때만, 진행 중 인계 기록이 없을 때만 가능하며
          결정 기록 + 점검 건 종료 + 종결 사유·시각 기록 + 현재 점검 시점 완료를 함께 처리한다.
        """
        who = self._who(actor)
        rationale = _require(rationale, "결정 근거")
        if decision not in M.DECISIONS:
            raise WorkflowError(f"결정은 {M.DECISIONS} 중 하나여야 합니다.")
        rule = M.DECISION_RULES[decision]
        nrq = (next_review_quarter or "").strip() or None
        if rule["next_review"] == "required" and nrq is None:
            raise WorkflowError(f"'{decision}'에는 다음 검토 분기가 필요합니다.")
        if rule["next_review"] == "none":
            nrq = None
        if nrq is not None and not QUARTER_RE.match(nrq):
            raise WorkflowError("다음 검토 분기는 2026Q3 형식이어야 합니다.")
        targets = list(dict.fromkeys(tuple(t) for t in (handoff_targets or [])))
        if decision != "인계" and targets:
            raise WorkflowError("인계 기록은 '인계'를 결정한 경우에만 만들 수 있습니다.")
        if decision == "인계" and not targets:
            raise WorkflowError("인계에는 검증된 담당 기관이 있는 지원 필요 기능을 1개 이상 골라야 합니다.")
        if decision == "종결" and not confirm_close:
            raise WorkflowError("'종결'은 점검 건을 닫습니다. 종결 확인을 선택해야 기록됩니다.")
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            scope = self._current_scope(s, case)
            if nrq is not None and nrq <= scope.quarter:
                raise WorkflowError(f"다음 검토 분기는 현재 점검 분기({scope.quarter}) 이후여야 합니다.")
            if decision == "인계":
                self._check_handoff_ready(s, case, scope, snapshot, targets)
            if decision == "종결":
                active = s.scalars(select(M.Referral.id).where(
                    M.Referral.case_id == case.id, M.Referral.status != "종결")).all()
                if active:
                    raise WorkflowError(f"진행 중인 인계 기록 {len(active)}건을 먼저 종결해야 점검 건을 종결할 수 있습니다.")
            before = _plain(case, CASE_FIELDS)
            now = datetime.now(timezone.utc)
            d = M.CaseDecision(case_id=case.id, quarterly_review_id=scope.id, decision=decision,
                               rationale=rationale, next_review_quarter=nrq, decided_by=who[0], decided_at=now)
            s.add(d)
            case.decision, case.next_review_quarter = decision, nrq
            case.status = rule["case_status"]
            if decision == "종결":
                case.closed_by, case.closed_at, case.closing_note = who[0], now, rationale
                scope_before = _plain(scope, SCOPE_FIELDS)
                scope.review_status, scope.reviewed_at = "완료", now
            s.flush()
            after = _plain(case, CASE_FIELDS)
            after["decision_record"] = _plain(d, DECISION_FIELDS)
            self._audit(s, who, "case.decision_recorded", "inspection_case", case.id,
                        before, after, scope.snapshot_quarter, scope.snapshot_version)
            if decision == "종결":
                self._audit(s, who, "case.closed", "inspection_case", case.id, before, after,
                            scope.snapshot_quarter, scope.snapshot_version)
                self._audit(s, who, "review.completed", "quarterly_review", scope.id, scope_before,
                            _plain(scope, SCOPE_FIELDS), scope.snapshot_quarter, scope.snapshot_version)
            out = dict(after)  # audit 기록(after)과 반환값을 분리
            out["referral_ids"] = [self._add_referral(s, who, case, scope, d, snapshot, tag, inst)
                                   for tag, inst in targets]
        return out

    # ------------------------------------------------------------ 인계
    def _candidates(self, s, snapshot: Snapshot, tag: str) -> list[dict]:
        return C.institution_candidates(tag, snapshot.reference["institution_routing_map"], self._registry_verified(s))

    @staticmethod
    def _fixed_snapshot(scope: M.QuarterlyReview, snapshot: Snapshot | None) -> Snapshot:
        if snapshot is None:
            raise WorkflowError("현재 점검 시점의 분석본이 필요합니다.")
        try:  # 화면 표시와 같은 검사(export.snapshot.verify_snapshot_binding)를 쓴다
            return verify_snapshot_binding(snapshot, scope.snapshot_quarter, scope.snapshot_version,
                                           scope.snapshot_data_hash)
        except SnapshotIntegrityError:
            raise WorkflowError("현재 점검 시점에 사용한 분석본과 다른 분석본입니다.") from None

    def _check_handoff_ready(self, s, case, scope, snapshot, targets):
        if not self._field_checked(s, scope.id):
            raise WorkflowError("이번 점검 시점의 현장확인 결과를 1개 이상 기록한 뒤에 인계할 수 있습니다.")
        current = self._current_support(s, scope.id)
        selected = set(current.function_tags) if current else set()
        fixed = self._fixed_snapshot(scope, snapshot)
        for tag, inst in targets:
            f = C.function(tag)
            if f is None:
                raise WorkflowError(f"등록되지 않은 지원 기능입니다: {tag}")
            if tag not in selected:
                raise WorkflowError(f"'{f['label']}'은(는) 이번 점검 시점에서 선택된 지원 필요 기능이 아닙니다.")
            if not f["referable"]:
                raise WorkflowError(f"'{f['label']}'은(는) 기관 인계 대상이 아닙니다.")
            if inst not in [c["institution"] for c in self._candidates(s, fixed, tag)]:
                raise WorkflowError(f"'{f['label']}'에 대해 검증된 담당 기관이 아닙니다({C.UNMAPPED_LABEL}).")

    def _add_referral(self, s, who, case, scope, decision, snapshot, tag, inst) -> int:
        cand = next(c for c in self._candidates(s, snapshot, tag) if c["institution"] == inst)
        dup = s.scalar(select(M.Referral).where(
            M.Referral.case_id == case.id, M.Referral.function_tag == tag,
            M.Referral.institution == inst, M.Referral.status != "종결"))
        if dup:
            raise WorkflowError(f"같은 기능·기관의 진행 중 인계 기록이 있습니다(#{dup.id}).")
        r = M.Referral(case_id=case.id, quarterly_review_id=scope.id, decision_id=decision.id, function_tag=tag,
                       institution=inst, institution_unit=cand["unit"], institution_source_url=cand["source_url"],
                       institution_source=cand["source"], mapping_verified_at=cand["verified_at"],
                       catalog_version=C.catalog_version(), status="작성", created_by=who[0],
                       created_at=datetime.now(timezone.utc))
        s.add(r)
        s.flush()
        self._audit(s, who, "referral.created", "referral", r.id, None, _plain(r, REFERRAL_FIELDS),
                    scope.snapshot_quarter, scope.snapshot_version)
        return r.id

    def institution_candidates(self, snapshot: Snapshot, function_tag: str) -> list[dict]:
        """기능 하나의 인계 가능(verified) 기관 후보(읽기 전용). 업종·분기·단계는 입력으로 받지 않는다."""
        with self.Session() as s:
            return self._candidates(s, snapshot, function_tag)

    def requirement_cards(self, function_tag: str) -> list[dict]:
        with self.Session() as s:
            rows = s.scalars(select(M.RequirementCard).where(M.RequirementCard.function_tag == function_tag))
            return [{c.name: getattr(r, c.name) for c in M.RequirementCard.__table__.columns} for r in rows]

    def create_referral(self, actor, snapshot: Snapshot, case_id: int, function_tag: str, institution: str) -> int:
        """이번 점검 시점에 이미 '인계'로 결정한 점검 건에 인계 기록을 추가한다."""
        who = self._who(actor)
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            scope = self._current_scope(s, case)
            d = s.scalar(select(M.CaseDecision).where(
                M.CaseDecision.quarterly_review_id == scope.id, M.CaseDecision.decision == "인계")
                .order_by(M.CaseDecision.id.desc()).limit(1))
            if case.decision != "인계" or d is None:
                raise WorkflowError("이번 점검 시점의 현재 결정이 '인계'인 경우에만 인계 기록을 만들 수 있습니다.")
            self._check_handoff_ready(s, case, scope, snapshot, [(function_tag, institution)])
            return self._add_referral(s, who, case, scope, d, snapshot, function_tag, institution)

    def advance_referral(self, actor, referral_id: int, to_status: str, text: str | None = None,
                         occurred_at: datetime | None = None, occurred_unknown: bool = False,
                         contact_method: str | None = None, contact_route: str | None = None,
                         external_reference: str | None = None) -> dict:
        """인계 기록 상태를 한 단계 옮긴다(수동). 허용된 전이만 가능하며 모두 audit 에 남는다.

        - 발송·접수·회신은 실제 업무 발생시각을 넣거나 '모름'을 명시해야 한다(현재 시각으로 채우지 않음).
        - 발송 기록에는 담당자가 실제로 쓴 연락·접수 방식과 경로를 남긴다. 시스템이 기관에 보내는 것이 아니다.
        """
        who = self._who(actor)
        if to_status not in REFERRAL_ACTIONS:
            raise WorkflowError(f"상태는 {tuple(REFERRAL_ACTIONS)} 중 하나여야 합니다.")
        action, field, required = REFERRAL_ACTIONS[to_status]
        text = (text or "").strip() or None
        if required and text is None:
            raise WorkflowError(f"{REFERRAL_INPUT_LABEL[field]}을(를) 입력해야 합니다.")
        stamp = REFERRAL_OCCURRED.get(to_status)
        if stamp:
            _check_occurred(occurred_at, occurred_unknown, "실제 발생 일시")
        if to_status == "발송 기록":
            if contact_method not in M.CONTACT_METHODS:
                raise WorkflowError(f"실제 연락·접수 방식을 {M.CONTACT_METHODS} 중에서 골라야 합니다.")
            contact_route = _require(contact_route, "실제 사용한 접수·연락 경로")
        now = datetime.now(timezone.utc)
        with self.Session.begin() as s:
            r = s.get(M.Referral, referral_id)
            if r is None:
                raise WorkflowError(f"인계 기록 {referral_id} 없음")
            self._open_case_or_fail(s, r.case_id)
            scope = s.get(M.QuarterlyReview, r.quarterly_review_id)
            if to_status not in M.REFERRAL_TRANSITIONS[r.status]:
                raise WorkflowError(f"'{r.status}' 상태에서는 '{to_status}'(으)로 바꿀 수 없습니다.")
            before = _plain(r, REFERRAL_FIELDS)
            if to_status == "발송 기록":  # (재)발송: 이번 회차 값만 남긴다(이전 회차는 audit 에 남음)
                r.received_by = r.received_at = r.received_note = None
                r.replied_by = r.replied_at = r.reply_content = None
                r.contact_method, r.contact_route = contact_method, contact_route
                r.external_reference = (external_reference or "").strip() or None
            if stamp and occurred_at is not None:
                earlier = [getattr(r, f"{p}_at") for p in REFERRAL_ORDER[:REFERRAL_ORDER.index(stamp)]]
                if any(e is not None and _aware(e) > occurred_at for e in earlier):
                    raise WorkflowError("실제 발생 일시가 이전 단계(발송·접수)보다 앞섭니다.")
            if stamp:
                setattr(r, f"{stamp}_by", who[0])
                setattr(r, f"{stamp}_at", occurred_at)
            if to_status == "종결":
                r.closed_by, r.closed_at = who[0], now
            setattr(r, field, text)
            r.status = to_status
            s.flush()
            after = _plain(r, REFERRAL_FIELDS)
            after["occurred_at_unknown"] = bool(stamp) and occurred_at is None
            self._audit(s, who, action, "referral", r.id, before, after,
                        scope.snapshot_quarter, scope.snapshot_version)
        return after

    # ------------------------------------------------------------ 기관 후보 등록부
    def propose_institution(self, actor, institution: str, function_description: str, source_url: str,
                            function_tags: list[str], unit: str | None = None, basis: str | None = None) -> dict:
        """카탈로그 밖 기관을 '제안(proposed)'으로만 저장한다. 검증 전에는 인계 대상이 아니다.

        verified 로 바꾸는 승인 기능은 로그인·관리자 권한 도입 전까지 제공하지 않는다.
        """
        who = self._who(actor)
        institution = _require(institution, "기관명")
        function_description = _require(function_description, "기관 기능 설명")
        source_url = _require(source_url, "공식 출처 URL")
        if not source_url.startswith(("http://", "https://")):
            raise WorkflowError("공식 출처는 http(s) 주소여야 합니다.")
        tags = list(dict.fromkeys(function_tags or []))
        if not tags or any(C.function(t) is None or not C.function(t)["referable"] for t in tags):
            raise WorkflowError("인계 대상 지원 기능을 1개 이상 골라야 합니다.")
        with self.Session.begin() as s:
            r = M.InstitutionRegistry(institution=institution, unit=(unit or "").strip() or None,
                                      function_description=function_description, function_tags=tags,
                                      source_url=source_url, basis=(basis or "").strip() or None, status="proposed",
                                      proposed_by=who[0], proposed_at=datetime.now(timezone.utc),
                                      is_example=self.demo)
            s.add(r)
            s.flush()
            after = _plain(r, REGISTRY_FIELDS)
            self._audit(s, who, "institution.proposed", "institution_registry", r.id, None, after, None, None)
        return after

    def institution_registry(self) -> list[dict]:
        with self.Session() as s:
            return [_plain(r, REGISTRY_FIELDS) for r in s.scalars(
                select(M.InstitutionRegistry).where(M.InstitutionRegistry.is_example.is_(self.demo))
                .order_by(M.InstitutionRegistry.id))]

    # ------------------------------------------------------------ 분기 재점검 = 새 점검 시점
    def due_reviews(self, resolve) -> list[dict]:
        """재점검 예정: 열린 점검 건 중, 담당자가 기록한 다음 검토 분기의 분석 자료가 있는 것.

        resolve(target_quarter) → 그 분기를 볼 분석본(당시 분석본 우선, 없으면 후향 재구성) 또는 None.
        우선순위를 새로 매기지 않는다(다음 검토 분기·점검 건 번호 순).
        """
        out = []
        with self.Session() as s:
            for case in s.scalars(select(M.InspectionCase).where(
                    M.InspectionCase.status.in_(M.OPEN_CASE_STATUSES),
                    M.InspectionCase.next_review_quarter.is_not(None), M.InspectionCase.is_example.is_(self.demo))
                    .order_by(M.InspectionCase.next_review_quarter, M.InspectionCase.id)):
                nrq = case.next_review_quarter
                snap = resolve(nrq)
                if snap is None or snap.get(case.industry, nrq) is None:
                    continue
                scopes = self._scopes(s, case.id)
                if any(sc.quarter == nrq for sc in scopes):
                    continue
                cur = scopes[-1]
                out.append({"case_id": case.id, "industry": case.industry, "review_quarter": nrq,
                            "previous_quarter": cur.quarter, "previous_stage": cur.current_stage,
                            "decision": case.decision, "case_status": case.status,
                            "snapshot": f"{snap.quarter} {snap.version}",
                            "snapshot_nature": snapshot_nature(snap.quarter, nrq), "is_example": case.is_example})
        return out

    def start_quarterly_review(self, actor, case_id: int, snapshot: Snapshot) -> dict:
        """다음 검토 분기의 재점검 시점을 연다. 직전 시점은 완료되고 그 기록은 그대로 보존된다.

        새 시점의 현장확인 문항은 그 분기 분석본에 등록된 확인질문을 복사한다. 모니터링 중이던 점검 건은
        담당자가 재점검을 시작하는 이 행동으로 '진행 중'이 된다.
        """
        who = self._who(actor)
        with self.Session.begin() as s:
            case = self._open_case_or_fail(s, case_id)
            nrq = case.next_review_quarter
            if nrq is None:
                raise WorkflowError("다음 검토 분기가 기록된 점검 건만 재점검할 수 있습니다.")
            rec = snapshot.get(case.industry, nrq)
            if rec is None:
                raise WorkflowError(f"{nrq} 분석본 자료가 아직 없어 재점검할 수 없습니다.")
            scopes = self._scopes(s, case.id)
            if any(sc.quarter == nrq for sc in scopes):
                raise WorkflowError(f"{nrq} 재점검은 이미 기록되었습니다.")
            prev = scopes[-1]
            now = datetime.now(timezone.utc)
            prev_before = _plain(prev, SCOPE_FIELDS)
            prev.review_status, prev.reviewed_at = "완료", now
            r = M.QuarterlyReview(
                case_id=case.id, review_kind="재점검", quarter=nrq, snapshot_quarter=snapshot.quarter,
                snapshot_version=snapshot.version, snapshot_data_hash=snapshot.meta["data_hash"],
                snapshot_nature=snapshot_nature(snapshot.quarter, nrq), previous_quarter=prev.quarter,
                previous_snapshot_quarter=prev.snapshot_quarter, previous_snapshot_version=prev.snapshot_version,
                previous_stage=prev.current_stage, current_stage=rec["triage"]["stage"], review_status="진행 중",
                reviewer=who[0], started_at=now)
            s.add(r)
            s.flush()
            n = self._copy_questions(s, case.id, r.id, rec)
            s.flush()
            self._audit(s, who, "review.completed", "quarterly_review", prev.id, prev_before,
                        _plain(prev, SCOPE_FIELDS), prev.snapshot_quarter, prev.snapshot_version)
            after = _plain(r, SCOPE_FIELDS)
            after["checklist_size"] = n
            self._audit(s, who, "review.started", "quarterly_review", r.id, None, after,
                        snapshot.quarter, snapshot.version)
            if case.status != "진행 중":
                case_before = _plain(case, CASE_FIELDS)
                case.status = "진행 중"
                s.flush()
                self._audit(s, who, "case.status_changed", "inspection_case", case.id, case_before,
                            _plain(case, CASE_FIELDS), snapshot.quarter, snapshot.version)
        return after

    # ------------------------------------------------------------ 조회
    def referral_events(self, referral_id: int) -> list[dict]:
        """인계 기록의 단계별 이력(audit 원본에서 파생). 실제 발생시각과 시스템 기록시각을 따로 준다."""
        out = []
        for a in reversed(self.audit_log(target_type="referral", target_id=referral_id)):
            after = a["after"] or {}
            status = after.get("status")
            created = a["action"] == "referral.created"
            stamp = None if created else REFERRAL_OCCURRED.get(status)
            field = None if created or status not in REFERRAL_ACTIONS else REFERRAL_ACTIONS[status][1]
            out.append({"action": a["action"], "status": status, "actor": a["actor"],
                        "recorded_at": a["created_at"],
                        "occurred_at": after.get(f"{stamp}_at") if stamp else None,
                        "occurred_unknown": bool(after.get("occurred_at_unknown")),
                        "has_occurred_time": bool(stamp),
                        "contact": ((after.get("contact_method"), after.get("contact_route"),
                                     after.get("external_reference")) if status == "발송 기록" and not created
                                    else None),
                        "text": after.get(field) if field else None})
        return out

    def clear_audit_log(self, actor, reason: str) -> int:
        """현재 실행 범위(운영/시연)의 변경 기록을 비운다 — 담당자가 사유를 적었을 때만.

        인계 처리 이력(발송·접수·회신 시각)은 변경 기록에서 파생되므로 함께 사라진다. 초기화 사실은 새 기록 1건
        ('변경 기록 초기화' · 사유 · 삭제 건수)으로 남긴다. 다른 실행 범위의 기록은 건드리지 않는다.
        """
        who = self._who(actor)
        reason = _require(reason, "초기화 사유")
        with self.Session.begin() as s:
            rows = list(s.scalars(select(M.AuditLog).where(M.AuditLog.is_example.is_(self.demo))))
            for row in rows:
                s.delete(row)
            s.flush()
            self._audit(s, who, "audit.cleared", "audit_log", "all", None,
                        {"reason": reason, "deleted_records": len(rows)}, None, None)
        return len(rows)

    def delete_case(self, actor, case_id: int, reason: str) -> dict:
        """점검 건과 그 하위 기록(점검 시점·현장확인 문항·결과·메모·지원 필요 기능·결정·인계)을 한 transaction으로 삭제한다.

        - 담당자가 사유를 적어야만 삭제한다(진행 중·종결 모두 가능).
        - 이 점검 건을 열기 위해서만 쓰인 점검 후보 검토(상태 '점검 건 개설')도 함께 지워 후보가 '미개설'로 돌아간다.
        - 감사로그는 지우지 않는다. 기존 기록은 그대로 두고 '점검 건 삭제' 기록(사유·삭제 건수·삭제 전 점검 건)을 추가한다.
        """
        who = self._who(actor)
        reason = _require(reason, "삭제 사유")
        with self.Session.begin() as s:
            case = self._case(s, case_id)
            before = _plain(case, CASE_FIELDS)
            snap_q, snap_v, review_id = case.snapshot_quarter, case.snapshot_version, case.candidate_review_id
            deleted = {}
            # 외래키 순서: 결과→문항, 인계→결정, 모든 하위 기록→점검 시점→점검 건
            for model in (M.CheckResult, M.CaseNote, M.CaseSupportNeed, M.Referral, M.CaseDecision, M.CaseCheckItem,
                          M.QuarterlyReview):
                rows = list(s.scalars(select(model).where(model.case_id == case_id)))
                deleted[model.__tablename__] = len(rows)
                for row in rows:
                    s.delete(row)
                s.flush()
            s.delete(case)
            s.flush()
            review = s.get(M.CandidateReview, review_id) if review_id else None
            if review is not None and review.status == "점검 건 개설" and s.scalar(
                    select(M.InspectionCase.id).where(M.InspectionCase.candidate_review_id == review.id)) is None:
                s.delete(review)
                deleted["candidate_reviews"] = 1
            self._audit(s, who, "case.deleted", "inspection_case", case_id, before,
                        {"reason": reason, "deleted_records": deleted}, snap_q, snap_v)
        return deleted

    def get_case(self, case_id: int) -> dict | None:
        with self.Session() as s:
            case = s.scalar(select(M.InspectionCase).where(M.InspectionCase.id == case_id)
                            .options(selectinload(M.InspectionCase.decisions),
                                     selectinload(M.InspectionCase.referrals)))
            if case is None:
                return None
            self._guard(case.is_example)
            out = _plain(case, CASE_FIELDS)
            out["decisions"] = [_plain(d, DECISION_FIELDS) for d in case.decisions]
            out["referrals"] = [_plain(r, REFERRAL_FIELDS) for r in case.referrals]
            out["scopes"] = []
            for sc in s.scalars(select(M.QuarterlyReview).where(M.QuarterlyReview.case_id == case.id)
                                .order_by(M.QuarterlyReview.quarter)
                                .options(selectinload(M.QuarterlyReview.checks),
                                         selectinload(M.QuarterlyReview.results),
                                         selectinload(M.QuarterlyReview.notes),
                                         selectinload(M.QuarterlyReview.support_needs))):
                d = _plain(sc, SCOPE_FIELDS)
                results = [_plain(r, RESULT_FIELDS) for r in sc.results]
                d["checks"] = []
                for item in sc.checks:
                    it = _plain(item, ITEM_FIELDS)
                    it["history"] = [r for r in results if r["check_item_id"] == item.id]
                    it["latest"] = it["history"][-1] if it["history"] else None
                    d["checks"].append(it)
                d["notes"] = [_plain(n, NOTE_FIELDS) for n in sc.notes]
                d["support_need_history"] = [_plain(n, SUPPORT_FIELDS) for n in sc.support_needs]
                d["support_needs"] = d["support_need_history"][-1] if sc.support_needs else None
                d["decisions"] = [x for x in out["decisions"] if x["quarterly_review_id"] == sc.id]
                d["referrals"] = [x for x in out["referrals"] if x["quarterly_review_id"] == sc.id]
                out["scopes"].append(d)
            out["current_scope"] = out["scopes"][-1]
            return out

    def list_cases(self, status: str | None = None) -> list[dict]:
        with self.Session() as s:
            q = select(M.InspectionCase).where(M.InspectionCase.is_example.is_(self.demo)) \
                .order_by(M.InspectionCase.id.desc())
            if status:
                q = q.where(M.InspectionCase.status == status)
            return [_plain(c, CASE_FIELDS) for c in s.scalars(q)]

    def count_cases(self) -> int:
        with self.Session() as s:
            return len(s.scalars(select(M.InspectionCase.id).where(
                M.InspectionCase.is_example.is_(self.demo))).all())

    def audit_log(self, target_type: str | None = None, target_id=None, limit: int = 1000,
                  include_all: bool = False) -> list[dict]:
        """현재 실행 범위의 감사 기록. 관리자 경계가 생기면 include_all=True로 원본 전체 조회 가능."""
        with self.Session() as s:
            q = select(M.AuditLog).order_by(M.AuditLog.id.desc()).limit(limit)
            if not include_all:
                q = q.where(M.AuditLog.is_example.is_(self.demo))
            if target_type:
                q = q.where(M.AuditLog.target_type == target_type)
            if target_id is not None:
                q = q.where(M.AuditLog.target_id == str(target_id))
            return [_plain(a, AUDIT_FIELDS) for a in s.scalars(q)]

    # ------------------------------------------------------------ 분기 운영 사후검토
    def operations_quarters(self, snapshot: Snapshot) -> list[str]:
        """사후검토에서 고를 수 있는 분기: 분석본 분기 + 실제 업무시각(종결·인계 발생)이 속한 분기."""
        qs = set(snapshot.quarters)
        with self.Session() as s:
            for c in s.scalars(select(M.InspectionCase).where(M.InspectionCase.is_example.is_(False))):
                if c.closed_at:
                    qs.add(quarter_of(c.closed_at))
            for r in s.scalars(select(M.Referral).join(M.InspectionCase).where(M.InspectionCase.is_example.is_(False))):
                for p in REFERRAL_ORDER:
                    if getattr(r, f"{p}_at"):
                        qs.add(quarter_of(getattr(r, f"{p}_at")))
        return sorted(qs)

    def operations_summary(self, snapshot: Snapshot, quarter: str) -> dict:
        """분기 운영 사후검토 지표. 시연 기록(is_example)은 모두 제외한다. 지표마다 기준 시점이 다르다.

        업무 운영 결과의 집계이며 모형 성능 평가가 아니다. 현장확인 결과를 정답으로 쓰지 않고,
        관찰·미개설 사례에 대해서는 어떤 비율도 계산하지 않는다.
        """
        recs = snapshot.by_quarter(quarter)
        cand = {stage: sorted(r["industry"] for r in recs if r["triage"]["stage"] == stage)
                for stage in CANDIDATE_TYPE}

        def ratio(num, den):
            return {"numerator": num, "denominator": den, "ratio": (num / den) if den else None}

        with self.Session() as s:
            cases = s.scalars(select(M.InspectionCase).options(
                selectinload(M.InspectionCase.referrals), selectinload(M.InspectionCase.decisions))).all()
            excluded = sum(bool(c.is_example) for c in cases)
            cases = [c for c in cases if not c.is_example]
            ids = {c.id for c in cases}
            opened_q = [c for c in cases if c.quarter == quarter]
            opened = {stage: sorted({c.industry for c in opened_q
                                     if c.origin == CANDIDATE_TYPE[stage] and c.industry in cand[stage]})
                      for stage in CANDIDATE_TYPE}
            scopes = [sc for sc in s.scalars(select(M.QuarterlyReview).options(
                selectinload(M.QuarterlyReview.checks), selectinload(M.QuarterlyReview.results),
                selectinload(M.QuarterlyReview.support_needs), selectinload(M.QuarterlyReview.decisions)))
                if sc.case_id in ids]
            scopes_q = [sc for sc in scopes if sc.quarter == quarter]
            results = {k: 0 for k in (*M.CHECK_RESULTS, "미실시")}
            for sc in scopes_q:
                for item in sc.checks:
                    hist = [r for r in sc.results if r.check_item_id == item.id]
                    results[hist[-1].result_code if hist else "미실시"] += 1
            support = {f["tag"]: 0 for f in C.functions()}
            with_selection = 0
            for sc in scopes_q:
                if sc.support_needs and sc.support_needs[-1].function_tags:
                    with_selection += 1
                    for t in sc.support_needs[-1].function_tags:
                        support[t] = support.get(t, 0) + 1
            decisions = {d: 0 for d in M.DECISIONS}
            for sc in scopes_q:
                if sc.decisions:
                    decisions[sc.decisions[-1].decision] += 1
            moves: dict[str, int] = {}
            for sc in scopes_q:
                if sc.review_kind == "재점검":
                    key = f"{sc.previous_stage} → {sc.current_stage}"
                    moves[key] = moves.get(key, 0) + 1
            scope_q_ids = {sc.id for sc in scopes_q}
            referrals = [r for c in cases for r in c.referrals]
            created_q = [r for r in referrals if r.quarterly_review_id in scope_q_ids]
            rid = [str(r.id) for r in referrals]
            events = list(s.scalars(select(M.AuditLog).where(
                M.AuditLog.target_type == "referral", M.AuditLog.target_id.in_(rid or ["-"]))))
            sent = {a.target_id for a in events if a.action == "referral.sent"}
            replied = {a.target_id for a in events if a.action == "referral.replied"}
            created_ids = {str(r.id) for r in created_q}
            occurred = {"발송": 0, "접수": 0, "회신": 0}
            unknown = {"발송": 0, "접수": 0, "회신": 0}
            for a in events:
                key = {"referral.sent": ("발송", "sent"), "referral.received": ("접수", "received"),
                       "referral.replied": ("회신", "replied")}.get(a.action)
                if key is None:
                    continue
                at = (a.after or {}).get(f"{key[1]}_at")
                if at is None:
                    unknown[key[0]] += 1
                elif quarter_of(at) == quarter:
                    occurred[key[0]] += 1
            closed = sum(1 for c in cases if c.closed_at is not None and quarter_of(c.closed_at) == quarter)
        return {
            "quarter": quarter, "snapshot": f"{snapshot.quarter} {snapshot.version}",
            "excluded_example_cases": excluded,
            "basis": {
                "candidates": "후보·개설: 점검 대상(개설) 분기",
                "field_results": "현장확인: 점검 시점 분기(최초 점검·재점검의 대상 분기)",
                "support": "지원 필요 기능: 점검 시점 분기",
                "decisions": "결정: 점검 시점 분기(시점별 마지막 결정)",
                "stage_moves": "단계 이동: 재점검 시점 분기",
                "referrals": "인계 생성: 인계를 결정한 점검 시점 분기",
                "occurred": "발송·접수·회신: 실제 업무 발생일의 달력 분기(발생일 미입력은 분기 배정 불가)",
                "closed": "종결: 점검 건을 실제로 종결한 날의 달력 분기",
            },
            "cases_opened": len(opened_q),
            "priority_candidates": len(cand["우선점검"]),
            "priority_opened": ratio(len(opened["우선점검"]), len(cand["우선점검"])),
            "check_candidates": len(cand["추가확인"]),
            "check_opened": ratio(len(opened["추가확인"]), len(cand["추가확인"])),
            "scopes": len(scopes_q),
            "field_results": results,
            "support_functions": support, "scopes_with_support_selection": with_selection,
            "decisions": decisions,
            "stage_moves": moves,
            "referrals_created": len(created_q),
            "referrals_sent": len(created_ids & sent),
            "referral_reply": ratio(len(created_ids & sent & replied), len(created_ids & sent)),
            "occurred_in_quarter": occurred,
            "occurred_unknown_all_quarters": unknown,
            "cases_closed": closed,
        }
