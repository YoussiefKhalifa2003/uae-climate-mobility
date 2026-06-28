"""Tests for Urban Exposure World Model v1."""

from app.core.exposure_world_model import _slot_summary


def test_slot_summary_from_timeline():
    horizon = {
        "peak_utci": 42.0,
        "safe_window_min": 12.0,
        "timeline": [
            {"utci": 30.0, "shade_pct": 100.0, "pm25": 20.0, "overlap_score": 0.2},
            {"utci": 42.0, "shade_pct": 0.0, "pm25": 60.0, "overlap_score": 0.7},
        ],
    }
    s = _slot_summary(horizon)
    assert s["peak_utci"] == 42.0
    assert s["mean_utci"] == 36.0
    assert s["shade_pct"] == 50.0
    assert s["mean_pm25"] == 40.0
    assert s["stress_score"] == 0.45


def test_slot_summary_empty_timeline():
    s = _slot_summary({"peak_utci": 35.0, "safe_window_min": 5.0, "timeline": []})
    assert s["mean_utci"] == 35.0
    assert s["shade_pct"] == 0.0
