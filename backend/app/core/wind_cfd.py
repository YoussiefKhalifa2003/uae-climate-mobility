"""Phase 5-lite — GPU canyon wind field (empirical deflection, not full LBM).

Computes local wind speed/direction adjustments from building height raster
and synoptic wind from Open-Meteo.
"""

from __future__ import annotations

import logging
import math

import numpy as np

from app.core import compute
from app.core.geo_engine import get_geo
from app.data.adapters import get_environment

logger = logging.getLogger(__name__)

_cache: dict[float, dict] = {}


def _wind_components(speed_ms: float, wind_from_deg: float) -> tuple[float, float]:
    """Meteorological 'from' direction -> (u_east, v_north) m/s."""
    blow_to = math.radians((wind_from_deg + 180.0) % 360.0)
    return speed_ms * math.sin(blow_to), speed_ms * math.cos(blow_to)


def compute_wind_field(hour: float, *, force: bool = False) -> dict:
    """Return u/v/speed grids at ~1.5 m (surface layer proxy)."""
    key = round(hour * 2) / 2.0
    if not force and key in _cache:
        return _cache[key]

    gd = get_geo()
    env = get_environment(hour)
    u0, v0 = _wind_components(float(env["wind_speed_ms"]), float(env["wind_dir_deg"]))
    speed0 = max(0.5, float(env["wind_speed_ms"]))

    if gd.height_raster is None:
        shape = (64, 64)
        u = np.full(shape, u0, dtype=np.float32)
        v = np.full(shape, v0, dtype=np.float32)
    else:
        h = gd.height_raster.astype(np.float32)
        shape = h.shape
        xp = compute.xp
        hg = xp.asarray(h)

        # Sobel-like gradients for canyon orientation.
        pad = xp.pad(hg, 1, mode="edge")
        gx = (pad[1:-1, 2:] - pad[1:-1, :-2]) * 0.5
        gy = (pad[2:, 1:-1] - pad[:-2, 1:-1]) * 0.5
        gx, gy = compute.to_cpu(gx), compute.to_cpu(gy)

        # Along-canyon speed-up when gradient aligns with wind; wake in tall lee.
        u_base = np.full(shape, u0, dtype=np.float32)
        v_base = np.full(shape, v0, dtype=np.float32)
        wind_mag = max(speed0, 0.1)
        align = (gx * u0 + gy * v0) / (np.hypot(gx, gy + 1e-6) * wind_mag + 1e-6)
        align = np.clip(align, -1.0, 1.0)

        h_norm = h / max(float(h.max()), 20.0)
        # Parallel alleys: venturi speed-up; cross-wind tall buildings: wake stagnation.
        speed_mult = 1.0 + 0.35 * np.abs(align) - 0.45 * h_norm * (1.0 - np.abs(align))
        speed_mult = np.clip(speed_mult, 0.15, 2.2).astype(np.float32)

        u = (u_base * speed_mult).astype(np.float32)
        v = (v_base * speed_mult).astype(np.float32)

    speed = np.hypot(u, v).astype(np.float32)
    field = {
        "hour": hour,
        "shape": list(shape),
        "u_ms": u.flatten().tolist(),
        "v_ms": v.flatten().tolist(),
        "speed_ms": speed.flatten().tolist(),
        "synoptic_speed_ms": speed0,
        "synoptic_dir_deg": float(env["wind_dir_deg"]),
        "speed_min": round(float(speed.min()), 2),
        "speed_max": round(float(speed.max()), 2),
    }
    _cache[key] = field
    return field


def wind_speed_grid(hour: float) -> np.ndarray | None:
    f = compute_wind_field(hour)
    gd = get_geo()
    if gd.height_raster is None:
        return None
    return np.array(f["speed_ms"], dtype=np.float32).reshape(gd.height_raster.shape)


def sample_wind_utm(x: float, y: float, hour: float) -> dict:
    gd = get_geo()
    f = compute_wind_field(hour)
    env = get_environment(hour)
    if gd.height_raster is None or gd.transform is None:
        return {
            "u_ms": f["u_ms"][0] if f["u_ms"] else 0.0,
            "v_ms": f["v_ms"][0] if f["v_ms"] else 0.0,
            "speed_ms": env["wind_speed_ms"],
        }
    from rasterio.transform import rowcol

    row, col = rowcol(gd.transform, x, y)
    h, w = gd.height_raster.shape
    row = int(np.clip(row, 0, h - 1))
    col = int(np.clip(col, 0, w - 1))
    idx = row * w + col
    u = f["u_ms"][idx]
    v = f["v_ms"][idx]
    return {"u_ms": round(u, 3), "v_ms": round(v, 3), "speed_ms": round(math.hypot(u, v), 3)}


def wind_raster_payload(hour: float) -> dict:
    """Particle / arrow overlay payload."""
    from app.core.geo_engine import sector_meta

    f = compute_wind_field(hour)
    meta = sector_meta()
    return {
        "hour": hour,
        "shape": f["shape"],
        "u_ms": f["u_ms"],
        "v_ms": f["v_ms"],
        "speed_ms": f["speed_ms"],
        "speed_min": f["speed_min"],
        "speed_max": f["speed_max"],
        "bounds_wgs84": meta["bounds_wgs84"],
    }


def invalidate_wind_cache() -> None:
    _cache.clear()
