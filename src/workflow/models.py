"""점검 업무 기록(Workflow) 도메인 모델 — PostgreSQL 기준 정의.

- 운영 대상 DB 는 PostgreSQL(Supabase 포함). JSON 컬럼은 PostgreSQL 에서 JSONB 로 생성된다.
- 로컬 실행은 같은 모델을 SQLite 로 연다(DSS_DATABASE_URL 미설정 시). 별도 mock 구조는 없다.
- 스키마는 Alembic migration(workflow/migrations)으로만 만들고 바꾼다. create_all 을 쓰지 않는다.
- 열거값은 DB 이식성을 위해 문자열 + CHECK 제약으로 둔다.
- 분석값(단계·지표)은 여기에 복사하지 않는다. 점검 시점마다 사용한 Snapshot 버전만 고정해 참조한다.

점검 시점(review scope) 구조:
  점검 건(inspection_cases)
   ├─ 최초 점검   (quarterly_reviews.review_kind='최초 점검')
   └─ 재점검 …    (quarterly_reviews.review_kind='재점검')
  현장확인 문항·결과, 메모, 지원 필요 기능, 결정, 인계 기록은 모두 점검 시점(quarterly_review_id)에 묶인다.
  이전 시점의 기록은 덮어쓰지 않으며 업무 테이블만으로 조회된다.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
    create_engine, event, false, text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{(ROOT / 'app_state' / 'workflow.db').as_posix()}"
DEFAULT_DEMO_DATABASE_URL = f"sqlite:///{(ROOT / 'app_state' / 'workflow-demo.db').as_posix()}"

# 업무 열거값
CANDIDATE_STATUSES = ("검토 중", "점검 건 개설", "점검 불필요")
CASE_ORIGINS = ("우선점검 후보", "검토 후보", "수동 개설(관찰)")
# 진행 중 = 적극 점검 / 모니터링 = 적극 점검은 끝났으나 다음 검토 계획 보존 / 종결 = 담당자 종결
CASE_STATUSES = ("진행 중", "모니터링", "종결")
OPEN_CASE_STATUSES = ("진행 중", "모니터링")
CHECK_METHODS = ("방문", "전화", "문서")
CHECK_RESULTS = ("확인", "부분 확인", "미확인", "반대증거")
DECISIONS = ("계속 점검", "추가확인", "모니터링 전환", "인계", "종결")
# 결정 → 결정 직후 점검 건 상태, 다음 검토 분기 필요 여부. 상태를 바꾸는 것은 담당자의 결정뿐이다.
DECISION_RULES = {
    "계속 점검": {"case_status": "진행 중", "next_review": "required"},
    "추가확인": {"case_status": "진행 중", "next_review": "required"},
    "모니터링 전환": {"case_status": "모니터링", "next_review": "required"},
    "인계": {"case_status": "진행 중", "next_review": "optional"},
    "종결": {"case_status": "종결", "next_review": "none"},
}
DECISIONS_NEED_NEXT_REVIEW = tuple(d for d, r in DECISION_RULES.items() if r["next_review"] == "required")
REVIEW_KINDS = ("최초 점검", "재점검")
REVIEW_STATUSES = ("진행 중", "완료")
SNAPSHOT_NATURES = ("contemporaneous", "reconstructed")
QUESTION_SOURCES = ("check_question", "check_questions_context")
REFERRAL_STATUSES = ("작성", "발송 기록", "접수 확인", "처리·회신 기록", "추가확인 필요", "종결")
# 인계 기록 상태전이(모두 수동). 종결은 끝 상태.
REFERRAL_TRANSITIONS = {
    "작성": ("발송 기록", "종결"),
    "발송 기록": ("접수 확인",),
    "접수 확인": ("처리·회신 기록",),
    "처리·회신 기록": ("종결", "추가확인 필요"),
    "추가확인 필요": ("발송 기록", "종결"),
    "종결": (),
}
# 발송 기록 시 담당자가 실제로 쓴 연락·접수 방식(시스템이 보내는 것이 아님)
CONTACT_METHODS = ("공문", "전자우편", "전화", "방문", "기관 온라인 창구(담당자 직접 입력)", "기타")
INSTITUTION_STATUSES = ("proposed", "verified", "rejected")

JsonType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class CandidateReview(Base):
    """점검 후보(Snapshot 에서 파생)에 대해 담당자가 검토를 시작했을 때만 생기는 기록."""

    __tablename__ = "candidate_reviews"
    __table_args__ = (
        UniqueConstraint("snapshot_quarter", "snapshot_version", "industry", "quarter"),
        CheckConstraint(_in("status", CANDIDATE_STATUSES), name="ck_candidate_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_quarter: Mapped[str] = mapped_column(String(6))
    snapshot_version: Mapped[str] = mapped_column(String(8))
    industry: Mapped[str] = mapped_column(String(40))
    quarter: Mapped[str] = mapped_column(String(6))
    candidate_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    reviewer: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class InspectionCase(Base):
    """점검 건 = 업종 × 분기 점검 건(기업 사건 아님). 개설·종결은 담당자 행동으로만."""

    __tablename__ = "inspection_cases"
    __table_args__ = (
        CheckConstraint(_in("origin", CASE_ORIGINS), name="ck_case_origin"),
        CheckConstraint(_in("status", CASE_STATUSES), name="ck_case_status"),
        CheckConstraint(f"decision IS NULL OR {_in('decision', DECISIONS)}", name="ck_case_decision"),
        CheckConstraint(_in("snapshot_nature", SNAPSHOT_NATURES), name="ck_case_snapshot_nature"),
        Index("uq_open_case_scope", "industry", "quarter", "is_example", unique=True,
              sqlite_where=text("status IN ('진행 중', '모니터링')"),
              postgresql_where=text("status IN ('진행 중', '모니터링')")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry: Mapped[str] = mapped_column(String(40))
    quarter: Mapped[str] = mapped_column(String(6))  # 최초 점검 대상 분기(target quarter)
    # 개설 시 사용한 분석본. snapshot_quarter = 분석 실행 분기(run quarter)
    snapshot_quarter: Mapped[str] = mapped_column(String(6))
    snapshot_version: Mapped[str] = mapped_column(String(8))
    snapshot_data_hash: Mapped[str] = mapped_column(String(64))
    # contemporaneous = 대상 분기 실행 분석본 / reconstructed = 후속 실행으로 후향 재구성된 과거분기
    snapshot_nature: Mapped[str] = mapped_column(String(16))
    triage_stage_at_open: Mapped[str] = mapped_column(String(10))
    origin: Mapped[str] = mapped_column(String(20))
    candidate_review_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_reviews.id"))
    opening_reason: Mapped[str] = mapped_column(Text)
    assignee: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10), default="진행 중")
    decision: Mapped[str | None] = mapped_column(String(20))
    next_review_quarter: Mapped[str | None] = mapped_column(String(6))
    opened_by: Mapped[str] = mapped_column(String(80))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_by: Mapped[str | None] = mapped_column(String(80))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_note: Mapped[str | None] = mapped_column(Text)  # 종결 사유(= 종결 결정 근거)
    # 시연·테스트 기록. 시연 모드 실행에서만 True 가 되며 분기 사후검토의 모든 운영지표에서 제외한다.
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    scopes: Mapped[list["QuarterlyReview"]] = relationship(back_populates="case", order_by="QuarterlyReview.quarter")
    decisions: Mapped[list["CaseDecision"]] = relationship(back_populates="case", order_by="CaseDecision.id")
    referrals: Mapped[list["Referral"]] = relationship(back_populates="case", order_by="Referral.id")


class QuarterlyReview(Base):
    """점검 시점(review scope): 최초 점검 또는 분기 재점검. 한 점검 건에 분기별로 누적된다.

    각 시점은 그때 사용한 분석본과 그 성격(당시 분석본/후향 재구성)을 고정한다.
    단계는 분석본 값을 옮긴 것이며, 이동의 의미는 기록하지 않는다.
    """

    __tablename__ = "quarterly_reviews"
    __table_args__ = (
        UniqueConstraint("case_id", "quarter"),
        CheckConstraint(_in("review_status", REVIEW_STATUSES), name="ck_review_status"),
        CheckConstraint(_in("review_kind", REVIEW_KINDS), name="ck_review_kind"),
        CheckConstraint(_in("snapshot_nature", SNAPSHOT_NATURES), name="ck_review_snapshot_nature"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    review_kind: Mapped[str] = mapped_column(String(10))
    quarter: Mapped[str] = mapped_column(String(6))  # 이 시점의 대상 분기(target quarter)
    snapshot_quarter: Mapped[str] = mapped_column(String(6))  # 분석 실행 분기(run quarter)
    snapshot_version: Mapped[str] = mapped_column(String(8))
    snapshot_data_hash: Mapped[str] = mapped_column(String(64))
    snapshot_nature: Mapped[str] = mapped_column(String(16))
    previous_quarter: Mapped[str | None] = mapped_column(String(6))
    previous_snapshot_quarter: Mapped[str | None] = mapped_column(String(6))
    previous_snapshot_version: Mapped[str | None] = mapped_column(String(8))
    previous_stage: Mapped[str | None] = mapped_column(String(10))
    current_stage: Mapped[str] = mapped_column(String(10))
    review_status: Mapped[str] = mapped_column(String(10), default="진행 중")
    reviewer: Mapped[str] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 시점 완료(다음 재점검 시작·종결)

    case: Mapped[InspectionCase] = relationship(back_populates="scopes")
    checks: Mapped[list["CaseCheckItem"]] = relationship(order_by="CaseCheckItem.position")
    results: Mapped[list["CheckResult"]] = relationship(order_by="CheckResult.id")
    notes: Mapped[list["CaseNote"]] = relationship(order_by="CaseNote.id")
    support_needs: Mapped[list["CaseSupportNeed"]] = relationship(order_by="CaseSupportNeed.id")
    decisions: Mapped[list["CaseDecision"]] = relationship(order_by="CaseDecision.id", viewonly=True)


class CaseCheckItem(Base):
    """현장확인 문항. 점검 시점마다 그 시점 분석본의 등록 확인질문을 그대로 복사한다."""

    __tablename__ = "case_check_items"
    __table_args__ = (CheckConstraint(_in("question_source", QUESTION_SOURCES), name="ck_check_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    quarterly_review_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reviews.id"))
    position: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text)
    question_source: Mapped[str] = mapped_column(String(40))


class CheckResult(Base):
    """현장확인 결과(추가만 함). 같은 문항을 다시 기록하면 새 행이 생기고, 현재 결과는 가장 최근 행.

    performed_at = 실제 확인 시각(담당자 입력, 모르면 NULL) / recorded_at = 시스템 입력 시각.
    """

    __tablename__ = "check_results"
    __table_args__ = (
        CheckConstraint(_in("method", CHECK_METHODS), name="ck_result_method"),
        CheckConstraint(_in("result_code", CHECK_RESULTS), name="ck_result_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    quarterly_review_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reviews.id"))
    check_item_id: Mapped[int] = mapped_column(ForeignKey("case_check_items.id"))
    method: Mapped[str] = mapped_column(String(10))
    result_code: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(Text)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CaseNote(Base):
    """점검 시점별 현장 메모(추가만 함)."""

    __tablename__ = "case_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    quarterly_review_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reviews.id"))
    note: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CaseDecision(Base):
    """결정 기록(이력). 점검 건의 현재 결정은 inspection_cases.decision."""

    __tablename__ = "case_decisions"
    __table_args__ = (CheckConstraint(_in("decision", DECISIONS), name="ck_decision_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    quarterly_review_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reviews.id"))
    decision: Mapped[str] = mapped_column(String(20))
    rationale: Mapped[str] = mapped_column(Text)
    next_review_quarter: Mapped[str | None] = mapped_column(String(6))
    decided_by: Mapped[str] = mapped_column(String(80))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped[InspectionCase] = relationship(back_populates="decisions")


class CaseSupportNeed(Base):
    """지원 필요 기능 선택 기록(추가만 함). 점검 시점별 현재 선택은 그 시점의 가장 최근 행.

    function_tags 값은 function_catalog.json 의 tag 이며 서비스에서 검증한다(목록을 여기에 중복 정의하지 않음).
    """

    __tablename__ = "case_support_needs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    quarterly_review_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reviews.id"))
    function_tags: Mapped[list] = mapped_column(JsonType)
    note: Mapped[str | None] = mapped_column(Text)
    # 선택 시점에 그 점검 시점의 현장확인 결과가 하나도 없었으면 False(= 현장확인 전·참고용 선택)
    field_checked: Mapped[bool] = mapped_column(Boolean)
    catalog_version: Mapped[str] = mapped_column(String(40))
    recorded_by: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Referral(Base):
    """인계 기록. '인계' 결정에 묶이며, 외부 기관 시스템과 연동하지 않는 수동 기록이다."""

    __tablename__ = "referrals"
    __table_args__ = (
        CheckConstraint(_in("status", REFERRAL_STATUSES), name="ck_referral_status"),
        CheckConstraint(f"contact_method IS NULL OR {_in('contact_method', CONTACT_METHODS)}",
                        name="ck_referral_contact_method"),
        Index("uq_active_referral", "case_id", "function_tag", "institution", unique=True,
              sqlite_where=text("status <> '종결'"), postgresql_where=text("status <> '종결'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("inspection_cases.id"))
    quarterly_review_id: Mapped[int] = mapped_column(ForeignKey("quarterly_reviews.id"))
    decision_id: Mapped[int] = mapped_column(ForeignKey("case_decisions.id"))
    function_tag: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str] = mapped_column(String(120))
    institution_unit: Mapped[str | None] = mapped_column(String(120))
    institution_source_url: Mapped[str | None] = mapped_column(Text)
    institution_source: Mapped[str | None] = mapped_column(String(40))  # catalog / registry:<id>
    mapping_verified_at: Mapped[str | None] = mapped_column(String(10))
    catalog_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="작성")
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # *_at(발송·접수·회신) = 담당자가 입력한 실제 업무 발생시각(모르면 비워 둠).
    # 시스템 저장시각은 audit_log.created_at 에 남는다. closed_at 은 내부 종결 처리의 기록시각.
    sent_by: Mapped[str | None] = mapped_column(String(80))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_note: Mapped[str | None] = mapped_column(Text)
    # 발송 기록 시 담당자가 실제로 사용한 연락·접수 방식과 경로(시스템 전송 아님), 외부 참조번호
    contact_method: Mapped[str | None] = mapped_column(String(40))
    contact_route: Mapped[str | None] = mapped_column(Text)
    external_reference: Mapped[str | None] = mapped_column(String(120))
    received_by: Mapped[str | None] = mapped_column(String(80))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_note: Mapped[str | None] = mapped_column(Text)
    replied_by: Mapped[str | None] = mapped_column(String(80))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_content: Mapped[str | None] = mapped_column(Text)
    followup_note: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[str | None] = mapped_column(String(80))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_note: Mapped[str | None] = mapped_column(Text)

    case: Mapped[InspectionCase] = relationship(back_populates="referrals")


class InstitutionRegistry(Base):
    """카탈로그 밖 기관 후보(관리용 데이터 구조). 담당자는 proposed 로만 제안할 수 있다.

    verified 로 바꾸는 승인 기능·화면은 로그인·관리자 권한 도입 이후에 만든다(지금은 없음).
    verified 행만 인계 대상으로 쓰인다. 기능 확인(function)과 실제 접수경로 확인(intake)은 따로 기록한다.
    """

    __tablename__ = "institution_registry"
    __table_args__ = (CheckConstraint(_in("status", INSTITUTION_STATUSES), name="ck_institution_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    institution: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(120))
    function_description: Mapped[str] = mapped_column(Text)
    function_tags: Mapped[list] = mapped_column(JsonType)
    source_url: Mapped[str] = mapped_column(Text)
    basis: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="proposed")
    proposed_by: Mapped[str] = mapped_column(String(80))
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    intake_route_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    intake_route: Mapped[str | None] = mapped_column(Text)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class RequirementCard(Base):
    """공식 문서에서 확인한 일반 요건 카드(자동 적격·승인 판정 아님)."""

    __tablename__ = "requirement_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    function_tag: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str] = mapped_column(String(120))
    program_name: Mapped[str] = mapped_column(String(200))
    eligibility: Mapped[str | None] = mapped_column(Text)
    support_content: Mapped[str | None] = mapped_column(Text)
    official_source_url: Mapped[str] = mapped_column(Text)
    source_document: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[str | None] = mapped_column(String(10))
    valid_to: Mapped[str | None] = mapped_column(String(10))
    verified_at: Mapped[str] = mapped_column(String(10))
    registered_by: Mapped[str] = mapped_column(String(80))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    requirement_id: Mapped[str | None] = mapped_column(String(16), unique=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("document_master.document_id"))
    title: Mapped[str | None] = mapped_column(String(200))
    target: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    application_period: Mapped[str | None] = mapped_column(Text)
    current_intake_status: Mapped[str | None] = mapped_column(String(24))
    application_method: Mapped[str | None] = mapped_column(Text)
    intake_url: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[str | None] = mapped_column(String(10))
    scope_note: Mapped[str | None] = mapped_column(Text)
    caveat: Mapped[str | None] = mapped_column(Text)
    card_status: Mapped[str | None] = mapped_column(String(24))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    auto_eligibility: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    reverification_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_verified_at: Mapped[str | None] = mapped_column(String(10))


class DocumentMaster(Base):
    __tablename__ = "document_master"

    document_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    institution: Mapped[str | None] = mapped_column(String(160))
    source_class: Mapped[str] = mapped_column(String(40))
    function_tag: Mapped[list] = mapped_column(JsonType)
    source_url: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    file_hash: Mapped[str | None] = mapped_column(String(64))
    effective_date: Mapped[str | None] = mapped_column(String(10))
    valid_from: Mapped[str | None] = mapped_column(String(10))
    valid_to: Mapped[str | None] = mapped_column(String(40))
    verified_at: Mapped[str] = mapped_column(String(10))
    evidence_level: Mapped[str] = mapped_column(String(40))
    content_extraction_scope: Mapped[str] = mapped_column(String(32))
    current_intake_status: Mapped[str] = mapped_column(String(24))
    scope_status: Mapped[str] = mapped_column(String(16))
    rag_status: Mapped[str] = mapped_column(String(32))
    requirement_card_status: Mapped[str] = mapped_column(String(24))
    intake_url: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)
    contact_role: Mapped[str | None] = mapped_column(String(40))
    caveat: Mapped[str | None] = mapped_column(Text)
    rag_scope: Mapped[str] = mapped_column(String(32), default="OFFICIAL")
    official: Mapped[bool] = mapped_column(Boolean, default=True)
    reverification_required: Mapped[bool] = mapped_column(Boolean, default=False)


class InstitutionMaster(Base):
    __tablename__ = "institution_master"

    institution_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    institution: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str | None] = mapped_column(String(160))
    function_tag: Mapped[str] = mapped_column(String(40))
    function_verified: Mapped[bool] = mapped_column(Boolean)
    intake_path_verified: Mapped[bool] = mapped_column(Boolean)
    current_intake_status: Mapped[str] = mapped_column(String(24))
    scope_status: Mapped[str] = mapped_column(String(16))
    jurisdiction_status: Mapped[str] = mapped_column(String(24))
    source_status: Mapped[str] = mapped_column(String(32))
    intake_type: Mapped[str | None] = mapped_column(String(40))
    intake_url: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(160))
    contact_role: Mapped[str | None] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[str] = mapped_column(String(10))
    caveat: Mapped[str | None] = mapped_column(Text)


class JurisdictionRule(Base):
    __tablename__ = "jurisdiction_rules"

    district: Mapped[str] = mapped_column(String(20), primary_key=True)
    institution: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(24))


class TeamProposal(Base):
    __tablename__ = "team_proposals"

    proposal_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document_master.document_id"))
    priority: Mapped[int | None] = mapped_column(Integer)
    priority_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    proposal_type: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    support_content: Mapped[str] = mapped_column(Text)
    kpi: Mapped[str | None] = mapped_column(Text)
    caveat: Mapped[str] = mapped_column(Text)
    source_class: Mapped[str] = mapped_column(String(40), default="TEAM_PROPOSAL")
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    rag_scope: Mapped[str] = mapped_column(String(32), default="POLICY_IDEA_ONLY")


class SourceEvidence(Base):
    __tablename__ = "source_evidence"
    __table_args__ = (Index("ix_source_evidence_document", "document_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(80), unique=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document_master.document_id"))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(240))
    heading: Mapped[str | None] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[str] = mapped_column(String(10))
    source_class: Mapped[str] = mapped_column(String(40))
    current_intake_status: Mapped[str] = mapped_column(String(24))
    caveat: Mapped[str | None] = mapped_column(Text)
    file_hash: Mapped[str | None] = mapped_column(String(64))


class RelatedDocument(Base):
    __tablename__ = "related_documents"
    __table_args__ = (UniqueConstraint("from_document_id", "to_document_id", "relation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_document_id: Mapped[str] = mapped_column(ForeignKey("document_master.document_id"))
    to_document_id: Mapped[str] = mapped_column(ForeignKey("document_master.document_id"))
    relation: Mapped[str] = mapped_column(String(80))
    equivalent_program: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_eligibility: Mapped[bool] = mapped_column(Boolean, default=False)
    caveat: Mapped[str] = mapped_column(Text)


class Work24EvidenceSnapshot(Base):
    """모형 입력과 분리된 업종×분기 채용시장 맥락 스냅샷(append-only)."""
    __tablename__ = "work24_evidence_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_id", "industry"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(80))
    quarter: Mapped[str] = mapped_column(String(6))
    collected_at: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(Text)
    data_hash: Mapped[str] = mapped_column(String(64))
    industry: Mapped[str] = mapped_column(String(80))
    posting_count: Mapped[int] = mapped_column(Integer)
    unique_company_count: Mapped[int] = mapped_column(Integer)
    new_posting_count: Mapped[int] = mapped_column(Integer)
    active_posting_count: Mapped[int] = mapped_column(Integer)
    headcount: Mapped[int | None] = mapped_column(Integer)
    district_distribution: Mapped[dict] = mapped_column(JsonType)
    title_distribution: Mapped[dict] = mapped_column(JsonType)
    skill_keyword_distribution: Mapped[dict] = mapped_column(JsonType)
    latest_registration_date: Mapped[str | None] = mapped_column(String(10))
    career_distribution: Mapped[dict | None] = mapped_column(JsonType)
    keyword_method: Mapped[str | None] = mapped_column(Text)
    source_text_fields: Mapped[list | None] = mapped_column(JsonType)
    derivation_version: Mapped[str | None] = mapped_column(String(48))
    model_input_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Work24EvidenceItem(Base):
    """스냅샷에 포함된 공고의 최소 추적 필드. 원자료를 대체하지 않는다."""
    __tablename__ = "work24_evidence_items"
    __table_args__ = (UniqueConstraint("snapshot_id", "posting_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(80))
    posting_id: Mapped[str] = mapped_column(String(80))
    company: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(40))
    industry: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    registered_date: Mapped[str | None] = mapped_column(String(10))
    closing_date: Mapped[str | None] = mapped_column(String(10))
    collected_at: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(Text)


class AuditLog(Base):
    """상태 변경 감사 기록. 추가만 하고 수정·삭제하지 않는다."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_scope_id", "is_example", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    # 신원 경계: 인증 공급자가 준 식별자(현재 로컬 프로토타입은 'local:<이름>')
    actor_id: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(80))
    before: Mapped[dict | None] = mapped_column(JsonType)
    after: Mapped[dict | None] = mapped_column(JsonType)
    snapshot_quarter: Mapped[str | None] = mapped_column(String(6))
    snapshot_version: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class SchemaOutdatedError(RuntimeError):
    """DB 가 현재 코드의 migration head 와 다름."""


