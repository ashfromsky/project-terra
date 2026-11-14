"""Unit tests for CSVReader and JSONReader tabular/GeoJSON decoding."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from geospatial_harmonization.domain.models.dataset import AssetReference
from geospatial_harmonization.readers import (
    AssetDecodeError,
    CSVReader,
    JSONReader,
    ReaderRegistry,
)


def test_csv_reader_decodes_numeric_categorical_and_coordinates(tmp_path: Path) -> None:
    csv_path = tmp_path / "stations.csv"
    csv_path.write_text(
        "\ufefflat,lon,temp_c,station\n50.45,30.52,18.2,KYIV\n49.84,24.03,,LVIV\n",
        encoding="utf-8",
    )
    registry = ReaderRegistry((CSVReader(),))
    decoded = registry.read(AssetReference("csv-1", csv_path.as_uri(), "csv", "text/csv"), csv_path)

    assert decoded.crs is None
    assert decoded.dimensions == {"record": 2}
    assert decoded.variables["lat"].semantics == "coordinate"
    assert decoded.variables["station"].semantics == "categorical"
    assert decoded.coordinates["lat"] == (50.45, 49.84)
    temps = decoded.arrays["temp_c"]
    assert isinstance(temps, np.ndarray) and math.isnan(float(temps[1]))
    assert any("without explicit CRS" in w for w in decoded.warnings)

    subset = registry.read(
        AssetReference("csv-1", csv_path.as_uri(), "csv", "text/csv"),
        csv_path,
        variables=("temp_c",),
    )
    assert list(subset.variables.keys()) == ["temp_c"]


def test_csv_reader_rejects_empty_or_ragged_files(tmp_path: Path) -> None:
    empty_rows = tmp_path / "hdr.csv"
    empty_rows.write_text("lat,lon\n", encoding="utf-8")
    with pytest.raises(AssetDecodeError, match="zero rows"):
        CSVReader().read(AssetReference("c1", empty_rows.as_uri(), "csv", "text/csv"), empty_rows)

    ragged = tmp_path / "bad.csv"
    ragged.write_text("a,b\n1,2,3\n", encoding="utf-8")
    with pytest.raises(AssetDecodeError, match="extra columns"):
        CSVReader().read(AssetReference("c2", ragged.as_uri(), "csv", "text/csv"), ragged)


def test_json_reader_handles_geojson_nested_payload_and_errors(tmp_path: Path) -> None:
    geojson_path = tmp_path / "obs.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [30.5, 50.4]},
                        "properties": {"precip": 12.5, "flag": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = ReaderRegistry((JSONReader(),))
    gj = registry.read(
        AssetReference("gj-1", geojson_path.as_uri(), "json", "application/geo+json"), geojson_path
    )
    assert gj.crs == "EPSG:4326"
    assert gj.coordinates["lon"] == (30.5,)
    assert gj.variables["flag"].semantics == "qa_flag"

    nested = tmp_path / "power.json"
    nested.write_text(
        json.dumps(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [30.5, 50.4, 150.0]},
                "properties": {"parameter": {"T2M": {"20260101": 1.2}}},
            }
        ),
        encoding="utf-8",
    )
    nd = registry.read(AssetReference("pwr-1", nested.as_uri(), "json", "application/json"), nested)
    assert nd.crs == "EPSG:4326"
    assert "payload" in nd.attributes

    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    with pytest.raises(AssetDecodeError, match="Failed to parse JSON"):
        JSONReader().read(AssetReference("bad", bad.as_uri(), "json", "application/json"), bad)
