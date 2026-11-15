"""Source catalog and official product policy exports."""

from terra_scientific.sources.catalog import (
    MODIS_SINUSOIDAL_PROJ4,
    MODIS_SINUSOIDAL_WKT,
    SOURCE_REGISTRY,
    SourceProductSpec,
    assert_quantitative_source_allowed,
    get_qa_policy,
    get_source_spec,
)

__all__ = [
    "MODIS_SINUSOIDAL_PROJ4",
    "MODIS_SINUSOIDAL_WKT",
    "SOURCE_REGISTRY",
    "SourceProductSpec",
    "assert_quantitative_source_allowed",
    "get_qa_policy",
    "get_source_spec",
]
