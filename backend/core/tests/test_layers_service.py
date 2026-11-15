"""Unit tests for LayerCatalogService using a fake LayerCatalogRepository."""

import asyncio

import httpx
import pytest

from terra.modules.layers.application.services import LayerCatalogService
from terra.modules.layers.domain.entities import (
    AvailableTimeRange,
    DataAvailabilityStatus,
    LayerDefinition,
    LegendConfiguration,
    MapLayerGroupId,
    MapTileSource,
    ValueRange,
)
from terra.modules.layers.domain.exceptions import LayerNotFoundError
from terra.modules.layers.infrastructure.color_ramps import VEGETATION_RAMP
from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository


def _sample_layer(
    layer_id: str = "ndvi-mod13q1", group_id: MapLayerGroupId = "vegetation"
) -> LayerDefinition:
    return LayerDefinition(
        id=layer_id,
        name="NDVI · MOD13Q1.061",
        short_name="NDVI",
        group_id=group_id,
        description="Test NDVI layer",
        data_source="NASA LP DAAC · MODIS Terra",
        product_id="MOD13Q1",
        product_version="061",
        variable="250m 16 days NDVI",
        unit="NDVI (0-1)",
        native_spatial_resolution="250 m",
        temporal_resolution="16-day composite",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "16-day"),
        attribution="NASA LP DAAC",
        availability_status="preview",
        rendering_type="choropleth",
        supported_tile_formats=("cog", "tilejson"),
        qa_policy="Pixel Reliability == 0",
        limitations="Cloud cover",
        color_ramp=VEGETATION_RAMP,
        value_range=ValueRange(-0.2, 1.0, 0.0, 1.0, 0.05),
        legend=LegendConfiguration(
            "Vegetation Index",
            "NDVI",
            "0.0",
            "0.5",
            "1.0",
            "linear-gradient(...)",
            "#d0dbe0",
            "NoData",
            VEGETATION_RAMP,
        ),
        tile_source=MapTileSource("src", "cog", None, "EPSG:4326", True, False),
    )


class FakeLayerRepository:
    def __init__(self, layers: list[LayerDefinition]) -> None:
        self._layers = layers

    async def list_layers(
        self,
        *,
        group_id: MapLayerGroupId | None = None,
        availability_status: DataAvailabilityStatus | None = None,
    ) -> list[LayerDefinition]:
        return [
            item
            for item in self._layers
            if (group_id is None or item.group_id == group_id)
            and (availability_status is None or item.availability_status == availability_status)
        ]

    async def get_by_id(self, layer_id: str) -> LayerDefinition | None:
        return next((item for item in self._layers if item.id == layer_id), None)


def test_layer_service_filtering_legend_and_coverage() -> None:
    async def scenario() -> None:
        repo = FakeLayerRepository([_sample_layer("ndvi-mod13q1", "vegetation")])
        service = LayerCatalogService(repo)

        assert len(await service.list_layers(group_id="vegetation")) == 1
        assert await service.list_layers(group_id="water") == []

        layer, legend = await service.get_legend("ndvi-mod13q1")
        assert layer.id == "ndvi-mod13q1"
        assert len(legend.stops) == 4

        cov = await service.get_coverage("ndvi-mod13q1")
        assert cov.total_expected_steps == 25 * 23
        assert cov.available_steps == 0
        assert cov.is_simulated_coverage is False

        with pytest.raises(LayerNotFoundError):
            await service.get_layer("missing")

    asyncio.run(scenario())


def test_layer_service_enriches_from_ghs_geotiff_and_rejects_zarr_only() -> None:
    zarr_dataset = {
        "dataset_id": "ds-ndvi-zarr-1",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "variables": {"NDVI": {"name": "NDVI", "units": "dimensionless"}},
        "units": {"NDVI": "dimensionless"},
        "spatial_metadata": {"crs": "EPSG:4326", "bounds": [-41.0, -10.0, -39.0, -8.0]},
        "assets": [{"data_format": "zarr", "storage_key": "derived/ndvi.zarr"}],
        "extensions": {
            "time_series": {"NDVI": {"timestamps": ["2024-06-01T00:00:00Z"], "values": [0.5]}}
        },
    }
    geotiff_dataset = {
        "dataset_id": "ds-ndvi-cog-1",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "variables": {"NDVI": {"name": "NDVI", "units": "dimensionless"}},
        "units": {"NDVI": "dimensionless"},
        "spatial_metadata": {"crs": "EPSG:4326", "bounds": [-41.0, -10.0, -39.0, -8.0]},
        "assets": [{"data_format": "geotiff", "storage_key": "derived/ndvi.tif"}],
        "extensions": {
            "time_series": {
                "NDVI": {
                    "timestamps": ["2024-06-01T00:00:00Z", "2024-06-17T00:00:00Z"],
                    "values": [0.55, 0.62],
                }
            }
        },
    }

    async def scenario() -> None:
        zarr_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=[zarr_dataset])
        )
        zarr_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=zarr_transport,
        )
        ndvi_zarr = await zarr_service.get_layer("ndvi-mod13q1")
        assert ndvi_zarr.availability_status == "unavailable"
        assert ndvi_zarr.unavailable_reason is not None
        assert "Zarr" in ndvi_zarr.unavailable_reason
        assert ndvi_zarr.active_dataset_id is None

        cog_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=[geotiff_dataset])
        )
        cog_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=cog_transport,
        )
        ndvi_cog = await cog_service.get_layer("ndvi-mod13q1")
        assert ndvi_cog.availability_status == "connected"
        assert ndvi_cog.active_dataset_id == "ds-ndvi-cog-1"
        assert ndvi_cog.available_dates == ("2024-06-01", "2024-06-17")
        assert ndvi_cog.dataset_bbox == (-41.0, -10.0, -39.0, -8.0)
        assert (
            ndvi_cog.tile_source.url_template == "/api/v1/layers/ndvi-mod13q1/tiles/{z}/{x}/{y}.png"
        )

    asyncio.run(scenario())