class DatabaseScopeError(RuntimeError):
    """운영·시연 DB 경계 설정이 안전하지 않음."""


def database_url_for_runtime(demo: bool, env: dict | None = None) -> str:
    """실행 모드별 DB URL.

    로컬 기본값은 물리적으로 다른 SQLite 파일을 쓴다. 외부 DB URL은 이름을 추측해 변형하지 않으며,
    시연 실행에는 별도의 DSS_DEMO_DATABASE_URL을 요구한다.
    """
    env = os.environ if env is None else env
    normal = (env.get("DSS_DATABASE_URL") or "").strip() or None
    demo_url = (env.get("DSS_DEMO_DATABASE_URL") or "").strip() or None
    normal_effective = normal or DEFAULT_DATABASE_URL
    if demo_url and make_url(demo_url) == make_url(normal_effective):
        raise DatabaseScopeError("DSS_DEMO_DATABASE_URL은 DSS_DATABASE_URL과 다른 DB여야 합니다.")
    if not demo:
        return normal_effective
    if demo_url:
        return demo_url
    if normal:
        raise DatabaseScopeError(
            "DSS_DEMO_MODE=1에서 외부/명시 DB를 사용할 때는 별도의 DSS_DEMO_DATABASE_URL이 필요합니다."
        )
    return DEFAULT_DEMO_DATABASE_URL


