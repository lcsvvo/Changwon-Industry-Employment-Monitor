"""Work24 파생 근거와 backend service 계약 메타데이터.

Revision ID: 0005_backend_services
Revises: 0004_policy_evidence
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_backend_services"
down_revision = "0004_policy_evidence"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("work24_evidence_snapshots") as batch:
        batch.add_column(sa.Column("latest_registration_date", sa.String(10)))
        batch.add_column(sa.Column("career_distribution", JSON_TYPE))
        batch.add_column(sa.Column("keyword_method", sa.Text()))
        batch.add_column(sa.Column("source_text_fields", JSON_TYPE))
        batch.add_column(sa.Column("derivation_version", sa.String(48)))


def downgrade() -> None:
    with op.batch_alter_table("work24_evidence_snapshots") as batch:
        for name in ("derivation_version", "source_text_fields", "keyword_method",
                     "career_distribution", "latest_registration_date"):
            batch.drop_column(name)
