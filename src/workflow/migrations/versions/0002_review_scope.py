"""Phase 4.5 운영 정합성: 점검 시점(review scope)·현장확인 결과 이력·메모·기관 후보·접수경로·모니터링 상태

Revision ID: 0002_review_scope
Revises: 0001_baseline
Create Date: 2026-09-21

데이터 이전 규칙(기존 기록을 지우지 않음):
- 모든 점검 건에 '최초 점검' 시점을 만든다(대상 분기 = 개설 분기, 분석본 = 개설 분석본).
- 기존 체크리스트 문항은 최초 점검 시점에 묶고, 문항 행에 있던 결과는 check_results 로 옮긴다
  (실제 확인 시각은 기록된 적이 없으므로 performed_at = NULL).
- 결정·지원 필요 기능은 기록 시각 기준으로 그때 진행 중이던 시점에 묶는다. 재점검 결정(decision_id)은 그 재점검에 묶는다.
- 인계 기록은 자신이 속한 결정의 시점에 묶는다.
- 분석본 성격: 분석 실행 분기 = 대상 분기이면 contemporaneous, 아니면 reconstructed.
- '모니터링 전환'이 현재 결정인 진행 중 점검 건은 상태를 '모니터링'으로 맞춘다. 그 밖의 상태는 바꾸지 않는다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_review_scope"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _nature(snapshot_quarter, quarter):
    return "contemporaneous" if snapshot_quarter == quarter else "reconstructed"


def upgrade() -> None:
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"

    # ---------------------------------------------------------------- 1. 새 테이블
    op.create_table(
        "case_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("inspection_cases.id"), nullable=False),
        sa.Column("quarterly_review_id", sa.Integer(), sa.ForeignKey("quarterly_reviews.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "institution_registry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("institution", sa.String(120), nullable=False),
        sa.Column("unit", sa.String(120), nullable=True),
        sa.Column("function_description", sa.Text(), nullable=False),
        sa.Column("function_tags", JSON, nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("proposed_by", sa.String(80), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(80), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("intake_route_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("intake_route", sa.Text(), nullable=True),
        sa.Column("is_example", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'verified', 'rejected')", name="ck_institution_status"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ---------------------------------------------------------------- 2. 컬럼 추가(우선 NULL 허용) · 제약 교체
    with op.batch_alter_table("candidate_reviews") as b:
        b.add_column(sa.Column("is_example", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("audit_log") as b:
        b.add_column(sa.Column("actor_id", sa.String(160), nullable=True))
    with op.batch_alter_table("inspection_cases") as b:
        b.add_column(sa.Column("snapshot_nature", sa.String(16), nullable=True))
        b.drop_constraint("ck_case_status", type_="check")
        b.create_check_constraint("ck_case_status", "status IN ('진행 중', '모니터링', '종결')")
    with op.batch_alter_table("quarterly_reviews") as b:
        b.add_column(sa.Column("review_kind", sa.String(10), nullable=True))
        b.add_column(sa.Column("snapshot_nature", sa.String(16), nullable=True))
        for col, typ in (("previous_quarter", sa.String(6)), ("previous_snapshot_quarter", sa.String(6)),
                         ("previous_snapshot_version", sa.String(8)), ("previous_stage", sa.String(10))):
            b.alter_column(col, existing_type=typ, nullable=True)
        b.drop_constraint("ck_review_status", type_="check")
        b.create_check_constraint("ck_review_status", "review_status IN ('진행 중', '완료', '검토 중')")
    for table in ("case_check_items", "case_decisions", "case_support_needs", "referrals"):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("quarterly_review_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("referrals") as b:
        b.add_column(sa.Column("institution_source", sa.String(40), nullable=True))
        b.add_column(sa.Column("contact_method", sa.String(40), nullable=True))
        b.add_column(sa.Column("contact_route", sa.Text(), nullable=True))
        b.add_column(sa.Column("external_reference", sa.String(120), nullable=True))

    op.create_table(
        "check_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("inspection_cases.id"), nullable=False),
        sa.Column("quarterly_review_id", sa.Integer(), sa.ForeignKey("quarterly_reviews.id"), nullable=False),
        sa.Column("check_item_id", sa.Integer(), sa.ForeignKey("case_check_items.id"), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("result_code", sa.String(10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", sa.String(80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("method IN ('방문', '전화', '문서')", name="ck_result_method"),
        sa.CheckConstraint("result_code IN ('확인', '부분 확인', '미확인', '반대증거')", name="ck_result_code"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ---------------------------------------------------------------- 3. 데이터 이전
    t = sa.text
    cases = bind.execute(t("SELECT id, quarter, snapshot_quarter, snapshot_version, snapshot_data_hash, "
                           "triage_stage_at_open, opened_by, opened_at, status, decision, closed_at, is_example "
                           "FROM inspection_cases ORDER BY id")).mappings().all()
    for c in cases:
        bind.execute(t("UPDATE inspection_cases SET snapshot_nature = :n WHERE id = :id"),
                     {"n": _nature(c["snapshot_quarter"], c["quarter"]), "id": c["id"]})
        if c["status"] == "진행 중" and c["decision"] == "모니터링 전환":
            bind.execute(t("UPDATE inspection_cases SET status = '모니터링' WHERE id = :id"), {"id": c["id"]})
        bind.execute(t("UPDATE candidate_reviews SET is_example = :e WHERE id IN "
                       "(SELECT candidate_review_id FROM inspection_cases WHERE id = :id)"),
                     {"e": bool(c["is_example"]), "id": c["id"]})
        bind.execute(t(
            "INSERT INTO quarterly_reviews (case_id, review_kind, quarter, snapshot_quarter, snapshot_version, "
            "snapshot_data_hash, snapshot_nature, current_stage, review_status, reviewer, started_at) "
            "VALUES (:case_id, '최초 점검', :q, :sq, :sv, :sh, :n, :stage, '진행 중', :by, :at)"),
            {"case_id": c["id"], "q": c["quarter"], "sq": c["snapshot_quarter"], "sv": c["snapshot_version"],
             "sh": c["snapshot_data_hash"], "n": _nature(c["snapshot_quarter"], c["quarter"]),
             "stage": c["triage_stage_at_open"], "by": c["opened_by"], "at": c["opened_at"]})

        scopes = bind.execute(t("SELECT id, quarter, snapshot_quarter, started_at, review_kind, decision_id "
                                "FROM quarterly_reviews WHERE case_id = :id ORDER BY quarter"),
                              {"id": c["id"]}).mappings().all()
        initial = next(s for s in scopes if s["review_kind"] == "최초 점검")
        for i, s in enumerate(scopes):
            nxt = scopes[i + 1] if i + 1 < len(scopes) else None
            done = nxt is not None or c["status"] == "종결"
            bind.execute(t("UPDATE quarterly_reviews SET review_kind = COALESCE(review_kind, '재점검'), "
                           "snapshot_nature = :n, review_status = :st, reviewed_at = :ra WHERE id = :id"),
                         {"n": _nature(s["snapshot_quarter"], s["quarter"]), "st": "완료" if done else "진행 중",
                          "ra": (nxt["started_at"] if nxt else c["closed_at"]) if done else None, "id": s["id"]})

        def scope_at(ts):
            """ts 시각에 진행 중이던 시점(시작 시각이 ts 이하인 가장 늦은 시점)."""
            chosen = initial["id"]
            for s in scopes:
                if s["started_at"] is not None and ts is not None and str(s["started_at"]) <= str(ts):
                    chosen = s["id"]
            return chosen

        bind.execute(t("UPDATE case_check_items SET quarterly_review_id = :s WHERE case_id = :id"),
                     {"s": initial["id"], "id": c["id"]})
        bind.execute(t(
            "INSERT INTO check_results (case_id, quarterly_review_id, check_item_id, method, result_code, note, "
            "performed_at, recorded_by, recorded_at) SELECT case_id, quarterly_review_id, id, method, result, memo, "
            "NULL, recorded_by, recorded_at FROM case_check_items WHERE case_id = :id AND result IS NOT NULL"),
            {"id": c["id"]})
        by_review = {s["decision_id"]: s["id"] for s in scopes if s["decision_id"] is not None}
        for d in bind.execute(t("SELECT id, decided_at FROM case_decisions WHERE case_id = :id"),
                              {"id": c["id"]}).mappings().all():
            bind.execute(t("UPDATE case_decisions SET quarterly_review_id = :s WHERE id = :d"),
                         {"s": by_review.get(d["id"], scope_at(d["decided_at"])), "d": d["id"]})
        for n in bind.execute(t("SELECT id, recorded_at FROM case_support_needs WHERE case_id = :id"),
                              {"id": c["id"]}).mappings().all():
            bind.execute(t("UPDATE case_support_needs SET quarterly_review_id = :s WHERE id = :n"),
                         {"s": scope_at(n["recorded_at"]), "n": n["id"]})
    bind.execute(t("UPDATE referrals SET quarterly_review_id = (SELECT quarterly_review_id FROM case_decisions "
                   "WHERE case_decisions.id = referrals.decision_id), institution_source = 'catalog'"))
    bind.execute(t("UPDATE quarterly_reviews SET review_status = '진행 중' WHERE review_status = '검토 중'"))

    # ---------------------------------------------------------------- 4. 옛 컬럼 제거 · NOT NULL · FK · 제약
    with op.batch_alter_table("inspection_cases") as b:
        b.alter_column("snapshot_nature", existing_type=sa.String(16), nullable=False)
        b.create_check_constraint("ck_case_snapshot_nature", "snapshot_nature IN ('contemporaneous', 'reconstructed')")
    if pg:
        op.drop_constraint("quarterly_reviews_decision_id_fkey", "quarterly_reviews", type_="foreignkey")
    with op.batch_alter_table("quarterly_reviews") as b:
        b.drop_column("decision_id")
        b.drop_column("review_note")
        b.alter_column("review_kind", existing_type=sa.String(10), nullable=False)
        b.alter_column("snapshot_nature", existing_type=sa.String(16), nullable=False)
        b.drop_constraint("ck_review_status", type_="check")
        b.create_check_constraint("ck_review_status", "review_status IN ('진행 중', '완료')")
        b.create_check_constraint("ck_review_kind", "review_kind IN ('최초 점검', '재점검')")
        b.create_check_constraint("ck_review_snapshot_nature",
                                  "snapshot_nature IN ('contemporaneous', 'reconstructed')")
    with op.batch_alter_table("case_check_items") as b:
        b.drop_constraint("ck_check_method", type_="check")
        b.drop_constraint("ck_check_result", type_="check")
        for col in ("method", "result", "memo", "recorded_by", "recorded_at"):
            b.drop_column(col)
    for table in ("case_check_items", "case_decisions", "case_support_needs", "referrals"):
        with op.batch_alter_table(table) as b:
            b.alter_column("quarterly_review_id", existing_type=sa.Integer(), nullable=False)
            b.create_foreign_key(f"fk_{table}_quarterly_review", "quarterly_reviews",
                                 ["quarterly_review_id"], ["id"])
    with op.batch_alter_table("referrals") as b:
        b.create_check_constraint(
            "ck_referral_contact_method",
            "contact_method IS NULL OR contact_method IN ('공문', '전자우편', '전화', '방문', "
            "'기관 온라인 창구(담당자 직접 입력)', '기타')")


def downgrade() -> None:
    raise NotImplementedError("0002 는 데이터 구조를 옮기므로 되돌리기(downgrade)를 지원하지 않습니다. 백업에서 복원하세요.")
