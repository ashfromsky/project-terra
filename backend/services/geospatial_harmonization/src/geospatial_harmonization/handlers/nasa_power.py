"""NASA POWER handler preserving MERRA-2 vs. CERES native variable provenance."""

import json
import math
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import (
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSemantics,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import SpatialBounds
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.handlers.base import (
    build_provenance,
    parse_handler_payload,
    safe_fetch_bytes,
    write_raw_asset,
)

_POWER_META: dict[str, tuple[str, str, str, VariableSemantics]] = {
    "T2M": ("degC", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "T2M_MAX": ("degC", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "T2M_MIN": ("degC", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "RH2M": ("%", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "WS10M": ("m/s", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "PRECTOTCORR": ("mm/day", "0.5x0.625", "MERRA-2", "continuous_extensive"),
    "ALLSKY_SFC_SW_DWN": ("MJ/m^2/day", "1.0x1.0", "CERES SYN1deg", "continuous_intensive"),
    "CLRSKY_SFC_SW_DWN": ("MJ/m^2/day", "1.0x1.0", "CERES SYN1deg", "continuous_intensive"),
}


def _as_map(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


class NASAPowerPayload(BaseModel):
    """Validated query parameters for NASA POWER point or regional retrieval."""

    model_config = ConfigDict(extra="forbid")

    product: str = "nasa_power"
    mode: Literal["point", "regional"] = "point"
    temporal: Literal["daily", "hourly"] = "daily"
    community: str = "AG"
    parameters: tuple[str, ...]
    start_date: date
    end_date: date
    latitude: float | None = None
    longitude: float | None = None
    min_lat: float | None = None
    max_lat: float | None = None
    min_lon: float | None = None
    max_lon: float | None = None

    @model_validator(mode="after")
    def _validate_request(self) -> "NASAPowerPayload":
        if not self.parameters:
            raise ValueError("parameters must be non-empty")
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        if self.mode == "point":
            if self.latitude is None or self.longitude is None:
                raise ValueError("point mode requires latitude and longitude")
        elif any(v is None for v in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)):
            raise ValueError("regional mode requires min_lat, max_lat, min_lon, and max_lon")
        return self


class NASAPowerHandler:
    """DataHandler for NASA POWER agro-climatology point and regional REST APIs."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        raw_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._base_url = cfg.nasa_power_base_url.rstrip("/")
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "nasa_power"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("nasa_power", "power_daily", "power_hourly")

    def _build_query(self, req: NASAPowerPayload) -> tuple[str, dict[str, str]]:
        url = f"{self._base_url}/temporal/{req.temporal}/{req.mode}"
        params = {
            "parameters": ",".join(req.parameters),
            "community": req.community,
            "start": req.start_date.strftime("%Y%m%d"),
            "end": req.end_date.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }
        if req.mode == "point":
            params["latitude"] = str(req.latitude)
            params["longitude"] = str(req.longitude)
        else:
            params["latitude-min"] = str(req.min_lat)
            params["latitude-max"] = str(req.max_lat)
            params["longitude-min"] = str(req.min_lon)
            params["longitude-max"] = str(req.max_lon)
        return url, params

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Fetch NASA POWER JSON and map MERRA-2/CERES variable specs cleanly."""
        req = parse_handler_payload(NASAPowerPayload, payload)
        url, params = self._build_query(req)
        host = (urlparse(self._base_url).hostname or "").lower()
        raw, final_url, media = await safe_fetch_bytes(
            url,
            allowed_hosts=[host] if host else None,
            params=params,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IncompatibleDatasetError(f"Invalid NASA POWER JSON response: {exc}") from exc
        if not isinstance(doc, Mapping):
            raise IncompatibleDatasetError("NASA POWER response root must be a JSON object")

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_power_"))
        fname = f"power_{req.mode}_{req.start_date:%Y%m%d}_{req.end_date:%Y%m%d}.json"
        _, asset = write_raw_asset(base_dir, fname, raw, "json", media or "application/json")

        header = _as_map(doc.get("header"))
        raw_fill = header.get("fill_value")
        fill_val = float(raw_fill) if isinstance(raw_fill, (int, float)) else -999.0
        param_meta = _as_map(doc.get("parameters"))
        raw_feats = doc.get("features")
        features_raw: list[object] = raw_feats if isinstance(raw_feats, list) else [doc]

        total_obs, excluded = 0, 0
        for feat in features_raw:
            props = _as_map(_as_map(feat).get("properties"))
            param_map = _as_map(props.get("parameter"))
            for series in param_map.values():
                if isinstance(series, Mapping):
                    for val in series.values():
                        total_obs += 1
                        if isinstance(val, (int, float)) and math.isclose(float(val), fill_val):
                            excluded += 1

        variables: dict[str, VariableSpec] = {}
        dims = ("time",) if req.mode == "point" else ("point", "time")
        for p_name in req.parameters:
            default_unit, native_res, src_prod, semantics = _POWER_META.get(
                p_name, ("1", "unknown", "NASA POWER", "continuous_intensive")
            )
            api_info = _as_map(param_meta.get(p_name))
            raw_unit = api_info.get("units")
            unit = raw_unit if isinstance(raw_unit, str) else default_unit
            variables[p_name] = VariableSpec(
                name=p_name,
                units=unit,
                dtype="float32",
                dimensions=dims,
                semantics=semantics,
                nodata=fill_val,
                attributes={"native_resolution_deg": native_res, "source_product": src_prod},
            )

        t_start = datetime(
            req.start_date.year, req.start_date.month, req.start_date.day, tzinfo=UTC
        )
        t_end = datetime(
            req.end_date.year, req.end_date.month, req.end_date.day, tzinfo=UTC
        ) + timedelta(days=1)
        valid_frac = (total_obs - excluded) / total_obs if total_obs > 0 else None
        bounds = (
            None
            if req.mode == "point"
            else SpatialBounds(
                float(req.min_lon or 0.0),
                float(req.min_lat or 0.0),
                float(req.max_lon or 0.0),
                float(req.max_lat or 0.0),
            )
        )
        spatial = SpatialMetadata(
            representation="point" if req.mode == "point" else "grid_series",
            crs="EPSG:4326",
            bounds=bounds,
            point_count=1 if req.mode == "point" else len(features_raw),
        )
        api_ver = str(_as_map(header.get("api")).get("version", "v2"))
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=f"nasa_power_{req.mode}_{req.start_date:%Y%m%d}_{req.end_date:%Y%m%d}",
            provider=self.provider,
            product=req.product,
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=spatial,
            temporal_metadata=TemporalSpec(t_start, t_end, req.temporal, "interval"),
            quality_metadata=QualityMetadata(
                qa_policy="nasa_power_fill_exclusion",
                valid_observation_fraction=valid_frac,
                excluded_count=excluded,
                exclusion_reasons=(f"fill_value == {fill_val}",) if excluded else (),
            ),
            assets=(asset,),
            provenance=build_provenance(self.provider, req.product, api_ver, final_url),
            extensions={"point_count": spatial.point_count, "mode": req.mode},
        )
