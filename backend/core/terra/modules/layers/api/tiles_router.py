"""Unified XYZ tile and TileJSON endpoints under ``/api/v1/tiles``."""

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from terra.modules.analytics.application.services import _METRIC_ALIASES
from terra.modules.layers.api.router import LayerServiceDep
from terra.modules.layers.domain.exceptions import (
    LayerDatasetUnavailableError,
    LayerNotFoundError,
    LayerRasterProxyError,
)

tiles_router = APIRouter(prefix="/tiles", tags=["tiles"])


def _resolve_layer_id(metric_id: str) -> str:
    return _METRIC_ALIASES.get(metric_id.lower(), metric_id)


@tiles_router.get(
    "/{metric_id}/{date}/{z}/{x}/{y}.png",
    responses={200: {"content": {"image/png": {}}}},
)
async def get_metric_tile(
    metric_id: str,
    date: str,
    z: int,
    x: int,
    y: int,
    service: LayerServiceDep,
    vmin: float | None = None,
    vmax: float | None = None,
) -> Response:
    """Serve an XYZ RGBA PNG tile for the specified metric, date, and tile coordinates."""
    if z < 0 or z > 22:
        raise HTTPException(status_code=422, detail="Zoom level z must be between 0 and 22")
    max_tile = 2**z
    if x < 0 or x >= max_tile or y < 0 or y >= max_tile:
        raise HTTPException(status_code=422, detail="Tile coordinates out of range for zoom level")

    layer_id = _resolve_layer_id(metric_id)
    try:
        png_bytes = await service.render_layer_tile(
            layer_id,
            z,
            x,
            y,
            timestamp=date,
            vmin=vmin,
            vmax=vmax,
        )
    except (LayerNotFoundError, LayerDatasetUnavailableError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LayerRasterProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@tiles_router.get("/{metric_id}/{date}/tilejson.json")
async def get_metric_tilejson(
    metric_id: str,
    date: str,
    service: LayerServiceDep,
    vmin: float | None = None,
    vmax: float | None = None,
) -> dict[str, Any]:
    """Generate TileJSON 2.2.0 metadata for the metric and date."""
    layer_id = _resolve_layer_id(metric_id)
    try:
        layer = await service.get_layer(layer_id)
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    bounds = list(layer.dataset_bbox) if layer.dataset_bbox else [-180.0, -90.0, 180.0, 90.0]
    center_lon = (bounds[0] + bounds[2]) / 2.0
    center_lat = (bounds[1] + bounds[3]) / 2.0

    tile_url = f"/api/v1/tiles/{metric_id}/{date}/{{z}}/{{x}}/{{y}}.png"
    if vmin is not None or vmax is not None:
        params: list[str] = []
        if vmin is not None:
            params.append(f"vmin={vmin}")
        if vmax is not None:
            params.append(f"vmax={vmax}")
        tile_url += "?" + "&".join(params)

    return {
        "tilejson": "2.2.0",
        "name": layer.name,
        "description": layer.description,
        "version": "1.0.0",
        "scheme": "xyz",
        "tiles": [tile_url],
        "minzoom": 0,
        "maxzoom": 18,
        "bounds": bounds,
        "center": [center_lon, center_lat, 2],
    }
