"""Layers catalog REST API endpoints under ``/api/v1/layers``."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from terra.modules.layers.api.schemas import (
    LayerDefinitionResponse,
    LayerLegendResponse,
    LayerMetadataResponse,
    TemporalCoverageResponse,
)
from terra.modules.layers.application.services import LayerCatalogService
from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    MapLayerGroupId,
)
from terra.modules.layers.domain.exceptions import LayerNotFoundError
from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository

router = APIRouter(prefix="/layers", tags=["layers"])


@lru_cache(maxsize=1)
def get_layer_service() -> LayerCatalogService:
    """Provide LayerCatalogService wired with the static catalog repository."""
    return LayerCatalogService(StaticLayerCatalogRepository())


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
    """Return temporal archive bounds and nominal data availability for a layer."""
    try:
        coverage = await service.get_coverage(layer_id)
    except LayerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TemporalCoverageResponse.from_domain(layer_id, coverage)