def make_engine(url: str | None = None, enforce_sqlite_foreign_keys: bool = True):
    url = url or os.environ.get("DSS_DATABASE_URL") or DEFAULT_DATABASE_URL
    if url.startswith("sqlite:///") and not url.endswith(":memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("sqlite"):
        # Python 3.12+ no longer supplies sqlite3's implicit datetime adapter.
        sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite" and enforce_sqlite_foreign_keys:
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(url: str | None = None, migrate: bool = True):
    """DB 를 Alembic migration head 로 맞춘 뒤 세션 팩토리를 만든다.

    migrate=False 이면 올리지 않고, head 가 아니면 SchemaOutdatedError 를 낸다(운영 DB 수동 migration 용).
    """
    from workflow import migrate as MG

    # SQLite의 Alembic batch migration은 테이블을 재생성하므로 migration 연결에서는 FK 검사를 잠시 끈다.
    # 실제 업무 세션을 여는 최종 엔진은 항상 FK 검사를 켠다.
    engine = make_engine(url, enforce_sqlite_foreign_keys=not migrate)
    if migrate:
        MG.upgrade(engine)
        if engine.dialect.name == "sqlite":
            if engine.url.database == ":memory:":
                with engine.connect() as connection:
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            else:
                resolved_url = str(engine.url)
                engine.dispose()
                engine = make_engine(resolved_url, enforce_sqlite_foreign_keys=True)
    current, head = MG.current_revision(engine), MG.head_revision()
    if current != head:
        raise SchemaOutdatedError(f"DB schema revision {current} ≠ 코드 head {head}. migration 이 필요합니다.")
    Session = sessionmaker(engine, expire_on_commit=False, future=True)
    from policy.bootstrap import seed_policy_master
    seed_policy_master(Session)
    return Session
