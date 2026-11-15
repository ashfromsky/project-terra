"""Shared transport, SSRF protection, and validation helpers for provider handlers."""

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from pydantic import BaseModel, ValidationError

from geospatial_harmonization import __version__
from geospatial_harmonization.domain.exceptions import (
    ObjectTooLargeError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderDisabledError,
    ProviderResponseError,
    ProviderValidationError,
    TransientTransferError,
)
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    ProvenanceRecord,
)
from geospatial_harmonization.handlers.catalog import DiscoveryResult

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_SCHEMES = frozenset({"https", "http"})
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_REDIRECT_HOPS = 8
_MAX_RETRY_AFTER_SECONDS = 30.0
_BINARY_DATA_FORMATS = frozenset({"hdf4", "hdf5", "netcdf", "geotiff", "zarr"})

EARTHDATA_ALLOWED_HOSTS = (
    "*.nasa.gov",
    "*.earthdata.nasa.gov",
    "*.earthdatacloud.nasa.gov",
    "*.eosdis.nasa.gov",
    "*.nsidc.org",
    "*.usgs.gov",
)
EARTHDATA_TOKEN_HOSTS = (
    "urs.earthdata.nasa.gov",
    "*.urs.earthdata.nasa.gov",
    "*.earthdata.nasa.gov",
    "*.earthdatacloud.nasa.gov",
    "*.eosdis.nasa.gov",
)
DEFAULT_PRESIGNED_HOSTS = (
    "*.cloudfront.net",
    "*.amazonaws.com",
)
_URS_HOST_PATTERNS = (
    "urs.earthdata.nasa.gov",
    "*.urs.earthdata.nasa.gov",
)


@dataclass(frozen=True, slots=True)
class CmrGranule:
    """Structured granule metadata extracted from a NASA CMR search entry."""

    granule_id: str
    producer_granule_id: str
    short_name: str
    version: str
    title: str
    data_url: str
    time_start: datetime | None = None
    time_end: datetime | None = None
    boxes: tuple[tuple[float, float, float, float], ...] = ()
    source_metadata: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.source_metadata is None:
            object.__setattr__(self, "source_metadata", {})


def parse_handler_payload[ModelT: BaseModel](
    model_cls: type[ModelT], payload: Mapping[str, object]
) -> ModelT:
    """Validate untrusted handler payload into a strict Pydantic model."""
    try:
        return model_cls.model_validate(dict(payload))
    except ValidationError as exc:
        raise ProviderValidationError(f"Invalid handler payload: {exc}") from exc


def _is_forbidden_ip(ip_str: str) -> bool:
    addr = ipaddress.ip_address(ip_str.split("%", 1)[0])
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _host_matches(host: str, allowlist: Sequence[str]) -> bool:
    h = host.lower().rstrip(".")
    for entry in allowlist:
        pattern = entry.strip().lower().rstrip(".")
        if not pattern:
            continue
        if pattern.startswith("*.") and (h == pattern[2:] or h.endswith(pattern[1:])):
            return True
        if h == pattern:
            return True
    return False


def is_urs_host(hostname: str) -> bool:
    """Return True when hostname belongs to NASA Earthdata URS login endpoints."""
    return _host_matches(hostname, _URS_HOST_PATTERNS)


def has_presigned_signature(url: str) -> bool:
    """Verify documented CloudFront or S3 presigned signature query parameters exist."""
    query = {k.lower(): v for k, v in parse_qs(urlparse(url).query).items() if v}
    if not query:
        return False
    is_s3_v4 = {"x-amz-signature", "x-amz-credential"} <= query.keys()
    is_s3_v2 = {"signature", "awsaccesskeyid", "expires"} <= query.keys()
    is_cloudfront = {"signature", "key-pair-id"} <= query.keys() and (
        "expires" in query or "policy" in query
    )
    return is_s3_v4 or is_s3_v2 or is_cloudfront


