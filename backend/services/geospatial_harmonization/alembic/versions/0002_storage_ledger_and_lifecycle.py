"""Create storage ledger, objects, asset refs, reservations, and audit tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_storage_ledger_and_lifecycle"
down_revision: str | Sequence[str] | None = "0001_initial_ghs_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ghs_storage_ledger_state",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("total_stored_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("raw_bytes", sa.BigInteger(), nullable=False),
        sa.Column("intermediate_bytes", sa.BigInteger(), nullable=False),
        sa.Column("derived_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("compression_savings_bytes", sa.BigInteger(), nullable=False),
        sa.Column("deduplication_savings_bytes", sa.BigInteger(), nullable=False),
        sa.Column("cleanup_deleted_objects", sa.Integer(), nullable=False),
        sa.Column("cleanup_reclaimed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("failed_uploads_count", sa.Integer(), nullable=False),
        sa.Column("orphaned_objects_count", sa.Integer(), nullable=False),
        sa.Column("missing_referenced_objects_count", sa.Integer(), nullable=False),
        sa.Column("last_reconciliation_diff_bytes", sa.BigInteger(), nullable=True),
        sa.Column("last_reconciliation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_storage_ledger_state"),
    )

    op.create_table(
        "ghs_storage_objects",
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("zone", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("original_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("data_format", sa.String(length=32), nullable=False),
        sa.Column("compression_codec", sa.String(length=32), nullable=True),
        sa.Column("ref_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("marked_orphan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("object_key", name="pk_ghs_storage_objects"),
    )
    op.create_index("ix_ghs_storage_objects_zone", "ghs_storage_objects", ["zone"], unique=False)
    op.create_index(
        "ix_ghs_storage_objects_content_sha256",
        "ghs_storage_objects",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_objects_status", "ghs_storage_objects", ["status"], unique=False
    )
    op.create_index(
        "ix_ghs_storage_objects_zone_status",
        "ghs_storage_objects",
        ["zone", "status"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_objects_sha_status",
        "ghs_storage_objects",
        ["content_sha256", "status"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_objects_zone_expires",
        "ghs_storage_objects",
        ["zone", "status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "ghs_storage_asset_refs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("ref_kind", sa.String(length=32), nullable=False),
        sa.Column("ref_owner_id", sa.String(length=128), nullable=False),
        sa.Column("asset_id", sa.String(length=512), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("product", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", _JSON_VARIANT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_key"],
            ["ghs_storage_objects.object_key"],
            name="fk_ghs_storage_asset_refs_object_key_ghs_storage_objects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_storage_asset_refs"),
        sa.UniqueConstraint(
            "object_key",
            "ref_kind",
            "ref_owner_id",
            "asset_id",
            name="uq_ghs_storage_asset_ref",
        ),
    )
    op.create_index(
        "ix_ghs_storage_asset_refs_object_key",
        "ghs_storage_asset_refs",
        ["object_key"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_asset_refs_owner",
        "ghs_storage_asset_refs",
        ["ref_kind", "ref_owner_id"],
        unique=False,
    )

    op.create_table(
        "ghs_storage_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("zone", sa.String(length=32), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actual_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_storage_reservations"),
    )
    op.create_index(
        "ix_ghs_storage_reservations_job_id",
        "ghs_storage_reservations",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_reservations_status",
        "ghs_storage_reservations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_reservations_status_expires",
        "ghs_storage_reservations",
        ["status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "ghs_storage_audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("zone", sa.String(length=32), nullable=True),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("bytes_delta", sa.BigInteger(), nullable=False),
        sa.Column("saved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("details_json", _JSON_VARIANT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ghs_storage_audit_events"),
    )
    op.create_index(
        "ix_ghs_storage_audit_events_event_type",
        "ghs_storage_audit_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_audit_events_zone",
        "ghs_storage_audit_events",
        ["zone"],
        unique=False,
    )
    op.create_index(
        "ix_ghs_storage_audit_events_created_at",
        "ghs_storage_audit_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ghs_storage_audit_events_created_at", table_name="ghs_storage_audit_events")
    op.drop_index("ix_ghs_storage_audit_events_zone", table_name="ghs_storage_audit_events")
    op.drop_index("ix_ghs_storage_audit_events_event_type", table_name="ghs_storage_audit_events")
    op.drop_table("ghs_storage_audit_events")

    op.drop_index(
        "ix_ghs_storage_reservations_status_expires", table_name="ghs_storage_reservations"
    )
    op.drop_index("ix_ghs_storage_reservations_status", table_name="ghs_storage_reservations")
    op.drop_index("ix_ghs_storage_reservations_job_id", table_name="ghs_storage_reservations")
    op.drop_table("ghs_storage_reservations")

    op.drop_index("ix_ghs_storage_asset_refs_owner", table_name="ghs_storage_asset_refs")
    op.drop_index("ix_ghs_storage_asset_refs_object_key", table_name="ghs_storage_asset_refs")
    op.drop_table("ghs_storage_asset_refs")

    op.drop_index("ix_ghs_storage_objects_zone_expires", table_name="ghs_storage_objects")
    op.drop_index("ix_ghs_storage_objects_sha_status", table_name="ghs_storage_objects")
    op.drop_index("ix_ghs_storage_objects_zone_status", table_name="ghs_storage_objects")
    op.drop_index("ix_ghs_storage_objects_status", table_name="ghs_storage_objects")
    op.drop_index("ix_ghs_storage_objects_content_sha256", table_name="ghs_storage_objects")
    op.drop_index("ix_ghs_storage_objects_zone", table_name="ghs_storage_objects")
    op.drop_table("ghs_storage_objects")

    op.drop_table("ghs_storage_ledger_state")
