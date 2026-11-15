"""Layers catalog REST API endpoints under ``/api/v1/layers``."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from terra.config import get_settings
from terra.modules.layers.api.schemas import (
    LayerDefinitionResponse,
    LayerLegendResponse,
    LayerMetadataResponse,
    LayerPointInspectionResponse,
    TemporalCoverageResponse,
)
from terra.modules.layers.application.services import LayerCatalogService
from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    MapLayerGroupId,
)
from terra.modules.layers.domain.exceptions import (
    LayerDatasetUnavailableError,
    LayerNotFoundError,
    LayerRasterProxyError,
)
from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository

router = APIRouter(prefix="/layers", tags=["layers"])


def get_layer_service() -> LayerCatalogService:
    """Provide LayerCatalogService wired with static catalog and configured GHS base URL."""
    settings = get_settings()
    return LayerCatalogService(
        StaticLayerCatalogRepository(),
        ghs_base_url=settings.ghs_base_url,
        ghs_timeout_seconds=settings.ghs_timeout_seconds,
    )


LayerServiceDep = Annotated[LayerCatalogService, Depends(get_layer_service)]


async def _load_layer_or_404(layer_id: str, service: LayerCatalogService) -> LayerDefinition:
    try:
        return await service.get_layer(layer_id)
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("", response_model=list[LayerDefinitionResponse])
async def list_layers(
    service: LayerServiceDep,
    group_id: Annotated[MapLayerGroupId | None, Query(alias="groupId")] = None,
    availability_status: Annotated[
        DataAvailabilityStatus | None, Query(alias="availabilityStatus")
    ] = None,
) -> list[LayerDefinitionResponse]:
    """List available environmental map layers with optional group and status filters."""
    layers = await service.list_layers(
        group_id=group_id,
        availability_status=availability_status,
    )
    return [LayerDefinitionResponse.model_validate(layer) for layer in layers]


@router.get("/{layer_id}", response_model=LayerDefinitionResponse)
async def get_layer(layer_id: str, service: LayerServiceDep) -> LayerDefinitionResponse:
    """Return the complete catalog definition for a layer."""
    layer = await _load_layer_or_404(layer_id, service)
    return LayerDefinitionResponse.model_validate(layer)


@router.get("/{layer_id}/metadata", response_model=LayerMetadataResponse)
async def get_layer_metadata(layer_id: str, service: LayerServiceDep) -> LayerMetadataResponse:
    """Return spatial/temporal resolution, units, QA policy, and source provenance."""
    layer = await _load_layer_or_404(layer_id, service)
    return LayerMetadataResponse.model_validate(layer)


@router.get("/{layer_id}/legend", response_model=LayerLegendResponse)
async def get_layer_legend(layer_id: str, service: LayerServiceDep) -> LayerLegendResponse:
    """Return color stops, labels, CSS gradient, and value range for a layer legend."""
    try:
        layer, legend = await service.get_legend(layer_id)
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return LayerLegendResponse.from_domain(layer, legend)


@router.get("/{layer_id}/coverage", response_model=TemporalCoverageResponse)
async def get_layer_coverage(layer_id: str, service: LayerServiceDep) -> TemporalCoverageResponse:
    """Return temporal archive bounds and live ingested data availability for a layer."""
    try:
        coverage = await service.get_coverage(layer_id)
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TemporalCoverageResponse.from_domain(layer_id, coverage)


@router.get(
    "/{layer_id}/tiles/{z}/{x}/{y}.png",
    responses={200: {"content": {"image/png": {}}}},
)
async def get_layer_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    service: LayerServiceDep,
    timestamp: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    dataset_id: Annotated[str | None, Query(alias="datasetId")] = None,
) -> Response:
    """Serve an XYZ RGBA PNG raster tile proxied from the active GHS raster dataset."""
    if z < 0 or z > 22:
        raise HTTPException(status_code=422, detail="Zoom level z must be between 0 and 22")
    max_tile = 2**z
    if x < 0 or x >= max_tile or y < 0 or y >= max_tile:
        raise HTTPException(status_code=422, detail="Tile coordinates out of range for zoom level")
    try:
        png_bytes = await service.render_layer_tile(
            layer_id,
            z,
            x,
            y,
            timestamp=timestamp,
            vmin=vmin,
            vmax=vmax,
            dataset_id=dataset_id,
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


@router.get("/{layer_id}/tilejson.json")
async def get_layer_tilejson(
    layer_id: str,
    service: LayerServiceDep,
    timestamp: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> dict[str, Any]:
    """Return TileJSON 2.2.0 metadata for this layer."""
    layer = await _load_layer_or_404(layer_id, service)
    bounds = list(layer.dataset_bbox) if layer.dataset_bbox else [-180.0, -90.0, 180.0, 90.0]
    center_lon = (bounds[0] + bounds[2]) / 2.0
    center_lat = (bounds[1] + bounds[3]) / 2.0

    tile_url = f"/api/v1/layers/{layer_id}/tiles/{{z}}/{{x}}/{{y}}.png"
    query_parts: list[str] = []
    if timestamp:
        query_parts.append(f"timestamp={timestamp}")
    if vmin is not None:
        query_parts.append(f"vmin={vmin}")
    if vmax is not None:
        query_parts.append(f"vmax={vmax}")
    if query_parts:
        tile_url += "?" + "&".join(query_parts)

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


@router.get(
    "/{layer_id}/render.png",
    responses={200: {"content": {"image/png": {}}}},
)
async def get_layer_render_png(
    layer_id: str,
    bbox: str,
    service: LayerServiceDep,
    crs: str = "EPSG:4326",
    width: int = 512,
    height: int = 512,
    timestamp: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    dataset_id: Annotated[str | None, Query(alias="datasetId")] = None,
) -> Response:
    """Serve a bounded RGBA PNG raster image proxied from the active GHS raster dataset."""
    parts = [part.strip() for part in bbox.split(",")]
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must contain 4 comma-separated floats")
    try:
        min_x, min_y, max_x, max_y = (float(p) for p in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="bbox coordinates must be valid numbers"
        ) from exc
    if min_x >= max_x or min_y >= max_y:
        raise HTTPException(
            status_code=422, detail="bbox min bounds must be strictly less than max bounds"
        )
    if width < 1 or width > 2048 or height < 1 or height > 2048:
        raise HTTPException(status_code=422, detail="width and height must be between 1 and 2048")
    try:
        png_bytes = await service.render_layer_image(
            layer_id,
            bbox,
            crs=crs,
            width=width,
            height=height,
            timestamp=timestamp,
            vmin=vmin,
            vmax=vmax,
            dataset_id=dataset_id,
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


@router.get("/{layer_id}/point", response_model=LayerPointInspectionResponse)
async def inspect_layer_point(
    layer_id: str,
    lon: float,
    lat: float,
    service: LayerServiceDep,
    timestamp: str | None = None,
    dataset_id: Annotated[str | None, Query(alias="datasetId")] = None,
) -> LayerPointInspectionResponse:
    """Return exact native-grid pixel inspection and QA metadata at WGS 84 (lon, lat)."""
    if lon < -180.0 or lon > 180.0 or lat < -90.0 or lat > 90.0:
        raise HTTPException(status_code=422, detail="lon/lat coordinates out of WGS 84 bounds")
    try:
        payload = await service.inspect_layer_point(
            layer_id,
            lon,
            lat,
            timestamp=timestamp,
            dataset_id=dataset_id,
        )
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LayerRasterProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return LayerPointInspectionResponse.model_validate(payload)