def validate_safe_url(
    url: str, *, allowed_hosts: Sequence[str] | None = None, require_https: bool = False
) -> str:
    """Reject non-HTTP schemes, allowlist violations, and private/loopback/link-local IPs."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES or (require_https and scheme != "https"):
        raise ProviderValidationError(f"Disallowed URL scheme '{parsed.scheme}'")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ProviderValidationError("URL missing valid hostname")
    if allowed_hosts is not None and not _host_matches(hostname, allowed_hosts):
        raise ProviderValidationError(f"Host '{hostname}' is not in trusted host allowlist")

    try:
        ipaddress.ip_address(hostname)
        ips = [hostname]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise TransientTransferError(f"Failed DNS resolution for '{hostname}': {exc}") from exc
        ips = [str(item[4][0]) for item in infos]
    if not ips or any(_is_forbidden_ip(ip) for ip in ips):
        raise ProviderValidationError(f"Resolved IP for '{hostname}' targets forbidden network")
    return url


def _validate_redirect_target(
    next_url: str,
    *,
    origin_url: str,
    allowed_hosts: Sequence[str] | None,
    presigned_hosts: Sequence[str] | None,
    require_https: bool,
    earthdata_auth: bool,
) -> tuple[str, bool]:
    parsed = urlparse(next_url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES or (require_https and scheme != "https"):
        raise ProviderValidationError(f"Disallowed URL scheme '{parsed.scheme}'")
    next_host = (parsed.hostname or "").strip().lower()
    if not next_host:
        raise ProviderValidationError("Redirect URL missing valid hostname")
    origin_host = (urlparse(origin_url).hostname or "").strip().lower()

    if allowed_hosts is None or _host_matches(next_host, allowed_hosts):
        validate_safe_url(next_url, allowed_hosts=allowed_hosts, require_https=require_https)
        return next_url, False

    trusted_origin = earthdata_auth or _host_matches(origin_host, EARTHDATA_ALLOWED_HOSTS)
    if (
        trusted_origin
        and presigned_hosts
        and _host_matches(next_host, presigned_hosts)
        and scheme == "https"
        and has_presigned_signature(next_url)
    ):
        validate_safe_url(next_url, allowed_hosts=None, require_https=True)
        return next_url, True

    raise ProviderValidationError(
        f"Host '{next_host}' is not in trusted host allowlist or lacks valid presigned signature"
    )


def _extract_auth_header(headers: Mapping[str, str] | None) -> tuple[str | None, dict[str, str]]:
    auth_value: str | None = None
    cleaned: dict[str, str] = {}
    for key, val in (headers or {}).items():
        if key.lower() == "authorization":
            auth_value = val
        elif key.lower() != "cookie":
            cleaned[key] = val
    return auth_value, cleaned


def _headers_for_url(
    target_url: str,
    *,
    origin_url: str,
    base_headers: Mapping[str, str],
    auth_value: str | None,
    earthdata_auth: bool,
    is_presigned_hop: bool,
) -> dict[str, str]:
    headers = dict(base_headers)
    if not auth_value or is_presigned_hop:
        return headers
    target_parsed = urlparse(target_url)
    origin_parsed = urlparse(origin_url)
    target_host = (target_parsed.hostname or "").lower()
    same_netloc = target_parsed.netloc.lower() == origin_parsed.netloc.lower()
    if earthdata_auth:
        if is_urs_host(target_host) or (
            same_netloc and _host_matches(target_host, EARTHDATA_TOKEN_HOSTS)
        ):
            headers["Authorization"] = auth_value
    elif same_netloc:
        headers["Authorization"] = auth_value
    return headers


def _retry_delay_seconds(
    resp: httpx.Response | None, attempt: int, backoff_seconds: float
) -> float:
    if resp is not None and (retry_after := resp.headers.get("retry-after")):
        try:
            return min(max(float(retry_after.strip()), 0.0), _MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass
    if backoff_seconds <= 0.0:
        return 0.0
    return min(backoff_seconds * (2.0**attempt), _MAX_RETRY_AFTER_SECONDS)


def _raise_for_status(url: str, status_code: int, *, detail: str | None = None) -> None:
    suffix = f" ({detail})" if detail else ""
    if status_code == 401:
        raise ProviderAuthenticationError(
            f"Authentication rejected (HTTP 401) for {url}{suffix}",
            status_code=status_code,
        )
    if status_code == 403:
        raise ProviderAuthorizationError(
            f"Authorization rejected (HTTP 403) for {url}{suffix}",
            status_code=status_code,
        )
    if status_code in _TRANSIENT_STATUS_CODES:
        raise TransientTransferError(
            f"Transient upstream HTTP {status_code} for {url}{suffix}",
            status_code=status_code,
        )
    if 400 <= status_code < 500:
        raise ProviderValidationError(
            f"Upstream rejected request with HTTP {status_code} for {url}{suffix}",
            status_code=status_code,
        )
    raise ProviderResponseError(
        f"Unexpected upstream HTTP {status_code} for {url}{suffix}",
        status_code=status_code,
    )


def _sanitize_error_snippet(body: bytes, max_chars: int = 240) -> str:
    text = body[:1024].decode("utf-8", errors="replace")
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) > max_chars:
        return collapsed[:max_chars] + "..."
    return collapsed


def _check_unexpected_html(
    url: str, media_type: str, data_format: DataFormat, preview: bytes
) -> None:
    if data_format not in _BINARY_DATA_FORMATS:
        return
    if media_type.lower() in {"text/html", "application/xhtml+xml"} or preview.lstrip().startswith(
        (b"<!DOCTYPE html", b"<html", b"<HTML")
    ):
        snippet = preview[:512].decode("utf-8", errors="replace").lower()
        if any(tok in snippet for tok in ("earthdata", "urs", "login", "authorize")):
            raise ProviderAuthenticationError(
                f"Upstream returned Earthdata HTML login response instead of {data_format} payload"
            )
        raise ProviderResponseError(
            f"Upstream returned HTML response instead of expected {data_format} payload for {url}"
        )


async def safe_fetch_bytes(
    url: str,
    *,
    allowed_hosts: Sequence[str] | None = None,
    presigned_hosts: Sequence[str] | None = DEFAULT_PRESIGNED_HOSTS,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_seconds: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
    require_https: bool = False,
    earthdata_auth: bool = False,
) -> tuple[bytes, str, str]:
    """Fetch bytes over httpx with SSRF checks, scoped auth forwarding, and bounded retries."""
    origin_url = validate_safe_url(url, allowed_hosts=allowed_hosts, require_https=require_https)
    auth_value, base_headers = _extract_auth_header(headers)
    if earthdata_auth:
        origin_host = (urlparse(origin_url).hostname or "").lower()
        if auth_value and not _host_matches(origin_host, EARTHDATA_TOKEN_HOSTS):
            auth_value = None

    current = origin_url
    is_presigned = False
    urs_hops = 0
    cookies = httpx.Cookies() if earthdata_auth else None

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport, cookies=cookies
    ) as client:
        cur_params: Mapping[str, str] | None = params
        for _ in range(_MAX_REDIRECT_HOPS):
            req_headers = _headers_for_url(
                current,
                origin_url=origin_url,
                base_headers=base_headers,
                auth_value=auth_value,
                earthdata_auth=earthdata_auth,
                is_presigned_hop=is_presigned,
            )
            if is_presigned and cookies is not None:
                client.cookies.clear()
            resp = await _request_with_retries(
                client,
                current,
                req_headers,
                cur_params,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
            )
            if resp.status_code in _REDIRECT_CODES and "location" in resp.headers:
                nxt = urljoin(current, resp.headers["location"])
                nxt, is_presigned = _validate_redirect_target(
                    nxt,
                    origin_url=origin_url,
                    allowed_hosts=allowed_hosts,
                    presigned_hosts=presigned_hosts,
                    require_https=require_https,
                    earthdata_auth=earthdata_auth,
                )
                nxt_host = (urlparse(nxt).hostname or "").lower()
                if is_urs_host(nxt_host):
                    urs_hops += 1
                    if not auth_value:
                        raise ProviderAuthenticationError(
                            "Earthdata token is required for protected granule access"
                        )
                    if urs_hops > 2:
                        raise ProviderAuthenticationError(
                            "Earthdata URS authentication loop detected; check EARTHDATA_TOKEN"
                        )
                current, cur_params = nxt, None
                continue
            if resp.status_code >= 400:
                _raise_for_status(
                    current, resp.status_code, detail=_sanitize_error_snippet(resp.content)
                )
            media = (
                resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
            )
            return resp.content, current, media or "application/octet-stream"
    raise ProviderResponseError(f"Exceeded maximum redirect hops for {url}")


async def _request_with_retries(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, str] | None,
    *,
    max_retries: int,
    backoff_seconds: float = 0.0,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code not in _TRANSIENT_STATUS_CODES or attempt == max_retries:
                if resp.status_code in _TRANSIENT_STATUS_CODES:
                    _raise_for_status(
                        url, resp.status_code, detail=_sanitize_error_snippet(resp.content)
                    )
                return resp
            delay = _retry_delay_seconds(resp, attempt, backoff_seconds)
            if delay > 0.0:
                await asyncio.sleep(delay)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == max_retries:
                raise TransientTransferError(f"HTTP transport error for {url}: {exc}") from exc
            delay = _retry_delay_seconds(None, attempt, backoff_seconds)
            if delay > 0.0:
                await asyncio.sleep(delay)
    raise TransientTransferError(f"Request failed for {url}: {last_exc}")


def write_raw_asset(
    raw_dir: Path, filename: str, data: bytes, data_format: DataFormat, media_type: str
) -> tuple[Path, AssetReference]:
    """Persist fetched raw bytes safely without mutating filename hierarchy."""
    safe_name = Path(filename).name or "asset.bin"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / safe_name
    dest.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ref = AssetReference(
        asset_id=safe_name,
        uri=dest.resolve().as_uri(),
        data_format=data_format,
        media_type=media_type,
        checksum_sha256=digest,
        size_bytes=len(data),
    )
    return dest, ref


async def safe_fetch_to_file(
    url: str,
    dest_dir: Path,
    filename: str | None = None,
    *,
    fallback_filename: str = "asset.bin",
    data_format: DataFormat = "unknown",
    allowed_hosts: Sequence[str] | None = None,
    presigned_hosts: Sequence[str] | None = DEFAULT_PRESIGNED_HOSTS,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_seconds: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
    require_https: bool = False,
    earthdata_auth: bool = False,
    max_bytes: int | None = None,
    chunk_bytes: int = 1_048_576,
) -> tuple[Path, AssetReference, str]:
    """Stream remote payload to disk with SSRF checks, presigned redirects, and SHA-256."""
    origin_url = validate_safe_url(url, allowed_hosts=allowed_hosts, require_https=require_https)
    auth_value, base_headers = _extract_auth_header(headers)
    if earthdata_auth:
        origin_host = (urlparse(origin_url).hostname or "").lower()
        if auth_value and not _host_matches(origin_host, EARTHDATA_TOKEN_HOSTS):
            auth_value = None

    dest_dir.mkdir(parents=True, exist_ok=True)
    current = origin_url
    is_presigned = False
    urs_hops = 0
    cookies = httpx.Cookies() if earthdata_auth else None

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport, cookies=cookies
    ) as client:
        cur_params: Mapping[str, str] | None = params
        for _ in range(_MAX_REDIRECT_HOPS):
            req_headers = _headers_for_url(
                current,
                origin_url=origin_url,
                base_headers=base_headers,
                auth_value=auth_value,
                earthdata_auth=earthdata_auth,
                is_presigned_hop=is_presigned,
            )
            if is_presigned and cookies is not None:
                client.cookies.clear()
            redirect_target: str | None = None
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                tmp_path = dest_dir / f".ghs-tmp-{uuid.uuid4().hex[:12]}.part"
                try:
                    async with client.stream(
                        "GET", current, headers=req_headers, params=cur_params
                    ) as resp:
                        if resp.status_code in _REDIRECT_CODES and "location" in resp.headers:
                            redirect_target = urljoin(current, resp.headers["location"])
                            break
                        if resp.status_code in _TRANSIENT_STATUS_CODES:
                            if attempt < max_retries:
                                delay = _retry_delay_seconds(resp, attempt, backoff_seconds)
                                if delay > 0.0:
                                    await asyncio.sleep(delay)
                                continue
                            snippet = await resp.aread()
                            _raise_for_status(
                                current,
                                resp.status_code,
                                detail=_sanitize_error_snippet(snippet),
                            )
                        if resp.status_code >= 400:
                            snippet = await resp.aread()
                            _raise_for_status(
                                current,
                                resp.status_code,
                                detail=_sanitize_error_snippet(snippet),
                            )

                        media = (
                            resp.headers.get("content-type", "application/octet-stream")
                            .split(";")[0]
                            .strip()
                            or "application/octet-stream"
                        )
                        if max_bytes is not None and (cl_hdr := resp.headers.get("content-length")):
                            try:
                                content_len = int(cl_hdr)
                            except ValueError:
                                content_len = -1
                            if content_len > max_bytes:
                                raise ObjectTooLargeError(
                                    f"Upstream content-length {content_len} exceeds limit "
                                    f"of {max_bytes} bytes",
                                    requested_bytes=content_len,
                                    limit_bytes=max_bytes,
                                    scope="object",
                                )

                        hasher = hashlib.sha256()
                        total = 0
                        first_chunk = b""
                        with tmp_path.open("wb") as out_f:
                            async for chunk in resp.aiter_bytes(chunk_size=chunk_bytes):
                                if not first_chunk and chunk:
                                    first_chunk = chunk[:512]
                                    _check_unexpected_html(current, media, data_format, first_chunk)
                                total += len(chunk)
                                if max_bytes is not None and total > max_bytes:
                                    raise ObjectTooLargeError(
                                        f"Download stream exceeded max limit of {max_bytes} bytes",
                                        requested_bytes=total,
                                        limit_bytes=max_bytes,
                                        scope="object",
                                    )
                                hasher.update(chunk)
                                out_f.write(chunk)

                        if not first_chunk:
                            _check_unexpected_html(current, media, data_format, b"")

                        raw_name = (
                            filename or Path(urlparse(current).path).name or fallback_filename
                        )
                        safe_name = Path(raw_name).name or fallback_filename
                        dest = dest_dir / safe_name
                        os.replace(tmp_path, dest)
                        ref = AssetReference(
                            asset_id=safe_name,
                            uri=dest.resolve().as_uri(),
                            data_format=data_format,
                            media_type=media,
                            checksum_sha256=hasher.hexdigest(),
                            size_bytes=total,
                        )
                        return dest, ref, current
                except httpx.HTTPError as exc:
                    tmp_path.unlink(missing_ok=True)
                    last_exc = exc
                    if attempt == max_retries:
                        raise TransientTransferError(
                            f"HTTP transport error for {current}: {exc}"
                        ) from exc
                    delay = _retry_delay_seconds(None, attempt, backoff_seconds)
                    if delay > 0.0:
                        await asyncio.sleep(delay)
                except BaseException:
                    tmp_path.unlink(missing_ok=True)
                    raise
                else:
                    tmp_path.unlink(missing_ok=True)

            if redirect_target is not None:
                nxt, is_presigned = _validate_redirect_target(
                    redirect_target,
                    origin_url=origin_url,
                    allowed_hosts=allowed_hosts,
                    presigned_hosts=presigned_hosts,
                    require_https=require_https,
                    earthdata_auth=earthdata_auth,
                )
                nxt_host = (urlparse(nxt).hostname or "").lower()
                if is_urs_host(nxt_host):
                    urs_hops += 1
                    if not auth_value:
                        raise ProviderAuthenticationError(
                            "Earthdata token is required for protected granule access"
                        )
                    if urs_hops > 2:
                        raise ProviderAuthenticationError(
                            "Earthdata URS authentication loop detected; check EARTHDATA_TOKEN"
                        )
                current, cur_params = nxt, None
                continue
            raise TransientTransferError(f"Request failed for {current}: {last_exc}")
    raise ProviderResponseError(f"Exceeded maximum redirect hops for {url}")


def build_provenance(
    provider: str,
    product: str,
    version: str,
    url: str,
    *,
    run_type: str | None = None,
    granule_id: str | None = None,
    source_metadata: Mapping[str, object] | None = None,
) -> ProvenanceRecord:
    """Create UTC-stamped ingestion provenance record."""
    return ProvenanceRecord(
        provider=provider,
        product=product,
        product_version=version,
        retrieved_at=datetime.now(UTC),
        software_version=__version__,
        run_type=run_type,
        source_urls=(url,),
        processing_steps=(f"ingest:{provider}:{product}",),
        granule_id=granule_id,
        source_metadata=dict(source_metadata or {}),
    )


def earthdata_hosts_for(cmr_url: str) -> tuple[str, ...]:
    """Return trusted NASA/DAAC download hosts alongside the configured CMR hostname."""
    cmr_host = (urlparse(cmr_url).hostname or "").lower()
    return (*EARTHDATA_ALLOWED_HOSTS, cmr_host) if cmr_host else EARTHDATA_ALLOWED_HOSTS


def _parse_iso_utc(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _parse_cmr_boxes(entry: Mapping[str, Any]) -> tuple[tuple[float, float, float, float], ...]:
    parsed: list[tuple[float, float, float, float]] = []
    raw_boxes = entry.get("boxes")
    if not isinstance(raw_boxes, list):
        return ()
    for item in raw_boxes:
        if not isinstance(item, str):
            continue
        parts = item.split()
        if len(parts) == 4:
            try:
                south, west, north, east = (float(p) for p in parts)
            except ValueError:
                continue
            parsed.append((west, south, east, north))
    return tuple(parsed)


def _select_granule_link(entry: Mapping[str, Any], extensions: tuple[str, ...]) -> str | None:
    links = entry.get("links")
    if not isinstance(links, list):
        return None
    fallback: str | None = None
    for link in links:
        if not isinstance(link, Mapping):
            continue
        href = str(link.get("href") or "").strip()
        if not href.startswith("https://") or not urlparse(href).path.lower().endswith(extensions):
            continue
        rel = str(link.get("rel") or "").lower()
        if rel.endswith("/data#") or rel == "data":
            return href
        if fallback is None:
            fallback = href
    return fallback


def _parse_cmr_entries(
    entries: object,
    *,
    short_name: str,
    version: str,
    extensions: tuple[str, ...],
) -> list[CmrGranule]:
    if not isinstance(entries, list):
        return []
    parsed: list[CmrGranule] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        href = _select_granule_link(entry, extensions)
        if href is None:
            continue
        concept_id = str(entry.get("id") or "").strip()
        producer_id = str(
            entry.get("producer_granule_id") or entry.get("title") or concept_id
        ).strip()
        title = str(entry.get("title") or producer_id or concept_id).strip()
        granule_id = producer_id or concept_id or Path(urlparse(href).path).name
        meta: dict[str, Any] = {
            key: entry[key]
            for key in (
                "id",
                "producer_granule_id",
                "title",
                "time_start",
                "time_end",
                "updated",
                "collection_concept_id",
                "data_center",
                "dataset_id",
            )
            if key in entry
        }
        parsed.append(
            CmrGranule(
                granule_id=granule_id,
                producer_granule_id=producer_id or granule_id,
                short_name=short_name,
                version=version,
                title=title,
                data_url=href,
                time_start=_parse_iso_utc(entry.get("time_start")),
                time_end=_parse_iso_utc(entry.get("time_end")),
                boxes=_parse_cmr_boxes(entry),
                source_metadata=meta,
            )
        )
    return parsed


def select_representative_granules(
    granules: Sequence[CmrGranule],
    max_granules: int,
    *,
    window_start: datetime | None = None,
) -> tuple[list[CmrGranule], dict[str, Any]]:
    """Select up to `max_granules` granules preserving full temporal coverage."""
    fallback_dt = window_start or datetime.min.replace(tzinfo=UTC)
    ordered = sorted(
        granules,
        key=lambda g: (g.time_start or fallback_dt, g.producer_granule_id),
    )
    deduped: list[CmrGranule] = []
    seen_keys: set[tuple[str, str]] = set()
    for item in ordered:
        key = (item.granule_id, item.data_url)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(item)

    if len(deduped) <= max_granules or max_granules <= 0:
        selected = deduped[: max(0, max_granules)]
        return selected, {
            "discovered_count": len(deduped),
            "selection_strategy": "chronological_all",
        }

    dated_groups: list[list[CmrGranule]] = []
    current_dt: datetime | None = None
    has_marker = False
    for item in deduped:
        if not has_marker or item.time_start != current_dt:
            dated_groups.append([item])
            current_dt = item.time_start
            has_marker = True
        else:
            dated_groups[-1].append(item)

    if len(dated_groups) >= 2:
        if len(dated_groups) >= max_granules:
            chosen_indices: list[int] = []
            used: set[int] = set()
            total_groups = len(dated_groups)
            if max_granules == 1:
                chosen_indices = [0]
            else:
                for step in range(max_granules):
                    idx = round(step * (total_groups - 1) / (max_granules - 1))
                    while idx in used and idx + 1 < total_groups:
                        idx += 1
                    while idx in used and idx > 0:
                        idx -= 1
                    if idx not in used:
                        used.add(idx)
                        chosen_indices.append(idx)
            chosen_indices.sort()
            selected = [dated_groups[idx][0] for idx in chosen_indices[:max_granules]]
        else:
            selected = [grp[0] for grp in dated_groups]
            extras = [g for grp in dated_groups for g in grp[1:]]
            need = max_granules - len(selected)
            if need > 0 and extras:
                selected.extend(extras[:need])
                selected.sort(key=lambda g: (g.time_start or fallback_dt, g.producer_granule_id))
        return selected, {
            "discovered_count": len(deduped),
            "selection_strategy": "uniform_temporal_stratification",
        }

    if max_granules == 1:
        return [deduped[0]], {
            "discovered_count": len(deduped),
            "selection_strategy": "uniform_temporal_stratification",
        }
    total_items = len(deduped)
    chosen_idxs: list[int] = []
    used_idx: set[int] = set()
    for step in range(max_granules):
        idx = round(step * (total_items - 1) / (max_granules - 1))
        if idx not in used_idx:
            used_idx.add(idx)
            chosen_idxs.append(idx)
    selected = [deduped[idx] for idx in sorted(chosen_idxs)]
    return selected, {
        "discovered_count": len(deduped),
        "selection_strategy": "uniform_temporal_stratification",
    }


async def discover_cmr_granules(
    cmr_url: str,
    product: str,
    window_start: datetime,
    window_end: datetime,
    extensions: tuple[str, ...],
    *,
    bbox: tuple[float, float, float, float] | None = None,
    headers: Mapping[str, str] | None = None,
    page_size: int = 10,
    max_pages: int = 10,
    stratify_target: int | None = None,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_seconds: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
    require_https: bool = True,
) -> list[CmrGranule]:
    """Query NASA CMR granules API with chronological sorting and safe pagination."""
    if "." not in product:
        raise ProviderValidationError(
            f"Product '{product}' must include short_name.version for CMR lookup"
        )
    short_name, version = product.split(".", 1)
    effective_page_size = min(max(1, page_size), 2000)
    t0 = window_start.astimezone(UTC).isoformat()
    t1 = window_end.astimezone(UTC).isoformat()

    async def _fetch_page(
        start_iso: str, end_iso: str, page_num: int, limit_size: int
    ) -> tuple[list[CmrGranule], int]:
        params = {
            "short_name": short_name,
            "version": version,
            "temporal": f"{start_iso},{end_iso}",
            "page_size": str(limit_size),
            "page_num": str(page_num),
            "sort_key[]": "+start_date",
        }
        if bbox is not None:
            params["bounding_box"] = ",".join(str(v) for v in bbox)
        raw, _, _ = await safe_fetch_bytes(
            f"{cmr_url.rstrip('/')}/granules.json",
            allowed_hosts=earthdata_hosts_for(cmr_url),
            headers=headers,
            params=params,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            transport=transport,
            require_https=require_https,
            earthdata_auth=bool(headers),
        )
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError(
                f"Malformed CMR JSON response for '{product}': {exc}"
            ) from exc
        entries = doc.get("feed", {}).get("entry", []) if isinstance(doc, Mapping) else []
        return _parse_cmr_entries(
            entries, short_name=short_name, version=version, extensions=extensions
        ), (len(entries) if isinstance(entries, list) else 0)

    results: list[CmrGranule] = []
    seen_keys: set[tuple[str, str]] = set()
    page_limit = max(1, max_pages)
    last_raw_count = 0
    for page_num in range(1, page_limit + 1):
        parsed_page, raw_count = await _fetch_page(t0, t1, page_num, effective_page_size)
        last_raw_count = raw_count
        added_on_page = 0
        for item in parsed_page:
            dedup = (item.granule_id, item.data_url)
            if dedup not in seen_keys:
                seen_keys.add(dedup)
                results.append(item)
                added_on_page += 1
        if raw_count < effective_page_size or added_on_page == 0:
            break

    total_span = window_end.astimezone(UTC) - window_start.astimezone(UTC)
    if (
        stratify_target is not None
        and last_raw_count >= effective_page_size
        and total_span > timedelta(days=30)
        and results
        and results[-1].time_end is not None
        and results[-1].time_end < window_end.astimezone(UTC) - timedelta(days=15)
    ):
        slots = max(2, min(stratify_target, 16))
        win_start_utc = window_start.astimezone(UTC)
        slice_span = min(timedelta(days=5), total_span / slots)
        per_slot = max(1, min(4, stratify_target // slots + 1))
        for slot in range(1, slots):
            offset = (total_span - slice_span) * (slot / (slots - 1))
            sub_start = win_start_utc + offset
            sub_end = min(window_end.astimezone(UTC), sub_start + slice_span)
            sub_items, _ = await _fetch_page(
                sub_start.isoformat(), sub_end.isoformat(), 1, per_slot
            )
            for item in sub_items:
                dedup = (item.granule_id, item.data_url)
                if dedup not in seen_keys:
                    seen_keys.add(dedup)
                    results.append(item)

    if not results:
        raise ProviderValidationError(f"No CMR granule download URL found for '{product}'")
    return results


async def discover_cmr_granule_url(
    cmr_url: str,
    product: str,
    window_start: datetime,
    window_end: datetime,
    extensions: tuple[str, ...],
    *,
    bbox: tuple[float, float, float, float] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_seconds: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Query NASA CMR granules API and return the first HTTPS data link matching extensions."""
    granules = await discover_cmr_granules(
        cmr_url,
        product,
        window_start,
        window_end,
        extensions,
        bbox=bbox,
        headers=headers,
        page_size=1,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        transport=transport,
        require_https=True,
    )
    return granules[0].data_url


