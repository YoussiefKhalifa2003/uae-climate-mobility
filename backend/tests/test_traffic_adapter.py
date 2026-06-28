"""Hour-scoped traffic scaling for the time slider."""

from app.data.traffic_adapter import diurnal_traffic_factor, is_hour_near_now


def test_diurnal_traffic_factor_peaks_at_rush():
    morning = diurnal_traffic_factor(8.0)
    night = diurnal_traffic_factor(3.0)
    assert morning > night
    assert 0.1 <= night <= 1.0
    assert 0.1 <= morning <= 1.0


def test_is_hour_near_now_current():
    from app.data.traffic_adapter import current_uae_hour

    assert is_hour_near_now(current_uae_hour()) is True
    assert is_hour_near_now((current_uae_hour() + 6) % 24) is False
