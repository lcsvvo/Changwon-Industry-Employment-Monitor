"""실행 범위 감사 추적과 동시성 제약

Revision ID: 0003_runtime_scope
Revises: 0002_review_scope
Create Date: 2026-09-21

- audit_log에 운영/시연 범위를 명시해 일반 조회가 현재 실행 범위만 보게 한다.
- 기존 audit 행은 연결된 업무 레코드의 is_example 값으로 보존·분류한다.
- 서비스의 선조회만으로 막던 중복 열린 점검 건·진행 중 인계를 DB 부분 unique index로도 막는다.
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "0003_runtime_scope"
down_revision = "0002_review_scope"
branch_labels = None
depends_on = None


DIRECT_SCOPE = {
    "candidate_review": "candidate_reviews",
    "inspection_case": "inspection_cases",
    "institution_registry": "institution_registry",
}
CHILD_SCOPE = {
    "case_check_item": "case_check_items",
    "check_result": "check_results",
    "case_note": "case_notes",
    "case_support_need": "case_support_needs",
    "referral": "referrals",
    "quarterly_review": "quarterly_reviews",
}


def _payload(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _existing_scope(bind, row) -> bool:
    """기존 audit 행을 원본 업무행에 연결한다. 연결 실패 시 payload, 마지막으로 운영(False)으로 둔다."""
    try:
        target_id = int(row["target_id"])
    except (TypeError, ValueError):
        target_id = None
    value = None
    if target_id is not None and row["target_type"] in DIRECT_SCOPE:
        table = DIRECT_SCOPE[row["target_type"]]
        value = bind.execute(sa.text(f"SELECT is_example FROM {table} WHERE id=:id"),
                             {"id": target_id}).scalar()
    elif target_id is not None and row["target_type"] in CHILD_SCOPE:
        table = CHILD_SCOPE[row["target_type"]]
        value = bind.execute(sa.text(
            f"SELECT c.is_example FROM {table} t JOIN inspection_cases c ON c.id=t.case_id WHERE t.id=:id"
        ), {"id": target_id}).scalar()
    if value is None:
        body = _payload(row["after_value"]) or _payload(row["before_value"])
        value = body.get("is_example")
        if value is None and body.get("case_id") is not None:
            value = bind.execute(sa.text("SELECT is_example FROM inspection_cases WHERE id=:id"),
                                 {"id": body["case_id"]}).scalar()
    return bool(value)


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("audit_log") as batch:
        batch.add_column(sa.Column("is_example", sa.Boolean(), server_default=sa.false(), nullable=False))

    rows = bind.execute(sa.text(
        'SELECT id, target_type, target_id, "before" AS before_value, "after" AS after_value FROM audit_log'
    )).mappings().all()
    for row in rows:
        if _existing_scope(bind, row):
            bind.execute(sa.text("UPDATE audit_log SET is_example=:v WHERE id=:id"),
                         {"v": True, "id": row["id"]})

    op.create_index("ix_audit_log_scope_id", "audit_log", ["is_example", "id"])
    open_where = sa.text("status IN ('진행 중', '모니터링')")
    op.create_index("uq_open_case_scope", "inspection_cases", ["industry", "quarter", "is_example"],
                    unique=True, sqlite_where=open_where, postgresql_where=open_where)
    referral_where = sa.text("status <> '종결'")
    op.create_index("uq_active_referral", "referrals", ["case_id", "function_tag", "institution"],
                    unique=True, sqlite_where=referral_where, postgresql_where=referral_where)


def downgrade() -> None:
    op.drop_index("uq_active_referral", table_name="referrals")
    op.drop_index("uq_open_case_scope", table_name="inspection_cases")
    op.drop_index("ix_audit_log_scope_id", table_name="audit_log")
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("is_example")
