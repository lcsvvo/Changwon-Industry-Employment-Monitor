"""Phase 0~4 baseline (Alembic 도입 전 create_all 구조)

Revision ID: 0001_baseline
Revises: 
Create Date: 2026-09-21

Alembic 도입 전 create_all 로 만들던 Phase 0~4 ORM 구조를 그대로 옮긴 기준점. 이후 변경은 새 revision 으로만 한다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor', sa.String(length=80), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=False),
    sa.Column('target_id', sa.String(length=80), nullable=False),
    sa.Column('before', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('after', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('snapshot_quarter', sa.String(length=6), nullable=True),
    sa.Column('snapshot_version', sa.String(length=8), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('candidate_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_quarter', sa.String(length=6), nullable=False),
    sa.Column('snapshot_version', sa.String(length=8), nullable=False),
    sa.Column('industry', sa.String(length=40), nullable=False),
    sa.Column('quarter', sa.String(length=6), nullable=False),
    sa.Column('candidate_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reviewer', sa.String(length=80), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('검토 중', '점검 건 개설', '점검 불필요')", name='ck_candidate_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('snapshot_quarter', 'snapshot_version', 'industry', 'quarter')
    )
    op.create_table('requirement_cards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('function_tag', sa.String(length=40), nullable=False),
    sa.Column('institution', sa.String(length=120), nullable=False),
    sa.Column('program_name', sa.String(length=200), nullable=False),
    sa.Column('eligibility', sa.Text(), nullable=True),
    sa.Column('support_content', sa.Text(), nullable=True),
    sa.Column('official_source_url', sa.Text(), nullable=False),
    sa.Column('source_document', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.String(length=10), nullable=True),
    sa.Column('valid_to', sa.String(length=10), nullable=True),
    sa.Column('verified_at', sa.String(length=10), nullable=False),
    sa.Column('registered_by', sa.String(length=80), nullable=False),
    sa.Column('registered_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('inspection_cases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('industry', sa.String(length=40), nullable=False),
    sa.Column('quarter', sa.String(length=6), nullable=False),
    sa.Column('snapshot_quarter', sa.String(length=6), nullable=False),
    sa.Column('snapshot_version', sa.String(length=8), nullable=False),
    sa.Column('snapshot_data_hash', sa.String(length=64), nullable=False),
    sa.Column('triage_stage_at_open', sa.String(length=10), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=False),
    sa.Column('candidate_review_id', sa.Integer(), nullable=True),
    sa.Column('opening_reason', sa.Text(), nullable=False),
    sa.Column('assignee', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=True),
    sa.Column('next_review_quarter', sa.String(length=6), nullable=True),
    sa.Column('opened_by', sa.String(length=80), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closed_by', sa.String(length=80), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closing_note', sa.Text(), nullable=True),
    sa.Column('is_example', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.CheckConstraint("decision IS NULL OR decision IN ('계속 점검', '추가확인', '모니터링 전환', '인계', '종결')", name='ck_case_decision'),
    sa.CheckConstraint("origin IN ('우선점검 후보', '검토 후보', '수동 개설(관찰)')", name='ck_case_origin'),
    sa.CheckConstraint("status IN ('진행 중', '종결')", name='ck_case_status'),
    sa.ForeignKeyConstraint(['candidate_review_id'], ['candidate_reviews.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('case_check_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('question_source', sa.String(length=40), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=True),
    sa.Column('result', sa.String(length=10), nullable=True),
    sa.Column('memo', sa.Text(), nullable=True),
    sa.Column('recorded_by', sa.String(length=80), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("method IS NULL OR method IN ('방문', '전화', '문서')", name='ck_check_method'),
    sa.CheckConstraint("question_source IN ('check_question', 'check_questions_context')", name='ck_check_source'),
    sa.CheckConstraint("result IS NULL OR result IN ('확인', '부분 확인', '미확인', '반대증거')", name='ck_check_result'),
    sa.ForeignKeyConstraint(['case_id'], ['inspection_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('case_decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('next_review_quarter', sa.String(length=6), nullable=True),
    sa.Column('decided_by', sa.String(length=80), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('계속 점검', '추가확인', '모니터링 전환', '인계', '종결')", name='ck_decision_value'),
    sa.ForeignKeyConstraint(['case_id'], ['inspection_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('case_support_needs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('function_tags', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('field_checked', sa.Boolean(), nullable=False),
    sa.Column('catalog_version', sa.String(length=40), nullable=False),
    sa.Column('recorded_by', sa.String(length=80), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['inspection_cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('quarterly_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('quarter', sa.String(length=6), nullable=False),
    sa.Column('snapshot_quarter', sa.String(length=6), nullable=False),
    sa.Column('snapshot_version', sa.String(length=8), nullable=False),
    sa.Column('snapshot_data_hash', sa.String(length=64), nullable=False),
    sa.Column('previous_quarter', sa.String(length=6), nullable=False),
    sa.Column('previous_snapshot_quarter', sa.String(length=6), nullable=False),
    sa.Column('previous_snapshot_version', sa.String(length=8), nullable=False),
    sa.Column('previous_stage', sa.String(length=10), nullable=False),
    sa.Column('current_stage', sa.String(length=10), nullable=False),
    sa.Column('review_status', sa.String(length=10), nullable=False),
    sa.Column('reviewer', sa.String(length=80), nullable=False),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('decision_id', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("review_status IN ('검토 중', '완료')", name='ck_review_status'),
    sa.ForeignKeyConstraint(['case_id'], ['inspection_cases.id'], ),
    sa.ForeignKeyConstraint(['decision_id'], ['case_decisions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'quarter')
    )
    op.create_table('referrals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('case_id', sa.Integer(), nullable=False),
    sa.Column('decision_id', sa.Integer(), nullable=False),
    sa.Column('function_tag', sa.String(length=40), nullable=False),
    sa.Column('institution', sa.String(length=120), nullable=False),
    sa.Column('institution_unit', sa.String(length=120), nullable=True),
    sa.Column('institution_source_url', sa.Text(), nullable=True),
    sa.Column('mapping_verified_at', sa.String(length=10), nullable=True),
    sa.Column('catalog_version', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_by', sa.String(length=80), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_note', sa.Text(), nullable=True),
    sa.Column('received_by', sa.String(length=80), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_note', sa.Text(), nullable=True),
    sa.Column('replied_by', sa.String(length=80), nullable=True),
    sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reply_content', sa.Text(), nullable=True),
    sa.Column('followup_note', sa.Text(), nullable=True),
    sa.Column('closed_by', sa.String(length=80), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closing_note', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('작성', '발송 기록', '접수 확인', '처리·회신 기록', '추가확인 필요', '종결')", name='ck_referral_status'),
    sa.ForeignKeyConstraint(['case_id'], ['inspection_cases.id'], ),
    sa.ForeignKeyConstraint(['decision_id'], ['case_decisions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('referrals')
    op.drop_table('quarterly_reviews')
    op.drop_table('case_support_needs')
    op.drop_table('case_decisions')
    op.drop_table('case_check_items')
    op.drop_table('inspection_cases')
    op.drop_table('requirement_cards')
    op.drop_table('candidate_reviews')
    op.drop_table('audit_log')
