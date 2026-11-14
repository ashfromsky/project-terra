"""Tests for DataCompressionManager, PrecisionPolicy, AOI windowing/clipping, and streaming."""

import hashlib
import socket
from pathlib import Path
from typing import Any

import h5py
import httpx
import netCDF4
import numpy as np
import pytest
import rasterio
import zarr
from rasterio.transform import from_origin

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import (
    ObjectTooLargeError,
    StorageImmutabilityError,
    StorageIntegrityError,
)
from geospatial_harmonization.domain.models.dataset import AssetReference, VariableSpec
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.storage import CompressionPolicy, PrecisionPolicy
from geospatial_harmonization.handlers.base import safe_fetch_to_file
from geospatial_harmonization.readers import AssetDecodeError, GeoTIFFReader
from geospatial_harmonization.storage.compression import (
    DataCompressionManager,
    compute_balanced_chunks,
    geotiff_creation_options,
    validate_precision_transition,
)
from geospatial_harmonization.transformations import clip_raster_to_aoi, warp_variable


def test_geotiff_and_cog_lossless_compression_and_skip_recompression(tmp_path: Path) -> None:
    mgr = DataCompressionManager(
        Settings(ghs_storage_raster_codec="ZSTD", ghs_storage_raster_cog_enabled=True)
    )
    src = tmp_path / "uncompressed.tif"
    data = np.repeat(np.linspace(250.123456789012, 310.987654321098, 64), 64).reshape(64, 64)
    with rasterio.open(
        src,
        "w",
        driver="GTiff",
        height=64,
        width=64,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=from_origin(10.0, 52.0, 0.05, 0.05),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
        dst.set_band_description(1, "LST_Day")
        dst.scales = (0.02,)
        dst.offsets = (10.0,)
        dst.units = ("K",)
        dst.update_tags(SOURCE_PRODUCT="MOD11A2")

    cog_out = tmp_path / "derived_cog.tif"
    res = mgr.optimize_geotiff(src, cog_out)
    assert res.skipped_reason is None
    assert res.compressed_bytes < res.original_bytes
    assert res.saved_bytes == res.original_bytes - res.compressed_bytes
    assert "SOURCE_PRODUCT" in res.metadata_preserved
    assert "units" in res.metadata_preserved

    with rasterio.open(cog_out) as chk:
        assert chk.dtypes == ("float64",)
        assert chk.compression == rasterio.enums.Compression.zstd
        assert chk.profile.get("tiled") is True
        assert chk.descriptions == ("LST_Day",)
        assert chk.scales == (0.02,)
        assert chk.offsets == (10.0,)
        assert chk.units == ("K",)
        assert chk.tags()["SOURCE_PRODUCT"] == "MOD11A2"
        np.testing.assert_array_equal(chk.read(1), data)

    recomp_skip = mgr.optimize_geotiff(cog_out)
    assert recomp_skip.skipped_reason == "already_compressed_below_savings_threshold"
    assert recomp_skip.saved_bytes == 0

    deflate_out = tmp_path / "deflate.tif"
    res_def = mgr.optimize_geotiff(src, deflate_out, codec="DEFLATE", cog=False)
    assert res_def.codec == "DEFLATE"
    with rasterio.open(deflate_out) as dchk:
        assert dchk.compression == rasterio.enums.Compression.deflate
        np.testing.assert_array_equal(dchk.read(1), data)

    big_opts = geotiff_creation_options(
        "float64", mgr.policy, estimated_raw_bytes=4_000_000_000, cog=False
    )
    assert big_opts["bigtiff"] == "YES"
    small_opts = geotiff_creation_options(
        "float64", mgr.policy, estimated_raw_bytes=1024, cog=False
    )
    assert small_opts["bigtiff"] == "IF_SAFER"


def test_netcdf_zarr_hdf5_and_raw_hdf4_preservation(tmp_path: Path) -> None:
    mgr = DataCompressionManager(
        Settings(ghs_storage_netcdf_complevel=5, ghs_storage_zarr_codec="zstd")
    )

    nc_in = tmp_path / "raw_classic.nc"
    expected_nc = np.arange(64 * 64, dtype=np.float64).reshape(1, 64, 64) * 0.125
    with netCDF4.Dataset(nc_in, "w", format="NETCDF3_CLASSIC") as ds:
        ds.Conventions = "CF-1.8"
        ds.createDimension("time", 1)
        ds.createDimension("y", 64)
        ds.createDimension("x", 64)
        v_t = ds.createVariable("temp", "f8", ("time", "y", "x"), fill_value=-9999.0)
        v_t.units = "K"
        v_t.scale_factor = 1.0
        v_t.add_offset = 0.0
        v_t[:] = expected_nc

    nc_out = tmp_path / "opt.nc"
    nc_res = mgr.optimize_netcdf(nc_in, nc_out)
    assert nc_res.skipped_reason is None
    assert nc_res.compressed_bytes < nc_res.original_bytes
    with netCDF4.Dataset(nc_out, "r") as chk_nc:
        assert chk_nc.Conventions == "CF-1.8"
        var = chk_nc.variables["temp"]
        assert var.dtype == np.float64
        assert var.filters()["zlib"] is True
        assert var.filters()["shuffle"] is True
        assert var.units == "K"
        assert float(var._FillValue) == -9999.0
        np.testing.assert_array_equal(np.asarray(var[:]), expected_nc)

    assert (
        mgr.optimize_netcdf(nc_out).skipped_reason == "already_compressed_below_savings_threshold"
    )

    z_in = tmp_path / "uncompressed.zarr"
    z_data = np.zeros((2, 64, 64), dtype=np.float64)
    z_data[:, 10:20, 10:20] = 42.125
    root_in = zarr.open_group(z_in, mode="w")
    root_in.attrs["project"] = "TERRA"
    arr_in = root_in.create_array(
        "precip",
        shape=z_data.shape,
        chunks=(2, 64, 64),
        dtype="float64",
        compressors=None,
        dimension_names=("time", "y", "x"),
        attributes={"units": "mm/hr"},
    )
    arr_in[:] = z_data

    z_out = tmp_path / "compressed.zarr"
    z_res = mgr.optimize_zarr(z_in, z_out)
    assert z_res.compressed_bytes < z_res.original_bytes
    z_chk = zarr.open_group(z_out, mode="r")
    assert z_chk.attrs["project"] == "TERRA"
    arr_chk = z_chk["precip"]
    assert isinstance(arr_chk, zarr.Array)
    assert arr_chk.dtype == np.float64
    assert arr_chk.attrs["units"] == "mm/hr"
    assert len(arr_chk.compressors) > 0
    np.testing.assert_array_equal(np.asarray(arr_chk[:]), z_data)

    balanced = compute_balanced_chunks((12, 4096, 4096), itemsize=8, target_chunk_bytes=1_048_576)
    chunk_bytes = int(np.prod(balanced)) * 8
    assert balanced[0] == 1
    assert 4_096 <= chunk_bytes <= 1_048_576

    h5_in = tmp_path / "uncompressed.h5"
    h5_data = np.ones((64, 64), dtype=np.float64) * 0.35
    with h5py.File(h5_in, "w") as hf:
        grp = hf.create_group("Soil_Moisture")
        grp.attrs["crs_wkt"] = "EPSG:6933"
        dset = grp.create_dataset("sm", data=h5_data, dtype="float64")
        dset.attrs["units"] = "cm^3/cm^3"

    h5_out = tmp_path / "compressed.h5"
    h5_res = mgr.optimize_hdf5(h5_in, h5_out)
    assert h5_res.compressed_bytes < h5_res.original_bytes
    with h5py.File(h5_out, "r") as hchk:
        ds_chk = hchk["Soil_Moisture/sm"]
        assert isinstance(ds_chk, h5py.Dataset)
        assert ds_chk.compression == "gzip"
        assert ds_chk.shuffle is True
        assert ds_chk.attrs["units"] == "cm^3/cm^3"
        np.testing.assert_array_equal(ds_chk[()], h5_data)

    hdf4_raw = tmp_path / "MOD13Q1.hdf"
    hdf4_bytes = b"\x0e\x03\x13\x01raw-hdf4-content"
    hdf4_raw.write_bytes(hdf4_bytes)
    hdf4_res = mgr.preserve_raw_source(hdf4_raw, data_format="hdf4")
    assert hdf4_res.skipped_reason == "preserve_raw_source_immutable"
    assert hdf4_raw.read_bytes() == hdf4_bytes


def test_precision_policy_blocks_silent_downcast_and_preserves_float64_warp() -> None:
    prec = PrecisionPolicy()
    validate_precision_transition("float64", "float64", prec, codec="ZSTD")
    validate_precision_transition("int32", "int64", prec)

    with pytest.raises(StorageIntegrityError, match="float64 -> float32"):
        validate_precision_transition("float64", "float32", prec)
    with pytest.raises(StorageIntegrityError, match="integer precision reduction"):
        validate_precision_transition("int32", "int16", prec)
    with pytest.raises(StorageIntegrityError, match="integer precision reduction"):
        validate_precision_transition("int16", "uint16", prec)
    with pytest.raises(StorageIntegrityError, match="integer dtype"):
        validate_precision_transition("uint16", "float32", prec)
    with pytest.raises(StorageIntegrityError, match="Lossy compression"):
        validate_precision_transition("float32", "float32", prec, codec="JPEG")
    with pytest.raises(StorageIntegrityError, match="Quantization"):
        validate_precision_transition("float32", "float32", prec, quantized=True)

    src_grid = GridSpec(
        "EPSG:4326", 1.0, 1.0, "degree", SpatialBounds(0.0, 0.0, 2.0, 2.0)
    ).resolved()
    dst_grid = src_grid
    high_prec_val = 123456.12345678901
    arr_f64 = np.full((2, 2), high_prec_val, dtype=np.float64)
    spec_f64 = VariableSpec("precise_var", "1", "float64", ("y", "x"), "continuous_intensive")

    warped, _ = warp_variable(arr_f64, spec_f64, src_grid, dst_grid, "nearest", {})
    assert warped.data.dtype == np.float64
    assert float(warped.data[0, 0]) == pytest.approx(high_prec_val, abs=1e-12)

    with pytest.raises(StorageIntegrityError, match="float64 -> float32"):
        warp_variable(
            arr_f64,
            spec_f64,
            src_grid,
            dst_grid,
            "nearest",
            {},
            target_dtype="float32",
        )


def test_windowed_geotiff_reader_and_aoi_clip_never_mutate_source(tmp_path: Path) -> None:
    src = tmp_path / "global_grid.tif"
    raster = np.arange(64 * 64, dtype=np.float64).reshape(64, 64)
    with rasterio.open(
        src,
        "w",
        driver="GTiff",
        height=64,
        width=64,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=from_origin(0.0, 64.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(raster, 1)
        dst.set_band_description(1, "temperature")
        dst.units = ("K",)
        dst.update_tags(ORIGIN="raw_archive")

    raw_digest = hashlib.sha256(src.read_bytes()).hexdigest()
    asset = AssetReference("g1", src.as_uri(), "geotiff", "image/tiff")
    reader = GeoTIFFReader()

    sub_aoi = SpatialBounds(min_x=20.0, min_y=30.0, max_x=25.0, max_y=35.0)
    decoded_win = reader.read_windowed(
        asset, src, aoi_bounds=sub_aoi, aoi_crs="EPSG:4326", pad_pixels=1
    )
    arr_win = np.asarray(decoded_win.arrays["temperature"])
    assert arr_win.shape == (7, 7)
    assert arr_win.dtype == np.float64
    assert decoded_win.grid is not None
    assert decoded_win.grid.bounds.min_x <= 20.0 and decoded_win.grid.bounds.max_x >= 25.0

    disjoint_aoi = SpatialBounds(min_x=100.0, min_y=10.0, max_x=110.0, max_y=20.0)
    decoded_disjoint = reader.read_windowed(
        asset, src, aoi_bounds=disjoint_aoi, aoi_crs="EPSG:4326", allow_disjoint_fallback=True
    )
    assert np.asarray(decoded_disjoint.arrays["temperature"]).shape == (1, 1)
    with pytest.raises(AssetDecodeError, match="do not intersect"):
        reader.read_windowed(
            asset, src, aoi_bounds=disjoint_aoi, aoi_crs="EPSG:4326", allow_disjoint_fallback=False
        )

    clipped = tmp_path / "clipped_aoi.tif"
    clip_res = clip_raster_to_aoi(
        src,
        clipped,
        aoi_bounds=sub_aoi,
        aoi_crs="EPSG:4326",
        compression=CompressionPolicy(raster_codec="ZSTD", raster_cog_enabled=True),
    )
    assert clip_res.compressed_bytes < clip_res.original_bytes
    with rasterio.open(clipped) as csrc:
        assert (csrc.width, csrc.height) == (5, 5)
        assert csrc.dtypes == ("float64",)
        assert csrc.units == ("K",)
        assert csrc.tags()["ORIGIN"] == "raw_archive"
        np.testing.assert_array_equal(csrc.read(1), raster[64 - 35 : 64 - 30, 20:25])

    with pytest.raises(StorageImmutabilityError):
        clip_raster_to_aoi(src, src, aoi_bounds=sub_aoi)

    assert hashlib.sha256(src.read_bytes()).hexdigest() == raw_digest


async def test_streaming_fetch_to_file_enforces_max_bytes_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_dns)
    payload = b"stream-chunk-" * 40
    observed_headers: list[dict[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        observed_headers.append(dict(request.headers))
        if request.url.host == "a.example.org":
            return httpx.Response(302, headers={"location": "https://b.example.org/data/sample.nc"})
        if request.url.path == "/too-big-stream":
            return httpx.Response(200, content=b"Z" * 500)
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/x-netcdf"},
        )

    transport = httpx.MockTransport(_handler)
    dest_dir = tmp_path / "dl"
    dest, ref, final_url = await safe_fetch_to_file(
        "https://a.example.org/start.nc",
        dest_dir,
        data_format="netcdf",
        allowed_hosts=("*.example.org",),
        headers={"Authorization": "Bearer top-secret"},
        transport=transport,
        chunk_bytes=64,
        max_bytes=1024,
    )
    assert final_url == "https://b.example.org/data/sample.nc"
    assert dest.name == "sample.nc"
    assert ref.size_bytes == len(payload)
    assert ref.checksum_sha256 == hashlib.sha256(payload).hexdigest()
    assert "authorization" in observed_headers[0]
    assert "authorization" not in observed_headers[1]
    assert not any(p.name.startswith(".ghs-tmp-") for p in dest_dir.iterdir())

    def _chunked_no_cl(_req: httpx.Request) -> httpx.Response:
        class _ChunkedStream(httpx.AsyncByteStream):
            async def __aiter__(self) -> Any:
                for _ in range(10):
                    yield b"X" * 100

        return httpx.Response(200, stream=_ChunkedStream())

    oversized_transport = httpx.MockTransport(_chunked_no_cl)
    with pytest.raises(ObjectTooLargeError):
        await safe_fetch_to_file(
            "https://b.example.org/big.nc",
            dest_dir,
            allowed_hosts=("*.example.org",),
            transport=oversized_transport,
            max_bytes=350,
            chunk_bytes=100,
        )
    assert not any(p.name.startswith(".ghs-tmp-") for p in dest_dir.iterdir())
