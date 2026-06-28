"""Routing + analytics behaviour checks."""

from app.core import analytics, router
from app.core.geo_engine import sector_meta


def _od():
    b = sector_meta()["bounds_wgs84"]
    o = {"lat": b["south"] + (b["north"] - b["south"]) * 0.3, "lon": b["west"] + (b["east"] - b["west"]) * 0.3}
    d = {"lat": b["south"] + (b["north"] - b["south"]) * 0.7, "lon": b["west"] + (b["east"] - b["west"]) * 0.7}
    return o, d


def test_route_returns_labeled_options():
    o, d = _od()
    res = router.route(o, d, "walk", "default", 14.0)
    labels = {opt["label"] for opt in res["options"]}
    assert {"Fastest", "Coolest", "Cleanest Air", "Balanced", "Cool Refuge"} <= labels


def test_coolest_has_at_least_as_much_shade_as_fastest():
    o, d = _od()
    res = router.route(o, d, "walk", "default", 14.0)
    by = {opt["label"]: opt["metrics"] for opt in res["options"]}
    assert by["Coolest"]["shade_pct"] >= by["Fastest"]["shade_pct"]


def test_cleanest_air_reduces_dose():
    o, d = _od()
    res = router.route(o, d, "walk", "asthma", 14.0)
    by = {opt["label"]: opt["metrics"] for opt in res["options"]}
    assert by["Cleanest Air"]["inhaled_pm25_ug"] <= by["Fastest"]["inhaled_pm25_ug"]


def test_profile_changes_walking_speed():
    o, d = _od()
    adult = router.route(o, d, "walk", "default", 14.0)["options"][0]["metrics"]["duration_min"]
    elderly = router.route(o, d, "walk", "elderly", 14.0)["options"][0]["metrics"]["duration_min"]
    assert elderly > adult  # elderly walk slower -> longer duration


def test_isochrone_returns_polygon():
    o, _ = _od()
    iso = analytics.comfort_isochrone(o, 10.0, 14.0, "default")
    assert iso["features"], "expected a reachable polygon"
    assert iso["features"][0]["properties"]["area_km2"] > 0


def test_route_includes_cvs_and_thermal_horizon():
    o, d = _od()
    res = router.route(o, d, "walk", "child", 14.0, live=False)
    opt = next(o for o in res["options"] if o["label"] == "Balanced")
    assert "cvs_score" in opt["metrics"]
    assert 0 <= opt["metrics"]["cvs_score"] <= 100
    assert opt.get("thermal_horizon") is not None
    assert len(opt["thermal_horizon"]["points"]) > 0
    assert len(opt["thermal_horizon"].get("timeline") or []) >= 1
    assert res.get("realtime") is not None


def test_exposure_for_label():
    o, d = _od()
    res = router.exposure_for_label(o, d, "walk", "child", 14.0, "Fastest", live=False)
    assert res is not None
    assert res["thermal_horizon"] is not None
    assert len(res["thermal_horizon"]["timeline"]) >= 1


def test_whatif_reduces_city_heat():
    from app.core.geo_engine import get_geo

    uids = list(get_geo().edges["uid"].head(30))
    res = analytics.what_if(uids, 0.8, 14.0)
    assert res["scenario_avg_utci_c"] <= res["baseline_avg_utci_c"]
