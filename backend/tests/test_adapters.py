"""Tests for live weather adapter hour-matching."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.data import adapters


def test_env_for_hour_uses_current_near_now():
    tz = ZoneInfo("Asia/Dubai")
    now = datetime.now(tz)
    hour = now.hour + now.minute / 60.0

    bundle = {
        "fetched_at": 1.0,
        "wx_live": True,
        "weather": {
            "current": {
                "air_temp_c": 39.5,
                "relative_humidity": 42.0,
                "wind_speed_ms": 2.1,
                "wind_dir_deg": 300.0,
            },
            "hourly": {
                "time": [now.replace(minute=0, second=0, microsecond=0).isoformat()],
                "air_temp_c": [36.0],
                "relative_humidity": [50.0],
                "wind_speed_ms": [1.0],
                "wind_dir_deg": [270.0],
            },
        },
    }

    env = adapters._env_for_hour(bundle, hour)
    assert env["air_temp_c"] == 39.5
    assert env["wx_mode"] == "current"


def test_env_for_hour_uses_hourly_for_other_hours():
    tz = ZoneInfo("Asia/Dubai")
    target = datetime.now(tz).replace(hour=6, minute=0, second=0, microsecond=0)
    bundle = {
        "fetched_at": 1.0,
        "wx_live": True,
        "weather": {
            "current": {
                "air_temp_c": 39.5,
                "relative_humidity": 42.0,
                "wind_speed_ms": 2.1,
                "wind_dir_deg": 300.0,
            },
            "hourly": {
                "time": [target.isoformat()],
                "air_temp_c": [31.2],
                "relative_humidity": [58.0],
                "wind_speed_ms": [1.4],
                "wind_dir_deg": [280.0],
            },
        },
    }

    env = adapters._env_for_hour(bundle, 6.0)
    assert env["air_temp_c"] == 31.2
    assert env["wx_mode"] == "hourly"


@patch("app.data.adapters.settings")
@patch("app.data.adapters._fetch_open_meteo_bundle")
@patch("app.data.adapters._fetch_open_meteo_aq_bundle")
def test_invalidate_fields_on_live_refresh(mock_aq, mock_wx, mock_settings):
    from app.core import solar_comfort

    mock_settings.use_live_data = True
    mock_settings.env_refresh_s = 60.0
    mock_settings.timezone = "Asia/Dubai"

    tz = ZoneInfo("Asia/Dubai")
    now = datetime.now(tz)
    tstr = now.replace(minute=0, second=0, microsecond=0).isoformat()
    mock_wx.return_value = {
        "current": {
            "air_temp_c": 40.0,
            "relative_humidity": 40.0,
            "wind_speed_ms": 2.0,
            "wind_dir_deg": 300.0,
        },
        "hourly": {
            "time": [tstr],
            "air_temp_c": [40.0],
            "relative_humidity": [40.0],
            "wind_speed_ms": [2.0],
            "wind_dir_deg": [300.0],
        },
    }
    mock_aq.return_value = {
        "current": {"pm25_ug_m3": 30.0, "aqi": 50},
        "hourly": {"time": [tstr], "pm25_ug_m3": [30.0], "aqi": [50]},
    }

    solar_comfort._FIELDS[14.0] = object()  # type: ignore[assignment]
    adapters._cache.clear()
    try:
        adapters.get_environment(14.0, force_refresh=True)
        assert 14.0 not in solar_comfort._FIELDS
    finally:
        solar_comfort._FIELDS.pop(14.0, None)
