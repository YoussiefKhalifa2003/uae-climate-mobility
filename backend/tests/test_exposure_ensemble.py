"""Tests for Phase 2 exposure ensemble bands."""

from app.core.exposure_ensemble import attach_timeline_bands, slot_band_summary


def test_attach_timeline_bands():
    timeline = [{"t_min": 0, "utci": 36.0, "pm25": 40.0, "shade_pct": 0}]
    env_p50 = {"air_temp_c": 38.0, "pm25_ug_m3": 40.0}
    env_p95 = {"air_temp_c": 40.0, "pm25_ug_m3": 50.0}
    out = attach_timeline_bands(timeline, env_p50, env_p95)
    assert out[0]["utci_p50"] == 36.0
    assert out[0]["utci_p95"] > 36.0
    assert out[0]["pm25_p95"] > 40.0


def test_slot_band_summary_confidence():
    timeline = attach_timeline_bands(
        [{"t_min": i, "utci": 34.0 + i * 0.5, "pm25": 30.0, "shade_pct": 20} for i in range(10)],
        {"air_temp_c": 38.0, "pm25_ug_m3": 30.0},
        {"air_temp_c": 40.0, "pm25_ug_m3": 38.0},
    )
    s = slot_band_summary(timeline, warn_utci=38.0, critical_utci=46.0)
    assert "confidence_pct" in s
    assert s["peak_utci_p95"] >= s["peak_utci_p50"]
