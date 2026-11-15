"""HTTP routes exposing satellite observation discovery, ingestion, and datasets."""

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from terra.modules.auth.api.dependencies import CurrentUserDep
from terra.modules.data_sources.api.dependencies import DataSourcesServiceDep
from terra.modules.data_sources.api.schemas import (
    AutoProvisionRequest,
    AutoProvisionResponse,
    DatasetAssetDownloadUrlResponse,
    DiscoverObservationsRequest,
    DiscoverObservationsResponse,
    IngestionOperationResponse,
    PreparedDatasetSummaryResponse,
    ProviderStatusResponse,
    StartIngestionRequest,
)
from terra.modules.data_sources.domain.exceptions import (
    DataSourcesAccessDeniedError,
    DataSourcesDomainError,
    DataSourcesGhsError,
    DataSourcesNotFoundError,
    DataSourcesValidationError,
)

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


def _raise_http(exc: DataSourcesDomainError) -> NoReturn:
    if isinstance(exc, DataSourcesValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, DataSourcesNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, DataSourcesAccessDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, DataSourcesGhsError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(exc),
    ) from exc


@router.get("/providers", response_model=list[ProviderStatusResponse])
async def list_providers(
    service: DataSourcesServiceDep,
) -> list[ProviderStatusResponse]:
    """List registered GHS environmental data providers and their capability metadata."""
    try:
        providers = await service.list_providers()
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return [ProviderStatusResponse.model_validate(item) for item in providers]


@router.post("/discover", response_model=DiscoverObservationsResponse)
async def discover_observations(
    body: DiscoverObservationsRequest,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
) -> DiscoverObservationsResponse:
    """Discover real satellite granules or station series for an AOI and time window."""
    try:
        result = await service.discover_observations(
            user.id,
            provider=body.provider,
            product=body.product,
            region_id=body.region_id,
            bbox=body.bbox,
            start_time=body.start_time,
            end_time=body.end_time,
            limit=body.limit,
        )
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return DiscoverObservationsResponse.model_validate(result)


@router.post(
    "/ingestions",
    response_model=IngestionOperationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_ingestion(
    body: StartIngestionRequest,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
) -> IngestionOperationResponse:
    """Launch a bounded GHS multi-observation ingestion job for an AOI."""
    try:
        record = await service.start_ingestion(
            user.id,
            provider=body.provider,
            product=body.product,
            region_id=body.region_id,
            bbox=body.bbox,
            start_time=body.start_time,
            end_time=body.end_time,
            max_granules=body.max_granules,
            variables=body.variables,
            target_cadence=body.target_cadence,
            target_aggregation=body.target_aggregation,
            run_type=body.run_type,
            overpass=body.overpass,
            parameters=body.parameters,
            community=body.community,
            execute_now=body.execute_now,
            idempotency_key=body.idempotency_key,
        )
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return IngestionOperationResponse.from_domain(record)


@router.get("/ingestions", response_model=list[IngestionOperationResponse])
async def list_ingestions(
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
) -> list[IngestionOperationResponse]:
    """List persisted user ingestion operations synced with current GHS job status."""
    try:
        records = await service.list_ingestions(user.id)
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return [IngestionOperationResponse.from_domain(item) for item in records]


@router.get("/ingestions/{operation_id}", response_model=IngestionOperationResponse)
async def get_ingestion(
    operation_id: UUID,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
) -> IngestionOperationResponse:
    """Get detailed status and dataset summary for one ingestion operation."""
    try:
        record = await service.get_ingestion(user.id, operation_id)
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return IngestionOperationResponse.from_domain(record)


@router.get("/datasets", response_model=list[PreparedDatasetSummaryResponse])
async def list_prepared_datasets(
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
    provider: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[PreparedDatasetSummaryResponse]:
    """List harmonized datasets persisted in GHS with Core lineage annotations."""
    try:
        datasets = await service.list_datasets(user.id, provider=provider, limit=limit)
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return [PreparedDatasetSummaryResponse.model_validate(item) for item in datasets]


@router.get("/datasets/{dataset_id}", response_model=PreparedDatasetSummaryResponse)
async def get_prepared_dataset(
    dataset_id: str,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
) -> PreparedDatasetSummaryResponse:
    """Inspect metadata, provenance, quality summary, and series preview for one GHS dataset."""
    try:
        dataset = await service.get_dataset(user.id, dataset_id)
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return PreparedDatasetSummaryResponse.model_validate(dataset)


@router.get("/datasets/{dataset_id}/download-url", response_model=DatasetAssetDownloadUrlResponse)
async def get_prepared_dataset_download_url(
    dataset_id: str,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
    asset_id: str | None = Query(default=None),
    expires_in: int | None = Query(default=None, ge=30, le=3600),
) -> DatasetAssetDownloadUrlResponse:
    """Resolve a direct presigned R2 URL (when enabled) or authenticated Core download endpoint."""
    try:
        info = await service.get_dataset_download_url(
            user.id,
            dataset_id,
            asset_id=asset_id,
            expires_in=expires_in,
        )
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return DatasetAssetDownloadUrlResponse.model_validate(info)


@router.get("/datasets/{dataset_id}/download")
async def download_prepared_dataset_asset(
    dataset_id: str,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
    asset_id: str | None = Query(default=None),
) -> Response:
    """Stream the primary harmonized GeoTIFF/JSON asset from GHS/R2 via Core authentication."""
    try:
        content, media_type, filename = await service.download_dataset_asset(
            user.id,
            dataset_id,
            asset_id=asset_id,
        )
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


@router.post("/provision", response_model=AutoProvisionResponse)
async def auto_provision_datasets(
    payload: AutoProvisionRequest,
    user: CurrentUserDep,
    service: DataSourcesServiceDep,
) -> AutoProvisionResponse:
    """Adaptively resolve, ingest, and evaluate real datasets for an AOI and analysis window."""
    try:
        outcome = await service.auto_provision(
            user.id,
            region_id=payload.region_id,
            bbox=payload.bbox,
            analysis_start=payload.analysis_start,
            analysis_end=payload.analysis_end,
            target_cadence=payload.target_cadence,
            baseline_type=payload.baseline_type,
            reference_start=payload.reference_start,
            reference_end=payload.reference_end,
            min_reference_years=payload.min_reference_years,
            qa_level=payload.qa_level,
            existing_dataset_ids=payload.existing_dataset_ids,
            desired_domains=payload.desired_domains,
            max_granules_per_product=payload.max_granules_per_product,
        )
    except DataSourcesDomainError as exc:
        _raise_http(exc)
    return AutoProvisionResponse.model_validate(outcome)
