"""Unit tests for Scientific Core method registry and P0/P1/P2 status boundaries."""

from terra_scientific.domain.enums import PriorityTier
from terra_scientific.methods.registry import DEFAULT_METHOD_REGISTRY


def test_method_registry_tracks_implemented_p0_p1_and_deferred_p2() -> None:
    mk = DEFAULT_METHOD_REGISTRY.get("mann_kendall")
    assert mk.priority == PriorityTier.P0
    assert mk.implemented is True
    assert mk.version == "1.0.0"

    smk = DEFAULT_METHOD_REGISTRY.get("seasonal_mann_kendall")
    assert smk.priority == PriorityTier.P0
    assert smk.implemented is True

    sens = DEFAULT_METHOD_REGISTRY.get("sens_slope")
    assert sens.priority == PriorityTier.P0
    assert sens.implemented is True

    pettitt = DEFAULT_METHOD_REGISTRY.get("pettitt_change_point")
    assert pettitt.priority == PriorityTier.P1
    assert pettitt.implemented is True

    bh = DEFAULT_METHOD_REGISTRY.get("benjamini_hochberg_fdr")
    assert bh.priority == PriorityTier.P1
    assert bh.implemented is True

    tri = DEFAULT_METHOD_REGISTRY.get("composite_tri")
    assert tri.priority == PriorityTier.P2
    assert tri.implemented is False
    assert "unvalidated" in tri.limitations[0].lower() or "withheld" in tri.limitations[0].lower()

    csd = DEFAULT_METHOD_REGISTRY.get("critical_slowing_down")
    assert csd.priority == PriorityTier.P2
    assert csd.implemented is False


def test_method_registry_lists_deterministic_metadata_without_blank_citations() -> None:
    implemented = DEFAULT_METHOD_REGISTRY.list_implemented()
    assert len(implemented) >= 12
    for spec in implemented:
        assert spec.name
        assert spec.version
        assert spec.reference
        assert len(spec.assumptions) >= 1
