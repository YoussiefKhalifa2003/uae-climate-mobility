"""Climate Vulnerability Score (CVS) and Thermal Horizon along routes.

CVS combines heat, shade, inhaled PM2.5, traffic delay, and profile weights
into a single 0–100 safety score (higher = safer for this traveller).

Thermal Horizon predicts UTCI / shade / PM2.5 minute-by-minute along a path
using moving sun geometry and live (or latest) environmental inputs.
"""

from __future__ import annotations

import math
from typing import Any

from app.core import solar_comfort
from app.core.air_quality import get_field, pm25_to_aqi, sample_pm25_utm

# Profile-specific UTCI alert thresholds (°C).
_PROFILE_THRESHOLDS: dict[str, dict[str, float]] = {
    "default": {"warn": 38.0, "critical": 46.0},
    "child": {"warn": 32.0, "critical": 38.0},
    "elderly": {"warn": 30.0, "critical": 35.0},
    "asthma": {"warn": 36.0, "critical": 42.0},
    "athlete": {"warn": 40.0, "critical": 48.0},
    "wheelchair": {"warn": 32.0, "critical": 38.0},
}

# CVS component weights per profile (must sum to 1.0).
_CVS_WEIGHTS: dict[str, dict[str, float]] = {
    "default": {"heat": 0.30, "shade": 0.25, "air": 0.25, "traffic": 0.20},
    "child": {"heat": 0.35, "shade": 0.30, "air": 0.20, "traffic": 0.15},
    "elderly": {"heat": 0.40, "shade": 0.30, "air": 0.15, "traffic": 0.15},
    "asthma": {"heat": 0.20, "shade": 0.15, "air": 0.45, "traffic": 0.20},
    "athlete": {"heat": 0.25, "shade": 0.15, "air": 0.30, "traffic": 0.30},
    "wheelchair": {"heat": 0.35, "shade": 0.30, "air": 0.20, "traffic": 0.15},
}

# Reference inhaled dose (µg) at which air component → 0.
_DOSE_REF_UG: dict[str, float] = {
    "default": 120.0,
    "child": 60.0,
    "elderly": 80.0,
    "asthma": 40.0,
    "athlete": 150.0,
    "wheelchair": 90.0,
}


def cvs_band(score: float) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 55:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "Critical"


def compute_cvs(metrics: dict, profile: str = "default") -> dict[str, Any]:
    """Return ``{score, band, components}`` for route metrics + profile."""
    weights = _CVS_WEIGHTS.get(profile, _CVS_WEIGHTS["default"])
    dose_ref = _DOSE_REF_UG.get(profile, 120.0)

    heat_sub = max(0.0, 100.0 - float(metrics.get("heat_risk_score", 50.0)))
    shade_sub = min(100.0, float(metrics.get("shade_pct", 0.0)))
    dose = float(metrics.get("inhaled_pm25_ug", 0.0))
    air_sub = max(0.0, 100.0 - min(100.0, dose / dose_ref * 100.0))

    dur = max(float(metrics.get("duration_min", 1.0)), 0.1)
    traffic_delay = float(metrics.get("traffic_delay_min", 0.0))
    traffic_sub = max(0.0, 100.0 - min(100.0, traffic_delay / dur * 100.0))

    components = {
        "heat": round(heat_sub, 1),
        "shade": round(shade_sub, 1),
        "air": round(air_sub, 1),
        "traffic": round(traffic_sub, 1),
    }

    score = sum(weights[k] * components[k] for k in weights)
    score = round(max(0.0, min(100.0, score)), 1)
    return {"score": score, "band": cvs_band(score), "components": components}


def _utci_path_color(utci: float) -> list[int]:
    """RGBA for map path segments from UTCI."""
    if utci < 26:
        return [74, 222, 128, 235]
    if utci < 32:
        return [250, 204, 21, 235]
    if utci < 38:
        return [251, 146, 60, 235]
    if utci < 46:
        return [248, 113, 113, 235]
    return [190, 24, 93, 235]


def _heat_stress_norm(utci: float, warn: float) -> float:
    return max(0.0, min(1.0, (utci - 26.0) / max(1.0, warn - 26.0 + 12.0)))


def _pm_stress_norm(pm25: float, baseline: float = 35.0) -> float:
    return max(0.0, min(1.0, (pm25 - baseline) / 80.0))


