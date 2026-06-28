"""Tests for Phase 8 intervention physics."""

from app.core.intervention_physics import (
    InterventionType,
    apply_intervention,
    dubai_walkability_index,
)


def test_solid_canopy_reduces_utci():
    new_utci, new_shade, meta = apply_intervention(
        base_utci=42.0,
        base_shade=0.1,
        hour=14.0,
        intervention=InterventionType.SOLID_CANOPY,
        intensity=1.0,
    )
    assert new_utci < 42.0
    assert new_shade > 0.1
    assert meta["intervention"] == "SolidCanopy"


def test_misting_drops_temperature():
    scen, _, meta = apply_intervention(
        base_utci=44.0,
        base_shade=0.0,
        hour=14.0,
        intervention=InterventionType.ACTIVE_MISTING,
        intensity=1.0,
    )
    assert scen < 44.0
    assert "t_air_delta_c" in meta


def test_walkability_index_increases_with_comfort():
    baseline = {
        "band_pct": {"Comfortable": 30.0},
        "dangerous_network_pct": 25.0,
        "avg_shade_pct": 20.0,
        "avg_utci_c": 40.0,
    }
    improved = {
        "band_pct": {"Comfortable": 55.0},
        "dangerous_network_pct": 10.0,
        "avg_shade_pct": 45.0,
        "avg_utci_c": 34.0,
    }
    b = dubai_walkability_index(baseline)
    s = dubai_walkability_index(improved, baseline_index=b["score"], iso_area_km2=0.5)
    assert s["score"] > b["score"]
    assert s["delta_vs_baseline"] is not None
