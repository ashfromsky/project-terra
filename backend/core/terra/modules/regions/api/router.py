"""Regions REST API endpoints under ``/api/v1/regions``."""

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from terra.api.dependencies import DbSessionDep
from terra.modules.auth.api.dependencies import CurrentUserDep
from terra.modules.regions.api.schemas import (
    RegionCreateRequest,
    RegionGeometryResponse,
    RegionResponse,
    RegionStatisticsResponse,
    RegionUpdateGeometryRequest,
    RegionUpdateMetadataRequest,
)
from terra.modules.regions.application.services import RegionService
from terra.modules.regions.domain.exceptions import (
    InvalidGeometryError,
    RegionAccessDeniedError,
    RegionDomainError,
    RegionNotFoundError,
)
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository

router = APIRouter(prefix="/regions", tags=["regions"])

_ERROR_STATUS: dict[type[RegionDomainError], int] = {
    InvalidGeometryError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    RegionNotFoundError: status.HTTP_404_NOT_FOUND,
    RegionAccessDeniedError: status.HTTP_403_FORBIDDEN,
}


def get_region_service(session: DbSessionDep) -> RegionService:
    """Provide RegionService wired with the SQLAlchemy RegionRepository."""
    return RegionService(SqlAlchemyRegionRepository(session))


RegionServiceDep = Annotated[RegionService, Depends(get_region_service)]


def _raise_http(exc: RegionDomainError) -> NoReturn:
    code = _ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=code, detail=str(exc))


@router.post("", response_model=RegionResponse, status_code=status.HTTP_201_CREATED)
async def create_region(
    body: RegionCreateRequest, current_user: CurrentUserDep, service: RegionServiceDep
) -> RegionResponse:
    """Create a new geographic territory for the authenticated user."""
    try:
        region = await service.create_region(
            owner_id=current_user.id,
            name=body.name,
            description=body.description,
            role=body.role,
            shape_type=body.shape_type,
            iso_a3=body.iso_a3,
            geometry=body.geometry,
        )
    except RegionDomainError as exc:
        _raise_http(exc)
    return RegionResponse.from_domain(region)


@router.get("", response_model=list[RegionResponse])
async def list_regions(
    current_user: CurrentUserDep, service: RegionServiceDep
) -> list[RegionResponse]:
    """List all geographic territories owned by the authenticated user."""
    return [RegionResponse.from_domain(r) for r in await service.list_regions(current_user.id)]


@router.get("/{region_id}", response_model=RegionResponse)
async def get_region(
    region_id: UUID, current_user: CurrentUserDep, service: RegionServiceDep
) -> RegionResponse:
    """Retrieve a single geographic territory."""
    try:
        return RegionResponse.from_domain(await service.get_region(region_id, current_user.id))
    except RegionDomainError as exc:
        _raise_http(exc)


@router.patch("/{region_id}", response_model=RegionResponse)
async def update_region_metadata(
    region_id: UUID,
    body: RegionUpdateMetadataRequest,
    current_user: CurrentUserDep,
    service: RegionServiceDep,
) -> RegionResponse:
    """Update region metadata fields without modifying geometry."""
    try:
        region = await service.update_metadata(
            region_id, current_user.id, **body.model_dump(exclude_unset=True)
        )
    except RegionDomainError as exc:
        _raise_http(exc)
    return RegionResponse.from_domain(region)


@router.delete("/{region_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_region(
    region_id: UUID, current_user: CurrentUserDep, service: RegionServiceDep
) -> Response:
    """Delete a geographic territory owned by the authenticated user."""
    try:
        await service.delete_region(region_id, current_user.id)
    except RegionDomainError as exc:
        _raise_http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{region_id}/geometry", response_model=RegionGeometryResponse)
async def get_region_geometry(
    region_id: UUID, current_user: CurrentUserDep, service: RegionServiceDep
) -> RegionGeometryResponse:
    """Return the region boundary as an EPSG:4326 GeoJSON Feature."""
    try:
        return RegionGeometryResponse.from_domain(
            await service.get_region(region_id, current_user.id)
        )
    except RegionDomainError as exc:
        _raise_http(exc)


@router.put("/{region_id}/geometry", response_model=RegionResponse)
async def update_region_geometry(
    region_id: UUID,
    body: RegionUpdateGeometryRequest,
    current_user: CurrentUserDep,
    service: RegionServiceDep,
) -> RegionResponse:
    """Replace region geometry and recompute WGS 84 spatial metrics."""
    try:
        region = await service.update_geometry(
            region_id, current_user.id, geometry=body.geometry, shape_type=body.shape_type
        )
    except RegionDomainError as exc:
        _raise_http(exc)
    return RegionResponse.from_domain(region)


@router.get("/{region_id}/statistics", response_model=RegionStatisticsResponse)
async def get_region_statistics(
    region_id: UUID, current_user: CurrentUserDep, service: RegionServiceDep
) -> RegionStatisticsResponse:
    """Return computed geometric metrics and environmental statistics availability."""
    try:
        return RegionStatisticsResponse.from_domain(
            await service.get_statistics(region_id, current_user.id)
        )
    except RegionDomainError as exc:
        _raise_http(exc)
