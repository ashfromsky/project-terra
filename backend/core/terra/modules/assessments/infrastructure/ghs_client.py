"""HTTP client fetching prepared datasets and raster assets from GHS."""

import asyncio
import os
import re
import tempfile
from pathlib import Path, PurePosixPath

import httpx
from terra_scientific.adapters.ghs import map_ghs_dataset_payload
from terra_scientific.domain.exceptions import ScientificCoreError
from terra_scientific.domain.models.dataset import ScientificDataset

from terra.config import Settings
from terra.modules.assessments.domain.exceptions import GhsIntegrationError

_VALID_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_RETRYABLE_STATUS_CODES = {502, 503, 504}
_MAX_GET_ATTEMPTS = 3


def _safe_filename(candidate: str | None, fallback: str) -> str:
    if not candidate:
        return fallback
    name = PurePosixPath(candidate.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        return fallback
    return name


class HttpxGhsDatasetClient:
    """Async httpx adapter implementing GhsDatasetClient against GHS HTTP API."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.ghs_base_url.rstrip("/")
        self._timeout = settings.ghs_timeout_seconds
        self._transport = transport

    async def _get_with_retry(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        timeout_override: float | None = None,
    ) -> httpx.Response:
        timeout = timeout_override if timeout_override is not None else self._timeout
        last_exc: httpx.HTTPError | None = None
        for attempt in range(1, _MAX_GET_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.get(path, params=params)
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_GET_ATTEMPTS:
                    await asyncio.sleep(0.2 * attempt)
                    continue
                return response
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < _MAX_GET_ATTEMPTS:
                    await asyncio.sleep(0.2 * attempt)
                    continue
                raise GhsIntegrationError(
                    f"Failed to contact GHS service at '{path}': {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise GhsIntegrationError(
                    f"Failed to contact GHS service at '{path}': {exc}"
                ) from exc
        raise GhsIntegrationError(f"Failed to contact GHS service at '{path}': {last_exc}")

    async def fetch_dataset(self, dataset_id: str) -> ScientificDataset:
        """Fetch GET /api/v1/datasets/{dataset_id} and map to ScientificDataset."""
        cleaned = dataset_id.strip()
        if not _VALID_DATASET_ID_RE.fullmatch(cleaned):
            raise GhsIntegrationError(f"Invalid GHS dataset identifier: '{dataset_id}'")

        response = await self._get_with_retry(f"/api/v1/datasets/{cleaned}")

        if response.status_code >= 400:
            raise GhsIntegrationError(
                f"GHS service returned HTTP {response.status_code} for dataset '{cleaned}'"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise GhsIntegrationError(
                f"GHS dataset '{cleaned}' returned non-JSON response"
            ) from exc

        if not isinstance(payload, dict):
            raise GhsIntegrationError(f"GHS dataset '{cleaned}' payload must be a JSON object")

        try:
            return map_ghs_dataset_payload(payload)
        except (ScientificCoreError, TypeError, ValueError, KeyError) as exc:
            raise GhsIntegrationError(
                f"GHS dataset '{cleaned}' failed Scientific Core mapping: {exc}"
            ) from exc

    async def download_dataset_asset(
        self,
        dataset_id: str,
        dest_dir: Path,
        *,
        asset_id: str | None = None,
        filename_hint: str | None = None,
    ) -> Path:
        """Download a prepared dataset raster asset from GHS into dest_dir atomically."""
        cleaned = dataset_id.strip()
        if not _VALID_DATASET_ID_RE.fullmatch(cleaned):
            raise GhsIntegrationError(f"Invalid GHS dataset identifier: '{dataset_id}'")

        params = {"asset_id": asset_id} if asset_id else None
        response = await self._get_with_retry(
            f"/api/v1/datasets/{cleaned}/asset-content",
            params=params,
            timeout_override=max(self._timeout, 120.0),
        )
        if response.status_code >= 400:
            raise GhsIntegrationError(
                f"GHS returned HTTP {response.status_code} downloading asset for '{cleaned}'"
            )

        dest_dir.mkdir(parents=True, exist_ok=True)
        resolved_dir = dest_dir.resolve()
        filename = _safe_filename(filename_hint, f"{cleaned}.tif")
        target = (resolved_dir / filename).resolve()
        if not target.is_relative_to(resolved_dir):
            raise GhsIntegrationError(f"Unsafe asset filename derived for dataset '{cleaned}'")

        fd, tmp_name = tempfile.mkstemp(prefix=".ghs-asset-", dir=resolved_dir)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(response.content)
            os.replace(tmp_path, target)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        return target

    async def publish_derived_dataset(self, payload: dict[str, object]) -> dict[str, object]:
        """Persist a derived or AOI-scoped spatial artifact in GHS."""
        try:
            timeout_cfg = httpx.Timeout(self._timeout, connect=min(self._timeout, 2.0))
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=timeout_cfg,
                transport=self._transport,
            ) as client:
                response = await client.post("/api/v1/datasets/derived", json=payload)
        except httpx.HTTPError as exc:
            raise GhsIntegrationError(
                f"Failed to contact GHS service to publish derived dataset: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise GhsIntegrationError(
                f"GHS service returned HTTP {response.status_code} publishing derived dataset"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise GhsIntegrationError("GHS derived dataset endpoint returned non-JSON") from exc

        if not isinstance(data, dict):
            raise GhsIntegrationError("GHS derived dataset response must be a JSON object")
        return data
