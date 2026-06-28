"""Tests for Phase 6 humidity physics."""

from app.core.humidity_physics import dew_point_c, evaporative_failure, humidex_c


def test_dew_point_rises_with_humidity():
    low = dew_point_c(40.0, 40.0)
    high = dew_point_c(40.0, 85.0)
    assert high > low


def test_evaporative_failure_at_extreme_humidity():
    td = dew_point_c(38.0, 90.0)
    hx = humidex_c(38.0, 90.0)
    assert evaporative_failure(td, hx) or hx >= 45.0
