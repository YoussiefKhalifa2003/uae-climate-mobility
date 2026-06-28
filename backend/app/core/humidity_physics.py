"""Phase 6 — Coastal humidity trapping, dew point, and Humidex engine."""

from __future__ import annotations

import logging
import math

import numpy as np

from app.config import settings
from app.core import compute
from app.core.geo_engine import get_geo
from app.data.adapters import get_environment

logger = logging.getLogger(__name__)

# Physiological thresholds (Gulf coastal summer).
DEW_POINT_CRITICAL_C = 28.0
HUMIDEX_DANGER_C = 45.0


def dew_point_c(t_air_c: float, rh_pct: float) -> float:
    """Magnus approximation for dew point (°C)."""
    rh = max(1.0, min(100.0, rh_pct))
    a = 17.27
    b = 237.7
    alpha = (a * t_air_c) / (b + t_air_c) + math.log(rh / 100.0)
    return (b * alpha) / (a - alpha)


def humidex_c(t_air_c: float, rh_pct: float) -> float:
    """Canadian Humidex from dry bulb + RH."""
    td = dew_point_c(t_air_c, rh_pct)
    e = 6.11 * math.exp(5417.7530 * ((1.0 / 273.16) - (1.0 / (td + 273.16))))
    return t_air_c + 0.5555 * (e - 10.0)


def evaporative_failure(dew_point: float, humidex: float) -> bool:
    return dew_point >= DEW_POINT_CRITICAL_C or humidex >= HUMIDEX_DANGER_C


def _canyon_aspect_factor(height_raster: np.ndarray) -> np.ndarray:
    """Proxy for street-canyon trapping: tall surroundings + low local height."""
    h = height_raster.astype(np.float32)
    pad = np.pad(h, 1, mode="edge")
    local_mean = (
        pad[:-2, :-2] + pad[:-2, 1:-1] + pad[:-2, 2:]
        + pad[1:-1, :-2] + pad[1:-1, 1:-1] + pad[1:-1, 2:]
        + pad[2:, :-2] + pad[2:, 1:-1] + pad[2:, 2:]
    ) / 9.0
    return np.clip((local_mean - h) / 40.0, 0.0, 1.0).astype(np.float32)


def compute_humidity_field(hour: float, *, wind_speed_grid: np.ndarray | None = None) -> dict:
    """Grid of RH, dew point, humidex, and trapping factor for the sector."""
    gd = get_geo()
    env = get_environment(hour)
    t_air = float(env["air_temp_c"])
    rh_base = float(env["relative_humidity"])

    if gd.height_raster is None:
        shape = (64, 64)
        canyon = np.zeros(shape, dtype=np.float32)
    else:
        shape = gd.height_raster.shape
        canyon = _canyon_aspect_factor(gd.height_raster)

    if wind_speed_grid is not None and wind_speed_grid.shape == shape:
        stagnation = np.clip(1.0 - wind_speed_grid / max(float(wind_speed_grid.max()), 0.5), 0.0, 1.0)
    else:
        stagnation = np.full(shape, 0.35, dtype=np.float32)

    trap = canyon * stagnation
    rh_grid = np.clip(rh_base + trap * 15.0, rh_base, 98.0).astype(np.float32)
    dew_grid = np.vectorize(dew_point_c)(t_air, rh_grid).astype(np.float32)
    humidex_grid = np.vectorize(humidex_c)(t_air, rh_grid).astype(np.float32)
    failure = (dew_grid >= DEW_POINT_CRITICAL_C) | (humidex_grid >= HUMIDEX_DANGER_C)

    return {
        "hour": hour,
        "shape": list(shape),
        "t_air_c": t_air,
        "rh_base_pct": rh_base,
        "dew_point_critical_c": DEW_POINT_CRITICAL_C,
        "humidex_danger_c": HUMIDEX_DANGER_C,
        "values": {
            "rh_pct": rh_grid.flatten().tolist(),
            "dew_point_c": dew_grid.flatten().tolist(),
            "humidex_c": humidex_grid.flatten().tolist(),
            "trap_factor": trap.flatten().tolist(),
            "evaporative_failure": failure.flatten().astype(np.float32).tolist(),
        },
        "stats": {
            "rh_max_pct": round(float(rh_grid.max()), 1),
            "dew_point_max_c": round(float(dew_grid.max()), 1),
            "humidex_max_c": round(float(humidex_grid.max()), 1),
            "failure_pct": round(float(failure.mean()) * 100.0, 1),
        },
    }


