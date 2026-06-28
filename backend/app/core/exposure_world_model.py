"""Urban Exposure World Model v1 — roll-forward exposure along a fixed route.

Fuses Open-Meteo hourly weather/AQ forecast with moving sun geometry and the
live traffic plume to answer: *what changes if I leave in 10 / 30 / 60 min?*
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.core import air_quality, solar_comfort
from app.core.climate_intelligence import thermal_horizon
from app.data.adapters import get_environment


def current_uae_hour() -> float:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    return now.hour + now.minute / 60.0 + now.second / 3600.0


def _slot_summary(horizon: dict) -> dict:
    tl = horizon.get("timeline") or []
    if not tl:
        return {
            "peak_utci": float(horizon.get("peak_utci", 0)),
            "mean_utci": float(horizon.get("peak_utci", 0)),
            "shade_pct": 0.0,
            "mean_pm25": 0.0,
            "safe_window_min": float(horizon.get("safe_window_min", 0)),
            "stress_score": 0.0,
        }
    mean_utci = sum(float(f["utci"]) for f in tl) / len(tl)
    shade = sum(1 for f in tl if float(f.get("shade_pct", 0)) >= 50) / len(tl) * 100.0
    mean_pm = sum(float(f["pm25"]) for f in tl) / len(tl)
    stress = sum(float(f.get("overlap_score", 0)) for f in tl) / len(tl)
    return {
        "peak_utci": float(horizon["peak_utci"]),
        "mean_utci": round(mean_utci, 1),
        "shade_pct": round(shade, 1),
        "mean_pm25": round(mean_pm, 1),
        "safe_window_min": float(horizon["safe_window_min"]),
        "stress_score": round(stress, 3),
    }


def build_forecast(
    graph,
    path: list,
    mode: str,
    profile: dict,
    *,
    base_hour: float | None = None,
    forecast_minutes: int = 60,
    step_minutes: int = 10,
    edge_speed_fn,
    congestion_map_fn,
    path_coords_fn,
    edge_attr_fn,
    enrich_fn,
) -> dict:
    """Roll exposure forward for delayed departures using hour-matched live env."""
    base = base_hour if base_hour is not None else current_uae_hour()

    # Assimilate observations once at departure = now.
    get_environment(base, force_refresh=True)

    delays: list[int] = list(range(0, forecast_minutes + 1, step_minutes))
    if not delays or delays[-1] != forecast_minutes:
        delays.append(forecast_minutes)

    cong = congestion_map_fn() if mode == "drive" else {}
    slots: list[dict] = []
    baseline_summary: dict | None = None

    for delay in delays:
        dep_hour = (base + delay / 60.0) % 24.0
        env = get_environment(dep_hour, force_refresh=False)

        solar_comfort.compute_hour(dep_hour, env)
        air_quality.compute_field(env)
        enrich = enrich_fn(dep_hour)

        horizon = thermal_horizon(
            graph,
            path,
            mode,
            profile,
            dep_hour,
            edge_speed_fn=edge_speed_fn,
            congestion_map=cong,
            path_coords_fn=path_coords_fn,
            edge_attr_fn=edge_attr_fn,
            enrich=enrich,
        )

        summary = _slot_summary(horizon)
        slot: dict = {
            "delay_minutes": delay,
            "departure_hour": round(dep_hour, 3),
            "env": {
                "source": env.get("source", "simulation"),
                "air_temp_c": env["air_temp_c"],
                "relative_humidity": env["relative_humidity"],
                "wind_speed_ms": env["wind_speed_ms"],
                "wind_dir_deg": env["wind_dir_deg"],
                "aqi": env.get("aqi"),
                "pm25_ug_m3": env.get("pm25_ug_m3"),
                "fetched_at": env.get("fetched_at"),
            },
            **summary,
            "peak_at_min": horizon["peak_at_min"],
            "total_min": horizon["total_min"],
            "timeline": horizon["timeline"],
        }

        if delay == 0:
            baseline_summary = summary
            slot["delta_vs_now"] = {"peak_utci": 0.0, "mean_utci": 0.0, "stress_score": 0.0}
        elif baseline_summary:
            slot["delta_vs_now"] = {
                "peak_utci": round(summary["peak_utci"] - baseline_summary["peak_utci"], 1),
                "mean_utci": round(summary["mean_utci"] - baseline_summary["mean_utci"], 1),
                "stress_score": round(summary["stress_score"] - baseline_summary["stress_score"], 3),
            }

        slots.append(slot)

    return {
        "base_hour": round(base, 3),
        "forecast_minutes": forecast_minutes,
        "step_minutes": step_minutes,
        "slots": slots,
        "assimilated": True,
        "model": "world_model_v1",
    }
