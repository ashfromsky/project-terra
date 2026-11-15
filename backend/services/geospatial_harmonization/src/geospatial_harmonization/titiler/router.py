"""TiTiler FastAPI router integration and COG tile rendering engine."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast
from urllib.parse import urlparse

import rasterio
from fastapi import APIRouter
from morecantile import Tile, tms
from rio_tiler.colormap import cmap
from rio_tiler.errors import TileOutsideBounds
from rio_tiler.io import Reader
from titiler.core.factory import TilerFactory

from geospatial_harmonization.application.cog_publisher import CogPublisher
from geospatial_harmonization.application.raster_viz import (
    _COLOR_RAMPS,
    _transparent_png,
)
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.domain.ports import DatasetRepository, StoragePort
from geospatial_harmonization.readers import ReaderRegistry

logger = logging.getLogger(__name__)


def build_rio_colormap(
    stops: tuple[tuple[float, tuple[int, int, int]], ...],
) -> dict[int, tuple[int, int, int, int]]:
    """Build a 256-level RGBA colormap lookup dictionary from stop points."""
    cmap_dict: dict[int, tuple[int, int, int, int]] = {}
    for i in range(256):
        t = i / 255.0
        if t <= stops[0][0]:
            r, g, b = stops[0][1]
        elif t >= stops[-1][0]:
            r, g, b = stops[-1][1]
        else:
            r, g, b = stops[0][1]
            for j in range(len(stops) - 1):
                t0, c0 = stops[j]
                t1, c1 = stops[j + 1]
                if t0 <= t <= t1:
                    span = max(1e-9, t1 - t0)
                    frac = (t - t0) / span
                    r = int(c0[0] + frac * (c1[0] - c0[0]))
                    g = int(c0[1] + frac * (c1[1] - c0[1]))
                    b = int(c0[2] + frac * (c1[2] - c0[2]))
                    break
        cmap_dict[i] = (r, g, b, 255)
    return cmap_dict


def resolve_colormap(name: str | None) -> Any:
    """Resolve colormap by TERRA preset name or standard matplotlib name."""
    if not name:
        return cmap.get("viridis")
    clean = name.lower().strip()
    if clean in _COLOR_RAMPS:
        return build_rio_colormap(_COLOR_RAMPS[clean][2])
    try:
        return cmap.get(clean)
    except Exception:
        return cmap.get("viridis")


def get_gdal_env_options(settings: Settings | None = None) -> dict[str, str]:
    """Resolve GDAL environment options supporting HTTP range reads and Cloudflare R2."""
    opts: dict[str, str] = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": "268435456",
    }
    if settings is not None and settings.storage_backend == "s3":
        opts["AWS_VIRTUAL_HOSTING"] = "FALSE"
        if settings.s3_endpoint_url:
            parsed = urlparse(settings.s3_endpoint_url)
            opts["AWS_S3_ENDPOINT"] = parsed.netloc or settings.s3_endpoint_url
            if parsed.scheme == "http":
                opts["AWS_HTTPS"] = "NO"
        if settings.aws_access_key_id:
            opts["AWS_ACCESS_KEY_ID"] = settings.aws_access_key_id.get_secret_value()
        if settings.aws_secret_access_key:
            opts["AWS_SECRET_ACCESS_KEY"] = settings.aws_secret_access_key.get_secret_value()
        if settings.s3_region:
            opts["AWS_REGION"] = settings.s3_region
    return opts


async def render_dataset_tile_titiler(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    datasets_repo: DatasetRepository | None,
    *,
    z: int,
    x: int,
    y: int,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
    settings: Settings | None = None,
) -> bytes:
    """Render an XYZ RGBA PNG tile from the dataset's COG using TiTiler/rio-tiler."""
    publisher = CogPublisher(storage=storage, readers=readers, datasets=datasets_repo)
    cog_res = await publisher.get_or_publish_cog(
        dataset,
        variable=variable,
        timestamp=timestamp,
        unit_conversion=unit_conversion,
    )

    cog_target: str
    if cog_res.local_path is not None and cog_res.local_path.is_file():
        cog_target = str(cog_res.local_path)
    elif storage is not None and hasattr(storage, "generate_presigned_download_url"):
        presigned = await storage.generate_presigned_download_url(
            cog_res.storage_key, expires_in=600
        )
        cog_target = presigned or cog_res.asset.uri
    else:
        cog_target = cog_res.asset.uri

    gdal_opts = get_gdal_env_options(settings)
    cm = resolve_colormap(colormap)

    def _render() -> bytes:
        with rasterio.Env(**gdal_opts):
            try:
                with Reader(cog_target) as cog:
                    web_tms = tms.get("WebMercatorQuad")
                    tile_bounds = web_tms.xy_bounds(Tile(x, y, z))
                    if not rasterio.coords.disjoint_bounds(
                        (tile_bounds.left, tile_bounds.bottom, tile_bounds.right, tile_bounds.top),
                        cog.bounds,
                    ):
                        try:
                            img = cog.tile(x, y, z, tilesize=256)
                        except TileOutsideBounds:
                            return _transparent_png(256, 256)

                        v_lo = float(vmin) if vmin is not None else 0.0
                        v_hi = float(vmax) if vmax is not None else 1.0
                        if v_lo >= v_hi:
                            v_hi = v_lo + 1.0

                        processed = img.post_process(in_range=((v_lo, v_hi),))
                        return cast(bytes, processed.render(img_format="PNG", colormap=cm))
                    return _transparent_png(256, 256)
            except TileOutsideBounds:
                return _transparent_png(256, 256)
            except Exception as exc:
                logger.warning(
                    "TiTiler render failed for dataset %s at z=%d x=%d y=%d: %s",
                    dataset.dataset_id,
                    z,
                    x,
                    y,
                    exc,
                )
                return _transparent_png(256, 256)

    return await asyncio.to_thread(_render)


def create_titiler_router(settings: Settings | None = None) -> APIRouter:
    """Create TiTiler router mounted under /cog."""
    factory = TilerFactory(router_prefix="")
    return factory.router
