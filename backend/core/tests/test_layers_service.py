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


def test_layer_service_enriches_from_ghs_geotiff_and_zarr_and_rejects_non_raster() -> None:
    json_dataset = {
        "dataset_id": "ds-ndvi-json-1",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "variables": {"NDVI": {"name": "NDVI", "units": "dimensionless"}},
        "units": {"NDVI": "dimensionless"},
        "spatial_metadata": {"crs": "EPSG:4326", "bounds": [-41.0, -10.0, -39.0, -8.0]},
        "assets": [{"data_format": "json", "storage_key": "derived/ndvi.json"}],
        "extensions": {
            "time_series": {"NDVI": {"timestamps": ["2024-06-01T00:00:00Z"], "values": [0.5]}}
        },
    }
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
        json_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=[json_dataset])
        )
        json_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=json_transport,
        )
        ndvi_json = await json_service.get_layer("ndvi-mod13q1")
        assert ndvi_json.availability_status == "unavailable"
        assert ndvi_json.unavailable_reason is not None
        assert "non-raster" in ndvi_json.unavailable_reason
        assert ndvi_json.active_dataset_id is None

        zarr_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=[zarr_dataset])
        )
        zarr_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=zarr_transport,
        )
        ndvi_zarr = await zarr_service.get_layer("ndvi-mod13q1")
        assert ndvi_zarr.availability_status == "connected"
        assert ndvi_zarr.tile_source.format == "zarr"
        assert ndvi_zarr.active_dataset_id == "ds-ndvi-zarr-1"

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


def test_layer_service_handles_ghs_unreachable_empty_and_aoi_preview() -> None:
    def _unreachable(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("GHS down")

    async def scenario() -> None:
        unreachable_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=httpx.MockTransport(_unreachable),
        )
        layers_unreachable = await unreachable_service.list_layers()
        assert len(layers_unreachable) == 16
        assert all(layer.availability_status != "connected" for layer in layers_unreachable)
        tri = next(layer for layer in layers_unreachable if layer.id == "experimental-tri")
        assert tri.availability_status == "unavailable"

        empty_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=httpx.MockTransport(lambda _req: httpx.Response(200, json=[])),
        )
        layers_empty = await empty_service.list_layers()
        assert all(layer.availability_status != "connected" for layer in layers_empty)

        aoi_derived_dataset = {
            "dataset_id": "ds-ndvi-anom-aoi",
            "product": "TERRA-NDVI-ANOM",
            "product_version": "1.0.0",
            "bbox_wgs84": [23.0, 48.0, 25.0, 49.5],
            "temporal": {"start": "2024-01-01T00:00:00Z", "end": "2024-06-01T00:00:00Z"},
            "variables": {"ndvi_zscore": {"units": "z-score"}},
            "extensions": {"scope": "aoi"},
            "assets": [{"role": "primary", "data_format": "geotiff", "uri": "/tmp/anom.tif"}],
        }
        tri_dataset = {
            "dataset_id": "ds-tri-fake",
            "product": "TERRA-TRI",
            "product_version": "0.1.0",
            "bbox_wgs84": [23.0, 48.0, 25.0, 49.5],
            "assets": [{"role": "primary", "data_format": "geotiff", "uri": "/tmp/tri.tif"}],
        }
        preview_service = LayerCatalogService(
            StaticLayerCatalogRepository(),
            ghs_base_url="http://ghs.test",
            ghs_transport=httpx.MockTransport(
                lambda _req: httpx.Response(200, json=[aoi_derived_dataset, tri_dataset])
            ),
        )
        anom = await preview_service.get_layer("ndvi-anomaly")
        assert anom.availability_status == "preview"
        assert anom.tile_source.is_connected is True
        assert anom.active_dataset_id == "ds-ndvi-anom-aoi"
        assert anom.dataset_bbox == (23.0, 48.0, 25.0, 49.5)

        tri_after = await preview_service.get_layer("experimental-tri")
        assert tri_after.availability_status == "unavailable"
        assert tri_after.tile_source.is_connected is False

    asyncio.run(scenario())
