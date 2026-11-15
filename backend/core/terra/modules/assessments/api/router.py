"""HTTP routes exposing Scientific Core assessments and method catalog."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from terra.modules.assessments.api.dependencies import AssessmentServiceDep
from terra.modules.assessments.api.schemas import (
    AssessmentComparisonResponse,
    AssessmentDetailResponse,
    AssessmentSummaryResponse,
    CompareAssessmentsRequest,
    CreateAssessmentRequest,
    MethodCatalogItemResponse,
    VariableComparisonSummary,
)
from terra.modules.assessments.domain.exceptions import (
    AssessmentAccessDeniedError,
    AssessmentDomainError,
    AssessmentNotFoundError,
    AssessmentRegionAccessDeniedError,
    AssessmentRegionNotFoundError,
    AssessmentValidationError,
    GhsIntegrationError,
)
from terra.modules.auth.api.dependencies import CurrentUserDep

router = APIRouter(prefix="/assessments", tags=["assessments"])


def _translate_domain_error(exc: AssessmentDomainError) -> HTTPException:
    if isinstance(exc, AssessmentValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    if isinstance(exc, (AssessmentNotFoundError, AssessmentRegionNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (AssessmentAccessDeniedError, AssessmentRegionAccessDeniedError)):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, GhsIntegrationError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/methods", response_model=list[MethodCatalogItemResponse])
def list_scientific_methods(service: AssessmentServiceDep) -> list[MethodCatalogItemResponse]:
    """List cataloged P0/P1 implemented methods and explicitly deferred P2 methods."""
    return [MethodCatalogItemResponse.from_spec(spec) for spec in service.list_methods()]


@router.post("", response_model=AssessmentDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_assessment(
    payload: CreateAssessmentRequest,
    user: CurrentUserDep,
    service: AssessmentServiceDep,
) -> AssessmentDetailResponse:
    """Create and optionally execute a reproducible Scientific Assessment."""
    try:
        assessment = await service.create_assessment(
            owner_id=user.id,
            title=payload.title,
            region_id=payload.region_id,
            execute_now=payload.execute_now,
            request_config=payload.request_config,
            ghs_dataset_ids=payload.ghs_dataset_ids,
            inline_datasets=payload.inline_datasets,
        )
    except AssessmentDomainError as exc:
        raise _translate_domain_error(exc) from exc
    return AssessmentDetailResponse.from_domain_detail(assessment)


@router.get("", response_model=list[AssessmentSummaryResponse])
async def list_assessments(
    user: CurrentUserDep,
    service: AssessmentServiceDep,
) -> list[AssessmentSummaryResponse]:
    """List scientific assessments owned by the authenticated user."""
    items = await service.list_assessments(user.id)
    return [AssessmentSummaryResponse.from_domain(item) for item in items]


@router.get("/{assessment_id}", response_model=AssessmentDetailResponse)
async def get_assessment(
    assessment_id: UUID,
    user: CurrentUserDep,
    service: AssessmentServiceDep,
) -> AssessmentDetailResponse:
    """Get a single Scientific Assessment and its full results."""
    try:
        assessment = await service.get_assessment(user.id, assessment_id)
    except AssessmentDomainError as exc:
        raise _translate_domain_error(exc) from exc
    return AssessmentDetailResponse.from_domain_detail(assessment)


@router.post("/{assessment_id}/execute", response_model=AssessmentDetailResponse)
async def execute_assessment(
    assessment_id: UUID,
    user: CurrentUserDep,
    service: AssessmentServiceDep,
) -> AssessmentDetailResponse:
    """Execute a queued or failed Scientific Assessment on demand."""
    try:
        assessment = await service.execute_assessment(user.id, assessment_id)
    except AssessmentDomainError as exc:
        raise _translate_domain_error(exc) from exc
    return AssessmentDetailResponse.from_domain_detail(assessment)


@router.post("/compare", response_model=AssessmentComparisonResponse)
async def compare_assessments(
    body: CompareAssessmentsRequest,
    user: CurrentUserDep,
    service: AssessmentServiceDep,
) -> AssessmentComparisonResponse:
    """Compare two completed Scientific Assessments owned by the current user."""
    try:
        bundle = await service.compare_assessments(
            user.id,
            body.primary_assessment_id,
            body.comparison_assessment_id,
        )
    except AssessmentDomainError as exc:
        raise _translate_domain_error(exc) from exc
    return AssessmentComparisonResponse(
        primary=AssessmentDetailResponse.from_domain_detail(bundle.primary),
        comparison=AssessmentDetailResponse.from_domain_detail(bundle.comparison),
        shared_variables=bundle.shared_variables,
        primary_only_variables=bundle.primary_only_variables,
        comparison_only_variables=bundle.comparison_only_variables,
        variable_comparisons=[
            VariableComparisonSummary.model_validate(item) for item in bundle.variable_comparisons
        ],
        compatibility_warnings=bundle.compatibility_warnings,
        methodology_notes=bundle.methodology_notes,
    )