def validate_wgs84_bbox(bbox: tuple[float, float, float, float]) -> None:
    """Validate WGS84 bounding box ordering and coordinate limits."""
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180.0 <= min_lon < max_lon <= 180.0):
        raise ProviderValidationError(
            "bbox longitudes must satisfy -180 <= min_lon < max_lon <= 180"
        )
    if not (-90.0 <= min_lat < max_lat <= 90.0):
        raise ProviderValidationError("bbox latitudes must satisfy -90 <= min_lat < max_lat <= 90")


def _safe_cmr_access_hint(data_url: str) -> str:
    parsed = urlparse(data_url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


async def discover_cmr_observations(
    *,
    enabled: bool,
    provider: str,
    product: str,
    cmr_url: str,
    token: str | None,
    extensions: tuple[str, ...],
    bbox: tuple[float, float, float, float],
    start_time: datetime,
    end_time: datetime,
    limit: int = 10,
    timeout: float = 30.0,
    max_retries: int = 2,
    backoff_seconds: float = 0.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[DiscoveryResult, ...]:
    """Shared CMR discovery workflow for Earthdata providers."""
    if not enabled:
        raise ProviderDisabledError(
            f"{provider.upper()} provider is disabled by configuration",
            provider=provider,
        )
    if end_time < start_time:
        raise ProviderValidationError("end_time cannot precede start_time", provider=provider)
    validate_wgs84_bbox(bbox)
    del token
    granules = await discover_cmr_granules(
        cmr_url,
        product,
        start_time,
        end_time,
        extensions,
        bbox=bbox,
        headers=None,
        page_size=min(max(limit * 4, 200), 2000),
        max_pages=3,
        stratify_target=limit,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        transport=transport,
        require_https=True,
    )
    selected_granules, _ = select_representative_granules(granules, limit, window_start=start_time)
    return tuple(
        DiscoveryResult(
            observation_id=g.granule_id,
            provider=provider,
            product=f"{g.short_name}.{g.version}",
            product_version=g.version,
            title=g.title,
            time_start=g.time_start,
            time_end=g.time_end,
            bbox=g.boxes[0] if g.boxes else bbox,
            query_mode="cmr_granule",
            access_hint=_safe_cmr_access_hint(g.data_url),
            metadata={
                "producer_granule_id": g.producer_granule_id,
                **dict(g.source_metadata),
            },
        )
        for g in selected_granules
    )


async def gather_bounded_granules(
    items: Sequence[Any],
    worker: Any,
    *,
    max_items: int = 12,
    max_concurrency: int = 3,
    key_fn: Any = None,
) -> tuple[list[Any], list[dict[str, str]]]:
    """Deduplicate items, execute bounded async fetches, and isolate per-granule failures."""
    seen_keys: set[str] = set()
    unique_items: list[tuple[str, Any]] = []
    limit = max(1, max_items)
    for item in items:
        key = str(key_fn(item) if key_fn is not None else item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_items.append((key, item))
        if len(unique_items) >= limit:
            break

    if not unique_items:
        raise ProviderValidationError("No candidate granules or URLs supplied for ingestion")

    sem = asyncio.Semaphore(max(1, max_concurrency))
    outcomes: list[tuple[int, Any | None, dict[str, str] | None, Exception | None]] = []

    async def _run_one(idx: int, item_key: str, item_val: Any) -> None:
        async with sem:
            try:
                res = await worker(item_val)
                outcomes.append((idx, res, None, None))
            except (ProviderAuthenticationError, ProviderDisabledError):
                raise
            except Exception as exc:
                outcomes.append((idx, None, {"item": item_key, "error": str(exc)}, exc))

    await asyncio.gather(*(_run_one(i, k, v) for i, (k, v) in enumerate(unique_items)))
    outcomes.sort(key=lambda row: row[0])

    successes = [res for _, res, err, _ in outcomes if err is None and res is not None]
    failures = [err for _, _, err, _ in outcomes if err is not None]
    if not successes:
        first_exc = next((exc for _, _, _, exc in outcomes if exc is not None), None)
        if first_exc is not None:
            raise first_exc
        raise ProviderResponseError("All candidate granule acquisitions failed")
    return successes, failures


def _mask_from_lon_lat(
    lons: Any,
    lats: Any,
    bbox: tuple[float, float, float, float],
) -> Any:
    import numpy as np

    min_lon, min_lat, max_lon, max_lat = bbox
    valid_geo = (
        np.isfinite(lons)
        & np.isfinite(lats)
        & (lons >= -180.0)
        & (lons <= 180.0)
        & (lats >= -90.0)
        & (lats <= 90.0)
    )
    mask = valid_geo & (lons >= min_lon) & (lons <= max_lon) & (lats >= min_lat) & (lats <= max_lat)
    if np.any(mask):
        return mask

    rows, cols = lons.shape
    half_dlon = 0.0
    half_dlat = 0.0
    if cols > 1:
        diffs_x = np.abs(np.diff(np.where(valid_geo, lons, np.nan), axis=1))
        finite_x = diffs_x[np.isfinite(diffs_x) & (diffs_x > 0)]
        if finite_x.size > 0:
            half_dlon = 0.5 * float(np.median(finite_x))
    if rows > 1:
        diffs_y = np.abs(np.diff(np.where(valid_geo, lats, np.nan), axis=0))
        finite_y = diffs_y[np.isfinite(diffs_y) & (diffs_y > 0)]
        if finite_y.size > 0:
            half_dlat = 0.5 * float(np.median(finite_y))
    if half_dlon == 0.0 and half_dlat == 0.0:
        return mask
    return (
        valid_geo
        & ((lons + half_dlon) >= min_lon)
        & ((lons - half_dlon) <= max_lon)
        & ((lats + half_dlat) >= min_lat)
        & ((lats - half_dlat) <= max_lat)
    )


def _find_coord_pair(
    decoded: Any,
    shape: tuple[int, int],
    dims: Sequence[str] | None = None,
) -> tuple[Any, Any] | None:
    import numpy as np

    rows, cols = shape
    lat_tokens = {"lat", "latitude"}
    lon_tokens = {"lon", "longitude"}

    def _pick(tokens: set[str], expected_1d: int) -> Any | None:
        arrays = getattr(decoded, "arrays", {}) or {}
        coords = getattr(decoded, "coordinates", {}) or {}
        for mapping in (arrays, coords):
            for name, raw in mapping.items():
                leaf = str(name).rsplit("/", 1)[-1].lower()
                if leaf not in tokens:
                    continue
                arr = np.asarray(raw, dtype=np.float64)
                if arr.shape == shape:
                    return arr
                if arr.ndim == 1 and arr.size == expected_1d:
                    return arr
        return None

    lon_lat_order = (
        dims is not None
        and len(dims) >= 2
        and str(dims[-2]).rsplit("/", 1)[-1].lower() in lon_tokens
        and str(dims[-1]).rsplit("/", 1)[-1].lower() in lat_tokens
    )
    if lon_lat_order:
        lon_arr = _pick(lon_tokens, rows)
        lat_arr = _pick(lat_tokens, cols)
        if lat_arr is None or lon_arr is None:
            return None
        if lon_arr.ndim == 1 and lat_arr.ndim == 1:
            lons, lats = np.meshgrid(lon_arr, lat_arr, indexing="ij")
            return lons, lats
        if lon_arr.shape == shape and lat_arr.shape == shape:
            return lon_arr, lat_arr
        return None

    lat_arr = _pick(lat_tokens, rows)
    lon_arr = _pick(lon_tokens, cols)
    if lat_arr is None or lon_arr is None:
        return None
    if lat_arr.ndim == 1 and lon_arr.ndim == 1:
        lats, lons = np.meshgrid(lat_arr, lon_arr, indexing="ij")
        return lons, lats
    if lat_arr.shape == shape and lon_arr.shape == shape:
        return lon_arr, lat_arr
    return None


def extract_aoi_mask_for_decoded(
    decoded: Any,
    shape: tuple[int, int],
    bbox: tuple[float, float, float, float] | None,
    dims: Sequence[str] | None = None,
) -> Any | None:
    """Compute a 2D boolean mask of pixels falling inside a WGS84 AOI bbox."""
    if bbox is None:
        return None
    validate_wgs84_bbox(bbox)
    import numpy as np

    lon_lat_order = (
        dims is not None
        and len(dims) >= 2
        and str(dims[-2]).rsplit("/", 1)[-1].lower() in {"lon", "longitude"}
        and str(dims[-1]).rsplit("/", 1)[-1].lower() in {"lat", "latitude"}
    )
    if lon_lat_order:
        pair = _find_coord_pair(decoded, shape, dims=dims)
        if pair is not None:
            lons, lats = pair
            return _mask_from_lon_lat(lons, lats, bbox)

    rows, cols = shape
    grid = getattr(decoded, "grid", None)
    if grid is not None and getattr(grid, "crs", None):
        try:
            from pyproj import CRS, Transformer

            resolved = grid.resolved()
            transform = resolved.transform
            if transform is not None and resolved.width == cols and resolved.height == rows:
                offset = 0.0 if grid.pixel_convention == "center" else 0.5
                cc, rr = np.meshgrid(
                    np.arange(cols, dtype=np.float64) + offset,
                    np.arange(rows, dtype=np.float64) + offset,
                )
                xs = transform.c + transform.a * cc + transform.b * rr
                ys = transform.f + transform.d * cc + transform.e * rr
                src_crs = CRS.from_user_input(grid.crs)
                if not src_crs.is_geographic or src_crs.to_epsg() != 4326:
                    transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
                    lons, lats = transformer.transform(xs, ys)
                    lons = np.asarray(lons, dtype=np.float64)
                    lats = np.asarray(lats, dtype=np.float64)
                else:
                    lons, lats = xs, ys
                return _mask_from_lon_lat(lons, lats, bbox)
        except Exception:
            pass

    pair = _find_coord_pair(decoded, shape, dims=dims)
    if pair is not None:
        lons, lats = pair
        return _mask_from_lon_lat(lons, lats, bbox)
    return None


def build_time_series_extension(
    *,
    timestamps: Sequence[datetime | str],
    values: Sequence[float | None],
    units: str | None = None,
    qa_layers: Mapping[str, Sequence[int | float | None]] | None = None,
    overpass_tags: Sequence[str] | None = None,
    valid_pixel_counts: Sequence[int] | None = None,
    total_pixel_counts: Sequence[int] | None = None,
    is_scaled: bool = True,
) -> dict[str, Any]:
    """Assemble sorted JSON-serializable observation time series for dataset extensions."""
    import math

    count = len(timestamps)
    if len(values) != count:
        raise ProviderValidationError("timestamps and values must share identical length")
    for qa_name, qa_seq in (qa_layers or {}).items():
        if len(qa_seq) != count:
            raise ProviderValidationError(
                f"QA layer '{qa_name}' length ({len(qa_seq)}) does not match timestamps ({count})"
            )
    if overpass_tags is not None and len(overpass_tags) != count:
        raise ProviderValidationError("overpass_tags length must match timestamps")
    if valid_pixel_counts is not None and len(valid_pixel_counts) != count:
        raise ProviderValidationError("valid_pixel_counts length must match timestamps")
    if total_pixel_counts is not None and len(total_pixel_counts) != count:
        raise ProviderValidationError("total_pixel_counts length must match timestamps")

    parsed_rows: list[tuple[datetime, str, int]] = []
    for idx, raw_ts in enumerate(timestamps):
        if isinstance(raw_ts, datetime):
            dt = raw_ts.replace(tzinfo=UTC) if raw_ts.tzinfo is None else raw_ts.astimezone(UTC)
        else:
            parsed_dt = _parse_iso_utc(raw_ts)
            if parsed_dt is None:
                raise ProviderValidationError(f"Invalid time series timestamp: {raw_ts!r}")
            dt = parsed_dt
        tag = str(overpass_tags[idx]) if overpass_tags is not None else ""
        parsed_rows.append((dt, tag, idx))

    parsed_rows.sort(key=lambda item: (item[0], item[1]))
    sorted_indices = [row[2] for row in parsed_rows]
    out_ts = [row[0].isoformat().replace("+00:00", "Z") for row in parsed_rows]
    out_vals: list[float | None] = []
    for idx in sorted_indices:
        v = values[idx]
        if v is None:
            out_vals.append(None)
        else:
            fv = float(v)
            out_vals.append(fv if math.isfinite(fv) else None)

    out_qa: dict[str, list[int | float | None]] = {}
    for qa_name, qa_seq in (qa_layers or {}).items():
        qa_out: list[int | float | None] = []
        for idx in sorted_indices:
            q_val = qa_seq[idx]
            if q_val is None:
                qa_out.append(None)
            elif isinstance(q_val, int) and not isinstance(q_val, bool):
                qa_out.append(int(q_val))
            else:
                fq = float(q_val)
                qa_out.append(fq if math.isfinite(fq) else None)
        out_qa[qa_name] = qa_out

    payload: dict[str, Any] = {
        "timestamps": out_ts,
        "values": out_vals,
        "qa_layers": out_qa,
        "is_scaled": is_scaled,
    }
    if units is not None:
        payload["units"] = units
    if overpass_tags is not None:
        payload["overpass_tags"] = [str(overpass_tags[idx]) for idx in sorted_indices]
    if valid_pixel_counts is not None:
        payload["valid_pixel_counts"] = [int(valid_pixel_counts[idx]) for idx in sorted_indices]
    if total_pixel_counts is not None:
        payload["total_pixel_counts"] = [int(total_pixel_counts[idx]) for idx in sorted_indices]
    return payload
