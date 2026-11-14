"""Shared transport, SSRF protection, and validation helpers for provider handlers."""

import hashlib
import ipaddress
import socket
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ValidationError

from geospatial_harmonization import __version__
from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    ProvenanceRecord,
)

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_ALLOWED_SCHEMES = frozenset({"https", "http"})


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
