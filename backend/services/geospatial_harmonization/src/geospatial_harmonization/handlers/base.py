"""Shared transport, SSRF protection, and validation helpers for provider handlers."""

import hashlib
import ipaddress
import json
import os
import socket
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ValidationError

from geospatial_harmonization import __version__
from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ObjectTooLargeError,
)
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    ProvenanceRecord,
)

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_SCHEMES = frozenset({"https", "http"})
EARTHDATA_ALLOWED_HOSTS = (
    "*.nasa.gov",
    "*.earthdata.nasa.gov",
    "*.earthdatacloud.nasa.gov",
    "*.nsidc.org",
    "*.usgs.gov",
)


def parse_handler_payload[ModelT: BaseModel](
    model_cls: type[ModelT], payload: Mapping[str, object]
) -> ModelT:
    """Validate untrusted handler payload into a strict Pydantic model."""
    try:
        return model_cls.model_validate(dict(payload))
    except ValidationError as exc:
        raise IncompatibleDatasetError(f"Invalid handler payload: {exc}") from exc


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


def validate_safe_url(
    url: str, *, allowed_hosts: Sequence[str] | None = None, require_https: bool = False
) -> str:
    """Reject non-HTTP schemes, allowlist violations, and private/loopback/link-local IPs."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES or (require_https and scheme != "https"):
        raise IncompatibleDatasetError(f"Disallowed URL scheme '{parsed.scheme}'")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise IncompatibleDatasetError("URL missing valid hostname")
    if allowed_hosts is not None and not _host_matches(hostname, allowed_hosts):
        raise IncompatibleDatasetError(f"Host '{hostname}' is not in trusted host allowlist")

    try:
        ipaddress.ip_address(hostname)
        ips = [hostname]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise IncompatibleDatasetError(
                f"Failed DNS resolution for '{hostname}': {exc}"
            ) from exc
        ips = [str(item[4][0]) for item in infos]
    if not ips or any(_is_forbidden_ip(ip) for ip in ips):
        raise IncompatibleDatasetError(f"Resolved IP for '{hostname}' targets forbidden network")
    return url


async def safe_fetch_bytes(
    url: str,
    *,
    allowed_hosts: Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    max_retries: int = 2,
    transport: httpx.AsyncBaseTransport | None = None,
    require_https: bool = False,
) -> tuple[bytes, str, str]:
    """Fetch bytes over httpx with SSRF validation on every redirect hop and retry handling."""
    current = validate_safe_url(url, allowed_hosts=allowed_hosts, require_https=require_https)
    req_headers = dict(headers or {})
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport
    ) as client:
        cur_params: Mapping[str, str] | None = params
        for _ in range(6):
            resp = await _request_with_retries(
                client, current, req_headers, cur_params, max_retries
            )
            if resp.status_code in _REDIRECT_CODES and "location" in resp.headers:
                nxt = urljoin(current, resp.headers["location"])
                validate_safe_url(nxt, allowed_hosts=allowed_hosts, require_https=require_https)
                if urlparse(nxt).netloc != urlparse(current).netloc:
                    req_headers.pop("Authorization", None)
                current, cur_params = nxt, None
                continue
            if resp.status_code >= 400:
                raise IncompatibleDatasetError(f"Upstream HTTP {resp.status_code} for {current}")
            media = (
                resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
            )
            return resp.content, current, media or "application/octet-stream"
    raise IncompatibleDatasetError(f"Exceeded maximum redirect hops for {url}")


async def _request_with_retries(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, str] | None,
    max_retries: int,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code < 500 or attempt == max_retries:
                return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == max_retries:
                raise IncompatibleDatasetError(f"HTTP transport error for {url}: {exc}") from exc
    raise IncompatibleDatasetError(f"Request failed for {url}: {last_exc}")


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
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    max_retries: int = 2,
    transport: httpx.AsyncBaseTransport | None = None,
    require_https: bool = False,
    max_bytes: int | None = None,
    chunk_bytes: int = 1_048_576,
) -> tuple[Path, AssetReference, str]:
    """Stream remote payload directly to disk with SSRF checks, max-bytes guard, and SHA-256."""
    current = validate_safe_url(url, allowed_hosts=allowed_hosts, require_https=require_https)
    req_headers = dict(headers or {})
    dest_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport
    ) as client:
        cur_params: Mapping[str, str] | None = params
        for _ in range(6):
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
                        if resp.status_code >= 500 and attempt < max_retries:
                            continue
                        if resp.status_code >= 400:
                            raise IncompatibleDatasetError(
                                f"Upstream HTTP {resp.status_code} for {current}"
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
                        with tmp_path.open("wb") as out_f:
                            async for chunk in resp.aiter_bytes(chunk_size=chunk_bytes):
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

                        media = (
                            resp.headers.get("content-type", "application/octet-stream")
                            .split(";")[0]
                            .strip()
                            or "application/octet-stream"
                        )
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
                        raise IncompatibleDatasetError(
                            f"HTTP transport error for {current}: {exc}"
                        ) from exc
                except BaseException:
                    tmp_path.unlink(missing_ok=True)
                    raise
                else:
                    tmp_path.unlink(missing_ok=True)

            if redirect_target is not None:
                validate_safe_url(
                    redirect_target, allowed_hosts=allowed_hosts, require_https=require_https
                )
                if urlparse(redirect_target).netloc != urlparse(current).netloc:
                    req_headers.pop("Authorization", None)
                current, cur_params = redirect_target, None
                continue
            raise IncompatibleDatasetError(f"Request failed for {current}: {last_exc}")
    raise IncompatibleDatasetError(f"Exceeded maximum redirect hops for {url}")


def build_provenance(
    provider: str, product: str, version: str, url: str, *, run_type: str | None = None
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
    )


def earthdata_hosts_for(cmr_url: str) -> tuple[str, ...]:
    """Return trusted NASA/DAAC download hosts alongside the configured CMR hostname."""
    cmr_host = (urlparse(cmr_url).hostname or "").lower()
    return (*EARTHDATA_ALLOWED_HOSTS, cmr_host) if cmr_host else EARTHDATA_ALLOWED_HOSTS


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
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Query NASA CMR granules API and return the first HTTPS data link matching extensions."""
    short_name, version = product.split(".", 1)
    t0 = window_start.astimezone(UTC).isoformat()
    t1 = window_end.astimezone(UTC).isoformat()
    params = {
        "short_name": short_name,
        "version": version,
        "temporal": f"{t0},{t1}",
        "page_size": "1",
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
        transport=transport,
    )
    doc = json.loads(raw.decode("utf-8"))
    entries = doc.get("feed", {}).get("entry", []) if isinstance(doc, Mapping) else []
    for entry in entries:
        for link in entry.get("links", []) if isinstance(entry, Mapping) else []:
            href = link.get("href", "") if isinstance(link, Mapping) else ""
            if href.startswith("https://") and href.lower().endswith(extensions):
                return str(href)
    raise IncompatibleDatasetError(f"No CMR granule download URL found for '{product}'")
