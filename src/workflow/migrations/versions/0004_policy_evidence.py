"""정책 원장, 관할 규칙, 근거 청크와 요건 카드 확장.

Revision ID: 0004_policy_evidence
Revises: 0003_runtime_scope
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_policy_evidence"
down_revision = "0003_runtime_scope"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "document_master",
        sa.Column("document_id", sa.String(16), primary_key=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("institution", sa.String(160)),
        sa.Column("source_class", sa.String(40), nullable=False),
        sa.Column("function_tag", JSON_TYPE, nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.Text()),
        sa.Column("local_path", sa.Text()),
        sa.Column("file_hash", sa.String(64)),
        sa.Column("effective_date", sa.String(10)),
        sa.Column("valid_from", sa.String(10)),
        sa.Column("valid_to", sa.String(40)),
        sa.Column("verified_at", sa.String(10), nullable=False),
        sa.Column("evidence_level", sa.String(40), nullable=False),
        sa.Column("content_extraction_scope", sa.String(32), nullable=False),
        sa.Column("current_intake_status", sa.String(24), nullable=False),
        sa.Column("scope_status", sa.String(16), nullable=False),
        sa.Column("rag_status", sa.String(32), nullable=False),
        sa.Column("requirement_card_status", sa.String(24), nullable=False),
        sa.Column("intake_url", sa.Text()),
        sa.Column("contact", sa.Text()),
        sa.Column("contact_role", sa.String(40)),
        sa.Column("caveat", sa.Text()),
        sa.Column("rag_scope", sa.String(32), nullable=False, server_default="OFFICIAL"),
        sa.Column("official", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reverification_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "institution_master",
        sa.Column("institution_id", sa.String(32), primary_key=True),
        sa.Column("institution", sa.String(160), nullable=False),
        sa.Column("unit", sa.String(160)),
        sa.Column("function_tag", sa.String(40), nullable=False),
        sa.Column("function_verified", sa.Boolean(), nullable=False),
        sa.Column("intake_path_verified", sa.Boolean(), nullable=False),
        sa.Column("current_intake_status", sa.String(24), nullable=False),
        sa.Column("scope_status", sa.String(16), nullable=False),
        sa.Column("jurisdiction_status", sa.String(24), nullable=False),
        sa.Column("source_status", sa.String(32), nullable=False),
        sa.Column("intake_type", sa.String(40)),
        sa.Column("intake_url", sa.Text()),
        sa.Column("phone", sa.String(80)),
        sa.Column("email", sa.String(160)),
        sa.Column("contact_role", sa.String(80)),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.String(10), nullable=False),
        sa.Column("caveat", sa.Text()),
    )
    op.create_table(
        "jurisdiction_rules",
        sa.Column("district", sa.String(20), primary_key=True),
        sa.Column("institution", sa.String(120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.String(10), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
    )
    op.create_table(
        "team_proposals",
        sa.Column("proposal_id", sa.String(16), primary_key=True),
        sa.Column("document_id", sa.String(16), sa.ForeignKey("document_master.document_id"), nullable=False),
        sa.Column("priority", sa.Integer()),
        sa.Column("priority_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("proposal_type", sa.String(80), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("support_content", sa.Text(), nullable=False),
        sa.Column("kpi", sa.Text()),
        sa.Column("caveat", sa.Text(), nullable=False),
        sa.Column("source_class", sa.String(40), nullable=False, server_default="TEAM_PROPOSAL"),
        sa.Column("official", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rag_scope", sa.String(32), nullable=False, server_default="POLICY_IDEA_ONLY"),
    )
    op.create_table(
        "source_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chunk_id", sa.String(80), nullable=False, unique=True),
        sa.Column("document_id", sa.String(16), sa.ForeignKey("document_master.document_id"), nullable=False),
        sa.Column("page_start", sa.Integer()),
        sa.Column("page_end", sa.Integer()),
        sa.Column("section", sa.String(240)),
        sa.Column("heading", sa.String(240)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.String(10), nullable=False),
        sa.Column("source_class", sa.String(40), nullable=False),
        sa.Column("current_intake_status", sa.String(24), nullable=False),
        sa.Column("caveat", sa.Text()),
        sa.Column("file_hash", sa.String(64)),
    )
    op.create_index("ix_source_evidence_document", "source_evidence", ["document_id"])
    op.create_table(
        "related_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_document_id", sa.String(16), sa.ForeignKey("document_master.document_id"), nullable=False),
        sa.Column("to_document_id", sa.String(16), sa.ForeignKey("document_master.document_id"), nullable=False),
        sa.Column("relation", sa.String(80), nullable=False),
        sa.Column("equivalent_program", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_eligibility", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("caveat", sa.Text(), nullable=False),
        sa.UniqueConstraint("from_document_id", "to_document_id", "relation"),
    )
    op.create_table(
        "work24_evidence_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(80), nullable=False),
        sa.Column("quarter", sa.String(6), nullable=False),
        sa.Column("collected_at", sa.String(40), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("industry", sa.String(80), nullable=False),
        sa.Column("posting_count", sa.Integer(), nullable=False),
        sa.Column("unique_company_count", sa.Integer(), nullable=False),
        sa.Column("new_posting_count", sa.Integer(), nullable=False),
        sa.Column("active_posting_count", sa.Integer(), nullable=False),
        sa.Column("headcount", sa.Integer()),
        sa.Column("district_distribution", JSON_TYPE, nullable=False),
        sa.Column("title_distribution", JSON_TYPE, nullable=False),
        sa.Column("skill_keyword_distribution", JSON_TYPE, nullable=False),
        sa.Column("model_input_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "industry"),
    )
    op.create_table(
        "work24_evidence_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(80), nullable=False),
        sa.Column("posting_id", sa.String(80), nullable=False),
        sa.Column("company", sa.Text()),
        sa.Column("district", sa.String(40)),
        sa.Column("industry", sa.String(80)),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("registered_date", sa.String(10)),
        sa.Column("closing_date", sa.String(10)),
        sa.Column("collected_at", sa.String(40), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "posting_id"),
    )
    with op.batch_alter_table("requirement_cards") as batch:
        batch.add_column(sa.Column("requirement_id", sa.String(16)))
        batch.add_column(sa.Column("document_id", sa.String(16)))
        batch.add_column(sa.Column("title", sa.String(200)))
        batch.add_column(sa.Column("target", sa.Text()))
        batch.add_column(sa.Column("requirements", sa.Text()))
        batch.add_column(sa.Column("application_period", sa.Text()))
        batch.add_column(sa.Column("current_intake_status", sa.String(24)))
        batch.add_column(sa.Column("application_method", sa.Text()))
        batch.add_column(sa.Column("intake_url", sa.Text()))
        batch.add_column(sa.Column("contact", sa.Text()))
        batch.add_column(sa.Column("effective_date", sa.String(10)))
        batch.add_column(sa.Column("scope_note", sa.Text()))
        batch.add_column(sa.Column("caveat", sa.Text()))
        batch.add_column(sa.Column("card_status", sa.String(24)))
        batch.add_column(sa.Column("evidence_url", sa.Text()))
        batch.add_column(sa.Column("auto_eligibility", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("reverification_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("last_verified_at", sa.String(10)))
        batch.create_unique_constraint("uq_requirement_cards_requirement_id", ["requirement_id"])
        batch.create_foreign_key("fk_requirement_cards_document", "document_master", ["document_id"], ["document_id"])


def downgrade() -> None:
    with op.batch_alter_table("requirement_cards") as batch:
        batch.drop_constraint("fk_requirement_cards_document", type_="foreignkey")
        batch.drop_constraint("uq_requirement_cards_requirement_id", type_="unique")
        for name in ("last_verified_at", "reverification_required", "auto_eligibility", "evidence_url",
                     "card_status", "caveat", "scope_note", "effective_date", "contact", "intake_url",
                     "application_method", "current_intake_status", "application_period", "requirements",
                     "target", "title", "document_id", "requirement_id"):
            batch.drop_column(name)
    op.drop_table("work24_evidence_items")
    op.drop_table("work24_evidence_snapshots")
    op.drop_table("related_documents")
    op.drop_index("ix_source_evidence_document", table_name="source_evidence")
    op.drop_table("source_evidence")
    op.drop_table("team_proposals")
    op.drop_table("jurisdiction_rules")
    op.drop_table("institution_master")
    op.drop_table("document_master")