def _build_minute_timeline(
    kinematics: list[tuple[float, float, float, float, float]],
    start_hour: float,
    thresholds: dict[str, float],
    air,
) -> tuple[list[dict], list[dict]]:
    """Build 1-min exposure frames + heat×pollution intersection events."""
    if not kinematics:
        return [], []

    total_min = max(1, int(math.ceil(kinematics[-1][0])))
    timeline: list[dict] = []
    intersections: list[dict] = []
    prev_utci: float | None = None

    for m in range(total_min + 1):
        t = float(m)
        # Interpolate along piecewise-linear kinematics.
        lat, lon, x, y = kinematics[0][1], kinematics[0][2], kinematics[0][3], kinematics[0][4]
        for j in range(len(kinematics) - 1):
            t0, la0, lo0, x0, y0 = kinematics[j]
            t1, la1, lo1, x1, y1 = kinematics[j + 1]
            if t1 <= t0:
                continue
            if t0 <= t <= t1 or (j == len(kinematics) - 2 and t >= t1):
                u = 0.0 if t <= t0 else min(1.0, (t - t0) / (t1 - t0))
                lat = la0 + (la1 - la0) * u
                lon = lo0 + (lo1 - lo0) * u
                x = x0 + (x1 - x0) * u
                y = y0 + (y1 - y0) * u
                break

        city_hour = (start_hour + t / 60.0) % 24.0
        comfort = solar_comfort.sample_utm(x, y, city_hour)
        pm25 = float(sample_pm25_utm(air, x, y))
        utci = float(comfort["utci"])
        shaded = bool(comfort.get("shaded", False))
        utci_delta = round(utci - prev_utci, 1) if prev_utci is not None else 0.0

        heat_n = _heat_stress_norm(utci, thresholds["warn"])
        pm_n = _pm_stress_norm(pm25)
        overlap = round(min(1.0, heat_n * 0.55 + pm_n * 0.45 + (0.25 if utci_delta >= 5.0 else 0.0)), 3)
        is_intersection = overlap >= 0.55 and heat_n >= 0.45 and pm_n >= 0.35

        frame = {
            "t_min": m,
            "city_hour": round(city_hour, 3),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "utci": round(utci, 1),
            "utci_delta": utci_delta,
            "pm25": round(pm25, 1),
            "aqi": pm25_to_aqi(pm25),
            "shade_pct": 100.0 if shaded else 0.0,
            "band": comfort.get("band", solar_comfort.heat_risk_band(utci)),
            "overlap_score": overlap,
            "intersection": is_intersection,
        }
        timeline.append(frame)

        if is_intersection and not any(abs(ix["t_min"] - m) < 2 for ix in intersections):
            intersections.append(
                {
                    "t_min": m,
                    "city_hour": round(city_hour, 3),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "utci": round(utci, 1),
                    "pm25": round(pm25, 1),
                    "overlap_score": overlap,
                    "message": (
                        f"At minute {m}, heat stress ({utci:.0f}°C UTCI) and PM2.5 ({pm25:.0f} µg/m³) "
                        f"peak together — inhalation risk elevated."
                    ),
                }
            )

        prev_utci = utci

    return timeline, intersections[:6]


