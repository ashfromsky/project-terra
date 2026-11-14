"""Unit tests for SSRF-guarded GenericHandler ingestion."""

import socket
from pathlib import Path

import numpy as np
import pytest
import rasterio
from httpx import MockTransport, Request, Response
from rasterio.transform import from_origin

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.ports import DataHandler
from geospatial_harmonization.handlers import GenericHandler, HandlerRegistry


def _geotiff_bytes(tmp_path: Path) -> bytes:
    p = tmp_path / "template.tif"
    with rasterio.open(
        p,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(10.0, 51.0, 0.25, 0.25),
    ) as dst:
        dst.write(np.ones((2, 2), dtype=np.float32), 1)
        dst.set_band_description(1, "value")
    return p.read_bytes()


async def test_generic_handler_ingests_allowlisted_tiff_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_dns(host: str, *_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        ip = "10.0.0.5" if "internal" in host else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    tiff_bytes = _geotiff_bytes(tmp_path)

    def handle_http(request: Request) -> Response:
        if request.url.path == "/redirect-internal":
            return Response(302, headers={"location": "http://internal.corp/secret.tif"})
        return Response(200, content=tiff_bytes, headers={"content-type": "image/tiff"})

    handler: DataHandler = GenericHandler(
        allowed_hosts=["trusted.example.org"],
        raw_dir=tmp_path / "raw",
        transport=MockTransport(handle_http),
    )
    reg = HandlerRegistry()
    reg.register(handler)
    assert reg.list_capabilities() == {"generic": ("*",)}

    ds = await handler.handle_payload(
        {"url": "https://trusted.example.org/sample.tif", "data_format": "geotiff"}
    )
    assert ds.provider == "generic"
    assert "value" in ds.variables
    assert ds.spatial_metadata.crs == "EPSG:4326"

    with pytest.raises(IncompatibleDatasetError, match="allowlist"):
        await handler.handle_payload({"url": "https://trusted.example.org/redirect-internal"})

    disabled = GenericHandler(allowed_hosts=(), transport=MockTransport(handle_http))
    with pytest.raises(IncompatibleDatasetError, match="disabled"):
        await disabled.handle_payload({"url": "https://trusted.example.org/sample.tif"})
