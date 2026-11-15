"""HTTP client adapter calling Geospatial Harmonization Service over HTTP."""

from typing import Any

import httpx

from terra.modules.data_sources.domain.exceptions import (
    DataSourcesGhsError,
    DataSourcesNotFoundError,
    DataSourcesValidationError,
)


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, str):
                return detail
            if detail is not None:
                return str(detail)
    except ValueError:
        pass
    text = response.text.strip()
    return text[:300] if text else f"HTTP {response.status_code}"


class HttpxGhsServiceClient:
    """Async httpx client implementing GhsServiceClient under ADR-0002 boundaries."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout_override: float | None = None,
        treat_404_as_not_found: bool = False,
    ) -> Any:
        timeout = timeout_override if timeout_override is not None else self._timeout
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=timeout) as client:
                response = await client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise DataSourcesGhsError(
                "Geospatial Harmonization Service request timed out.",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            raise DataSourcesGhsError(
                "Geospatial Harmonization Service is unreachable.",
                status_code=503,
            ) from exc

        if response.status_code == 404 and treat_404_as_not_found:
            raise DataSourcesNotFoundError(_extract_error_detail(response))
        if response.status_code in {400, 422}:
            raise DataSourcesValidationError(_extract_error_detail(response))
        if 400 <= response.status_code < 500:
            raise DataSourcesGhsError(
                _extract_error_detail(response),
                status_code=response.status_code,
            )
        if response.status_code >= 500:
            raise DataSourcesGhsError(
                f"GHS upstream error ({response.status_code}): {_extract_error_detail(response)}",
                status_code=502,
            )

        return response.json()

    async def list_providers(self) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", "/api/v1/providers")
        if not isinstance(payload, list):
            raise DataSourcesGhsError("Unexpected response format from GHS /providers.")
        return payload

    async def discover_observations(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            "/api/v1/discover",
            json_body=payload,
            timeout_override=max(self._timeout, 45.0),
        )
        if not isinstance(result, dict):
            raise DataSourcesGhsError("Unexpected response format from GHS /discover.")
        return result

    async def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._request_json("POST", "/api/v1/jobs", json_body=payload)
        if not isinstance(result, dict):
            raise DataSourcesGhsError("Unexpected response format from GHS /jobs.")
        return result

    async def run_harmonize_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._request_json(
            "POST",
            "/api/v1/harmonize",
            json_body=payload,
            timeout_override=max(self._timeout, 120.0),
        )
        if not isinstance(result, dict):
            raise DataSourcesGhsError("Unexpected response format from GHS /harmonize.")
        return result

    async def get_job(self, job_id: str) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            f"/api/v1/jobs/{job_id}",
            treat_404_as_not_found=True,
        )
        if not isinstance(result, dict):
            raise DataSourcesGhsError("Unexpected response format from GHS /jobs/{job_id}.")
        return result

    async def list_datasets(
        self,
        *,
        provider: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if provider:
            params["provider"] = provider
        result = await self._request_json("GET", "/api/v1/datasets", params=params)
        if not isinstance(result, list):
            raise DataSourcesGhsError("Unexpected response format from GHS /datasets.")
        return result

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            f"/api/v1/datasets/{dataset_id}",
            treat_404_as_not_found=True,
        )
        if not isinstance(result, dict):
            raise DataSourcesGhsError("Unexpected response format from GHS /datasets/{dataset_id}.")
        return result
