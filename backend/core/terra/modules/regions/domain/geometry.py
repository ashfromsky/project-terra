"""Pure-Python WGS 84 (EPSG:4326) GeoJSON validation and spherical metrics."""

import itertools
import math
from typing import Any

from terra.modules.regions.domain.entities import GeometryMetrics
from terra.modules.regions.domain.exceptions import InvalidGeometryError

_EARTH_RADIUS_KM = 6371.0088


def _validate_position(pos: Any) -> tuple[float, float]:
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        raise InvalidGeometryError("Each coordinate must be a [lon, lat] pair")
    lon, lat = pos[0], pos[1]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (lon, lat)):
        raise InvalidGeometryError("Coordinates must be numeric")
    lon_f, lat_f = float(lon), float(lat)
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        raise InvalidGeometryError("Coordinates must be finite numbers")
    if not (-180.0 <= lon_f <= 180.0 and -90.0 <= lat_f <= 90.0):
        raise InvalidGeometryError("Coordinates out of WGS 84 bounds ([-180, 180], [-90, 90])")
    return (round(lon_f, 6), round(lat_f, 6))


def _validate_ring(ring: Any) -> list[tuple[float, float]]:
    if not isinstance(ring, list) or len(ring) < 4:
        raise InvalidGeometryError("Each linear ring must contain at least 4 positions")
    coords = [_validate_position(p) for p in ring]
    if coords[0] != coords[-1]:
        raise InvalidGeometryError("Linear ring must be closed (first position == last position)")
    if len(set(coords[:-1])) < 3:
        raise InvalidGeometryError("Linear ring must have at least 3 distinct vertices")
    return coords


def _spherical_ring_area_km2(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in itertools.pairwise(ring):
        total += math.radians(lon2 - lon1) * (
            2.0 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        )
    return abs((total * _EARTH_RADIUS_KM * _EARTH_RADIUS_KM) / 2.0)


def _measure_polygon(rings_raw: Any) -> tuple[list[list[list[float]]], float]:
    if not isinstance(rings_raw, list) or not rings_raw:
        raise InvalidGeometryError("Polygon must contain an exterior linear ring")
    rings = [_validate_ring(r) for r in rings_raw]
    area = _spherical_ring_area_km2(rings[0]) - sum(
        _spherical_ring_area_km2(hole) for hole in rings[1:]
    )
    if area <= 0.0:
        raise InvalidGeometryError("Polygon must have a positive non-zero area")
    return [[[lon, lat] for lon, lat in ring] for ring in rings], area


def validate_and_measure_geometry(
    geometry: dict[str, Any],
) -> tuple[dict[str, Any], GeometryMetrics]:
    """Validate GeoJSON Polygon/MultiPolygon in EPSG:4326 and compute spatial metrics."""
    if not isinstance(geometry, dict):
        raise InvalidGeometryError("Geometry must be a GeoJSON object")
    geom_type, coords = geometry.get("type"), geometry.get("coordinates")

    if geom_type == "Polygon":
        norm_poly, area = _measure_polygon(coords)
        polygons, normalized = [norm_poly], {"type": "Polygon", "coordinates": norm_poly}
    elif geom_type == "MultiPolygon":
        if not isinstance(coords, list) or not coords:
            raise InvalidGeometryError("MultiPolygon must contain at least one Polygon")
        measured = [_measure_polygon(p) for p in coords]
        polygons = [p for p, _ in measured]
        area = sum(a for _, a in measured)
        normalized = {"type": "MultiPolygon", "coordinates": polygons}
    else:
        raise InvalidGeometryError("Geometry type must be 'Polygon' or 'MultiPolygon'")

    verts = [pt for poly in polygons for pt in poly[0][:-1]]
    lons, lats, n = [p[0] for p in verts], [p[1] for p in verts], len(verts)
    metrics = GeometryMetrics(
        approx_area_km2=round(area, 2),
        bbox=(round(min(lons), 4), round(min(lats), 4), round(max(lons), 4), round(max(lats), 4)),
        centroid=(round(sum(lons) / n, 4), round(sum(lats) / n, 4)),
        vertex_count=n,
        polygon_count=len(polygons),
    )
    return normalized, metrics
