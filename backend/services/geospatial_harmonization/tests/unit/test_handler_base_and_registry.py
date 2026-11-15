"""Unit tests for SSRF transport protections and HandlerRegistry dispatch."""

import json
import socket
from datetime import UTC, datetime

import pytest
from httpx import MockTransport, Request, Response

from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderResponseError,
    ProviderValidationError,
    TransientTransferError,
)
from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.handlers import HandlerRegistry
from geospatial_harmonization.handlers.base import (
    EARTHDATA_ALLOWED_HOSTS,
    discover_cmr_granules,
    safe_fetch_bytes,
    safe_fetch_to_file,
    validate_safe_url,
)


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


async def test_earthdata_presigned_redirect_strips_auth_and_rejects_unsigned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    seen_headers: list[tuple[str, str | None]] = []

    def handle_http(request: Request) -> Response:
        seen_headers.append((request.url.host, request.headers.get("authorization")))
        if request.url.path == "/unsigned-redir":
            return Response(
                302, headers={"location": "https://d123.cloudfront.net/public/file.hdf"}
            )
        if request.url.host == "data.lpdaac.earthdatacloud.nasa.gov":
            return Response(
                303,
                headers={
                    "location": (
                        "https://d123.cloudfront.net/s3-path/MOD13Q1.hdf"
                        "?Expires=1900000000&Signature=abc123&Key-Pair-Id=APK123"
                    )
                },
            )
        return Response(200, content=b"HDF4DATA", headers={"content-type": "application/x-hdf"})

    assert isinstance(tmp_path, Path)
    dest, ref, final_url = await safe_fetch_to_file(
        "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod/MOD13Q1.hdf",
        tmp_path,
        data_format="hdf4",
        allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
        headers={"Authorization": "Bearer secret-edl"},
        transport=MockTransport(handle_http),
        require_https=True,
        earthdata_auth=True,
    )
    assert dest.read_bytes() == b"HDF4DATA"
    assert ref.size_bytes == 8
    assert "d123.cloudfront.net" in final_url
    assert seen_headers == [
        ("data.lpdaac.earthdatacloud.nasa.gov", "Bearer secret-edl"),
        ("d123.cloudfront.net", None),
    ]

    with pytest.raises(ProviderValidationError, match="allowlist"):
        await safe_fetch_bytes(
            "https://d123.cloudfront.net/s3-path/MOD13Q1.hdf?Expires=1&Signature=x&Key-Pair-Id=k",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            transport=MockTransport(handle_http),
            require_https=True,
            earthdata_auth=True,
        )

    with pytest.raises(ProviderValidationError, match="presigned signature"):
        await safe_fetch_bytes(
            "https://data.lpdaac.earthdatacloud.nasa.gov/unsigned-redir",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            transport=MockTransport(handle_http),
            require_https=True,
            earthdata_auth=True,
        )


