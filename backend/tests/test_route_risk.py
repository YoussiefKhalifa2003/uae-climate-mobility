"""Tests for Phase 2 route-risk advisory."""

from app.core.router import _route_risk_recommendation


def test_recommends_safest_p95_when_peak_lower():
    options = [
        {"label": "Balanced", "confidence_pct": 62.0, "peak_utci_p95": 44.0, "duration_min": 18},
        {"label": "Safest (P95)", "confidence_pct": 58.0, "peak_utci_p95": 40.0, "duration_min": 20},
    ]
    label, advisory = _route_risk_recommendation(options, temp_spread_c=2.0)
    assert label == "Safest (P95)"
    assert "Safest (P95)" in advisory
    assert "±2.0°C" in advisory


def test_recommends_highest_confidence_by_default():
    options = [
        {"label": "Balanced", "confidence_pct": 72.0, "peak_utci_p95": 36.0, "duration_min": 18},
        {"label": "Coolest", "confidence_pct": 81.0, "peak_utci_p95": 35.0, "duration_min": 22},
    ]
    label, _ = _route_risk_recommendation(options, temp_spread_c=0.8)
    assert label == "Coolest"
