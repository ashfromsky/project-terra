"""Unit tests for SSRF transport protections and HandlerRegistry dispatch."""

import socket

import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.handlers import HandlerRegistry
from geospatial_harmonization.handlers.base import safe_fetch_bytes, validate_safe_url


class _StubHandler:
    def __init__(self, provider: str, products: tuple[str, ...]) -> None:
        self._provider = provider
        self._products = products

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def supported_products(self) -> tuple[str, ...]:
        return self._products

    async def handle_payload(self, payload: object) -> SpatialDataset:
        raise NotImplementedError


def test_ssrf_guards_block_private_ips_schemes_and_untrusted_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_dns(host: str, *_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        ip = "169.254.169.254" if "metadata" in host else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    with pytest.raises(IncompatibleDatasetError, match="scheme"):
        validate_safe_url("file:///etc/passwd")
    with pytest.raises(IncompatibleDatasetError, match="forbidden network"):
        validate_safe_url("http://127.0.0.1/secret", allowed_hosts=["127.0.0.1"])
    with pytest.raises(IncompatibleDatasetError, match="forbidden network"):
        validate_safe_url("https://metadata.example.com/latest", allowed_hosts=["*.example.com"])
    with pytest.raises(IncompatibleDatasetError, match="allowlist"):
        validate_safe_url("https://evil.org/data.tif", allowed_hosts=["data.nasa.gov"])
    assert (
        validate_safe_url("https://data.nasa.gov/a.tif", allowed_hosts=["*.nasa.gov"])
        == "https://data.nasa.gov/a.tif"
    )


async def test_safe_fetch_retries_blocks_bad_redirects_and_registry_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_dns(host: str, *_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        ip = "10.0.0.2" if "internal" in host else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    calls = 0

    def handle_http(request: Request) -> Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/redir":
            return Response(302, headers={"location": "http://internal.corp/secret"})
        if calls == 1:
            return Response(503)
        return Response(200, content=b"ok", headers={"content-type": "text/plain"})

    body, _, media = await safe_fetch_bytes(
        "https://trusted.example.org/file",
        allowed_hosts=["trusted.example.org"],
        max_retries=1,
        transport=MockTransport(handle_http),
    )
    assert body == b"ok" and media == "text/plain" and calls == 2

    with pytest.raises(IncompatibleDatasetError, match="allowlist"):
        await safe_fetch_bytes(
            "https://trusted.example.org/redir",
            allowed_hosts=["trusted.example.org"],
            transport=MockTransport(handle_http),
        )

    reg = HandlerRegistry()
    modis = _StubHandler("modis", ("MOD13Q1.061",))
    generic = _StubHandler("generic", ("*",))
    reg.register(modis)
    reg.register(generic)
    assert reg.get("modis", "MOD13Q1.061") is modis
    with pytest.raises(IncompatibleDatasetError, match="No handler registered"):
        reg.get("modis", "UNKNOWN_PRODUCT")
