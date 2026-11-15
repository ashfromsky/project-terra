"""Add retry, progress, and idempotency columns to ghs_harmonization_jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_job_retry_and_idempotency"
down_revision: str | Sequence[str] | None = "0002_storage_ledger_and_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ghs_harmonization_jobs",
        sa.Column("error_category", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ghs_harmonization_jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ghs_harmonization_jobs",
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "ghs_harmonization_jobs",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_ghs_jobs_status_next_retry_at",
        "ghs_harmonization_jobs",
        ["status", "next_retry_at"],
    )
    op.create_index(
        "ix_ghs_jobs_idempotency_key",
        "ghs_harmonization_jobs",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_ghs_jobs_idempotency_key", table_name="ghs_harmonization_jobs")
    op.drop_index("ix_ghs_jobs_status_next_retry_at", table_name="ghs_harmonization_jobs")
    op.drop_column("ghs_harmonization_jobs", "idempotency_key")
    op.drop_column("ghs_harmonization_jobs", "progress_pct")
    op.drop_column("ghs_harmonization_jobs", "next_retry_at")
    op.drop_column("ghs_harmonization_jobs", "error_category")
