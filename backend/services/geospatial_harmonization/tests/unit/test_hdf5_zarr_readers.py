"""Unit tests for HDF5Reader and ZarrReader using real h5py and zarr v3 stores."""

from pathlib import Path

import h5py
import numpy as np
import pytest
import zarr

from geospatial_harmonization.domain.models.dataset import AssetReference, DataFormat
from geospatial_harmonization.readers import (
    AssetDecodeError,
    HDF5Reader,
    ReaderRegistry,
    ZarrReader,
)


def _ref(
    aid: str, p: Path, fmt: DataFormat = "unknown", media: str = "application/octet-stream"
) -> AssetReference:
    return AssetReference(aid, p.as_uri(), fmt, media)


def test_hdf5_reader_decodes_grouped_smap_like_file_and_blocks_qa_scaling(tmp_path: Path) -> None:
    h5_path = tmp_path / "smap_sample.h5"
    with h5py.File(h5_path, mode="w") as h5f:
        h5f.attrs["crs_wkt"] = "EPSG:6933"
        am = h5f.create_group("Soil_Moisture_Retrieval_Data_AM")
        x = am.create_dataset("x", data=np.array([0.0, 9000.0, 18000.0]))
        x.attrs["axis"] = "X"
        y = am.create_dataset("y", data=np.array([18000.0, 9000.0]))
        y.attrs["axis"] = "Y"
        sm = am.create_dataset("soil_moisture", data=np.full((2, 3), 0.25, dtype=np.float32))
        sm.attrs.update(
            {"units": "cm3/cm3", "DimensionNames": b"y,x", "_FillValue": np.float32(-9999.0)}
        )
        qf = am.create_dataset(
            "retrieval_qual_flag", data=np.array([[0, 8, 1], [0, 0, 8]], dtype=np.uint16)
        )
        qf.attrs.update({"DimensionNames": "y,x", "scale_factor": np.float32(0.01)})

    reg = ReaderRegistry((HDF5Reader(),))
    dec = reg.read(_ref("h5-1", h5_path, "hdf5", "application/x-hdf5"), h5_path)
    assert (
        dec.crs == "EPSG:6933"
        and dec.grid is not None
        and (dec.grid.width, dec.grid.height) == (3, 2)
    )
    assert dec.variables["Soil_Moisture_Retrieval_Data_AM/soil_moisture"].dimensions == ("y", "x")
    qa = dec.variables["Soil_Moisture_Retrieval_Data_AM/retrieval_qual_flag"]
    assert qa.semantics == "qa_flag" and qa.scale_factor is None
    assert any("Dropped scaling" in w for w in dec.warnings)

    corrupt = tmp_path / "corrupt.h5"
    corrupt.write_bytes(b"\x89HDF\r\n\x1a\ncorrupted")
    with pytest.raises(AssetDecodeError, match="Failed to decode HDF5"):
        reg.read(_ref("h5-bad", corrupt, "hdf5"), corrupt)


def test_zarr_v3_reader_decodes_grouped_store_and_preserves_missing_crs(tmp_path: Path) -> None:
    store = tmp_path / "cube.zarr"
    root = zarr.open_group(store, mode="w")
    root.create_array("lon", data=np.array([10.0, 10.5, 11.0]), dimension_names=("lon",)).attrs[
        "units"
    ] = "degrees_east"
    root.create_array("lat", data=np.array([50.0, 50.5]), dimension_names=("lat",)).attrs[
        "units"
    ] = "degrees_north"
    ndvi = root.create_array(
        "ndvi", data=np.full((2, 3), 0.7, dtype=np.float32), dimension_names=("lat", "lon")
    )
    ndvi.attrs["units"] = "1"

    reg = ReaderRegistry((ZarrReader(),))
    dec = reg.read(_ref("zr-1", store, "zarr", "application/x-zarr"), store)
    assert (
        dec.crs == "EPSG:4326"
        and dec.grid is not None
        and dec.grid.resolution_x == pytest.approx(0.5)
    )
    assert dec.variables["ndvi"].dimensions == ("lat", "lon")

    unref_store = tmp_path / "unref_store"
    zarr.open_group(unref_store, mode="w").create_array(
        "band", data=np.ones((2, 2), dtype=np.float32), dimension_names=("r", "c")
    )
    unref = reg.read(_ref("zr-2", unref_store), unref_store)
    assert unref.crs is None and unref.grid is None
    assert any("No explicit CRS" in w for w in unref.warnings)
