"""Hybrid environmental data layer.

One interface, two backends:
  * Simulation  - physics-based defaults; always works offline.
  * Live        - Open-Meteo (weather + air quality, keyless) and OpenWeather
                  Air Pollution (real AQI, needs OPENWEATHER_API_KEY).

Auto-selects live when reachable, otherwise falls back silently to simulation.
Results are cached briefly in-process to avoid hammering the APIs.
Live weather uses Open-Meteo *current* observations for "now" and hourly
forecast slots for other clock hours so UTCI stays hour-accurate.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.data import provenance

logger = logging.getLogger(__name__)

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_AQ = "https://air-quality-api.open-meteo.com/v1/air-quality"
_OPENWEATHER_AQ = "http://api.openweathermap.org/data/2.5/air_pollution"

# OpenWeather AQI (1-5) -> US-style AQI midpoints + representative PM2.5
_OWM_AQI_MAP = {1: (25, 6.0), 2: (75, 20.0), 3: (125, 45.0), 4: (175, 90.0), 5: (300, 180.0)}

_cache: dict[str, tuple[float, dict]] = {}
# Prefer settings default; keep a sane floor for accuracy.
_TTL_S = max(60.0, min(settings.env_refresh_s, 120.0))

# Use current obs when the requested hour is within this window of now.
_NOW_WINDOW_S = 45 * 60


def _diurnal_temp(hour: float) -> float:
    """Simple diurnal curve around the configured ambient (peak ~15:00)."""
    base = settings.air_temp_c
    swing = 7.0
    phase = (hour - 9.0) / 24.0 * 2 * math.pi
    return base - swing * 0.5 + swing * 0.5 * math.sin(phase)


def _simulated(hour: float) -> dict:
    return {
        "source": "simulation",
        "air_temp_c": round(_diurnal_temp(hour), 1),
        "relative_humidity": settings.relative_humidity,
        "wind_speed_ms": settings.wind_speed_ms,
        "wind_dir_deg": settings.wind_dir_deg,
        "aqi": 110,
        "pm25_ug_m3": 38.0,
        "fetched_at": time.time(),
        "wx_live": False,
        "aq_live": False,
    }


def _parse_local_time(tstr: str, tz: ZoneInfo) -> datetime:
    """Parse Open-Meteo local timestamps (with or without offset)."""
    if tstr.endswith("Z"):
        return datetime.fromisoformat(tstr.replace("Z", "+00:00")).astimezone(tz)
    dt = datetime.fromisoformat(tstr)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _nearest_index(times: list[str], target: datetime, tz: ZoneInfo) -> int:
    if not times:
        return 0
    best_i = 0
    best_d = float("inf")
    for i, tstr in enumerate(times):
        dt = _parse_local_time(tstr, tz)
        d = abs((dt - target).total_seconds())
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _target_datetime(hour: float, tz: ZoneInfo) -> datetime:
    now = datetime.now(tz)
    h = int(hour) % 24
    minute = int(round((hour % 1) * 60)) % 60
    return now.replace(hour=h, minute=minute, second=0, microsecond=0)


def _fetch_open_meteo_bundle() -> dict | None:
    """Fetch current + hourly weather from Open-Meteo."""
    try:
        params = {
            "latitude": settings.center_lat,
            "longitude": settings.center_lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
            "forecast_days": 2,
            "wind_speed_unit": "ms",
            "timezone": settings.timezone,
        }
        r = httpx.get(_OPEN_METEO, params=params, timeout=settings.live_data_timeout_s)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current") or {}
        hourly = data.get("hourly") or {}
        if not hourly.get("time"):
            return None
        return {
            "current": {
                "air_temp_c": float(cur["temperature_2m"]),
                "relative_humidity": float(cur["relative_humidity_2m"]),
                "wind_speed_ms": float(cur["wind_speed_10m"]),
                "wind_dir_deg": float(cur["wind_direction_10m"]),
                "time": cur.get("time"),
            },
            "hourly": {
                "time": hourly["time"],
                "air_temp_c": [float(v) for v in hourly["temperature_2m"]],
                "relative_humidity": [float(v) for v in hourly["relative_humidity_2m"]],
                "wind_speed_ms": [float(v) for v in hourly["wind_speed_10m"]],
                "wind_dir_deg": [float(v) for v in hourly["wind_direction_10m"]],
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("Open-Meteo weather unavailable (%s)", exc)
        return None


def _fetch_open_meteo_aq_bundle() -> dict | None:
    """Keyless live PM2.5 + European AQI — current + hourly."""
    try:
        params = {
            "latitude": settings.center_lat,
            "longitude": settings.center_lon,
            "current": "pm2_5,pm10,european_aqi",
            "hourly": "pm2_5,european_aqi",
            "forecast_days": 2,
            "timezone": settings.timezone,
        }
        r = httpx.get(_OPEN_METEO_AQ, params=params, timeout=settings.live_data_timeout_s)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current", {})
        hourly = data.get("hourly") or {}
        pm25 = cur.get("pm2_5")
        if pm25 is None and not hourly.get("pm2_5"):
            return None
        out: dict = {}
        if pm25 is not None:
            out["current"] = {"pm25_ug_m3": float(pm25)}
            eu_aqi = cur.get("european_aqi")
            if eu_aqi is not None:
                out["current"]["aqi"] = int(eu_aqi)
        if hourly.get("time") and hourly.get("pm2_5"):
            out["hourly"] = {
                "time": hourly["time"],
                "pm25_ug_m3": [float(v) if v is not None else None for v in hourly["pm2_5"]],
                "aqi": [int(v) if v is not None else None for v in hourly.get("european_aqi", [])],
            }
        return out or None
    except Exception as exc:  # noqa: BLE001
        logger.info("Open-Meteo AQ unavailable (%s)", exc)
        return None


def _fetch_openweather_aq() -> dict | None:
    if not settings.openweather_api_key:
        return None
    try:
        params = {
            "lat": settings.center_lat,
            "lon": settings.center_lon,
            "appid": settings.openweather_api_key,
        }
        r = httpx.get(_OPENWEATHER_AQ, params=params, timeout=settings.live_data_timeout_s)
        r.raise_for_status()
        item = r.json()["list"][0]
        owm_aqi = int(item["main"]["aqi"])
        aqi, pm25 = _OWM_AQI_MAP.get(owm_aqi, (110, 38.0))
        pm25 = float(item["components"].get("pm2_5", pm25))
        return {"current": {"aqi": aqi, "pm25_ug_m3": pm25}}
    except Exception as exc:  # noqa: BLE001
        logger.info("OpenWeather AQ unavailable (%s)", exc)
        return None


def _load_live_bundle(force_refresh: bool) -> dict:
    """Fetch or return cached live weather/AQ bundle."""
    ck = "env_live"
    now = time.time()
    if not force_refresh and ck in _cache and now - _cache[ck][0] < _TTL_S:
        return _cache[ck][1]

    bundle: dict = {"fetched_at": now, "wx_live": False, "aq_live": False}
    if settings.use_live_data:
        wx = _fetch_open_meteo_bundle()
        if wx:
            bundle["weather"] = wx
            bundle["wx_live"] = True

        aq = _fetch_open_meteo_aq_bundle()
        aq_src = "open-meteo-aq"
        if aq:
            bundle["air"] = aq
            bundle["aq_live"] = True
        else:
            ow = _fetch_openweather_aq()
            if ow:
                bundle["air"] = ow
                bundle["aq_live"] = True
                aq_src = "openweather"

        if bundle["wx_live"] and bundle["aq_live"]:
            bundle["source"] = f"live:open-meteo+{aq_src}"
        elif bundle["wx_live"]:
            bundle["source"] = "live:open-meteo"
        elif bundle["aq_live"]:
            bundle["source"] = f"live:{aq_src}"

    _cache[ck] = (now, bundle)

    if bundle.get("wx_live") or bundle.get("aq_live"):
        try:
            from app.core import solar_comfort

            solar_comfort.invalidate_fields()
        except Exception:  # noqa: BLE001
            pass

    return bundle


def _env_for_hour(bundle: dict, hour: float) -> dict:
    """Hour-matched live env from cached Open-Meteo bundle."""
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    target = _target_datetime(hour, tz)
    use_current = abs((target - now).total_seconds()) <= _NOW_WINDOW_S

    out: dict = {"fetched_at": bundle.get("fetched_at", time.time())}

    wx = bundle.get("weather")
    if wx and bundle.get("wx_live"):
        if use_current and wx.get("current"):
            cur = wx["current"]
            out.update(
                {
                    "air_temp_c": cur["air_temp_c"],
                    "relative_humidity": cur["relative_humidity"],
                    "wind_speed_ms": cur["wind_speed_ms"],
                    "wind_dir_deg": cur["wind_dir_deg"],
                }
            )
            out["wx_mode"] = "current"
        elif wx.get("hourly"):
            h = wx["hourly"]
            idx = _nearest_index(h["time"], target, tz)
            out.update(
                {
                    "air_temp_c": h["air_temp_c"][idx],
                    "relative_humidity": h["relative_humidity"][idx],
                    "wind_speed_ms": h["wind_speed_ms"][idx],
                    "wind_dir_deg": h["wind_dir_deg"][idx],
                }
            )
            out["wx_mode"] = "hourly"

    air = bundle.get("air")
    if air and bundle.get("aq_live"):
        if use_current and air.get("current"):
            out.update({k: v for k, v in air["current"].items() if v is not None})
            out["aq_mode"] = "current"
        elif air.get("hourly"):
            ah = air["hourly"]
            idx = _nearest_index(ah["time"], target, tz)
            pm25 = ah["pm25_ug_m3"][idx] if idx < len(ah["pm25_ug_m3"]) else None
            if pm25 is not None:
                out["pm25_ug_m3"] = pm25
            if ah.get("aqi") and idx < len(ah["aqi"]) and ah["aqi"][idx] is not None:
                out["aqi"] = ah["aqi"][idx]
            out["aq_mode"] = "hourly"

    return out


def get_live_pm25() -> float | None:
    """Latest live PM2.5 at sector center (for air model calibration)."""
    snap = get_environment()
    return snap.get("pm25_ug_m3")


def get_environment(hour: float = 14.0, force_refresh: bool = False) -> dict:
    """Return environmental snapshot for `hour` (live hourly forecast when possible)."""
    snap = _simulated(hour)
    wx_live = False
    aq_live = False

    if settings.use_live_data:
        bundle = _load_live_bundle(force_refresh)
        live = _env_for_hour(bundle, hour)
        if live:
            snap.update({k: v for k, v in live.items() if k not in ("fetched_at", "wx_mode", "aq_mode")})
            snap["fetched_at"] = live.get("fetched_at", time.time())
        wx_live = bundle.get("wx_live", False)
        aq_live = bundle.get("aq_live", False)
        if bundle.get("source"):
            snap["source"] = bundle["source"]
            if wx_live and live.get("wx_mode") == "hourly":
                snap["source"] = str(snap["source"]).replace("live:open-meteo", "live:open-meteo-hourly", 1)

    snap["wx_live"] = wx_live
    snap["aq_live"] = aq_live

    provenance.set_source(
        "weather",
        "Weather (top bar)",
        snap["source"] if wx_live else "simulation",
        wx_live,
        f"{snap['air_temp_c']}°C · RH {snap['relative_humidity']:.0f}% · wind {snap['wind_speed_ms']:.1f} m/s",
    )
    provenance.set_source(
        "aqi_point",
        "AQI / PM2.5 (top bar)",
        snap["source"] if aq_live else "simulation (AQI=110 default)",
        aq_live,
        f"PM2.5 {snap.get('pm25_ug_m3', '?')} µg/m³ · AQI {snap.get('aqi', '?')}",
    )
    return snap


def get_env_scenarios(hour: float, force_refresh: bool = False) -> dict[str, dict]:
    """Central (P50) and stress (P95/P05) env scenarios from hourly forecast spread."""
    p50 = get_environment(hour, force_refresh=force_refresh)
    h_lo = get_environment((hour - 0.5) % 24.0, force_refresh=False)
    h_hi = get_environment((hour + 0.5) % 24.0, force_refresh=False)

    temps = [float(p50["air_temp_c"]), float(h_lo["air_temp_c"]), float(h_hi["air_temp_c"])]
    temp_spread = max(temps) - min(temps)
    temp_bump = max(1.2, temp_spread * 1.35)

    pm50 = float(p50.get("pm25_ug_m3") or 38.0)
    pm_vals = [pm50, float(h_lo.get("pm25_ug_m3") or pm50), float(h_hi.get("pm25_ug_m3") or pm50)]
    pm_bump = max(pm50 * 0.18, (max(pm_vals) - min(pm_vals)) * 1.4)

    p95 = dict(p50)
    p95["air_temp_c"] = round(float(p50["air_temp_c"]) + temp_bump, 1)
    p95["relative_humidity"] = min(98.0, float(p50["relative_humidity"]) + 4.0)
    p95["wind_speed_ms"] = max(0.5, float(p50["wind_speed_ms"]) * 0.82)
    p95["pm25_ug_m3"] = round(pm50 + pm_bump, 1)
    if p95.get("aqi") is not None:
        from app.core.air_quality import pm25_to_aqi

        p95["aqi"] = pm25_to_aqi(p95["pm25_ug_m3"])

    p05 = dict(p50)
    p05["air_temp_c"] = round(float(p50["air_temp_c"]) - temp_bump * 0.55, 1)
    p05["relative_humidity"] = max(5.0, float(p50["relative_humidity"]) - 3.0)
    p05["pm25_ug_m3"] = round(max(5.0, pm50 - pm_bump * 0.6), 1)

    return {"p50": p50, "p95": p95, "p05": p05, "temp_spread_c": round(temp_spread, 2)}


def live_station_snapshot() -> dict:
    """Single live monitoring point at sector center for map markers."""
    env = get_environment()
    return {
        "name": "Downtown Dubai · Live Monitor",
        "lat": settings.center_lat,
        "lon": settings.center_lon,
        "pm25_ug_m3": env.get("pm25_ug_m3"),
        "aqi": env.get("aqi"),
        "source": env.get("source", "simulation"),
        "live": env.get("wx_live", False) or env.get("aq_live", False),
        "updated_at": env.get("fetched_at", time.time()),
    }
