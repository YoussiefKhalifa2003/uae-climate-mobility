"""Tests for Phase 5-lite wind field."""

from app.core.wind_cfd import compute_wind_field, invalidate_wind_cache


def test_wind_field_has_grid():
    invalidate_wind_cache()
    f = compute_wind_field(14.0, force=True)
    assert f["shape"][0] > 0
    assert len(f["speed_ms"]) == f["shape"][0] * f["shape"][1]
    assert f["speed_max"] >= f["speed_min"]
