"""Create initial ghs_datasets, ghs_assets, and ghs_harmonization_jobs tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_ghs_tables"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ghs_datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("product", sa.String(length=128), nullable=False),
        sa.Column("payload_json", _JSON_VARIANT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_datasets"),
    )
    op.create_index("ix_ghs_datasets_provider", "ghs_datasets", ["provider"], unique=False)
    op.create_index("ix_ghs_datasets_product", "ghs_datasets", ["product"], unique=False)
    op.create_index("ix_ghs_datasets_created_at", "ghs_datasets", ["created_at"], unique=False)

    op.create_table(
        "ghs_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=512), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("data_format", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["ghs_datasets.id"],
            name="fk_ghs_assets_dataset_id_ghs_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_assets"),
    )
    op.create_index("ix_ghs_assets_dataset_id", "ghs_assets", ["dataset_id"], unique=False)

    op.create_table(
        "ghs_harmonization_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("product", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("plan_json", _JSON_VARIANT, nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dataset_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_harmonization_jobs"),
    )
    op.create_index(
        "ix_ghs_harmonization_jobs_provider", "ghs_harmonization_jobs", ["provider"], unique=False
    )
    op.create_index(
        "ix_ghs_harmonization_jobs_product", "ghs_harmonization_jobs", ["product"], unique=False
    )
    op.create_index(
        "ix_ghs_jobs_status_created_at",
        "ghs_harmonization_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_jobs_status_lease_expires_at",
        "ghs_harmonization_jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ghs_jobs_status_lease_expires_at", table_name="ghs_harmonization_jobs")
    op.drop_index("ix_ghs_jobs_status_created_at", table_name="ghs_harmonization_jobs")
    op.drop_index("ix_ghs_harmonization_jobs_product", table_name="ghs_harmonization_jobs")
    op.drop_index("ix_ghs_harmonization_jobs_provider", table_name="ghs_harmonization_jobs")
    op.drop_table("ghs_harmonization_jobs")
    op.drop_index("ix_ghs_assets_dataset_id", table_name="ghs_assets")
    op.drop_table("ghs_assets")
    op.drop_index("ix_ghs_datasets_created_at", table_name="ghs_datasets")
    op.drop_index("ix_ghs_datasets_product", table_name="ghs_datasets")
    op.drop_index("ix_ghs_datasets_provider", table_name="ghs_datasets")
    op.drop_table("ghs_datasets")