def humidity_raster_payload(hour: float, wind_speed_grid: np.ndarray | None = None) -> dict:
    """Frontend-ready humidity overlay (mirrors comfort raster shape)."""
    field = compute_humidity_field(hour, wind_speed_grid=wind_speed_grid)
    gd = get_geo()
    from app.core.geo_engine import sector_meta

    meta = sector_meta()
    shape = field["shape"]
    rh = np.array(field["values"]["rh_pct"], dtype=np.float32).reshape(shape)
    return {
        "hour": hour,
        "shape": shape,
        "rh_min": round(float(rh.min()), 1),
        "rh_max": round(float(rh.max()), 1),
        "humidex_max": field["stats"]["humidex_max_c"],
        "failure_pct": field["stats"]["failure_pct"],
        "values": field["values"]["rh_pct"],
        "bounds_wgs84": meta["bounds_wgs84"],
        "stats": field["stats"],
    }


def sample_humidity_utm(x: float, y: float, hour: float, wind_speed_grid: np.ndarray | None = None) -> dict:
    """Point sample for routing enrichment."""
    gd = get_geo()
    env = get_environment(hour)
    t_air = float(env["air_temp_c"])
    rh_base = float(env["relative_humidity"])

    if gd.height_raster is None or gd.transform is None:
        trap = 0.2
        wind_local = float(env["wind_speed_ms"])
    else:
        from rasterio.transform import rowcol

        row, col = rowcol(gd.transform, x, y)
        h, w = gd.height_raster.shape
        if 0 <= row < h and 0 <= col < w:
            local_h = float(gd.height_raster[row, col])
            r0, r1 = max(0, row - 2), min(h, row + 3)
            c0, c1 = max(0, col - 2), min(w, col + 3)
            neigh = gd.height_raster[r0:r1, c0:c1]
            canyon = max(0.0, min(1.0, (float(neigh.mean()) - local_h) / 40.0))
            if wind_speed_grid is not None and wind_speed_grid.shape == gd.height_raster.shape:
                wind_local = float(wind_speed_grid[row, col])
            else:
                wind_local = float(env["wind_speed_ms"])
            stagnation = max(0.0, 1.0 - wind_local / max(float(env["wind_speed_ms"]), 0.5))
            trap = canyon * stagnation
        else:
            trap = 0.2
            wind_local = float(env["wind_speed_ms"])

    rh = min(98.0, rh_base + trap * 15.0)
    td = dew_point_c(t_air, rh)
    hx = humidex_c(t_air, rh)
    fail = evaporative_failure(td, hx)
    return {
        "rh_pct": round(rh, 1),
        "dew_point_c": round(td, 1),
        "humidex_c": round(hx, 1),
        "trap_factor": round(trap, 3),
        "evaporative_failure": fail,
        "wind_local_ms": round(wind_local if gd.height_raster is not None else env["wind_speed_ms"], 2),
    }


def routing_humidity_penalty(humidity_sample: dict, shade: float) -> float:
    """Extra cost multiplier when sweat evaporation fails — shade MRT still helps."""
    if not humidity_sample.get("evaporative_failure"):
        return 1.0
    # High humidity: shade less effective for *perceived* recovery; push indoor/refuge.
    shade_relief = 1.0 - 0.55 * float(shade)
    humidex_norm = max(0.0, min(1.0, (humidity_sample["humidex_c"] - 40.0) / 15.0))
    return 1.0 + shade_relief * humidex_norm * 0.85
