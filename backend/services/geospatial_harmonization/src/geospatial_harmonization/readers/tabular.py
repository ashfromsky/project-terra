"""CSV, JSON, and RFC 7946 GeoJSON readers with shared tabular normalization."""

import csv
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    VariableSpec,
)
from geospatial_harmonization.readers._helpers import (
    canonical_crs_string,
    infer_variable_semantics,
    select_variables,
)
from geospatial_harmonization.readers.registry import AssetDecodeError


def _parse_column(
    raw_values: list[object],
) -> tuple[NDArray[np.float64] | tuple[str, ...], bool, str]:
    parsed: list[float] = []
    saw_value = False
    for raw in raw_values:
        if raw is None or raw == "":
            parsed.append(math.nan)
            continue
        if isinstance(raw, bool):
            return tuple(str(v) for v in raw_values), False, "string"
        try:
            num = float(str(raw))
        except ValueError:
            return tuple("" if v is None else str(v) for v in raw_values), False, "string"
        saw_value = True
        parsed.append(num if math.isfinite(num) else math.nan)
    if saw_value:
        return np.asarray(parsed, dtype=np.float64), True, "float64"
    return tuple("" if v is None else str(v) for v in raw_values), False, "string"


def _rows_to_decoded(
    asset: AssetReference,
    fmt: DataFormat,
    rows: Sequence[Mapping[str, object]],
    variables: tuple[str, ...] | None,
    crs: str | None = None,
    warnings: tuple[str, ...] = (),
    extra_attrs: dict[str, object] | None = None,
) -> DecodedDataset:
    if not rows:
        raise AssetDecodeError(f"Tabular asset '{asset.asset_id}' contains zero rows")
    columns = list(dict.fromkeys(k for row in rows for k in row))
    selected = select_variables(columns, variables)
    var_specs: dict[str, VariableSpec] = {}
    arrays: dict[str, object] = {}
    coordinates: dict[str, tuple[float | int | str, ...]] = {}
    for col in selected:
        data, is_numeric, dtype = _parse_column([row.get(col) for row in rows])
        sem = infer_variable_semantics(col, {}, is_numeric=is_numeric)
        var_specs[col] = VariableSpec(col, "1", dtype, ("record",), sem)
        arrays[col] = data
        if sem == "coordinate" and len(rows) <= 4096:
            coordinates[col] = (
                tuple(float(x) for x in data) if isinstance(data, np.ndarray) else data
            )
    warn_list = list(warnings)
    if crs is None and any(spec.semantics == "coordinate" for spec in var_specs.values()):
        warn_list.append("Coordinate columns present without explicit CRS metadata.")
    return DecodedDataset(
        asset=asset,
        data_format=fmt,
        variables=var_specs,
        dimensions={"record": len(rows)},
        coordinates=coordinates,
        arrays=arrays,
        attributes=extra_attrs or {},
        crs=crs,
        warnings=tuple(warn_list),
    )


class CSVReader:
    """Tabular CSV decoder preserving coordinate and missing-CRS warnings."""

    @property
    def data_format(self) -> DataFormat:
        return "csv"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if header and b"\x00" in header:
            return False
        text = header.decode("utf-8", errors="ignore")
        return asset.data_format == "csv" or asset.uri.lower().endswith(".csv") or "," in text

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise AssetDecodeError(f"CSV '{path.name}' is missing a header row")
                rows: list[dict[str, object]] = []
                for row in reader:
                    if None in row:
                        raise AssetDecodeError(f"CSV '{path.name}' contains ragged extra columns")
                    rows.append({k: v for k, v in row.items() if k is not None})
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise AssetDecodeError(f"Failed to parse CSV '{path.name}': {exc}") from exc
        return _rows_to_decoded(asset, "csv", rows, variables)


class JSONReader:
    """JSON and RFC 7946 GeoJSON decoder preserving nested provider metadata."""

    @property
    def data_format(self) -> DataFormat:
        return "json"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        stripped = header.lstrip(b"\xef\xbb\xbf \t\r\n")
        if stripped:
            return stripped.startswith((b"{", b"["))
        return asset.data_format == "json" or asset.uri.lower().endswith((".json", ".geojson"))

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssetDecodeError(f"Failed to parse JSON '{path.name}': {exc}") from exc

        if isinstance(payload, list) and payload and all(isinstance(r, dict) for r in payload):
            return _rows_to_decoded(asset, "json", payload, variables)
        if not isinstance(payload, dict):
            raise AssetDecodeError(f"Unsupported JSON root structure in '{path.name}'")

        crs_str = canonical_crs_string(payload.get("crs"))
        gtype = payload.get("type")
        if gtype in ("FeatureCollection", "Feature"):
            raw_feats = payload.get("features", []) if gtype == "FeatureCollection" else [payload]
            feats = raw_feats if isinstance(raw_feats, list) else []
            rows, has_geometry = _extract_geojson_rows(feats)
            effective_crs = crs_str or ("EPSG:4326" if has_geometry else None)
            if rows and any(k not in ("lon", "lat") for row in rows for k in row):
                return _rows_to_decoded(
                    asset,
                    "json",
                    rows,
                    variables,
                    crs=effective_crs,
                    extra_attrs={"geojson_type": gtype, "feature_count": len(feats)},
                )
            crs_str = effective_crs
        return _dict_to_decoded(asset, payload, variables, crs_str)


def _extract_geojson_rows(features: list[object]) -> tuple[list[dict[str, object]], bool]:
    rows: list[dict[str, object]] = []
    has_geometry = False
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        row: dict[str, object] = (
            {str(k): v for k, v in props.items() if not isinstance(v, (dict, list))}
            if isinstance(props, dict)
            else {}
        )
        geom = feat.get("geometry")
        if isinstance(geom, dict) and geom.get("coordinates") is not None:
            has_geometry = True
            coords = geom.get("coordinates")
            if geom.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
                row.setdefault("lon", coords[0])
                row.setdefault("lat", coords[1])
        if row:
            rows.append(row)
    return rows, has_geometry


def _dict_to_decoded(
    asset: AssetReference,
    payload: dict[str, object],
    variables: tuple[str, ...] | None,
    crs_str: str | None,
) -> DecodedDataset:
    series_keys = [
        k for k, v in payload.items() if isinstance(v, list) and v and not isinstance(v[0], dict)
    ]
    selected = select_variables(series_keys, variables) if series_keys else ()
    if variables is not None and not series_keys:
        raise AssetDecodeError(f"Requested variables not found in JSON object: {list(variables)}")
    var_specs: dict[str, VariableSpec] = {}
    arrays: dict[str, object] = {}
    record_len = 0
    for key in selected:
        raw_list = payload[key]
        if isinstance(raw_list, list):
            record_len = max(record_len, len(raw_list))
            data, is_numeric, dtype = _parse_column(raw_list)
            var_specs[key] = VariableSpec(
                key, "1", dtype, ("record",), infer_variable_semantics(key, {}, is_numeric)
            )
            arrays[key] = data
    dims = {"record": record_len} if selected else {}
    warns = () if crs_str else ("No explicit CRS metadata found in JSON object.",)
    return DecodedDataset(
        asset=asset,
        data_format="json",
        variables=var_specs,
        dimensions=dims,
        arrays=arrays,
        attributes={"payload": payload},
        crs=crs_str,
        warnings=warns,
    )
