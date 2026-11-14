"""Unit tests for storage settings, domain models, and StorageZoneManager."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from geospatial_harmonization import domain
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import (
    ObjectTooLargeError,
    StorageBudgetExceededError,
    StorageImmutabilityError,
    StorageIntegrityError,
    StorageReservationError,
)
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    CompressionPolicy,
    StorageObjectRecord,
    StorageReservation,
    StoredObjectInfo,
)
from geospatial_harmonization.storage.zones import StorageZoneManager


def test_storage_settings_defaults_env_overrides_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = Settings(_env_file=None, environment="test")
    assert defaults.ghs_storage_budget_bytes == 8_000_000_000
    assert defaults.ghs_storage_warning_threshold == pytest.approx(0.80)
    assert defaults.ghs_storage_hard_limit_threshold == pytest.approx(1.00)
    assert defaults.ghs_storage_max_object_bytes == 2_147_483_648
    assert defaults.ghs_storage_max_job_output_bytes == 1_073_741_824
    assert defaults.ghs_storage_estimation_enabled is True
    assert defaults.ghs_storage_reservation_ttl_seconds == 3600
    assert defaults.ghs_storage_allow_lossy_compression is False
    assert defaults.ghs_admin_token is None

    monkeypatch.setenv("GHS_STORAGE_BUDGET_BYTES", "5000000000")
    monkeypatch.setenv("GHS_STORAGE_WARNING_THRESHOLD", "0.75")
    monkeypatch.setenv("GHS_STORAGE_HARD_LIMIT_THRESHOLD", "0.95")
    monkeypatch.setenv("GHS_STORAGE_MAX_OBJECT_BYTES", "100000000")
    monkeypatch.setenv("GHS_STORAGE_MAX_JOB_OUTPUT_BYTES", "50000000")
    monkeypatch.setenv("GHS_STORAGE_ESTIMATION_ENABLED", "false")
    monkeypatch.setenv("GHS_STORAGE_RESERVATION_TTL_SECONDS", "1200")
    monkeypatch.setenv("GHS_ADMIN_TOKEN", "super-secret-admin-token")

    loaded = Settings(_env_file=None, environment="test")
    assert loaded.ghs_storage_budget_bytes == 5_000_000_000
    assert loaded.ghs_storage_warning_threshold == pytest.approx(0.75)
    assert loaded.ghs_storage_hard_limit_threshold == pytest.approx(0.95)
    assert loaded.ghs_storage_max_object_bytes == 100_000_000
    assert loaded.ghs_storage_max_job_output_bytes == 50_000_000
    assert loaded.ghs_storage_estimation_enabled is False
    assert loaded.ghs_storage_reservation_ttl_seconds == 1200
    assert "super-secret-admin-token" not in repr(loaded)
    assert "super-secret-admin-token" not in str(loaded)
    assert loaded.ghs_admin_token is not None
    assert loaded.ghs_admin_token.get_secret_value() == "super-secret-admin-token"

    with pytest.raises(ValidationError, match="warning_threshold"):
        Settings(
            _env_file=None,
            ghs_storage_warning_threshold=0.95,
            ghs_storage_hard_limit_threshold=0.80,
        )

    with pytest.raises(ValidationError, match="multiple of 16"):
        Settings(_env_file=None, ghs_storage_raster_block_size=100)


def test_storage_domain_models_and_exceptions_validation() -> None:
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    digest = "a" * 64

    info = StoredObjectInfo(key="raw/modis/a.hdf", size_bytes=128, last_modified=now)
    assert info.size_bytes == 128

    with pytest.raises(StorageIntegrityError):
        StoredObjectInfo(key="", size_bytes=10)
    with pytest.raises(StorageIntegrityError):
        StorageObjectRecord(
            object_key="raw/modis/a.hdf",
            zone="raw",
            content_sha256="short",
            size_bytes=10,
            media_type="application/x-hdf",
            data_format="hdf4",
            created_at=now,
            updated_at=now,
        )
    with pytest.raises(StorageIntegrityError):
        AssetReferenceLink(
            object_key="raw/modis/a.hdf",
            ref_kind="dataset",
            ref_owner_id="",
            asset_id="a1",
            provider="modis",
            product="MOD13Q1.061",
            created_at=now,
        )
    with pytest.raises(StorageReservationError):
        StorageReservation(
            reservation_id=uuid4(),
            job_id="job-1",
            operation="harmonize",
            zone="derived",
            reserved_bytes=100,
            status="active",
            created_at=now,
            expires_at=now - timedelta(seconds=1),
        )
    with pytest.raises(StorageIntegrityError):
        CompressionPolicy(raster_block_size=250)

    budget_err = StorageBudgetExceededError(
        "exceeded",
        requested_bytes=200,
        available_bytes=50,
        budget_bytes=1000,
        reserved_bytes=950,
        zone="derived",
    )
    assert budget_err.code == "STORAGE_BUDGET_EXCEEDED"
    assert budget_err.available_bytes == 50

    too_large = ObjectTooLargeError("too big", requested_bytes=500, limit_bytes=100, scope="object")
    assert too_large.code == "OBJECT_TOO_LARGE"
    assert hasattr(domain, "StorageLedgerRepository")
    assert len(digest) == 64


def test_storage_zone_manager_keys_policies_and_immutability_guards() -> None:
    cfg = Settings(
        _env_file=None,
        ghs_storage_raw_retention_days=365,
        ghs_storage_intermediate_retention_seconds=900,
        ghs_storage_derived_retention_days=90,
    )
    mgr = StorageZoneManager(cfg)
    ds_id = uuid4()
    digest = "0123456789abcdef" * 4

    modis_key = mgr.raw_key("modis", "MOD13Q1.061", ds_id, "tile.hdf", content_sha256=digest)
    gpm_key = mgr.raw_key("gpm_imerg", "GPM_3IMERGHH.07", ds_id, "imerg.nc4")
    smap_key = mgr.raw_key("smap", "SPL3SMP_E.006", ds_id, "smap.h5")
    power_key = mgr.raw_key("nasa_power", "power_daily", ds_id, "power.json")

    assert modis_key == f"raw/modis/MOD13Q1.061/{digest[:16]}/tile.hdf"
    assert gpm_key.startswith("raw/gpm/GPM_3IMERGHH.07/")
    assert smap_key.startswith("raw/smap/SPL3SMP_E.006/")
    assert power_key.startswith("raw/nasa-power/power_daily/")

    inter_key = mgr.intermediate_key(ds_id, "clipped.tif", stage="clip")
    deriv_key = mgr.derived_key(ds_id, "ndvi.tif", product="MOD13Q1.061", content_sha256=digest)
    assert inter_key == f"intermediate/{ds_id}/clip/clipped.tif"
    assert deriv_key == f"derived/MOD13Q1.061/{digest[:16]}/ndvi.tif"

    assert mgr.infer_zone(modis_key) == "raw"
    assert mgr.infer_zone(inter_key) == "intermediate"
    assert mgr.infer_zone(deriv_key) == "derived"
    with pytest.raises(ValueError, match="zone"):
        mgr.infer_zone("unknown/foo.tif")
    with pytest.raises(ValueError, match="Unsafe"):
        mgr.infer_zone("raw/../etc/passwd")

    raw_policy = mgr.policy_for("raw")
    inter_policy = mgr.policy_for("intermediate")
    deriv_policy = mgr.policy_for("derived")
    assert raw_policy.immutable is True and raw_policy.auto_cleanup_on_job_success is False
    assert raw_policy.retention_seconds == 365 * 86400
    assert inter_policy.immutable is False and inter_policy.auto_cleanup_on_job_success is True
    assert inter_policy.retention_seconds == 900
    assert deriv_policy.immutable is True and deriv_policy.retention_seconds == 90 * 86400

    now = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    assert mgr.expiration_for("intermediate", now=now) == now + timedelta(seconds=900)

    assert mgr.assert_writable(modis_key, exists_in_store=False) == "raw"
    assert mgr.assert_writable(inter_key, exists_in_store=True) == "intermediate"
    with pytest.raises(StorageImmutabilityError, match="overwrite"):
        mgr.assert_writable(modis_key, exists_in_store=True)

    with pytest.raises(StorageImmutabilityError, match="raw zone"):
        mgr.assert_deletable(modis_key, reason="job_completed")
    with pytest.raises(StorageImmutabilityError, match="protected"):
        mgr.assert_deletable(deriv_key, reason="job_completed")
    assert mgr.assert_deletable(inter_key, reason="job_completed") == "intermediate"
