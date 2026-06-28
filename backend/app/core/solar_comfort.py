"""Module 2 - Solar geometry + Thermal-Comfort engine.

Pipeline:
  1. Solar position (azimuth/elevation) via pvlib, with a NOAA fallback.
  2. GPU raster shadow casting: ray-march a building-height raster along the
     sun vector to produce a city-wide sun/shade mask (CuPy, NumPy fallback).
  3. Thermal comfort per cell: Mean Radiant Temperature -> UTCI + WBGT, with
     heat-risk banding (pythermalcomfort if available, analytic fallback).
  4. Per-edge shade fractions for the router, and a full-day precompute so the
     UI time-slider is instant.

All heavy array math runs through ``app.core.compute.xp`` (GPU or CPU).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from app.config import settings
from app.core import compute
from app.core.geo_engine import get_geo
from app.data import cache

logger = logging.getLogger(__name__)

# Reference date for solar geometry (UAE summer extreme).
_REF_YEAR, _REF_MONTH, _REF_DAY = 2024, 7, 15

# Hours sampled for the full-day precompute (half-hourly).
_DAY_HOURS = [h / 2.0 for h in range(0, 48)]

try:
    from pythermalcomfort.models import utci as _ptc_utci  # type: ignore

    _HAS_PTC = True
except Exception:  # noqa: BLE001
    _HAS_PTC = False


# ----------------------------------------------------------------- solar


def solar_position(hour: float) -> tuple[float, float]:
    """Return (azimuth_deg, elevation_deg) for the configured center at `hour`."""
    try:
        import pandas as pd
        import pvlib

        tz = ZoneInfo(settings.timezone)
        minute = int(round((hour % 1) * 60)) % 60
        h = int(hour) % 24
        dt = datetime(_REF_YEAR, _REF_MONTH, _REF_DAY, h, minute, tzinfo=tz)
        idx = pd.DatetimeIndex([dt])
        sp = pvlib.solarposition.get_solarposition(idx, settings.center_lat, settings.center_lon)
        az = float(sp["azimuth"].iloc[0])
        el = float(sp["apparent_elevation"].iloc[0])
        return az, el
    except Exception as exc:  # noqa: BLE001
        logger.debug("pvlib unavailable (%s); NOAA fallback.", exc)
        return _solar_position_fallback(hour)


def _solar_position_fallback(hour: float) -> tuple[float, float]:
    """Compact NOAA solar-position approximation (deg)."""
    lat = math.radians(settings.center_lat)
    lon = settings.center_lon
    doy = datetime(_REF_YEAR, _REF_MONTH, _REF_DAY).timetuple().tm_yday
    frac = 2 * math.pi / 365.0 * (doy - 1 + (hour - 12) / 24.0)
    decl = (
        0.006918
        - 0.399912 * math.cos(frac)
        + 0.070257 * math.sin(frac)
        - 0.006758 * math.cos(2 * frac)
        + 0.000907 * math.sin(2 * frac)
        - 0.002697 * math.cos(3 * frac)
        + 0.00148 * math.sin(3 * frac)
    )
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(frac)
        - 0.032077 * math.sin(frac)
        - 0.014615 * math.cos(2 * frac)
        - 0.040849 * math.sin(2 * frac)
    )
    # Convert local clock hour to solar time (UAE tz offset +4).
    tz_offset = 4.0
    time_offset = eqtime + 4 * lon - 60 * tz_offset
    tst = hour * 60 + time_offset
    ha = math.radians(tst / 4.0 - 180.0)
    cos_zen = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zen = math.acos(cos_zen)
    el = 90.0 - math.degrees(zen)
    az_rad = math.atan2(
        -math.sin(ha),
        math.tan(decl) * math.cos(lat) - math.sin(lat) * math.cos(ha),
    )
    az = (math.degrees(az_rad) + 180.0) % 360.0
    return az, el


# ----------------------------------------------------- raster shadow casting


def _shift(arr, drow: int, dcol: int):
    """Shift a 2D array by (drow, dcol), zero-filling exposed edges."""
    xp = compute.xp
    out = xp.zeros_like(arr)
    h, w = arr.shape
    r0s, r0d = (max(0, -drow), max(0, drow))
    c0s, c0d = (max(0, -dcol), max(0, dcol))
    rh = h - abs(drow)
    cw = w - abs(dcol)
    if rh <= 0 or cw <= 0:
        return out
    out[r0d : r0d + rh, c0d : c0d + cw] = arr[r0s : r0s + rh, c0s : c0s + cw]
    return out


def shadow_mask(height_raster: np.ndarray, hour: float) -> np.ndarray:
    """Boolean mask (True = shaded). Ray-marches toward the sun on the GPU."""
    xp = compute.xp
    az, el = solar_position(hour)
    H = xp.asarray(height_raster, dtype=xp.float32)

    if el <= 0.5:  # sun at/below horizon -> everything is "shaded" (night)
        return compute.to_cpu(xp.ones(H.shape, dtype=bool))

    res = float(settings.raster_resolution_m)
    az_rad = math.radians(az)
    # Direction TOWARD the sun in pixel space (row 0 = north/maxy).
    dcol = math.sin(az_rad)
    drow = -math.cos(az_rad)
    tan_el = math.tan(math.radians(el))

    max_h = float(height_raster.max()) if height_raster.size else 0.0
    if max_h <= 0:
        return compute.to_cpu(xp.zeros(H.shape, dtype=bool))
    max_reach_m = max_h / max(tan_el, 1e-3)
    steps = int(min(500, math.ceil(max_reach_m / res)))

    shaded = xp.zeros(H.shape, dtype=bool)
    for k in range(1, steps + 1):
        orow = int(round(k * drow))
        ocol = int(round(k * dcol))
        if orow == 0 and ocol == 0:
            continue
        ray_h = k * res * tan_el  # height of sun ray above ground at this cell
        blocker = _shift(H, orow, ocol)
        shaded |= blocker > ray_h
    return compute.to_cpu(shaded)


# ------------------------------------------------------------ thermal comfort


def mean_radiant_temp(t_air: float, shaded_mask: np.ndarray, elevation_deg: float) -> np.ndarray:
    """MRT raster (deg C): sunlit cells gain strong solar radiant load."""
    sun_factor = max(0.0, math.sin(math.radians(max(elevation_deg, 0.0))))
    sunlit_gain = 28.0 * sun_factor  # peak ~+28C radiant in open UAE midday
    shade_gain = 3.5  # longwave from warm ground/walls
    mrt = np.where(shaded_mask, t_air + shade_gain, t_air + sunlit_gain)
    return mrt.astype(np.float32)


def _utci_approx(t_air: float, mrt: np.ndarray, wind: float | np.ndarray, rh: float) -> np.ndarray:
    """Analytic UTCI surrogate (deg C) used when pythermalcomfort is absent."""
    w = np.asarray(wind, dtype=np.float32)
    v = np.clip(w, 0.5, 17.0)
    e = rh / 100.0 * 6.105 * np.exp(17.27 * t_air / (237.7 + t_air)) / 10.0  # kPa
    dtr = mrt - t_air
    utci = (
        t_air
        + 0.607 * (mrt - t_air)
        - 1.4 * (v - 0.5) ** 0.5
        + 0.35 * (e - 1.0)
        + 0.0009 * dtr * dtr * 0
    )
    return utci.astype(np.float32)


def utci_raster(t_air: float, mrt: np.ndarray, wind: float, rh: float) -> np.ndarray:
    if _HAS_PTC:
        try:
            flat = mrt.reshape(-1)
            # Sample distinct MRT values (only two: sun/shade) for speed.
            uniq = np.unique(np.round(flat, 2))
            lut = {}
            for m in uniq:
                res = _ptc_utci(tdb=t_air, tr=float(m), v=max(0.5, wind), rh=rh)
                lut[m] = float(res["utci"]) if isinstance(res, dict) else float(res)
            out = np.vectorize(lambda m: lut[round(m, 2)])(mrt)
            return out.astype(np.float32)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pythermalcomfort failed (%s); analytic UTCI.", exc)
    return _utci_approx(t_air, mrt, wind, rh)


def wbgt_estimate(t_air: float, rh: float, shaded_mask: np.ndarray, elevation_deg: float) -> np.ndarray:
    """Outdoor WBGT (deg C). BoM shade approximation + solar increment."""
    e = rh / 100.0 * 6.105 * math.exp(17.27 * t_air / (237.7 + t_air))  # hPa
    wbgt_shade = 0.567 * t_air + 0.393 * e + 3.94
    solar_inc = 4.0 * max(0.0, math.sin(math.radians(max(elevation_deg, 0.0))))
    out = np.where(shaded_mask, wbgt_shade, wbgt_shade + solar_inc)
    return out.astype(np.float32)


_UTCI_BANDS = [
    (26.0, "Comfortable"),
    (32.0, "Moderate"),
    (38.0, "Strong"),
    (46.0, "Very Strong"),
    (float("inf"), "Extreme"),
]


def heat_risk_band(utci_value: float) -> str:
    for thresh, label in _UTCI_BANDS:
        if utci_value < thresh:
            return label
    return "Extreme"


def heat_risk_score(utci_value: float) -> float:
    """Continuous 0-100 risk from UTCI (clamped around 20-50 C)."""
    return float(max(0.0, min(100.0, (utci_value - 20.0) / 30.0 * 100.0)))


# --------------------------------------------------------------- comfort field


@dataclass
class HourlyField:
    hour: float
    azimuth: float
    elevation: float
    t_air: float
    shaded: np.ndarray  # bool raster
    utci: np.ndarray  # float raster
    wbgt: np.ndarray  # float raster
    _edge_shade: dict | None = None  # uid -> shade fraction (0..1); lazy

    @property
    def edge_shade(self) -> dict:
        """Per-edge shade fractions, computed lazily on first access.

        This is only needed for routing, not for the heat-raster display, so we
        keep it out of the fast day-precompute path.
        """
        if self._edge_shade is None:
            self._edge_shade = _compute_edge_shade(self.shaded, get_geo().transform)
        return self._edge_shade


_FIELDS: dict[float, HourlyField] = {}


def invalidate_fields() -> None:
    """Drop cached UTCI rasters so the next request uses fresh live weather."""
    _FIELDS.clear()


def _row_col(transform, x: float, y: float) -> tuple[int, int]:
    # transform: Affine(res,0,minx,0,-res,maxy) -> col=(x-minx)/res, row=(maxy-y)/res
    col = int((x - transform.c) / transform.a)
    row = int((y - transform.f) / transform.e)
    return row, col


def _compute_edge_shade(shaded: np.ndarray, transform) -> dict:
    gd = get_geo()
    edges = gd.edges
    if edges is None or not len(edges):
        return {}
    h, w = shaded.shape
    out: dict[str, float] = {}
    for uid, geom in zip(edges["uid"], edges.geometry):
        try:
            length = geom.length
            n = max(2, int(length / 8.0))
            shaded_count = 0
            total = 0
            for i in range(n + 1):
                pt = geom.interpolate(i / n, normalized=True)
                r, c = _row_col(transform, pt.x, pt.y)
                if 0 <= r < h and 0 <= c < w:
                    total += 1
                    if shaded[r, c]:
                        shaded_count += 1
            out[uid] = shaded_count / total if total else 0.0
        except Exception:  # noqa: BLE001
            out[uid] = 0.0
    return out


def compute_hour(hour: float, env: dict | None = None) -> HourlyField:
    """Compute (and cache in-process) the comfort field for one hour."""
    if hour in _FIELDS:
        return _FIELDS[hour]
    from app.data.adapters import get_environment

    env = env or get_environment(hour)
    gd = get_geo()
    az, el = solar_position(hour)
    t_air = env["air_temp_c"]
    rh = env["relative_humidity"]
    wind = env["wind_speed_ms"]

    shaded = shadow_mask(gd.height_raster, hour)
    mrt = mean_radiant_temp(t_air, shaded, el)
    try:
        from app.core.wind_cfd import wind_speed_grid

        wgrid = wind_speed_grid(hour)
    except Exception:  # noqa: BLE001
        wgrid = None
    if wgrid is not None and wgrid.shape == mrt.shape:
        utci = _utci_approx(t_air, mrt, np.clip(wgrid, 0.5, 17.0), rh)
    else:
        utci = utci_raster(t_air, mrt, wind, rh)
    wbgt = wbgt_estimate(t_air, rh, shaded, el)

    # edge_shade is computed lazily (only routing needs it) to keep the
    # day-precompute and time-slider fast.
    field = HourlyField(
        hour=hour,
        azimuth=az,
        elevation=el,
        t_air=t_air,
        shaded=shaded,
        utci=utci,
        wbgt=wbgt,
    )
    _FIELDS[hour] = field
    return field


def get_field(hour: float) -> HourlyField:
    # snap to nearest half hour we precompute
    snapped = round(hour * 2) / 2.0
    return compute_hour(snapped)


def precompute_day() -> None:
    """Warm the half-hourly comfort fields (uses GPU when present)."""
    logger.info("Precomputing daily comfort fields (%d slots)...", len(_DAY_HOURS))
    for h in _DAY_HOURS:
        compute_hour(h)
    logger.info("Daily comfort precompute complete.")


def sample_point(lat: float, lon: float, hour: float) -> dict:
    """Comfort + shade at a single coordinate."""
    from pyproj import Transformer

    gd = get_geo()
    field = get_field(hour)
    t = Transformer.from_crs("EPSG:4326", f"EPSG:{gd.utm_epsg}", always_xy=True)
    x, y = t.transform(lon, lat)
    r, c = _row_col(gd.transform, x, y)
    h, w = field.shaded.shape
    if not (0 <= r < h and 0 <= c < w):
        return {"shaded": False, "utci": field.t_air, "wbgt": field.t_air, "band": "Unknown"}
    u = float(field.utci[r, c])
    return {
        "shaded": bool(field.shaded[r, c]),
        "utci": u,
        "wbgt": float(field.wbgt[r, c]),
        "band": heat_risk_band(u),
        "score": heat_risk_score(u),
    }


def sample_utm(x: float, y: float, hour: float) -> dict:
    """Fast comfort lookup by UTM coords (no coordinate transforms)."""
    gd = get_geo()
    field = get_field(hour)
    r, c = _row_col(gd.transform, x, y)
    h, w = field.shaded.shape
    if not (0 <= r < h and 0 <= c < w):
        return {"shaded": False, "utci": field.t_air, "wbgt": field.t_air, "band": "Unknown", "score": 0.0}
    u = float(field.utci[r, c])
    return {
        "shaded": bool(field.shaded[r, c]),
        "utci": u,
        "wbgt": float(field.wbgt[r, c]),
        "band": heat_risk_band(u),
        "score": heat_risk_score(u),
    }


def comfort_raster_payload(hour: float) -> dict:
    """Downsampled UTCI raster + bounds for the frontend BitmapLayer."""
    gd = get_geo()
    field = get_field(hour)
    utci = field.utci
    # Downsample to keep payload light.
    step = max(1, max(utci.shape) // 256)
    small = utci[::step, ::step]
    return {
        "hour": hour,
        "azimuth": field.azimuth,
        "elevation": field.elevation,
        "shape": list(small.shape),
        "utci_min": float(small.min()),
        "utci_max": float(small.max()),
        "values": small.round(2).flatten().tolist(),
        "bounds_wgs84": _bounds_wgs(gd),
    }


def _bounds_wgs(gd) -> dict:
    from pyproj import Transformer

    minx, miny, maxx, maxy = gd.bounds_utm
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    west, south = t.transform(minx, miny)
    east, north = t.transform(maxx, maxy)
    return {"west": west, "south": south, "east": east, "north": north}
