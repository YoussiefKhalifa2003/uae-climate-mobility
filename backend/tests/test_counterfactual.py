"""Tests for Phase 3 counterfactual twin."""

from app.core import analytics
from app.core.geo_engine import get_geo, sector_meta


def test_counterfactual_twin_reduces_utci():
    uids = list(get_geo().edges["uid"].head(20))
    res = analytics.counterfactual_twin(uids, 0.8, 14.0)
    assert res["scenario"]["avg_utci_c"] <= res["baseline"]["avg_utci_c"]
    assert res["delta"]["edges_targeted"] == 20
    assert res["target_baseline"] is not None
    assert res["target_scenario"]["avg_utci_c"] < res["target_baseline"]["avg_utci_c"]
    assert res["delta"]["target_avg_utci_reduction_c"] > 0
    assert len(res["affected_segments"]["features"]) == 20


def test_counterfactual_isochrone_gain():
    b = sector_meta()["bounds_wgs84"]
    origin = {"lat": (b["south"] + b["north"]) / 2, "lon": (b["west"] + b["east"]) / 2}
    uids = list(get_geo().edges["uid"].head(15))
    res = analytics.counterfactual_twin(
        uids, 0.9, 14.0, origin=origin, isochrone_minutes=10, profile="default"
    )
    assert res["isochrone"] is not None
    assert res["isochrone"]["scenario_area_km2"] >= res["isochrone"]["baseline_area_km2"]