def thermal_horizon(
    graph,
    path: list,
    mode: str,
    profile: dict,
    start_hour: float,
    *,
    edge_speed_fn,
    congestion_map: dict[str, float] | None = None,
    path_coords_fn,
    edge_attr_fn,
    enrich: dict | None = None,
) -> dict[str, Any]:
    """Predict comfort along a route as the traveller moves and the sun shifts."""
    profile_name = profile.get("_name", "default")
    thresholds = _PROFILE_THRESHOLDS.get(profile_name, _PROFILE_THRESHOLDS["default"])
    cong_map = congestion_map or {}
    coords_ll, coords_xy, seg_lengths = path_coords_fn(graph, path)
    segs_static = edge_attr_fn(graph, path, enrich or {})

    air = get_field()
    elapsed_min = 0.0
    points: list[dict] = []
    alerts: list[dict] = []
    kinematics: list[tuple[float, float, float, float, float]] = []
    prev_utci: float | None = None
    prev_shaded: bool | None = None
    peak_utci = 0.0
    peak_at_min = 0.0
    critical_at_min: float | None = None

    if coords_ll:
        kinematics.append((0.0, coords_ll[0][1], coords_ll[0][0], coords_xy[0][0], coords_xy[0][1]))

    for i, (u, v) in enumerate(zip(path[:-1], path[1:])):
        data = graph.get_edge_data(u, v)
        k = min(data, key=lambda kk: data[kk].get("length", 1.0))
        length = data[k].get("length", 1.0)
        uid = f"{u}_{v}_{k}"
        kph = edge_speed_fn(graph, u, v, k, mode, profile)
        free_ms = max(kph / 3.6, 0.4)

        if mode == "drive":
            cong = cong_map.get(uid, 0.0)
            actual_ms = free_ms * (1.0 - cong * 0.68)
        else:
            static_utci = segs_static[i][1] if i < len(segs_static) else 35.0
            heat_pen = 1.0 + max(0.0, (static_utci - 30.0) / 12.0) * 0.35
            actual_ms = free_ms / heat_pen

        seg_min = length / max(actual_ms, 0.4) / 60.0
        mid_t = elapsed_min + seg_min / 2.0
        arrival_hour = (start_hour + mid_t / 60.0) % 24.0

        mid_x = (coords_xy[i][0] + coords_xy[i + 1][0]) / 2
        mid_y = (coords_xy[i][1] + coords_xy[i + 1][1]) / 2
        comfort = solar_comfort.sample_utm(mid_x, mid_y, arrival_hour)
        pm25 = float(sample_pm25_utm(air, mid_x, mid_y))
        utci = float(comfort["utci"])
        shaded = bool(comfort.get("shaded", False))
        shade_pct = 100.0 if shaded else 0.0

        lon, lat = coords_ll[i + 1] if i + 1 < len(coords_ll) else coords_ll[-1]
        band = comfort.get("band", solar_comfort.heat_risk_band(utci))

        points.append(
            {
                "t_min": round(mid_t, 1),
                "utci": round(utci, 1),
                "shade_pct": round(shade_pct, 1),
                "pm25": round(pm25, 1),
                "aqi": pm25_to_aqi(pm25),
                "band": band,
                "lat": lat,
                "lon": lon,
                "color": _utci_path_color(utci),
            }
        )

        if utci > peak_utci:
            peak_utci = utci
            peak_at_min = mid_t

        if critical_at_min is None and utci >= thresholds["critical"]:
            critical_at_min = mid_t
            alerts.append(
                {
                    "type": "critical_heat",
                    "severity": "critical",
                    "message": f"Critical heat ({utci:.0f}°C UTCI) in ~{mid_t:.0f} min",
                    "at_min": round(mid_t, 1),
                    "at_km": round(sum(seg_lengths[: i + 1]) / 1000.0, 2),
                }
            )
        elif utci >= thresholds["warn"] and not any(a["type"] == "heat_warning" for a in alerts):
            alerts.append(
                {
                    "type": "heat_warning",
                    "severity": "warning",
                    "message": f"Heat stress rising ({utci:.0f}°C UTCI) in ~{mid_t:.0f} min",
                    "at_min": round(mid_t, 1),
                    "at_km": round(sum(seg_lengths[: i + 1]) / 1000.0, 2),
                }
            )

        if prev_utci is not None and utci - prev_utci >= 5.0:
            alerts.append(
                {
                    "type": "heat_wall",
                    "severity": "warning",
                    "message": f"Heat wall ahead: +{utci - prev_utci:.0f}°C UTCI in ~{mid_t:.0f} min",
                    "at_min": round(mid_t, 1),
                    "at_km": round(sum(seg_lengths[: i + 1]) / 1000.0, 2),
                }
            )

        if prev_shaded is True and not shaded:
            alerts.append(
                {
                    "type": "shade_ends",
                    "severity": "info",
                    "message": f"Shade corridor ends in ~{mid_t:.0f} min",
                    "at_min": round(mid_t, 1),
                    "at_km": round(sum(seg_lengths[: i + 1]) / 1000.0, 2),
                }
            )

        if pm25 >= 75.0 and not any(a["type"] == "pollution_spike" for a in alerts):
            alerts.append(
                {
                    "type": "pollution_spike",
                    "severity": "warning",
                    "message": f"PM2.5 spike ({pm25:.0f} µg/m³) ahead in ~{mid_t:.0f} min",
                    "at_min": round(mid_t, 1),
                    "at_km": round(sum(seg_lengths[: i + 1]) / 1000.0, 2),
                }
            )

        prev_utci = utci
        prev_shaded = shaded
        elapsed_min += seg_min
        end_lat = coords_ll[i + 1][1] if i + 1 < len(coords_ll) else coords_ll[-1][1]
        end_lon = coords_ll[i + 1][0] if i + 1 < len(coords_ll) else coords_ll[-1][0]
        end_x = coords_xy[i + 1][0]
        end_y = coords_xy[i + 1][1]
        kinematics.append((elapsed_min, end_lat, end_lon, end_x, end_y))

    safe_window_min = (
        round(critical_at_min, 1) if critical_at_min is not None else round(elapsed_min, 1)
    )

    timeline, intersections = _build_minute_timeline(kinematics, start_hour, thresholds, air)

    return {
        "points": points,
        "timeline": timeline,
        "intersections": intersections,
        "alerts": alerts[:8],
        "peak_utci": round(peak_utci, 1),
        "peak_at_min": round(peak_at_min, 1),
        "total_min": round(elapsed_min, 1),
        "safe_window_min": safe_window_min,
        "thresholds": thresholds,
        "departure_hour": round(start_hour, 3),
    }
