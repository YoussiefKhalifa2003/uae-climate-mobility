"""Module 3.5 - Air-Quality engine (emissions -> dispersion -> AQI + dose).

Turns the traffic emission grid into a PM2.5 concentration field using a
lightweight Gaussian-plume dispersion model: emissions are convolved with an
anisotropic kernel stretched downwind (FFT convolution on the GPU). The field
yields a US-EPA AQI raster and supports inhalation-dose sampling along any
path - the metric that actually matters for asthma/children.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

from app.config import settings
from app.core import compute
from app.core.geo_engine import get_geo
from app.core.traffic_sim import get_sim

logger = logging.getLogger(__name__)

# US EPA PM2.5 (24h) AQI breakpoints: (Clow, Chigh, Ilow, Ihigh)
_PM25_BP = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 500.4, 301, 500),
]

# Breathing rates (m^3/min) by activity intensity.
BREATHING_RATE = {
    "rest": 0.0125,
    "walk": 0.025,
    "bike": 0.045,
    "athlete": 0.06,
    "drive": 0.013,  # in-cabin, partially filtered
}


def pm25_to_aqi(pm: float) -> int:
    for clow, chigh, ilow, ihigh in _PM25_BP:
        if clow <= pm <= chigh:
            return int(round((ihigh - ilow) / (chigh - clow) * (pm - clow) + ilow))
    return 500


_pm25_to_aqi_vec = np.vectorize(pm25_to_aqi)


def _dispersion_kernel(size: int, wind_dir_deg: float, wind_speed: float):
    """Anisotropic plume kernel oriented downwind (in grid pixel space)."""
    xp = compute.xp
    # Meteorological wind_dir is the direction wind comes FROM; it blows toward +180.
    blow = math.radians((wind_dir_deg + 180.0) % 360.0)
    # Downwind unit vector in (col=east, row=north-up). Grid row 0 = south here.
    ux, uy = math.sin(blow), math.cos(blow)

    half = size // 2
    yy, xx = xp.meshgrid(
        xp.arange(size) - half, xp.arange(size) - half, indexing="ij"
    )
    xx = xx.astype(xp.float32)
    yy = yy.astype(xp.float32)
    # along = downwind distance, cross = perpendicular distance
    along = xx * ux + yy * uy
    cross = -xx * uy + yy * ux

    # Plume: decays downwind, spreads crosswind; near-zero upwind.
    decay_len = 6.0 + wind_speed * 2.5
    sigma_cross = 1.5 + 0.18 * xp.maximum(along, 0.0)
    k = xp.where(
        along >= 0,
        xp.exp(-along / decay_len) * xp.exp(-(cross**2) / (2 * sigma_cross**2)),
        xp.exp(along / 1.2) * xp.exp(-(cross**2) / (2 * 1.0**2)),  # slight upwind bleed
    )
    k = k / (k.sum() + 1e-9)
    return k


def _fft_convolve(field, kernel):
    """Same-size circular FFT convolution on the active backend."""
    xp = compute.xp
    fs = xp.fft.rfft2(field)
    # center the kernel for proper alignment
    ks = xp.fft.rfft2(xp.fft.ifftshift(kernel))
    out = xp.fft.irfft2(fs * ks, s=field.shape)
    return xp.real(out)


@dataclass
class AirField:
    pm25: np.ndarray  # [G,G] ug/m3
    aqi: np.ndarray  # [G,G] int
    bounds_utm: tuple[float, float, float, float]
    baseline_pm25: float
    max_pm25: float


_FIELD: AirField | None = None


def compute_field(env: dict | None = None) -> AirField:
    """Recompute the concentration field from the live emission grid."""
    from app.data.adapters import get_environment
    from app.data import provenance

    env = env or get_environment()
    sim = get_sim()
    xp = compute.xp

    emission = xp.asarray(sim.emission_grid_cpu())
    if float(emission.max()) <= 0:
        emission = emission + 1e-3

    try:
        from app.core.v2x_optimizer import get_v2x_scenario

        emission = emission * get_v2x_scenario().emission_scale()
    except Exception:  # noqa: BLE001
        pass

    kernel = _dispersion_kernel(emission.shape[0], env["wind_dir_deg"], env["wind_speed_ms"])
    conc = _fft_convolve(emission, kernel)
    conc = xp.clip(conc, 0.0, None)

    # Scale dispersed field to a plausible traffic PM2.5 increment.
    cmax = float(conc.max()) or 1.0
    traffic_increment = 60.0  # ug/m3 at the worst bottleneck
    conc_scaled = conc / cmax * traffic_increment

    baseline = float(env.get("pm25_ug_m3") or 38.0)
    pm25 = compute.to_cpu(conc_scaled) + baseline
    aqi = _pm25_to_aqi_vec(pm25).astype(np.int32)

    aq_live = "live" in str(env.get("source", ""))
    provenance.set_source(
        "air_map",
        "Air Quality (map layer)",
        "hybrid:live-baseline+traffic-plume" if aq_live else "simulated:traffic-plume",
        aq_live,
        f"Baseline PM2.5 {baseline:.1f} µg/m³ from {env.get('source', '?')} + Gaussian dispersion of traffic emissions",
    )

    global _FIELD
    _FIELD = AirField(
        pm25=pm25.astype(np.float32),
        aqi=aqi,
        bounds_utm=sim.bounds_utm,
        baseline_pm25=baseline,
        max_pm25=float(pm25.max()),
    )
    return _FIELD


def get_field(refresh: bool = False) -> AirField:
    if _FIELD is None or refresh:
        return compute_field()
    return _FIELD


def _cell_of(field: AirField, x: float, y: float) -> tuple[int, int]:
    minx, miny, maxx, maxy = field.bounds_utm
    g = field.pm25.shape[0]
    ix = int(np.clip((x - minx) / (maxx - minx) * g, 0, g - 1))
    iy = int(np.clip((y - miny) / (maxy - miny) * g, 0, g - 1))
    return iy, ix


def sample_pm25_utm(field: AirField, x: float, y: float) -> float:
    iy, ix = _cell_of(field, x, y)
    return float(field.pm25[iy, ix])


def inhaled_dose(
    coords_utm: list[tuple[float, float]],
    seg_lengths_m: list[float],
    speed_ms: float,
    activity: str = "walk",
) -> dict:
    """Estimate inhaled PM2.5 (micrograms) along a path.

    dose = sum(concentration[ug/m3] * breathing_rate[m3/min] * minutes_in_segment)
    """
    field = get_field()
    br = BREATHING_RATE.get(activity, BREATHING_RATE["walk"])
    total_ug = 0.0
    conc_sum = 0.0
    for (x, y), seg_len in zip(coords_utm, seg_lengths_m):
        conc = sample_pm25_utm(field, x, y)  # ug/m3
        minutes = (seg_len / max(speed_ms, 0.3)) / 60.0
        total_ug += conc * br * minutes
        conc_sum += conc * seg_len
    total_len = sum(seg_lengths_m) or 1.0
    avg_conc = conc_sum / total_len
    return {
        "inhaled_pm25_ug": round(total_ug, 2),
        "avg_pm25_ug_m3": round(avg_conc, 1),
        "avg_aqi": pm25_to_aqi(avg_conc),
    }


def heatmap_payload(max_points: int = 4000) -> dict:
    """Legacy point cloud for HeatmapLayer — prefer ``air_raster_payload``."""
    from pyproj import Transformer

    field = get_field()
    gd = get_geo()
    g = field.pm25.shape[0]
    minx, miny, maxx, maxy = field.bounds_utm
    cellx = (maxx - minx) / g
    celly = (maxy - miny) / g
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)

    step = max(1, g * g // max_points)
    pts = []
    flat = field.pm25.flatten()
    thresh = field.baseline_pm25 + 2.0  # only emit cells above background
    for idx in range(0, g * g, step):
        val = flat[idx]
        if val < thresh:
            continue
        iy, ix = divmod(idx, g)
        x = minx + (ix + 0.5) * cellx
        y = miny + (iy + 0.5) * celly
        lon, lat = t.transform(x, y)
        pts.append([round(lon, 6), round(lat, 6), round(float(val), 1)])
    return {
        "points": pts,
        "baseline_pm25": field.baseline_pm25,
        "max_pm25": field.max_pm25,
    }


def _bounds_wgs(gd) -> dict:
    from pyproj import Transformer

    minx, miny, maxx, maxy = gd.bounds_utm
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)
    west, south = t.transform(minx, miny)
    east, north = t.transform(maxx, maxy)
    return {"west": west, "south": south, "east": east, "north": north}


def _hotspots_from_raster(
    pm25: np.ndarray,
    gd,
    baseline: float,
    max_points: int = 900,
) -> list[list[float]]:
    """Peak pollution cells as [lon, lat, weight] for the frontend bloom layer."""
    from pyproj import Transformer

    h, w = pm25.shape
    minx, miny, maxx, maxy = gd.bounds_utm
    cellx = (maxx - minx) / w
    celly = (maxy - miny) / h
    t = Transformer.from_crs(f"EPSG:{gd.utm_epsg}", "EPSG:4326", always_xy=True)

    excess = pm25 - baseline
    thresh = float(np.percentile(excess, 72))  # top ~28 % of cells
    thresh = max(thresh, 4.0)
    flat = pm25.ravel()
    idxs = np.where(excess.ravel() >= thresh)[0]
    if idxs.size == 0:
        return []
    if idxs.size > max_points:
        idxs = idxs[np.argsort(flat[idxs])[-max_points:]]

    pts: list[list[float]] = []
    for idx in idxs:
        iy, ix = divmod(int(idx), w)
        x = minx + (ix + 0.5) * cellx
        y = miny + (iy + 0.5) * celly
        lon, lat = t.transform(x, y)
        weight = float(flat[idx] - baseline)
        pts.append([round(lon, 6), round(lat, 6), round(weight, 2)])
    return pts


def air_raster_payload(max_dim: int = 320) -> dict:
    """Full PM2.5 raster + bounds for the frontend BitmapLayer.

    Upsamples and smooths the coarse emission grid so the overlay fills the
    entire urban area with silky gradients instead of sparse blobs.
    """
    from scipy.ndimage import gaussian_filter, zoom

    field = get_field()
    gd = get_geo()
    pm25 = field.pm25.astype(np.float32)

    # Widen plumes slightly, then upscale for smooth full-area coverage.
    pm25 = gaussian_filter(pm25, sigma=1.4)
    g = pm25.shape[0]
    factor = max(1.0, max_dim / g)
    if factor > 1.05:
        pm25 = zoom(pm25, factor, order=3)
    pm25 = gaussian_filter(pm25, sigma=0.9)

    from app.data.adapters import live_station_snapshot

    return {
        "shape": list(pm25.shape),
        "pm25_min": float(pm25.min()),
        "pm25_max": float(pm25.max()),
        "baseline_pm25": field.baseline_pm25,
        "values": pm25.round(2).flatten().tolist(),
        "bounds_wgs84": _bounds_wgs(gd),
        "hotspots": _hotspots_from_raster(pm25, gd, field.baseline_pm25),
        "stations": [live_station_snapshot()],
        "source": "hybrid:live-baseline+traffic-plume",
    }