async def test_earthdata_urs_oauth_handshake_and_error_classification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from pathlib import Path

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    urs_calls = 0

    def handle_http(request: Request) -> Response:
        nonlocal urs_calls
        if request.url.path == "/401":
            return Response(401, content=b"Unauthorized")
        if request.url.path == "/403":
            return Response(403, content=b"EULA required")
        if request.url.path == "/429":
            return Response(429, headers={"retry-after": "0"})
        if request.url.path == "/html-login":
            return Response(
                200,
                content=b"<!DOCTYPE html><html><title>Earthdata Login</title></html>",
                headers={"content-type": "text/html"},
            )
        if (
            request.url.host == "data.gesdisc.earthdata.nasa.gov"
            and request.url.path == "/data/file.HDF5"
        ):
            if "urs_session=ok" in request.headers.get("cookie", ""):
                return Response(
                    200,
                    content=b"\x89HDF\r\n\x1a\n",
                    headers={"content-type": "application/x-hdf5"},
                )
            return Response(
                302,
                headers={
                    "location": "https://urs.earthdata.nasa.gov/oauth/authorize?client=gesdisc"
                },
            )
        if request.url.host == "urs.earthdata.nasa.gov":
            urs_calls += 1
            assert request.headers.get("authorization") == "Bearer valid-edl"
            return Response(
                302,
                headers={
                    "location": "https://data.gesdisc.earthdata.nasa.gov/login?code=abc",
                    "set-cookie": "urs_urs=1; Path=/",
                },
            )
        if request.url.path == "/login":
            return Response(
                302,
                headers={
                    "location": "https://data.gesdisc.earthdata.nasa.gov/data/file.HDF5",
                    "set-cookie": "urs_session=ok; Path=/",
                },
            )
        return Response(404)

    assert isinstance(tmp_path, Path)
    dest, _, _ = await safe_fetch_to_file(
        "https://data.gesdisc.earthdata.nasa.gov/data/file.HDF5",
        tmp_path,
        data_format="hdf5",
        allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
        headers={"Authorization": "Bearer valid-edl"},
        transport=MockTransport(handle_http),
        require_https=True,
        earthdata_auth=True,
    )
    assert dest.read_bytes().startswith(b"\x89HDF") and urs_calls == 1

    with pytest.raises(ProviderAuthenticationError, match="token is required"):
        await safe_fetch_bytes(
            "https://data.gesdisc.earthdata.nasa.gov/data/file.HDF5",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            transport=MockTransport(handle_http),
            require_https=True,
            earthdata_auth=True,
        )

    with pytest.raises(ProviderAuthenticationError):
        await safe_fetch_bytes(
            "https://data.gesdisc.earthdata.nasa.gov/401",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            transport=MockTransport(handle_http),
        )
    with pytest.raises(ProviderAuthorizationError):
        await safe_fetch_bytes(
            "https://data.gesdisc.earthdata.nasa.gov/403",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            transport=MockTransport(handle_http),
        )
    with pytest.raises(TransientTransferError):
        await safe_fetch_bytes(
            "https://data.gesdisc.earthdata.nasa.gov/429",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            max_retries=1,
            transport=MockTransport(handle_http),
        )
    with pytest.raises(ProviderAuthenticationError, match="HTML login"):
        await safe_fetch_to_file(
            "https://data.gesdisc.earthdata.nasa.gov/html-login",
            tmp_path,
            data_format="hdf5",
            allowed_hosts=EARTHDATA_ALLOWED_HOSTS,
            transport=MockTransport(handle_http),
        )


async def test_discover_cmr_granules_preserves_metadata_and_prefers_data_rel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    def handle_cmr(request: Request) -> Response:
        if request.url.host == "cmr.earthdata.nasa.gov":
            return Response(
                200,
                content=json.dumps(
                    {
                        "feed": {
                            "entry": [
                                {
                                    "id": "G999-LPCLOUD",
                                    "producer_granule_id": "MOD13Q1.A2024001.h12v10.061.hdf",
                                    "title": "MOD13Q1.A2024001.h12v10.061",
                                    "time_start": "2024-01-01T00:00:00.000Z",
                                    "time_end": "2024-01-16T23:59:59.000Z",
                                    "boxes": ["-10 -60 0 -50"],
                                    "links": [
                                        {
                                            "rel": "http://esipfed.org/ns/fedsearch/1.1/metadata#",
                                            "href": "https://data.lpdaac.earthdatacloud.nasa.gov/meta.hdf",
                                        },
                                        {
                                            "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                                            "href": "https://data.lpdaac.earthdatacloud.nasa.gov/MOD13Q1.A2024001.hdf",
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                ).encode("utf-8"),
            )
        return Response(404)

    granules = await discover_cmr_granules(
        "https://cmr.earthdata.nasa.gov/search",
        "MOD13Q1.061",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 17, tzinfo=UTC),
        (".hdf",),
        transport=MockTransport(handle_cmr),
    )
    assert len(granules) == 1
    g = granules[0]
    assert g.producer_granule_id == "MOD13Q1.A2024001.h12v10.061.hdf"
    assert g.data_url.endswith("/MOD13Q1.A2024001.hdf")
    assert g.boxes == ((-60.0, -10.0, -50.0, 0.0),)
    assert g.time_start == datetime(2024, 1, 1, tzinfo=UTC)
    assert g.source_metadata["id"] == "G999-LPCLOUD"

    with pytest.raises(ProviderValidationError, match="No CMR granule"):
        await discover_cmr_granules(
            "https://cmr.earthdata.nasa.gov/search",
            "MOD13Q1.061",
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 17, tzinfo=UTC),
            (".nc",),
            transport=MockTransport(handle_cmr),
        )


def test_discover_error_classification_helpers() -> None:
    from geospatial_harmonization.domain.exceptions import classify_exception

    assert classify_exception(ProviderAuthenticationError("bad")) == ("authentication", False)
    assert classify_exception(TransientTransferError("timeout")) == ("network", True)
    assert classify_exception(ProviderResponseError("bad html")) == ("provider", False)
