"""Air-quality dispersion + dose checks."""

from app.core import air_quality


def test_pm25_to_aqi_breakpoints():
    assert air_quality.pm25_to_aqi(0) == 0
    assert air_quality.pm25_to_aqi(12.0) == 50
    assert 50 < air_quality.pm25_to_aqi(20) < 100
    assert air_quality.pm25_to_aqi(1000) == 500


def test_dispersion_field_above_baseline():
    field = air_quality.compute_field()
    assert field.max_pm25 >= field.baseline_pm25
    assert field.pm25.min() > 0


def test_inhaled_dose_scales_with_exposure():
    air_quality.compute_field()
    coords = [(500000.0, 2780000.0)] * 5  # arbitrary in-grid points
    seg = [100.0] * 5
    slow = air_quality.inhaled_dose(coords, seg, speed_ms=0.7, activity="walk")
    fast = air_quality.inhaled_dose(coords, seg, speed_ms=3.0, activity="walk")
    # Slower walking through the same air inhales more.
    assert slow["inhaled_pm25_ug"] > fast["inhaled_pm25_ug"]
